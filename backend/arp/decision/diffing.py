from __future__ import annotations

from arp.decision.roles import pretty
from arp.schemas.decision import AuditEntry, MechanismConfig

_SETTING_LABELS = {
    "mode": "Scoring mode",
    "level_min": "Lowest level",
    "level_max": "Highest level",
    "norm": "Normalisation method",
    "winsor_pct": "Winsorised tails (%)",
    "missing": "Missing-data policy",
    "weighting": "Weighting preset",
    "min_coverage_pct": "Minimum weight covered (%)",
    "normalise_within": "Peer cohort column",
    "min_cohort_size": "Minimum cohort size",
    "require_grounded_coverage": "Sufficiency keyed off grounded coverage",
    "grounded_confidence_min": "Grounded-confidence floor",
    "cut_mode": "Cut-point mode",
    "cluster_threshold": "Clustering threshold",
    "label_column": "Label column",
    "size_column": "Size column",
    "segment_column": "Segment column",
}


def describe_changes(before: MechanismConfig, after: MechanismConfig, *, by: str | None = None) -> list[AuditEntry]:
    """Every difference between two framework versions, as audit entries
    marked `origin="human"`.

    This is the other half of the audit log's promise. A derivation trail
    alone says what the data suggested; without this, a reviewer cannot
    tell which of the rules in front of them a person then changed -- and
    that is precisely the distinction the log exists to draw.
    """
    entries: list[AuditEntry] = []

    for field, label in _SETTING_LABELS.items():
        old, new = getattr(before, field, None), getattr(after, field, None)
        if old != new:
            entries.append(
                AuditEntry(
                    stage="Edit",
                    item=label,
                    decision=f"{_render(old)} -> {_render(new)}",
                    why="changed by hand",
                    origin="human",
                    by=by,
                )
            )

    old_veto, new_veto = before.veto, after.veto
    if old_veto != new_veto:
        entries.append(
            AuditEntry(
                stage="Edit",
                item="Dimension floor",
                decision=(
                    f"{'on' if new_veto.enabled else 'off'}, below {new_veto.min_score:g}, "
                    f"dimensions with {new_veto.min_criteria}+ criteria"
                ),
                why="changed by hand",
                origin="human",
                by=by,
            )
        )

    entries.extend(_criteria_changes(before, after, by))
    entries.extend(_level_changes(before, after, by))
    entries.extend(_dimension_changes(before, after, by))
    entries.extend(_gate_changes(before, after, by))
    entries.extend(_rule_changes(before, after, by))
    entries.extend(_tier_changes(before, after, by))

    if before.pinned_cuts != after.pinned_cuts:
        entries.append(
            AuditEntry(
                stage="Edit",
                item="Cut-points",
                decision=_render(after.pinned_cuts),
                why="pinned by hand -- these now survive a re-run against different data",
                origin="human",
                by=by,
            )
        )
    return entries


def _tier_changes(before: MechanismConfig, after: MechanismConfig, by: str | None) -> list[AuditEntry]:
    """Tier names and actions are what a decision reads as, so
    renaming one is recorded like any other rule change."""
    old = {t.rank: t for t in before.tiers}
    new = {t.rank: t for t in after.tiers}
    entries: list[AuditEntry] = []
    if len(old) != len(new):
        entries.append(
            AuditEntry(stage="Edit", item="Tiers", decision=f"{len(old)} -> {len(new)} tiers", why="changed by hand", origin="human", by=by)
        )
    for rank in sorted(set(old) & set(new)):
        if (old[rank].name, old[rank].action) != (new[rank].name, new[rank].action):
            entries.append(
                AuditEntry(
                    stage="Edit",
                    item=f"Tier {rank}",
                    decision=f"{_tier_label(old[rank])} -> {_tier_label(new[rank])}",
                    why="renamed by hand",
                    origin="human",
                    by=by,
                )
            )
    return entries


def _tier_label(tier) -> str:
    return f"{tier.name} ({tier.action or 'no action'})"


def _rule_changes(before: MechanismConfig, after: MechanismConfig, by: str | None) -> list[AuditEntry]:
    return _graph_changes(before.rule_graph, after.rule_graph, "Rule graph", by) + _graph_changes(
        before.tier_graph, after.tier_graph, "Tier rules", by
    )


def _graph_changes(old_graph: dict | None, new_graph: dict | None, label: str, by: str | None) -> list[AuditEntry]:
    """Node-level: which rule boxes were added, removed or edited. Dragging
    a node on the canvas moves `position` only and is not an edit."""

    def nodes(graph: dict | None) -> dict[str, tuple]:
        graph = graph or {}
        return {
            str(n.get("id")): (n.get("name") or n.get("type"), n.get("type"), n.get("content"))
            for n in graph.get("nodes", [])
        }

    def edges(graph: dict | None) -> set[tuple]:
        return {(e.get("sourceId"), e.get("targetId"), e.get("sourceHandle")) for e in (graph or {}).get("edges", [])}

    old, new = nodes(old_graph), nodes(new_graph)
    changes = [f"added {new[i][0]}" for i in new if i not in old]
    changes += [f"removed {old[i][0]}" for i in old if i not in new]
    changes += [f"edited {new[i][0]}" for i in new if i in old and new[i] != old[i]]
    if edges(old_graph) != edges(new_graph):
        changes.append("rewired")
    if not changes:
        return []
    return [AuditEntry(stage="Edit", item=label, decision="; ".join(changes), why="changed by hand", origin="human", by=by)]


def _criteria_changes(before: MechanismConfig, after: MechanismConfig, by: str | None) -> list[AuditEntry]:
    old = {c.column: c for c in before.criteria}
    new = {c.column: c for c in after.criteria}
    entries: list[AuditEntry] = []
    for column, criterion in new.items():
        previous = old.get(column)
        if previous is None:
            entries.append(AuditEntry(stage="Edit", item=pretty(column), decision="added as a criterion", why="added by hand", origin="human", by=by))
            continue
        if previous.direction != criterion.direction:
            entries.append(
                AuditEntry(
                    stage="Edit",
                    item=pretty(column),
                    decision=f"direction {previous.direction} -> {criterion.direction}",
                    why="the inferred direction was overridden -- the single correction most worth recording, "
                    "because a wrong direction inverts a ranking without looking wrong",
                    origin="human",
                    by=by,
                )
            )
        if previous.enabled != criterion.enabled:
            entries.append(
                AuditEntry(
                    stage="Edit",
                    item=pretty(column),
                    decision="enabled" if criterion.enabled else "parked",
                    why="changed by hand",
                    origin="human",
                    by=by,
                )
            )
        if previous.weight != criterion.weight:
            entries.append(
                AuditEntry(stage="Edit", item=pretty(column), decision=f"weight {previous.weight:g} -> {criterion.weight:g}", why="changed by hand", origin="human", by=by)
            )
        if previous.dimension_id != criterion.dimension_id:
            names = {d.id: d.name for d in after.dimensions}
            entries.append(
                AuditEntry(
                    stage="Edit",
                    item=pretty(column),
                    decision=f"moved to {names.get(criterion.dimension_id, criterion.dimension_id)}",
                    why="regrouped by hand -- the derived grouping came from rank correlation alone",
                    origin="human",
                    by=by,
                )
            )
    for column in old:
        if column not in new:
            entries.append(AuditEntry(stage="Edit", item=pretty(column), decision="removed as a criterion", why="removed by hand", origin="human", by=by))
    return entries


def _level_changes(before: MechanismConfig, after: MechanismConfig, by: str | None) -> list[AuditEntry]:
    """Level-grid edits, per criterion: which were added or removed, and
    which had their rules, default, weight, cluster or on/off state changed."""
    old = {c.id: c for c in before.level_criteria}
    new = {c.id: c for c in after.level_criteria}
    entries: list[AuditEntry] = []

    def entry(item: str, decision: str) -> AuditEntry:
        return AuditEntry(stage="Edit", item=item, decision=decision, why="changed by hand", origin="human", by=by)

    for cid, criterion in new.items():
        previous = old.get(cid)
        if previous is None:
            entries.append(entry(criterion.name, f"level criterion added ({len(criterion.rules)} rules)"))
            continue
        changes = []
        if previous.rules != criterion.rules:
            changes.append("level rules: " + "; ".join(f"{r.level} if {r.when}" for r in criterion.rules))
        if previous.otherwise != criterion.otherwise:
            changes.append(f"default level {_render(previous.otherwise)} -> {_render(criterion.otherwise)}")
        if previous.weight != criterion.weight:
            changes.append(f"weight {previous.weight:g} -> {criterion.weight:g}")
        if previous.dimension_id != criterion.dimension_id:
            names = {d.id: d.name for d in after.dimensions}
            changes.append(f"moved to {names.get(criterion.dimension_id, criterion.dimension_id)}")
        if previous.enabled != criterion.enabled:
            changes.append("enabled" if criterion.enabled else "parked")
        if previous.name != criterion.name:
            changes.append(f"renamed from {previous.name}")
        entries.extend(entry(criterion.name, change) for change in changes)
    entries.extend(entry(c.name, "level criterion removed") for cid, c in old.items() if cid not in new)
    return entries


def _dimension_changes(before: MechanismConfig, after: MechanismConfig, by: str | None) -> list[AuditEntry]:
    old = {d.id: d for d in before.dimensions}
    new = {d.id: d for d in after.dimensions}
    entries: list[AuditEntry] = []
    for dimension_id, dimension in new.items():
        previous = old.get(dimension_id)
        if previous is None:
            entries.append(AuditEntry(stage="Edit", item=dimension.name, decision="dimension added", why="added by hand", origin="human", by=by))
            continue
        if previous.name != dimension.name:
            entries.append(AuditEntry(stage="Edit", item=dimension.name, decision=f"renamed from {previous.name}", why="renamed by hand", origin="human", by=by))
        if previous.weight != dimension.weight:
            entries.append(
                AuditEntry(
                    stage="Edit",
                    item=dimension.name,
                    decision=f"weight {previous.weight:g} -> {dimension.weight:g}",
                    why="changed by hand -- the derived weight was the square root of its criteria count",
                    origin="human",
                    by=by,
                )
            )
    for dimension_id, dimension in old.items():
        if dimension_id not in new:
            entries.append(AuditEntry(stage="Edit", item=dimension.name, decision="dimension removed", why="removed by hand", origin="human", by=by))
    return entries


def _gate_changes(before: MechanismConfig, after: MechanismConfig, by: str | None) -> list[AuditEntry]:
    old = {(g.column, g.op, g.value): g for g in before.gates}
    new = {(g.column, g.op, g.value): g for g in after.gates}
    entries: list[AuditEntry] = []
    for key, gate in new.items():
        previous = old.get(key)
        if previous is None:
            entries.append(
                AuditEntry(stage="Edit", item=pretty(gate.column), decision=f"gate added ({gate.op} {gate.value} -> {gate.outcome})", why="added by hand", origin="human", by=by)
            )
        elif previous.outcome != gate.outcome:
            entries.append(
                AuditEntry(stage="Edit", item=pretty(gate.column), decision=f"gate outcome {previous.outcome} -> {gate.outcome}", why="changed by hand", origin="human", by=by)
            )
    for key, gate in old.items():
        if key not in new:
            entries.append(AuditEntry(stage="Edit", item=pretty(gate.column), decision="gate removed", why="removed by hand", origin="human", by=by))
    return entries


def _render(value) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        return ", ".join(f"{v:g}" if isinstance(v, (int, float)) else str(v) for v in value) or "(none)"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
