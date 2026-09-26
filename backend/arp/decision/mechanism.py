from __future__ import annotations

from arp.decision import cluster as clustering
from arp.decision.dataset import Dataset
from arp.decision.normalise import normalise_column
from arp.decision.parsing import to_number
from arp.decision.profiling import numeric_values, profile_dataset
from arp.decision.roles import has_keyword, load_keywords, pretty, propose_cohort_column, propose_roles
from arp.decision.rules import apply_rules
from arp.decision.scoring import compute_scores, ranks_of
from arp.decision.stability import ALTERNATIVE_PRESETS, alternative_norm, rank_ranges
from arp.decision.tree import derive_cuts, dimension_scores, gate_hit, tier_for_score, veto_dimensions
from arp.decision.weighting import breadth_adjusted_weight, effective_weights
from arp.schemas.common import now_iso
from arp.schemas.decision import (
    AuditEntry,
    ColumnProfile,
    Criterion,
    DecisionResult,
    Dimension,
    EntityDecision,
    GateRule,
    HistogramBin,
    MechanismConfig,
    NormMethod,
    RoleProposal,
    TierSummary,
)

_HISTOGRAM_BINS = 20


def _cohort_values(dataset: Dataset, config: MechanismConfig) -> list[str | None] | None:
    if not config.normalise_within or config.normalise_within not in dataset.columns:
        return None
    return [(row.get(config.normalise_within) or "").strip() or None for row in dataset.rows]


def _normalise_all(
    dataset: Dataset,
    profiles: dict[str, ColumnProfile],
    config: MechanismConfig,
    columns: list[str],
    method: NormMethod,
    cohorts: list[str | None] | None,
) -> dict[str, list[float | None]]:
    directions = {c.column: c.direction for c in config.criteria}
    out: dict[str, list[float | None]] = {}
    for column in columns:
        profile = profiles.get(column)
        if profile is None:
            continue
        out[column] = normalise_column(
            numeric_values(dataset, profile),
            profile,
            method=method,
            winsor_pct=config.winsor_pct,
            direction=directions.get(column, "higher"),
            cohorts=cohorts,
            min_cohort_size=config.min_cohort_size,
        )
    return out


def active_criteria(config: MechanismConfig, profiles: dict[str, ColumnProfile]) -> list[str]:
    return [c.column for c in config.criteria if c.enabled and c.column in profiles]


def derive_mechanism(dataset: Dataset, *, name: str | None = None, cluster_threshold: float = 0.72) -> tuple[MechanismConfig, list[AuditEntry]]:
    """Reads a table and proposes a complete mechanism for it, with an
    audit entry behind every choice.

    Nothing here is applied: the result is a proposal a human edits and
    ratifies. That separation is the whole point -- `apply_mechanism` then
    runs a *fixed* set of rules against any dataset, including next
    quarter's.
    """
    profiles = profile_dataset(dataset)
    proposals = propose_roles(profiles, dataset.columns)
    audit: list[AuditEntry] = []

    config = MechanismConfig(name=name or f"Framework for {dataset.name}", cluster_threshold=cluster_threshold)

    for proposal in proposals:
        audit.append(
            AuditEntry(stage="Roles", item=proposal.column, decision=proposal.role, why=proposal.role_reason)
        )
        if proposal.role == "criterion":
            audit.append(
                AuditEntry(
                    stage="Direction",
                    item=proposal.column,
                    decision="higher is better" if proposal.direction == "higher" else "lower is better",
                    why=proposal.direction_reason,
                    needs_check=proposal.needs_check,
                )
            )

    by_role: dict[str, list[RoleProposal]] = {}
    for proposal in proposals:
        by_role.setdefault(proposal.role, []).append(proposal)

    config.label_column = by_role.get("label", [None])[0].column if by_role.get("label") else (dataset.columns[0] if dataset.columns else None)
    config.size_column = by_role["size"][0].column if by_role.get("size") else None
    config.segment_column = by_role["segment"][0].column if by_role.get("segment") else None

    cohort_column, cohort_reason = propose_cohort_column(profiles, proposals, dataset.row_count, config.min_cohort_size)
    config.normalise_within = cohort_column
    audit.append(
        AuditEntry(
            stage="Peer cohorts",
            item=cohort_column or "(whole table)",
            decision="normalise within cohort" if cohort_column else "normalise across the whole table",
            why=cohort_reason
            + (
                " -- an indicator's percentile is only meaningful against comparable peers"
                if cohort_column
                else ""
            ),
            needs_check=cohort_column is None,
        )
    )

    for proposal in by_role.get("gate", []):
        severe = has_keyword(proposal.column, load_keywords()["severe"])
        config.gates.append(GateRule(column=proposal.column, op="is", value="Yes", outcome="exclude" if severe else "demote"))
        audit.append(
            AuditEntry(
                stage="Gates",
                item=proposal.column,
                decision="hard exclusion" if severe else "demote one tier",
                why=(
                    "severity wording -- a knockout belongs in the tree, not in the average"
                    if severe
                    else "flag wording -- treated as a modifier so it cannot be averaged away"
                ),
            )
        )

    criteria_columns = [p.column for p in by_role.get("criterion", [])]
    if not criteria_columns:
        audit.append(
            AuditEntry(
                stage="Dimensions",
                item="-",
                decision="no criteria found",
                why="no numeric, ordinal or binary column carried usable spread",
                needs_check=True,
            )
        )
        return config, audit

    config.criteria = [
        Criterion(column=p.column, dimension_id="", weight=1.0, enabled=True, direction=p.direction)
        for p in by_role["criterion"]
    ]
    cohorts = _cohort_values(dataset, config)
    reference = _normalise_all(dataset, profiles, config, criteria_columns, "percentile", cohorts)
    correlations = clustering.correlation_matrix(reference)
    clusters = clustering.cluster_criteria(criteria_columns, correlations, config.cluster_threshold)

    criteria_by_column = {c.column: c for c in config.criteria}
    for index, members in enumerate(clusters):
        dimension_id = f"d{index}"
        dimension_name = clustering.name_cluster(members, correlations)
        config.dimensions.append(
            Dimension(id=dimension_id, name=dimension_name, weight=breadth_adjusted_weight(len(members)), derived_from=list(members))
        )
        for member in members:
            criteria_by_column[member].dimension_id = dimension_id
        if len(members) > 1:
            low, high = clustering.cluster_range(members, correlations)
            audit.append(
                AuditEntry(
                    stage="Dimensions",
                    item=dimension_name,
                    decision=f"{len(members)} criteria grouped",
                    why=(
                        f"rank correlation {low:.2f}-{high:.2f} between "
                        + ", ".join(pretty(m) for m in members)
                        + f" (complete linkage at {config.cluster_threshold:.2f}) -- grouped so the shared signal is counted once"
                    ),
                )
            )
        else:
            audit.append(
                AuditEntry(
                    stage="Dimensions",
                    item=dimension_name,
                    decision="stands alone",
                    why=f"no rank correlation at or above {config.cluster_threshold:.2f} with any other criterion",
                )
            )

    audit.append(
        AuditEntry(
            stage="Weighting",
            item="Preset",
            decision="breadth-adjusted dimensions",
            why=(
                f"{len(config.dimensions)} dimensions weighted by the square root of how many criteria they hold -- "
                "a theme measured seven ways counts for more than one measured once, but not seven times more; "
                "criteria then split their dimension evenly"
            ),
        )
    )
    audit.append(
        AuditEntry(
            stage="Normalisation",
            item="Method",
            decision="percentile rank",
            why="ranks are unaffected by outliers and by the units each indicator is reported in",
        )
    )
    audit.append(
        AuditEntry(
            stage="Missing data",
            item="Policy",
            decision="re-weight over what is present",
            why=(
                f"no value is invented; an entity below {config.min_coverage_pct:.0f}% of weight covered is routed "
                "to a data-collection outcome instead of being scored"
            ),
        )
    )
    audit.append(
        AuditEntry(
            stage="Comparability",
            item="Cluster threshold",
            decision=f"{config.cluster_threshold:.2f}",
            why=(
                "the rank-correlation floor for grouping two criteria into one dimension. It is a judgement call, "
                "so two frameworks derived at different thresholds are not directly comparable"
            ),
        )
    )
    return config, audit


def apply_mechanism(
    dataset: Dataset,
    config: MechanismConfig,
    *,
    derivation_audit: list[AuditEntry] | None = None,
    with_stability: bool = True,
) -> DecisionResult:
    """Applies a fixed mechanism to a table.

    The evaluation order is fixed and is the reason results are
    reproducible: sufficiency, then hard gates, then the score band, then
    modifiers. Anything a gate settles never reaches the score.

    A framework's rule graph runs first of all: its calculated columns
    are part of the table every later step sees.
    """
    audit = list(derivation_audit or [])
    if config.rule_graph:
        dataset, rule_audit = apply_rules(dataset, config.rule_graph)
        audit.extend(rule_audit)
    profiles = profile_dataset(dataset)
    columns = active_criteria(config, profiles)
    cohorts = _cohort_values(dataset, config)
    n = dataset.row_count

    normalised = _normalise_all(dataset, profiles, config, columns, config.norm, cohorts)
    # Always computed: entropy weighting needs it, and so does the
    # entropy alternative specification the rank-stability band is
    # measured over, whatever preset the framework itself uses.
    minmax = _normalise_all(dataset, profiles, config, columns, "minmax", cohorts)
    weights = effective_weights(config, columns, minmax)
    confidence = {c: dataset.confidence[c] for c in columns if c in dataset.confidence}
    base = compute_scores(
        normalised,
        weights,
        missing=config.missing,
        row_count=n,
        confidence=confidence,
        confidence_min=config.grounded_confidence_min,
    )

    use_grounded = config.require_grounded_coverage and bool(confidence)
    if config.require_grounded_coverage and not confidence:
        audit.append(
            AuditEntry(
                stage="Sufficiency",
                item="Grounded coverage",
                decision="not available",
                why=(
                    "the framework asks for grounded coverage but this table carries no per-cell confidence, so the "
                    "sufficiency gate fell back to plain weight covered -- a table built from an extraction run "
                    "would carry it"
                ),
                needs_check=True,
            )
        )

    gate_hits: list[list[GateRule]] = []
    excluded_by: list[GateRule | None] = []
    insufficient: list[bool] = []
    for i in range(n):
        hits = [g for g in config.gates if gate_hit(g, dataset, profiles, i)]
        gate_hits.append(hits)
        excluded_by.append(next((g for g in hits if g.outcome == "exclude"), None))
        coverage = base[i].grounded_coverage if use_grounded else base[i].coverage
        coverage = coverage if coverage is not None else base[i].coverage
        insufficient.append(base[i].score is None or coverage * 100 < config.min_coverage_pct)

    def mask(values: list[float | None]) -> list[float | None]:
        return [v if (excluded_by[i] is None and not insufficient[i]) else None for i, v in enumerate(values)]

    eligible = mask([b.score for b in base])
    cuts, cuts_origin = derive_cuts(eligible, config)

    # with_stability=False is for callers that re-run this many times over
    # (the tipping-point sweep in `sensitivity.py`), where the rank band of
    # each intermediate run is computed and thrown away.
    specifications = [eligible]
    if with_stability:
        for preset in ALTERNATIVE_PRESETS:
            alt_weights = effective_weights(config, columns, minmax, preset=preset)
            alt = compute_scores(normalised, alt_weights, missing=config.missing, row_count=n)
            specifications.append(mask([r.score for r in alt]))
        alt_norm = _normalise_all(dataset, profiles, config, columns, alternative_norm(config.norm), cohorts)
        alt_scores = compute_scores(alt_norm, weights, missing=config.missing, row_count=n)
        specifications.append(mask([r.score for r in alt_scores]))

    rank_min, rank_max = rank_ranges(specifications)
    ranks = ranks_of(eligible)

    tiers_by_rank = {t.rank: t for t in config.tiers}
    lowest_tier = max(tiers_by_rank) if tiers_by_rank else 4
    vetoable = veto_dimensions(config, columns)
    dimension_names = {d.id: d.name for d in config.dimensions}
    size_profile = profiles.get(config.size_column) if config.size_column else None

    entities: list[EntityDecision] = []
    for i, row in enumerate(dataset.rows):
        row_score = base[i]
        dimensions = dimension_scores(row_score.contributions, config)
        notes: list[str] = []
        status = "scored"
        tier: int | None = None

        if excluded_by[i] is not None:
            status = "excluded"
            notes.append(f"Gate: {pretty(excluded_by[i].column)}")
        elif insufficient[i]:
            status = "insufficient"
            covered = row_score.grounded_coverage if use_grounded else row_score.coverage
            label = "grounded weight covered" if use_grounded else "of weight covered"
            notes.append(f"{(covered or 0.0) * 100:.0f}% {label}")
        else:
            tier = tier_for_score(row_score.score, cuts)
            demotions = [g for g in gate_hits[i] if g.outcome == "demote"]
            for gate in demotions:
                notes.append(f"Demoted: {pretty(gate.column)}")
            veto_name = None
            for dimension_id in vetoable:
                value = dimensions.get(dimension_id)
                if value is not None and value < config.veto.min_score:
                    veto_name = dimension_names.get(dimension_id, dimension_id)
                    break
            if veto_name:
                notes.append(f"Demoted: {veto_name} below {config.veto.min_score:.0f}")
            steps = len(demotions) + (1 if veto_name else 0)
            if steps:
                tier = min(lowest_tier, tier + steps)
            for gate in gate_hits[i]:
                if gate.outcome == "flag":
                    notes.append(f"Flag: {pretty(gate.column)}")

        size = to_number(row.get(config.size_column), size_profile.decimal_comma) if size_profile else None
        tier_definition = tiers_by_rank.get(tier) if tier else None
        entities.append(
            EntityDecision(
                entity_key=str(row.get(config.label_column) or f"row_{i + 1}"),
                name=str(row.get(config.label_column) or f"Row {i + 1}"),
                segment=(row.get(config.segment_column) or None) if config.segment_column else None,
                cohort=cohorts[i] if cohorts else None,
                score=row_score.score,
                coverage=row_score.coverage,
                grounded_coverage=row_score.grounded_coverage,
                status=status,
                tier=tier,
                tier_name=tier_definition.name if tier_definition else None,
                tier_action=tier_definition.action if tier_definition else None,
                notes=notes,
                rank=ranks[i] if status == "scored" else None,
                rank_min=rank_min[i] if status == "scored" else None,
                rank_max=rank_max[i] if status == "scored" else None,
                size=size,
                leverage=(size * (100.0 - row_score.score) / 100.0) if (size is not None and row_score.score is not None and status == "scored") else None,
                dimension_scores=dimensions,
                contributions=row_score.contributions,
            )
        )

    leveraged = sorted((e for e in entities if e.leverage is not None), key=lambda e: -e.leverage)
    for position, entity in enumerate(leveraged):
        entity.leverage_rank = position + 1

    audit.append(
        AuditEntry(
            stage="Cut-points",
            item=", ".join(f"{c:.1f}" for c in cuts) or "-",
            decision=cuts_origin,
            why=(
                f"drawn over the {sum(1 for v in eligible if v is not None)} entities still eligible after gates and "
                "sufficiency -- an excluded entity should not move the band its peers are judged against"
            )
            + ("" if cuts_origin == config.cut_mode else f"; '{config.cut_mode}' was requested but there was too little data for it"),
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
        effective_weights=weights,
        entities=entities,
        tier_summary=_tier_summary(entities, config),
        histogram=_histogram(entities),
        scored_count=sum(1 for e in entities if e.status == "scored"),
        excluded_count=sum(1 for e in entities if e.status == "excluded"),
        insufficient_count=sum(1 for e in entities if e.status == "insufficient"),
        audit=audit,
    )


def _tier_summary(entities: list[EntityDecision], config: MechanismConfig) -> list[TierSummary]:
    summary: list[TierSummary] = []
    for definition in sorted(config.tiers, key=lambda t: t.rank):
        members = [e for e in entities if e.tier == definition.rank]
        sizes = [e.size for e in members if e.size is not None]
        summary.append(
            TierSummary(
                rank=definition.rank,
                name=definition.name,
                action=definition.action,
                count=len(members),
                size_total=sum(sizes) if sizes else None,
            )
        )
    return summary


def _histogram(entities: list[EntityDecision]) -> list[HistogramBin]:
    scores = [e.score for e in entities if e.status == "scored" and e.score is not None]
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if high <= low:
        return [HistogramBin(lower=low, upper=low, count=len(scores))]
    width = (high - low) / _HISTOGRAM_BINS
    bins = [HistogramBin(lower=low + i * width, upper=low + (i + 1) * width, count=0) for i in range(_HISTOGRAM_BINS)]
    for score in scores:
        index = min(_HISTOGRAM_BINS - 1, int((score - low) / width))
        bins[index].count += 1
    return bins
