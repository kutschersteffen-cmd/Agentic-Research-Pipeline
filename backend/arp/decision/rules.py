"""Calculated columns from a rule graph (GoRules JSON Decision Model).

A framework's `rule_graph` is evaluated once per row, before anything is
profiled or scored. Every output key that is not already a column becomes
a new column -- a formula such as `capex / revenue * 100`, or an AND/OR
condition such as `capex_ratio > 10 and coal_expansion_flag`. From there
the engine treats it like any column: it can be a criterion or a gate, and
a compound condition gates through the ordinary `is Yes` gate rule. That
is the whole integration: nothing downstream knows the column was
computed.

The browser evaluates the same graph with the same engine build (ZEN
2.0.2 as WASM) for the live preview while a rule is being edited; the
score a reviewer sees and the audit trail records is always this one.

Two rules keep the source data authoritative:

- A rule never overwrites a source column. An output under an existing
  column name is dropped and the audit log says so.
- A row the graph cannot evaluate -- arithmetic on a missing value,
  division by zero -- gets blank calculated values, which the missing-data
  policy then handles like any other gap. The count and the first error
  are logged, flagged for checking.
"""

from __future__ import annotations

import json
from typing import Any

import zen

from arp.decision.dataset import Dataset
from arp.decision.parsing import to_bool, to_number
from arp.decision.profiling import profile_dataset
from arp.decision.roles import slug
from arp.schemas.decision import AuditEntry, ColumnProfile, EntityDecision, MechanismConfig


def rule_inputs(
    dataset: Dataset, profiles: dict[str, ColumnProfile] | None = None, rows: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    """The typed context each row is evaluated against: numbers as numbers,
    booleans as booleans, blanks as null. Every column is addressable by
    its name (`$["Scope 1 (t)"]`) and, where that differs, by its slug
    (`scope_1_t`), so an expression needs no quoting for ordinary names."""
    profiles = profiles or profile_dataset(dataset)
    aliases = {slug(c): c for c in dataset.columns if slug(c) and slug(c) not in dataset.columns}
    out: list[dict[str, Any]] = []
    for row in dataset.rows if rows is None else rows:
        typed = {column: _typed(row.get(column, ""), profiles.get(column)) for column in dataset.columns}
        typed.update({alias: typed[column] for alias, column in aliases.items()})
        out.append(typed)
    return out


def _typed(raw: str, profile: ColumnProfile | None) -> Any:
    if profile is not None and profile.type == "boolean":
        value = to_bool(raw)
        return None if value is None else value == 1
    if profile is not None and profile.type in ("numeric", "ordinal"):
        return to_number(raw, profile.decimal_comma)
    return str(raw).strip() or None


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _flatten(result: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def _error_text(exc: Exception) -> str:
    # ZEN errors are a JSON line followed by a Rust backtrace.
    first = str(exc).split("\n", 1)[0]
    try:
        return str(json.loads(first).get("source") or first)
    except (ValueError, AttributeError):
        return first


def evaluate_rows(graph: dict[str, Any], contexts: list[dict[str, Any]]) -> list[dict[str, Any] | str]:
    """One result per context: the flattened output, or the error text.

    Raises ValueError for a graph that cannot run at all (a dangling edge,
    a malformed node). An expression syntax error is not caught here -- the
    engine reports it per row, and it surfaces as every row failing.
    """
    content = json.dumps(graph)
    try:
        zen.ZenEngine().create_decision(content).validate()
    except RuntimeError as exc:
        raise ValueError(f"Rule graph does not compile: {_error_text(exc)}") from exc
    # The batch call evaluates in parallel inside the engine: ~4x faster
    # than a Python loop, which matters because every edit re-scores.
    engine = zen.ZenEngine({"loader": lambda _key: content})
    responses = engine.evaluate_batch([{"key": "rules", "context": c} for c in contexts])
    return [
        _flatten(r["data"].get("result") or {})
        if r.get("success")
        else str((r.get("error") or {}).get("source") or r.get("error"))
        for r in responses
    ]


def apply_rules(dataset: Dataset, graph: dict[str, Any]) -> tuple[Dataset, list[AuditEntry]]:
    """Returns a copy of `dataset` with the graph's calculated columns
    appended, and the audit entries describing what happened."""
    inputs = rule_inputs(dataset)
    calculated: list[str] = []
    values: list[dict[str, Any]] = []
    overwrites: set[str] = set()
    failures: list[tuple[int, str]] = []

    for i, (context, result) in enumerate(zip(inputs, evaluate_rows(graph, inputs), strict=True)):
        if isinstance(result, str):
            failures.append((i, result))
            values.append({})
            continue
        row_values: dict[str, Any] = {}
        for key, value in result.items():
            if key in context:
                if value != context[key]:
                    overwrites.add(key)
                continue
            if key not in calculated:
                calculated.append(key)
            row_values[key] = value
        values.append(row_values)

    rows = [{**row, **{c: _cell(v.get(c)) for c in calculated}} for row, v in zip(dataset.rows, values, strict=True)]
    augmented = dataset.model_copy(update={"columns": [*dataset.columns, *calculated], "rows": rows})

    audit = [
        AuditEntry(
            stage="Rules",
            item=", ".join(calculated) or "-",
            decision=f"{len(calculated)} calculated {'column' if len(calculated) == 1 else 'columns'}",
            why="evaluated per row by the framework's rule graph before profiling and scoring; they enter criteria "
            "and gates like any other column",
            needs_check=not calculated,
        )
    ]
    if failures:
        row_index, message = failures[0]
        audit.append(
            AuditEntry(
                stage="Rules",
                item=f"{len(failures)} of {len(inputs)} rows",
                decision="calculated values left blank",
                why=f"the graph could not be evaluated for these rows -- first: row {row_index + 1}, {message}. A missing "
                "input or a division by zero does this; guard it with a condition (revenue > 0 ? capex / revenue : null) "
                "or let the missing-data policy handle the gap",
                needs_check=True,
            )
        )
    if overwrites:
        audit.append(
            AuditEntry(
                stage="Rules",
                item=", ".join(sorted(overwrites)),
                decision="output ignored",
                why="a rule may add columns but never rewrite a source value; give the output a new name",
                needs_check=True,
            )
        )
    return augmented, audit


# --- tier rules: a second graph, run after scoring ---------------------------
#
# The score band needs every row (cut-points come from the distribution), and
# ZEN sees one row at a time -- so the engine draws the band and hands it to
# the graph, which decides the final tier. Sufficiency stays in the engine: a
# rule cannot score an entity on a fraction of its criteria.


def tier_contexts(
    dataset: Dataset,
    profiles: dict[str, ColumnProfile],
    entities: list[EntityDecision],
    bands: list[int | None],
    config: MechanismConfig,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """What a tier graph sees per entity: every column (typed, as for rule
    graphs) plus the engine's own results. Engine keys win over a column of
    the same name."""
    rows = dataset.rows if limit is None else dataset.rows[:limit]
    dim_keys = {d.id: f"dim_{slug(d.name)}" for d in config.dimensions}
    peers: dict[str | None, list[float]] = {}
    for e in entities:
        if e.status == "scored" and e.score is not None:
            peers.setdefault(e.cohort, []).append(e.score)
    out = rule_inputs(dataset, profiles, rows=rows)
    for i, context in enumerate(out):
        e = entities[i]
        group = peers.get(e.cohort, [])
        scored = e.status == "scored" and e.score is not None and bool(group)
        context.update({key: e.dimension_scores.get(dim_id) for dim_id, key in dim_keys.items()})
        context.update(
            score=e.score,
            band=bands[i],
            rank=e.rank,
            percentile=100.0 * sum(1 for s in group if s <= e.score) / len(group) if scored else None,
            coverage=e.coverage,
            grounded_coverage=e.grounded_coverage,
            status=e.status,
            cohort=e.cohort,
            segment=e.segment,
            tier_count=len(config.tiers),
        )
    return out


def apply_tier_graph(
    graph: dict[str, Any],
    entities: list[EntityDecision],
    contexts: list[dict[str, Any]],
    bands: list[int | None],
    config: MechanismConfig,
) -> list[AuditEntry]:
    """Sets each scored entity's final tier from the graph's `tier` output,
    or excludes it on `exclude: true`. A row the graph cannot evaluate, or
    whose `tier` is not a whole number in range, keeps its band and is
    flagged -- the same policy calculated columns follow."""
    tiers_by_rank = {t.rank: t for t in config.tiers}
    lowest = max(tiers_by_rank) if tiers_by_rank else 4
    targets = [i for i, e in enumerate(entities) if e.status == "scored"]
    results = evaluate_rows(graph, [contexts[i] for i in targets])
    failures: list[tuple[str, str]] = []
    down = up = excluded = 0

    for i, result in zip(targets, results, strict=True):
        e, band = entities[i], bands[i]
        if isinstance(result, str):
            failures.append((e.name, result))
            e.notes.append("Tier rules could not be evaluated; band kept")
            continue
        if result.get("exclude") is True:
            e.status, e.tier, e.tier_name, e.tier_action = "excluded", None, None, None
            e.rank = e.rank_min = e.rank_max = e.leverage = None
            e.notes.append("Excluded by tier rules")
            excluded += 1
        else:
            tier = result.get("tier")
            if isinstance(tier, bool) or not isinstance(tier, (int, float)) or tier != int(tier) or not 1 <= tier <= lowest:
                failures.append((e.name, f"`tier` must be a whole number from 1 to {lowest}, got {tier!r}"))
                e.notes.append("Tier rules gave no valid tier; band kept")
                continue
            tier = int(tier)
            if band is not None and tier != band:
                e.notes.append(f"Tier rules: band {band} -> {tier}")
                down += tier > band
                up += tier < band
            definition = tiers_by_rank.get(tier)
            e.tier, e.tier_name, e.tier_action = (
                tier,
                definition.name if definition else None,
                definition.action if definition else None,
            )
        note = result.get("note")
        if isinstance(note, str) and note.strip():
            e.notes.append(note.strip())

    audit = [
        AuditEntry(
            stage="Tier rules",
            item=f"{len(targets)} scored entities",
            decision=f"{down + up + excluded} changed: {down} moved down, {up} moved up, {excluded} excluded",
            why="the framework's tier rules replace the gates and the dimension floor; they ran per entity after the "
            "score band was drawn, so an exclusion here does not redraw its peers' cut-points"
            + ("; moving an entity up is allowed but departs from the band the scores support, so it is flagged" if up else ""),
            needs_check=up > 0,
        )
    ]
    if failures:
        name, message = failures[0]
        audit.append(
            AuditEntry(
                stage="Tier rules",
                item=f"{len(failures)} of {len(targets)} entities",
                decision="band kept",
                why=f"no valid `tier` from the tier rules -- first: {name}, {message}",
                needs_check=True,
            )
        )
    replaced = [g for g in config.gates if g.outcome != "exclude"]
    if replaced:
        audit.append(
            AuditEntry(
                stage="Tier rules",
                item=f"{len(replaced)} demote/flag gate{'s' if len(replaced) != 1 else ''}",
                decision="not applied",
                why="the tier rules decide demotions here; exclusion gates still apply before scoring. Remove these "
                "gates or move them into the tier rules",
                needs_check=True,
            )
        )
    return audit
