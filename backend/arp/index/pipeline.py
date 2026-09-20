from __future__ import annotations

from math import fsum

from arp.index.calc import divisor_for_level, index_shares, market_cap, one_way_turnover
from arp.index.capping import apply_constraints
from arp.index.fields import metric_value
from arp.index.screens import apply_screens
from arp.index.selection import apply_selection
from arp.index.trajectory import apply_trajectory
from arp.index.weighting import apply_tilts, base_weights, weighted_average
from arp.schemas.index import (
    Constituent,
    ConstructionSpec,
    IndexCandidate,
    IndexState,
    ReviewDiagnostics,
    ReviewResult,
    StageTrace,
)


def _all_metric_fields(candidates: list[IndexCandidate]) -> list[str]:
    fields: set[str] = set()
    for candidate in candidates:
        fields.update(candidate.metrics)
    return sorted(fields)


def run_review(
    spec: ConstructionSpec,
    candidates: list[IndexCandidate],
    *,
    index_id: str,
    review_date: str,
    prior_state: IndexState | None = None,
    calibration_id: str | None = None,
    calibration_version: int | None = None,
) -> ReviewResult:
    """Runs one index review end to end, deterministically.

    `f(data, spec, prior_state)` -- the third argument is what a
    path-dependent methodology needs and what a pure screening or tilting
    one ignores. Every stage appends a trace line, so the funnel a committee
    reviews and the audit trail a regulator asks for are the same object.
    """
    universe = sorted(candidates, key=lambda c: c.company_id)
    if not universe:
        raise ValueError("the parent universe is empty")

    traces: list[StageTrace] = [
        StageTrace(
            stage="universe",
            rule_type="parent_universe",
            label="parent universe",
            candidates_in=len(universe),
            candidates_out=len(universe),
            detail={"index_currency": spec.index_currency},
        )
    ]
    exceptions: list[str] = []

    eligible, screen_traces = apply_screens(universe, spec.screens)
    traces.extend(screen_traces)
    if not eligible:
        raise ValueError("every company was screened out -- no eligible universe remains")

    incumbents = set(prior_state.prior_members) if prior_state else set()
    selected, selection_trace, selection_exceptions = apply_selection(eligible, spec.selection, incumbents)
    traces.append(selection_trace)
    exceptions.extend(selection_exceptions)
    if not selected:
        raise ValueError("the selection rule selected no companies")

    weights = base_weights(selected, spec.base_weighting)
    traces.append(
        StageTrace(
            stage="weighting",
            rule_type=spec.base_weighting.scheme,
            label=f"base weighting: {spec.base_weighting.scheme}",
            candidates_in=len(selected),
            candidates_out=len(weights),
            detail={"max_weight": round(max(weights.values()), 6), "field": spec.base_weighting.field or ""},
        )
    )
    base_snapshot = dict(weights)

    weights, tilt_multipliers, tilt_traces = apply_tilts(weights, selected, spec.tilts)
    traces.extend(tilt_traces)
    # What the methodology asked for, before any constraint touched it. The
    # least-squares path projects from here so the result is the closest
    # feasible portfolio to the rules' own target, not to an
    # already-constrained intermediate.
    methodology_target = dict(weights)

    weights, constraint_trace, constraint_exceptions = apply_constraints(weights, selected, spec.constraints)
    traces.append(constraint_trace)
    exceptions.extend(constraint_exceptions)

    state = IndexState(index_id=index_id, review_date=review_date)
    trajectory_iterations = 0
    if spec.trajectory.enabled:
        weights, state, trajectory_trace, trajectory_exceptions = apply_trajectory(
            weights,
            selected,
            spec.trajectory,
            spec.constraints,
            index_id=index_id,
            review_date=review_date,
            universe_candidates=eligible,
            prior_state=prior_state,
            projection_base=methodology_target,
        )
        traces.append(trajectory_trace)
        exceptions.extend(trajectory_exceptions)
        trajectory_iterations = int(trajectory_trace.detail.get("iterations", 0) or 0)

    weights = {k: round(v, spec.rounding.weight_decimals) for k, v in sorted(weights.items())}

    previous_level = prior_state.index_level if prior_state and prior_state.index_level else spec.calendar.base_level
    previous_divisor = prior_state.divisor if prior_state and prior_state.divisor else None
    if previous_divisor:
        # A continuing index is reconstituted at its current capitalisation,
        # `level x divisor`, which is what keeps the level continuous across
        # the rebalance.
        target_market_cap = previous_level * previous_divisor
    else:
        # Inception: capitalise the index at the real aggregate float market
        # cap of its constituents and derive the divisor from the base level.
        # Using the bare base level instead would make index shares a few
        # hundredths of a share -- arithmetically valid, but unusable for
        # anyone replicating the index.
        target_market_cap = fsum(c.float_mcap for c in selected)
    shares = index_shares(weights, selected, index_market_cap=target_market_cap, rounding=spec.rounding)
    realised_market_cap = market_cap(shares, selected)
    # The divisor is derived from the ROUNDED shares, so the published
    # shares reproduce the published level exactly rather than leaving a
    # rounding residual that compounds review after review.
    divisor = divisor_for_level(realised_market_cap, previous_level)

    by_id = {c.company_id: c for c in selected}
    constituents = [
        Constituent(
            company_id=company_id,
            name=by_id[company_id].name,
            sector=by_id[company_id].sector,
            country=by_id[company_id].country,
            weight=weights[company_id],
            base_weight=round(base_snapshot.get(company_id, 0.0), spec.rounding.weight_decimals),
            tilt_multiplier=round(tilt_multipliers.get(company_id, 1.0), 6),
            capping_factor=round(weights[company_id] / base_snapshot[company_id], 6) if base_snapshot.get(company_id) else 1.0,
            price=by_id[company_id].price,
            fx_rate=by_id[company_id].fx_rate,
            index_shares=shares[company_id],
            metrics=dict(sorted(by_id[company_id].metrics.items())),
        )
        for company_id in sorted(weights)
    ]

    metric_fields = _all_metric_fields(selected)
    universe_weights = base_weights(eligible, spec.base_weighting)
    weighted_metrics: dict[str, float] = {}
    universe_metrics: dict[str, float] = {}
    for field in metric_fields:
        values = {c.company_id: metric_value(c, field) for c in selected}
        clean = {k: v for k, v in values.items() if v is not None}
        index_value = weighted_average(weights, clean)
        if index_value is not None:
            weighted_metrics[field] = round(index_value, 6)
        universe_values = {c.company_id: metric_value(c, field) for c in eligible}
        universe_clean = {k: v for k, v in universe_values.items() if v is not None}
        universe_value = weighted_average(universe_weights, universe_clean)
        if universe_value is not None:
            universe_metrics[field] = round(universe_value, 6)

    turnover = one_way_turnover(prior_state.prior_weights, weights) if prior_state and prior_state.prior_weights else None
    sum_squares = fsum(w * w for w in weights.values())

    state = state.model_copy(
        update={
            "index_id": index_id,
            "review_date": review_date,
            "divisor": divisor,
            "index_level": previous_level,
            "prior_weights": weights,
            "prior_members": sorted(weights),
        }
    )

    diagnostics = ReviewDiagnostics(
        universe_size=len(universe),
        eligible_size=len(eligible),
        selected_size=len(selected),
        final_size=len(weights),
        weighted_metrics=weighted_metrics,
        universe_weighted_metrics=universe_metrics,
        effective_n=round(1.0 / sum_squares, 4) if sum_squares > 0 else 0.0,
        max_weight=round(max(weights.values()), 6),
        one_way_turnover=round(turnover, 6) if turnover is not None else None,
        capping_iterations=int(constraint_trace.detail.get("iterations", 0) or 0),
        trajectory_iterations=trajectory_iterations,
    )

    # The constraint set is applied once here and, when a trajectory is
    # enabled, again inside it with the intensity target added. Keeping both
    # passes is deliberate -- the standalone one is the safety net for a
    # trajectory that has no target yet -- but a condition that trips in both
    # should be reported once, not twice, on the committee pack.
    exceptions = list(dict.fromkeys(exceptions))

    return ReviewResult(
        index_id=index_id,
        review_date=review_date,
        calibration_id=calibration_id,
        calibration_version=calibration_version,
        config_hash=spec.content_hash(),
        constituents=constituents,
        diagnostics=diagnostics,
        trace=traces,
        state=state,
        exceptions=exceptions,
    )
