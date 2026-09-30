"""Levels mode: scoring on a fixed scale from rules over each entity's own data.

The relative mode (mechanism.apply_mechanism) places every criterion among
the other entities in the table, so a score moves when the peers change.
A maturity-style framework needs the opposite: "a short-term target
covering at least 65%" is level 4 for every company, whoever else is in
the run. Here each criterion carries a level grid -- ordered rules, first
match wins -- and cluster and total scores are weighted averages of levels
on the framework's own scale.

What is shared with the relative mode, unchanged: the rule graph runs first
(calculated columns), gates settle exclusions before anything is scored,
the sufficiency gate routes thin entities to data collection, cut-points
and tier rules set the tier. What does not apply: normalisation, derived
dimensions, rank-stability bands and the dimension floor, which are all
about relative placement.
"""

from __future__ import annotations

import zen

from arp.decision.dataset import Dataset
from arp.decision.parsing import to_number
from arp.decision.roles import pretty, slug
from arp.decision.rules import apply_tier_graph, rule_inputs, tier_contexts
from arp.decision.scoring import ranks_of
from arp.decision.tree import derive_cuts, gate_hit, tier_for_score
from arp.schemas.common import now_iso
from arp.schemas.decision import (
    AuditEntry,
    ColumnProfile,
    CriterionContribution,
    DecisionResult,
    EntityDecision,
    GateRule,
    LevelCriterion,
    LevelOverride,
    MechanismConfig,
)


def level_weights(config: MechanismConfig) -> dict[str, float]:
    """Each enabled criterion's share of the total, summing to 1: its share of
    its cluster times the cluster's share of all clusters that have one."""
    criteria = [c for c in config.level_criteria if c.enabled]
    clusters = {d.id: d.weight for d in config.dimensions}
    in_cluster: dict[str, float] = {}
    for c in criteria:
        in_cluster[c.dimension_id] = in_cluster.get(c.dimension_id, 0.0) + c.weight
    used = {d: w for d, w in clusters.items() if in_cluster.get(d)}
    total = sum(used.values())
    if not total:
        return {}
    return {
        c.id: (c.weight / in_cluster[c.dimension_id]) * (used[c.dimension_id] / total)
        for c in criteria
        if c.dimension_id in used
    }


def evaluate_levels(dataset: Dataset, config: MechanismConfig, profiles: dict[str, ColumnProfile]) -> tuple[list[dict[str, tuple[int | None, bool]]], int]:
    """Per row, per criterion: (level, from_default). A rule whose condition
    cannot be decided on a row -- a comparison against a blank value, or a
    blank flag -- does not match. If no rule holds, the criterion's
    `otherwise` applies, unless a rule was undecided and the criterion has
    `otherwise_on_blank` off: then the row gets no level. Returns the levels
    and how many rule evaluations errored."""
    contexts = rule_inputs(dataset, profiles)
    criteria = [c for c in config.level_criteria if c.enabled]
    compiled = {(c.id, i): zen.compile_expression(r.when) for c in criteria for i, r in enumerate(c.rules) if r.when.strip()}
    errors = 0
    out: list[dict[str, tuple[int | None, bool]]] = []
    for context in contexts:
        row: dict[str, tuple[int | None, bool]] = {}
        for criterion in criteria:
            level: int | None = None
            blank = False  # a rule could not be decided: a value it reads is blank
            for i, rule in enumerate(criterion.rules):
                if (criterion.id, i) not in compiled:  # a rule not written yet
                    continue
                try:
                    hit = compiled[(criterion.id, i)].evaluate(context)
                except Exception:  # noqa: BLE001 - a blank the rule compares against
                    errors += 1
                    blank = True
                    continue
                if hit is True:
                    level = rule.level
                    break
                blank = blank or not isinstance(hit, bool)  # a bare blank flag evaluates to null
            if level is not None:
                row[criterion.id] = (level, False)
            elif blank and not criterion.otherwise_on_blank:
                row[criterion.id] = (None, False)
            else:
                row[criterion.id] = (criterion.otherwise, criterion.otherwise is not None)
        out.append(row)
    return out, errors


def _missing_level(config: MechanismConfig) -> float | None:
    """How a criterion without a level counts: `penalise` as the bottom of
    the scale, `neutral` as its midpoint, otherwise not at all (the scores
    are averaged over the criteria that have a level)."""
    if config.missing == "penalise":
        return float(config.level_min)
    if config.missing == "neutral":
        return (config.level_min + config.level_max) / 2
    return None


def apply_overrides(
    dataset: Dataset, config: MechanismConfig, levels: list[dict[str, tuple[int | None, bool]]], overrides: list[LevelOverride], audit: list[AuditEntry]
) -> dict[tuple[int, str], tuple[int | None, LevelOverride]]:
    """Puts reviewers' levels in place of the rules' ones. Returns, per
    (row, criterion) overridden, the level the rules gave and the override.
    An override that no longer fits -- the entity or criterion is gone, or
    the level is off this framework's scale -- is left out, and says so."""
    rows = {str(row.get(config.label_column) or f"row_{i + 1}"): i for i, row in enumerate(dataset.rows)}
    criteria = {c.id: c for c in config.level_criteria}
    applied: dict[tuple[int, str], tuple[int | None, LevelOverride]] = {}
    for override in overrides:
        criterion = criteria.get(override.criterion_id)
        i = rows.get(override.entity_key)
        problem = (
            "the entity is not in this table" if i is None
            else "the criterion is not in this framework version" if criterion is None
            else f"level {override.level} is off the {config.level_min}-{config.level_max} scale"
            if not config.level_min <= override.level <= config.level_max
            else None
        )
        item = f"{override.entity_key} · {criterion.name if criterion else override.criterion_id}"
        if problem:
            audit.append(AuditEntry(stage="Overrides", item=item, decision="not applied", why=f"{problem}; set by {override.reviewer}", needs_check=True))
            continue
        original = levels[i][override.criterion_id][0] if override.criterion_id in levels[i] else None
        levels[i][override.criterion_id] = (override.level, False)
        applied[(i, override.criterion_id)] = (original, override)
        audit.append(
            AuditEntry(
                stage="Overrides",
                item=item,
                decision=f"level {'none' if original is None else original} -> {override.level} by {override.reviewer}",
                why=override.reason,
            )
        )
    return applied


def apply_levels(
    dataset: Dataset,
    config: MechanismConfig,
    profiles: dict[str, ColumnProfile],
    audit: list[AuditEntry],
    overrides: list[LevelOverride] | None = None,
) -> DecisionResult:
    from arp.decision.mechanism import _PREVIEW_ROWS, _cohort_values, _cuts_fallback_reason, _histogram, _tier_summary

    n = dataset.row_count
    weights = level_weights(config)
    criteria: dict[str, LevelCriterion] = {c.id: c for c in config.level_criteria if c.enabled and c.id in weights}
    levels, errors = evaluate_levels(dataset, config, profiles)
    overridden = apply_overrides(dataset, config, levels, overrides or [], audit)
    if errors:
        audit.append(
            AuditEntry(
                stage="Levels",
                item="Rule conditions",
                decision=f"{errors} evaluations did not match because a value was blank or of the wrong type",
                why="missing data never earns a level; such a row falls to the next rule, then to the criterion's default",
                needs_check=True,
            )
        )
    missing_as = _missing_level(config)
    cohorts = _cohort_values(dataset, config)

    rows_scored: list[tuple[float | None, float, dict[str, float | None], list[CriterionContribution]]] = []
    for i in range(n):
        contributions: list[CriterionContribution] = []
        by_cluster: dict[str, list[tuple[float, float]]] = {}
        covered = 0.0
        for cid, criterion in criteria.items():
            level, from_default = levels[i][cid]
            value = float(level) if level is not None else missing_as
            imputed = from_default or (level is None and value is not None)
            if level is not None:
                covered += weights[cid]
            if value is not None:
                by_cluster.setdefault(criterion.dimension_id, []).append((value, criterion.weight))
            original, override = overridden.get((i, cid), (None, None))
            contributions.append(
                CriterionContribution(
                    column=criterion.name,
                    normalised=value,
                    weight=weights[cid],
                    contribution=(value or 0.0) * weights[cid],
                    imputed=imputed,
                    criterion_id=cid,
                    overridden_from=float(original) if override is not None and original is not None else None,
                    override=override,
                )
            )
        cluster_scores: dict[str, float | None] = {}
        for dimension in config.dimensions:
            members = by_cluster.get(dimension.id)
            cluster_scores[dimension.id] = sum(v * w for v, w in members) / sum(w for _, w in members) if members and sum(w for _, w in members) else None
        present = [(s, d.weight) for d in config.dimensions if (s := cluster_scores.get(d.id)) is not None and d.weight > 0]
        total = sum(s * w for s, w in present) / sum(w for _, w in present) if present else None
        rows_scored.append((total, covered, cluster_scores, contributions))

    gate_hits: list[list[GateRule]] = []
    excluded_by: list[GateRule | None] = []
    insufficient: list[bool] = []
    for i in range(n):
        hits = [g for g in config.gates if (not config.tier_graph or g.outcome == "exclude") and gate_hit(g, dataset, profiles, i)]
        gate_hits.append(hits)
        excluded_by.append(next((g for g in hits if g.outcome == "exclude"), None))
        total, covered, _, _ = rows_scored[i]
        insufficient.append(total is None or covered * 100 < config.min_coverage_pct)

    eligible = [s[0] if excluded_by[i] is None and not insufficient[i] else None for i, s in enumerate(rows_scored)]
    cuts, cuts_origin = derive_cuts(eligible, config)
    ranks = ranks_of(eligible)
    tiers_by_rank = {t.rank: t for t in config.tiers}
    lowest_tier = max(tiers_by_rank) if tiers_by_rank else 4
    size_profile = profiles.get(config.size_column) if config.size_column else None
    span = config.level_max - config.level_min

    entities: list[EntityDecision] = []
    for i, row in enumerate(dataset.rows):
        total, covered, cluster_scores, contributions = rows_scored[i]
        notes: list[str] = [f"Override: {c.column} {'—' if c.overridden_from is None else f'{c.overridden_from:g}'} → {c.normalised:g}" for c in contributions if c.override is not None]
        status = "scored"
        tier: int | None = None
        if excluded_by[i] is not None:
            status = "excluded"
            notes.append(f"Gate: {pretty(excluded_by[i].column)}")
        elif insufficient[i]:
            status = "insufficient"
            notes.append(f"{covered * 100:.0f}% of weight has a level")
        else:
            tier = tier_for_score(total, cuts)
            demotions = [g for g in gate_hits[i] if g.outcome == "demote"]
            notes.extend(f"Demoted: {pretty(g.column)}" for g in demotions)
            if demotions:
                tier = min(lowest_tier, tier + len(demotions))
            notes.extend(f"Flag: {pretty(g.column)}" for g in gate_hits[i] if g.outcome == "flag")
        size = to_number(row.get(config.size_column), size_profile.decimal_comma) if size_profile else None
        tier_definition = tiers_by_rank.get(tier) if tier else None
        entities.append(
            EntityDecision(
                entity_key=str(row.get(config.label_column) or f"row_{i + 1}"),
                name=str(row.get(config.label_column) or f"Row {i + 1}"),
                segment=(row.get(config.segment_column) or None) if config.segment_column else None,
                cohort=cohorts[i] if cohorts else None,
                score=total,
                coverage=covered,
                grounded_coverage=None,
                status=status,
                tier=tier,
                tier_name=tier_definition.name if tier_definition else None,
                tier_action=tier_definition.action if tier_definition else None,
                notes=notes,
                rank=ranks[i] if status == "scored" else None,
                rank_min=ranks[i] if status == "scored" else None,
                rank_max=ranks[i] if status == "scored" else None,
                size=size,
                # Position size times the gap to the top of the scale, as the
                # relative mode does with the gap to 100.
                leverage=(size * (config.level_max - total) / span) if (size is not None and total is not None and status == "scored") else None,
                dimension_scores=cluster_scores,
                contributions=contributions,
            )
        )

    bands = [tier_for_score(e.score, cuts) if e.status == "scored" and e.score is not None else None for e in entities]
    level_keys = {cid: f"lvl_{slug(c.name)}" for cid, c in criteria.items()}
    contexts = tier_contexts(dataset, profiles, entities, bands, config, limit=None if config.tier_graph else _PREVIEW_ROWS)
    for i, context in enumerate(contexts):
        # Tier rules can name a criterion's level directly: `lvl_governance < 3`.
        context.update({key: levels[i][cid][0] for cid, key in level_keys.items()})
    if config.tier_graph:
        audit.extend(apply_tier_graph(config.tier_graph, entities, contexts, bands, config))

    leveraged = sorted((e for e in entities if e.leverage is not None), key=lambda e: -e.leverage)
    for position, entity in enumerate(leveraged):
        entity.leverage_rank = position + 1

    audit.append(
        AuditEntry(
            stage="Cut-points",
            item=", ".join(f"{c:.2f}" for c in cuts) or "-",
            decision=cuts_origin,
            why=f"on the {config.level_min}-{config.level_max} level scale, over the {sum(1 for v in eligible if v is not None)} "
            "entities still eligible after gates and sufficiency"
            + ("" if cuts_origin == config.cut_mode else f"; '{config.cut_mode}' was requested but {_cuts_fallback_reason(config, eligible)}"),
        )
    )

    return DecisionResult(
        framework_id=config.framework_id,
        framework_version=config.version,
        dataset_id=dataset.dataset_id,
        computed_at=now_iso(),
        norm=config.norm,
        effective_cuts=cuts,
        cuts_origin=cuts_origin,
        effective_weights={criteria[cid].name: w for cid, w in weights.items() if cid in criteria},
        entities=entities,
        tier_summary=_tier_summary(entities, config),
        histogram=_histogram(entities),
        scored_count=sum(1 for e in entities if e.status == "scored"),
        excluded_count=sum(1 for e in entities if e.status == "excluded"),
        insufficient_count=sum(1 for e in entities if e.status == "insufficient"),
        audit=audit,
        tier_inputs=contexts[:_PREVIEW_ROWS],
    )
