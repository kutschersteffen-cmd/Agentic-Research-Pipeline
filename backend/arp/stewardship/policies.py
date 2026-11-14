"""Versioned house policies for the stage studios: design a new version,
calibrate it against the active one, then activate it with a named approver.

Six policies so far:

- `monitoring_rules`: the ZEN decision table that raises triggers (stage 1);
- `coverage_rules`: the ZEN decision table that proposes coverage tiers (stage 2);
- `escalation_rules`: tier caps and the escalation recommendations (stages 2 and 5);
- `phrase_blocklist`: the E8 style check on outreach and client-facing text (stage 3);
- `house_voting`: the house voting positions on the issue catalogue (stage 4);
- `priority_weights`: the component weights of the worklist's priority score (`worklist.py`).

Client streams have their own store (`PolicyStore(root, client=True)` on the
stream's directory) for the policies that have a client form: so far
`escalation_rules`, a graph chained on the house result, whose version 0
returns the house answer unchanged.

Each theme dossier has its own store (`PolicyStore(root, theme=True)` under
`themes/<dossier_id>/`) for `theme_standards`: the stewardship expectations
derived from the theme's approved position. The house store does not know it.

Version 0 is the bundled draft in `data/`, always available as the baseline.
Saved versions are immutable files; activations are an append-only log, and
the active version is the last activation. Nothing is stored that fails
validation, and nothing becomes active without `approved_by`, who must not be
the person who saved that version (four-eyes).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from arp.schemas.engagement import EngagementRecord
from arp.stewardship import escalation, monitoring, style
from arp.stewardship.backtest import backtest
from arp.stewardship.policy_graph import evaluate as evaluate_votes
from arp.stewardship.policy_graph import generate
from arp.stewardship.policy_review import _validate_position, load
from arp.stewardship.tiers import TIER_LABELS, TIERS, tier_contexts
from arp.stewardship.tiers import evaluate as evaluate_tiers
from arp.stewardship.tiers import load_graph as default_coverage_graph
from arp.storage.atomic_io import atomic_write_text
from arp.storage.jsonl_io import append_jsonl


def _validate_coverage(graph: dict, sample: dict) -> None:
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("A coverage policy is a rule graph with nodes and edges")
    try:
        evaluate_tiers(graph, tier_contexts(sample, []))
    except RuntimeError as exc:
        raise ValueError(f"The coverage rules do not run: {exc}") from exc


def _validate_monitoring(graph: dict, sample: dict) -> None:
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("A monitoring policy is a rule graph with nodes and edges")
    try:
        monitoring.evaluate(graph, sample, [])
    except RuntimeError as exc:
        raise ValueError(f"The monitoring rules do not run: {exc}") from exc


def _validate_escalation(graph: dict, sample: dict) -> None:
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("An escalation policy is a rule graph with nodes and edges")
    # every engagement under every tier, and under no tier, must get a valid cap and recommendation
    ctxs = [{**c, "tier": {"tier": t}} for c in escalation.contexts(sample, [], {}, [], sla_days=30) for t in [*TIERS, None]]
    try:
        escalation.evaluate(graph, ctxs)
    except RuntimeError as exc:
        raise ValueError(f"The escalation rules do not run: {exc}") from exc


def _validate_client_escalation(graph: dict, sample: dict) -> None:
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("An escalation policy is a rule graph with nodes and edges")
    base = escalation.contexts(sample, [], {}, [], sla_days=30)
    ctxs = [{**c, "tier": {"tier": t}} for c in base for t in [*TIERS, None]]
    try:
        escalation.client_evaluate(graph, ctxs, escalation.evaluate(escalation.load_graph(), ctxs))
    except RuntimeError as exc:
        raise ValueError(f"The escalation rules do not run: {exc}") from exc


def _validate_voting(policy: dict, sample: dict) -> None:
    catalogue = load("policy_issue_catalogue.json")
    issues = {i["issue_id"]: i for i in catalogue["issues"]}
    positions = policy.get("positions") or []
    ids = [p["issue_id"] for p in positions]
    if sorted(ids) != sorted(issues):
        missing, extra = set(issues) - set(ids), set(ids) - set(issues)
        raise ValueError(
            f"A voting policy needs exactly one position per catalogue issue (missing {sorted(missing)}, unknown {sorted(extra)})"
        )
    for p in positions:
        _validate_position(issues[p["issue_id"]], p, catalogue["position_actions"])
    evaluate_votes(generate(policy)["graph"], [])  # compiles


_NUMERIC = ("number", "percentage", "currency_amount")
_TEXT_KEYS = ("title", "expectation", "definition", "where_reported")


def _validate_theme_standards(content: dict, sample: dict) -> None:
    """`sample` holds the approved position's paragraph count (`paragraphs`), the released registry fields
    (`released`: field_id -> {name, data_type, allowed_values, ...}) and the ids of the theme's own released fields
    (`carried`). Stops at the first failure."""
    standards = content.get("standards") or []
    schema_fields = {f["field_id"]: f for f in (content.get("schema") or {}).get("fields", [])}
    released = sample["released"]
    if not standards or [s.get("standard_id") for s in standards] != [f"S{i}" for i in range(1, len(standards) + 1)]:
        raise ValueError("standard ids must be S1..Sn")
    for s in standards:
        for key in _TEXT_KEYS:
            if not str(s.get(key) or "").strip():
                raise ValueError(f"standard '{s['standard_id']}': {key} is blank")
    for s in standards:
        for n in s.get("rests_on") or []:
            if not 1 <= n <= sample["paragraphs"]:
                raise ValueError(f"standard '{s['standard_id']}': position has no paragraph {n}")
    for s in standards:
        if s["data"] == "existing" and s["field_id"] not in released:
            raise ValueError(f"standard '{s['standard_id']}': unknown or unreleased field '{s['field_id']}'")
    for s in standards:
        if s["data"] == "new":
            if s["field_id"] not in schema_fields:
                raise ValueError(f"standard '{s['standard_id']}': field '{s['field_id']}' is not in the new schema")
            if s["field_id"] in released:
                raise ValueError(f"standard '{s['standard_id']}': field '{s['field_id']}' is released, use data \"existing\"")
    for fid, f in schema_fields.items():  # a released field that is not a carried theme field cannot be added again
        if fid in released and fid not in sample.get("carried", ()):
            raise ValueError(f"new field '{f['name']}' is already released")
    used = {s["field_id"] for s in standards}
    for fid, f in schema_fields.items():
        if fid not in released and fid not in used:
            raise ValueError(f"new field '{f['name']}' is used by no standard")
    for s in standards:
        field = released[s["field_id"]] if s["data"] == "existing" else schema_fields[s["field_id"]]
        kind, op, value, sid = str(field["data_type"]), s["operator"], s["value"], s["standard_id"]
        if kind in ("string", "date"):
            raise ValueError(f"standard '{sid}': field '{s['field_id']}' is {kind}, not checkable")
        if kind not in _NUMERIC and op != "==":
            raise ValueError(f"standard '{sid}': operator '{op}' does not fit {kind}")
        fits = (
            isinstance(value, (int, float)) and not isinstance(value, bool) if kind in _NUMERIC
            else isinstance(value, bool) if kind == "boolean"
            else isinstance(value, str) and value in (field.get("allowed_values") or [])
        )
        if not fits:
            raise ValueError(f"standard '{sid}': value {json.dumps(value)} does not fit {kind}")


def load_priority_weights() -> dict:
    return load("priority_weights.json")


def component_ids() -> list[str]:
    return [c["id"] for c in load_priority_weights()["components"]]


def validate_weights(content: dict, _sample: dict | None = None) -> None:
    comps = content.get("components") if isinstance(content, dict) else None
    if not isinstance(comps, list) or not all(isinstance(c, dict) for c in comps):
        raise ValueError("A priority_weights version lists components: [{id, weight}]")
    ids, known = [c.get("id") for c in comps], component_ids()
    if missing := [i for i in known if i not in ids]:
        raise ValueError(f"Missing components: {', '.join(missing)}")
    if unknown := [str(i) for i in ids if i not in known]:
        raise ValueError(f"Unknown components: {', '.join(unknown)}")
    if twice := sorted(i for i, n in Counter(ids).items() if n > 1):
        raise ValueError(f"Components listed twice: {', '.join(twice)}")
    for c in comps:
        w = c.get("weight")
        if isinstance(w, bool) or not isinstance(w, int) or not 0 <= w <= 100:
            raise ValueError(f"The weight of {c['id']} must be a whole number from 0 to 100")
    if (total := sum(c["weight"] for c in comps)) != 100:
        raise ValueError(f"Weights must add up to 100 (now {total})")


POLICIES: dict[str, dict[str, Callable]] = {
    "monitoring_rules": {"default": monitoring.load_graph, "validate": _validate_monitoring},
    "coverage_rules": {"default": default_coverage_graph, "validate": _validate_coverage},
    "escalation_rules": {
        "default": escalation.load_graph,
        "validate": _validate_escalation,
        "client_default": escalation.load_client_default,
        "client_validate": _validate_client_escalation,
    },
    "phrase_blocklist": {"default": style.load_blocklist, "validate": style.validate_blocklist},
    "house_voting": {"default": lambda: load("house_voting_policy_draft.json"), "validate": _validate_voting},
    "priority_weights": {"default": load_priority_weights, "validate": validate_weights},
    "theme_standards": {
        "theme_default": lambda: {"policy_id": "theme_standards", "standards": [], "schema": None},
        "theme_validate": _validate_theme_standards,
    },
}


class PolicyStore:
    def __init__(self, root: Path, client: bool = False, theme: bool = False) -> None:
        self.root = root / "policies"
        self.client = client
        self.theme = theme

    def _spec(self, policy_id: str, key: str) -> Callable:
        spec = POLICIES.get(policy_id, {})
        fn = spec.get(f"client_{key}" if self.client else f"theme_{key}" if self.theme else key)
        if fn is None:
            raise KeyError(policy_id)
        return fn

    def _dir(self, policy_id: str) -> Path:
        self._spec(policy_id, "default")  # raises for an unknown policy, or one without a client form
        return self.root / policy_id

    def versions(self, policy_id: str) -> list[dict]:
        d = self._dir(policy_id)
        note = "Same as the house" if self.client else "Bundled draft"
        metas = [{"version": 0, "note": note, "created_by": "system", "created_at": None}]
        if d.exists():
            for path in sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:])):
                metas.append({k: v for k, v in json.loads(path.read_text()).items() if k != "content"})
        return metas

    def content(self, policy_id: str, version: int) -> dict:
        if version == 0:
            return self._spec(policy_id, "default")()
        path = self._dir(policy_id) / f"v{version}.json"
        if not path.exists():
            raise KeyError(f"{policy_id} v{version}")
        return json.loads(path.read_text())["content"]

    def activations(self, policy_id: str) -> list[dict]:
        # Strict on purpose (not read_jsonl, which skips torn lines): a damaged
        # four-eyes log must fail loudly, never fall back to an older policy.
        path = self._dir(policy_id) / "activations.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []

    def active_version(self, policy_id: str) -> int:
        log = self.activations(policy_id)
        return log[-1]["version"] if log else 0

    def active(self, policy_id: str) -> dict:
        return self.content(policy_id, self.active_version(policy_id))

    def save(self, policy_id: str, content: dict, note: str, created_by: str, sample: dict) -> int:
        if not created_by.strip():
            raise ValueError("A policy version needs created_by")
        self._spec(policy_id, "validate")(content, sample)
        version = max(v["version"] for v in self.versions(policy_id)) + 1
        if "policy_id" in content:  # stamp the store version into the policy, so reviews and builds cite it
            content = {**content, "version": f"v{version}"}
        d = self._dir(policy_id)
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "version": version,
            "note": note,
            "created_by": created_by,
            "created_at": datetime.now(UTC).isoformat(),
            "content": content,
        }
        atomic_write_text(d / f"v{version}.json", json.dumps(record, indent=2, ensure_ascii=False))
        return version

    def activate(self, policy_id: str, version: int, approved_by: str) -> dict:
        if not approved_by.strip():
            raise ValueError("Activating a policy version needs approved_by")
        content = self.content(policy_id, version)  # raises for an unknown version
        meta = next(v for v in self.versions(policy_id) if v["version"] == version)
        # theme_standards only: the owner may activate their own edit alone; the row records the path.
        own_edit = self.theme and content.get("path") == "owner_edit"
        if version > 0 and not own_edit and meta["created_by"].strip().lower() == approved_by.strip().lower():
            raise ValueError("Four-eyes rule: a version must be activated by someone other than the person who saved it")
        row = {"version": version, "approved_by": approved_by, "approved_at": datetime.now(UTC).isoformat()}
        if "path" in content:
            row["path"] = content["path"]
        append_jsonl(self._dir(policy_id) / "activations.jsonl", row)
        return row


def coverage_preview(candidate: dict, active: dict, sample: dict, records: list[EngagementRecord]) -> dict:
    """What a candidate coverage table would change against the active one."""
    contexts = tier_contexts(sample, records)
    new = evaluate_tiers(candidate, contexts)
    old = {r["issuer_id"]: r for r in evaluate_tiers(active, contexts)}
    changes = [
        {
            "issuer_id": r["issuer_id"],
            "company": r["name"],
            "from": TIER_LABELS[old[r["issuer_id"]]["tier"]],
            "to": TIER_LABELS[r["tier"]],
            "rule": r["rule"],
            "reason": r["reason"],
        }
        for r in new
        if r["tier"] != old[r["issuer_id"]]["tier"]
    ]
    return {
        "companies": len(new),
        "distribution_candidate": {TIER_LABELS[t]: n for t, n in Counter(r["tier"] for r in new).items()},
        "distribution_active": {TIER_LABELS[t]: n for t, n in Counter(r["tier"] for r in old.values()).items()},
        "rules_fired": dict(Counter(r["rule"] for r in new)),
        "changes": changes,
        "assignments": new,
    }


def voting_preview(candidate: dict, active: dict, sample: dict) -> dict:
    """Back-test of a candidate house voting policy against the active one."""
    bt = backtest(active, candidate, sample)
    changed = [r for r in bt["rows"] if r["changed"]]
    return {k: bt[k] for k in ("resolutions", "changed", "base_votes", "other_votes", "affected_by_issue", "masked_by_issue")} | {
        "changed_rows": changed[:100],
        "unused_parameters": generate(candidate)["unused_parameters"],
        "no_vote_effect": generate(candidate)["no_vote_effect"],
    }
