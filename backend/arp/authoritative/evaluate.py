"""Runs a calculate-only framework's rule graph over a source-values dataset: one verdict per company and declared
output, each with the inputs it read and the ZEN trace that computed it. Deterministic, no LLM."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import zen
from pydantic import BaseModel

from arp.decision.dataset import Dataset
from arp.schemas.decision import MechanismConfig

NO_RULE_VALUE = "no_rule_value"


class Verdict(BaseModel):
    company_id: str
    output: str
    status: Literal["value", "no_value"]
    value: Any = None
    unit: str | None = None
    period_end: str | None = None
    reason: str | None = None
    derivation: dict


_NUMBER = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")


def _typed(raw: str):
    """One cell as the rules see it, decided from that cell alone: Decision Studio's column profiling looks at every
    row, so one company's value would change another company's type (0/1 read as booleans, a number read as text)."""
    if raw == "":
        return None
    if raw in ("true", "false"):
        return raw == "true"
    if _NUMBER.fullmatch(raw):
        return int(raw) if raw.lstrip("-").isdigit() else float(raw)
    return raw


def _contexts(dataset: Dataset) -> list[dict]:
    return [{c: _typed(row.get(c, "")) for c in dataset.columns} for row in dataset.rows]


def _run(graph: dict, contexts: list[dict], *, trace: bool) -> list[dict]:
    content = json.dumps(graph)
    engine = zen.ZenEngine({"loader": lambda _key: content})
    return engine.evaluate_batch([{"key": "rules", "context": c} for c in contexts], {"trace": trace})


def _node_texts(graph: dict) -> dict[str, list[str]]:
    """Every expression or decision-table cell per node id: what a reader needs to see how a value was computed."""
    out: dict[str, list[str]] = {}
    for node in graph.get("nodes", []):
        content = node.get("content") or {}
        texts = [e.get("value", "") for e in content.get("expressions", [])]
        texts += [st.get("condition", "") for st in content.get("statements", []) if st.get("condition")]
        for rule in content.get("rules", []):
            texts += [str(v) for k, v in rule.items() if k != "_id" and v not in ("", None)]
        if texts:
            out[node["id"]] = texts
    return out


def _input_aliases(dataset: Dataset) -> list[str]:
    return [c for c in dataset.columns if c not in ("company_id", "Company") and "__" not in c]


def check_outputs(dataset: Dataset, config: MechanismConfig) -> None:
    """Raises ValueError when an output would shadow a dataset column, or no row's result contains it."""
    for out in config.outputs:
        if out.column in dataset.columns:
            raise ValueError(f"Output {out.column!r} has the name of an input column; a rule never overwrites a source column.")
    if not config.outputs:
        raise ValueError("An authoritative framework declares at least one output.")
    responses = _run(config.rule_graph or {}, _contexts(dataset), trace=False)
    produced = {k for r in responses if r.get("success") for k in (r["data"].get("result") or {})}
    missing = [o.column for o in config.outputs if o.column not in produced]
    if missing:
        raise ValueError(f"The rule graph never outputs {', '.join(missing)} on dataset {dataset.dataset_id}.")


def _blank(raw: str) -> str | None:
    return raw if raw != "" else None


def evaluate(dataset: Dataset, config: MechanismConfig, *, snapshot_id: str) -> list[Verdict]:
    graph = config.rule_graph or {}
    contexts = _contexts(dataset)
    responses = _run(graph, contexts, trace=True)
    texts = _node_texts(graph)
    aliases = _input_aliases(dataset)
    units = {o.column: o.unit for o in config.outputs}
    provenance = {"framework_id": config.framework_id, "framework_version": config.version,
                  "dataset_id": dataset.dataset_id, "dataset_as_of": dataset.as_of, "snapshot_id": snapshot_id}
    verdicts: list[Verdict] = []
    for row, context, response in zip(dataset.rows, contexts, responses, strict=True):
        ok = bool(response.get("success"))
        result = (response["data"].get("result") or {}) if ok else {}
        nodes = (response["data"].get("trace") or {}) if ok else {}
        for out in config.outputs:
            trace = [
                {"node": n.get("name"), "expressions": texts.get(node_id, []), "output": n.get("output") or {}}
                for node_id, n in sorted(nodes.items(), key=lambda kv: kv[1].get("order", 0))
                if node_id in texts  # every rule node that ran: an output may be computed over several chained nodes
            ]
            # shortcut: an input counts as used when its name occurs in an expression that computed this output, so
            # the losing side of `a ?? b` is listed too; the trace shows the actual result. Upgrade: parse the AST.
            used = [a for a in aliases if any(re.search(rf"\b{re.escape(a)}\b", t) for node in trace for t in node["expressions"])]
            inputs = {
                a: {
                    "value": context.get(a),
                    **{c: _blank(row.get(f"{a}__{c}", "")) for c in ("status", "source", "provider", "period_end", "unit")},
                    "observation_id": int(row[f"{a}__observation_id"]) if row.get(f"{a}__observation_id") else None,
                }
                for a in used
            }
            value = result.get(out.column)
            if not ok:
                error = response.get("error") or {}
                reason = f"rule_error: {error.get('source') or error}"
            else:
                reason = None if value is not None else NO_RULE_VALUE
            period = result.get(f"{out.column}__period_end")
            verdicts.append(Verdict(
                company_id=row["company_id"], output=out.column, status="value" if reason is None else "no_value",
                value=value if reason is None else None, unit=units[out.column],
                period_end=str(period) if period is not None and reason is None else None, reason=reason,
                derivation={"inputs": inputs, "trace": trace, **provenance},
            ))
    return verdicts

