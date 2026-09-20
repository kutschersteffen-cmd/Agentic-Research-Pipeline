from __future__ import annotations

from datetime import date
from typing import Callable
from math import exp, fsum

from arp.index.fields import EPS, metric_value, resolve_missing
from arp.index.optimize import LinearConstraint
from arp.index.risk import RiskModel
from arp.index.weighting import normalise, weighted_average
from arp.schemas.index import (
    ConstraintSet,
    DecarbonisationTrajectory,
    IndexCandidate,
    IndexState,
    StageTrace,
)


def _tolerance_for(target: float, rule_tolerance: float) -> float:
    """Scale the convergence tolerance to the magnitude of the target.

    A GHG intensity target is ~10^2 and a green-revenue-share target is
    ~10^-1; an absolute tolerance that suits one reports spurious misses on
    the other. Relative tolerance makes the convergence test mean the same
    thing for any metric.
    """
    return rule_tolerance * max(1.0, abs(target))


def minimum_achievable(values: dict[str, float], single_name_cap: float | None) -> float | None:
    """The lowest weighted average the constraint set can reach: fill from
    the lowest-metric name down, each at the single-name cap.

    An optimistic bound (it ignores group caps and 5/10/40, which can only
    tighten it), which is exactly what makes it useful in an error message:
    if the target is below this, no weighting can reach it and the honest
    answer is to relax a constraint, widen the universe, or lower the
    ambition -- not to iterate harder.
    """
    if not values:
        return None
    ordered = sorted(values.items(), key=lambda kv: (kv[1], kv[0]))
    cap = single_name_cap if single_name_cap and single_name_cap > 0 else 1.0
    remaining, total = 1.0, 0.0
    for _company_id, value in ordered:
        take = min(cap, remaining)
        total += take * value
        remaining -= take
        if remaining <= 1e-12:
            break
    if remaining > 1e-9:
        # Not enough names to reach full weight at this cap -- the cap
        # itself is infeasible; the capping waterfall reports that.
        return total / (1.0 - remaining) if remaining < 1.0 else None
    return total


def _years_between(base: str, review: str) -> float:
    """Whole-year count from the base date, floored at zero.

    Deliberately not a fractional day count: the EU trajectory is a
    year-on-year geometric progression, so a review three months after the
    base owes the base level, not a quarter of the first year's cut.
    """
    b, r = date.fromisoformat(base), date.fromisoformat(review)
    years = r.year - b.year - (1 if (r.month, r.day) < (b.month, b.day) else 0)
    return float(max(0, years))


def required_metric_value(
    rule: DecarbonisationTrajectory,
    *,
    review_date: str,
    base_date: str | None,
    base_value: float | None,
    universe_value: float | None,
    shortfall_carry: float,
) -> tuple[float | None, str]:
    """The target the index must hit at this review, and which constraint
    set it.

    Two reductions bind at once and one of them moves. The trajectory decays
    geometrically from a *fixed* base; the universe-relative floor is
    measured against the investable universe *as it stands at this review*,
    which itself decarbonises over time. Whichever is tighter binds, and
    which one that is can change over the index's life -- so it is recorded
    per review rather than assumed.

    `shortfall_carry` implements Article 8 of Regulation (EU) 2020/1818: a
    year whose target was missed is owed, and the debt tightens the next
    target rather than being forgiven.
    """
    targets: dict[str, float] = {}
    if base_value is not None and base_date is not None:
        years = _years_between(base_date, review_date)
        target = base_value * (1.0 - rule.annual_reduction_rate) ** years
        if shortfall_carry > 0:
            target *= 1.0 - shortfall_carry
        targets["trajectory"] = target
    if rule.universe_reduction_pct is not None and universe_value is not None:
        targets["universe_relative"] = universe_value * (1.0 - rule.universe_reduction_pct)
    if not targets:
        return None, "none"
    binding = min(targets, key=lambda k: targets[k])
    return targets[binding], binding


def solve_intensity_tilt(
    weights: dict[str, float],
    values: dict[str, float],
    target: float,
    *,
    max_strength: float,
    tolerance: float,
    project: Callable[[dict[str, float]], dict[str, float]] | None = None,
) -> tuple[dict[str, float], float, int]:
    """Finds the smallest exponential tilt that brings the weighted-average
    metric down to `target`.

    `w_i(lambda) ∝ w_i · exp(-lambda · x_i)` where `x_i` is the metric scaled
    by its weighted mean. The weighted average is monotonically decreasing
    in lambda, so a bisection converges, needs no solver, no risk model and
    no licence, and returns byte-identical results everywhere. It also
    preserves the *ordering* of the input weights, so the methodology's
    tilts and caps are not silently undone by the trajectory step.

    `project` is applied to the tilted weights before the average is
    measured -- in practice, the constraint set. Searching over the
    *composed* function (tilt, then cap) rather than alternating the two is
    what makes this land on the target in one pass: alternating converges
    only slowly, because each capping step hands weight back to exactly the
    names the tilt just took it from.

    This is the Solactive-shaped route to PAB/CTB compliance rather than the
    MSCI/STOXX risk-model optimisation -- see
    `docs/INDEX_METHODOLOGY_LANDSCAPE.md` section 6 C3.
    """
    apply_projection = project or (lambda w: w)
    keys = sorted(k for k in weights if k in values)
    if not keys:
        return weights, 0.0, 0

    def waci(lam: float) -> tuple[dict[str, float], float]:
        scale = max(fsum(weights[k] * values[k] for k in keys), EPS)
        tilted = {k: weights[k] * exp(-lam * values[k] / scale) for k in keys}
        for k in weights:
            if k not in tilted:
                tilted[k] = weights[k]
        tilted = apply_projection(normalise(tilted))
        return tilted, weighted_average(tilted, values) or 0.0

    tol = _tolerance_for(target, tolerance)
    base_weights, base_value = waci(0.0)
    if base_value <= target + tol:
        return base_weights, 0.0, 0

    high_weights, high_value = waci(max_strength)
    if high_value > target + tol:
        # Even the strongest permitted tilt cannot reach the target -- the
        # eligible universe simply does not contain enough low-intensity
        # weight. The caller turns this into an exception, never a silent
        # near-miss.
        return high_weights, max_strength, 1

    low, high = 0.0, max_strength
    best = high_weights
    for iteration in range(1, 101):
        mid = (low + high) / 2.0
        candidate_weights, value = waci(mid)
        if value > target:
            low = mid
        else:
            best, high = candidate_weights, mid
        if abs(value - target) <= tol or high - low <= 1e-12:
            return best, high, iteration
    return best, high, 100


def apply_trajectory(
    weights: dict[str, float],
    candidates: list[IndexCandidate],
    rule: DecarbonisationTrajectory,
    constraints: ConstraintSet,
    *,
    index_id: str,
    review_date: str,
    universe_candidates: list[IndexCandidate],
    prior_state: IndexState | None,
    projection_base: dict[str, float] | None = None,
    risk_model: RiskModel | None = None,
    benchmark: dict[str, float] | None = None,
) -> tuple[dict[str, float], IndexState, StageTrace, list[str]]:
    """Applies the path-dependent layer and returns the state the next
    review needs."""
    from arp.index.capping import apply_constraints  # local import: capping imports weighting, not trajectory

    exceptions: list[str] = []
    values: dict[str, float] = {}
    for candidate in candidates:
        value = metric_value(candidate, rule.metric_field)
        if value is None:
            if resolve_missing(rule.missing, rule_label="decarbonisation trajectory", field=rule.metric_field, company_id=candidate.company_id):
                continue
            continue
        values[candidate.company_id] = value

    universe_values = {
        c.company_id: metric_value(c, rule.metric_field)
        for c in universe_candidates
        if metric_value(c, rule.metric_field) is not None
    }
    universe_float = {c.company_id: c.float_mcap for c in universe_candidates if c.company_id in universe_values}
    universe_weights = normalise(universe_float) if universe_float else {}
    universe_value = weighted_average(universe_weights, {k: v for k, v in universe_values.items() if v is not None}) if universe_weights else None

    base_date = prior_state.base_date if prior_state and prior_state.base_date else (rule.base_date or review_date)
    base_value = prior_state.base_metric_value if prior_state and prior_state.base_metric_value is not None else None
    shortfall = prior_state.shortfall_carry if prior_state and rule.compensate_missed_targets else 0.0

    current = dict(weights)
    achieved_before = weighted_average(current, values)
    # On the first review under this trajectory there is no base yet, so
    # only the universe-relative floor can bind. The base is then set from
    # what this review *achieved* -- the index's own intensity after
    # construction, which is what the regulation measures the year-on-year
    # reduction against. Anchoring on the pre-tilt value instead would let
    # the trajectory lag the universe floor for years and never ratchet.
    establishing_base = base_value is None

    target, binding = required_metric_value(
        rule,
        review_date=review_date,
        base_date=base_date,
        base_value=base_value,
        universe_value=universe_value,
        shortfall_carry=shortfall,
    )

    iterations = 0
    method = constraints.solver.method
    solved_by_projection = False
    if target is not None and values:
        if method != "waterfall":
            # The target is linear in the weights. `avg over covered <= tau`
            # is `sum_covered w_i (x_i - tau) <= 0`, so it goes straight into
            # the same programme as the caps and binds simultaneously with
            # them -- no tilt, no bisection, one solve. The projection starts
            # from the methodology's own target weights (pre-constraint)
            # rather than from the already-capped vector, so the answer is
            # the closest feasible portfolio to what the rules asked for.
            base = projection_base or current
            current, _trace, notes = apply_constraints(
                base,
                candidates,
                constraints,
                extra_linear=[
                    LinearConstraint(
                        label=f"{rule.metric_field} <= {target:.6f}",
                        coefficients={k: v - target for k, v in values.items()},
                        rhs=0.0,
                    )
                ],
                risk_model=risk_model,
                benchmark=benchmark,
            )
            exceptions.extend(notes)
            iterations = 1
            solved_by_projection = (weighted_average(current, values) or 0.0) <= target + _tolerance_for(target, rule.tolerance)
            if not solved_by_projection:
                exceptions.append(
                    f"the '{method}' programme did not deliver the decarbonisation target; "
                    "falling back to the deterministic tilt search"
                )
                current = dict(weights)

        if method == "waterfall" or not solved_by_projection:
            constraint_notes: list[str] = []

            def project(candidate_weights: dict[str, float]) -> dict[str, float]:
                projected, _trace, notes = apply_constraints(
                    candidate_weights, candidates, constraints, risk_model=risk_model, benchmark=benchmark
                )
                constraint_notes.extend(notes)
                return projected

            current, _strength, iterations = solve_intensity_tilt(
                current, values, target, max_strength=rule.max_tilt_strength, tolerance=rule.tolerance, project=project
            )
            # Deduplicate: the projection runs once per bisection step, so an
            # infeasible cap would otherwise be reported ~100 times.
            for note in dict.fromkeys(constraint_notes):
                exceptions.append(note)

        if (weighted_average(current, values) or 0.0) > target + _tolerance_for(target, rule.tolerance):
            floor_value = minimum_achievable(values, constraints.single_name_cap)
            reason = (
                f"target {target:.4f} is below the minimum achievable {floor_value:.4f} under a "
                f"{constraints.single_name_cap:.2%} single-name cap -- relax the cap, widen the eligible universe, "
                f"or lower the reduction"
                if floor_value is not None and target < floor_value
                else f"the eligible universe does not hold enough low-{rule.metric_field} weight"
            )
            exceptions.append(
                f"decarbonisation target {target:.4f} not reached "
                f"(achieved {weighted_average(current, values):.4f}): {reason}"
            )

    achieved = weighted_average(current, values)
    if establishing_base:
        base_value = achieved
    new_shortfall = 0.0
    if target is not None and achieved is not None and achieved > target + _tolerance_for(target, rule.tolerance):
        new_shortfall = min(1.0, max(0.0, (achieved - target) / target)) if target > EPS else 0.0
        if rule.compensate_missed_targets:
            exceptions.append(
                f"target missed by {new_shortfall:.2%}; carried forward to the next review under the compensation rule"
            )

    state = IndexState(
        index_id=index_id,
        review_date=review_date,
        base_date=base_date,
        base_metric_value=base_value,
        required_metric_value=target,
        achieved_metric_value=achieved,
        universe_metric_value=universe_value,
        shortfall_carry=new_shortfall,
        binding_constraint=binding,  # type: ignore[arg-type]
    )
    trace = StageTrace(
        stage="trajectory",
        rule_type="decarbonisation_trajectory",
        label=f"{rule.metric_field} trajectory",
        candidates_in=len(weights),
        candidates_out=len(current),
        detail={
            "binding": binding,
            "base_date": base_date or "",
            "base_value": round(base_value, 6) if base_value is not None else "",
            "target": round(target, 6) if target is not None else "",
            "before": round(achieved_before, 6) if achieved_before is not None else "",
            "achieved": round(achieved, 6) if achieved is not None else "",
            "universe": round(universe_value, 6) if universe_value is not None else "",
            "shortfall_carried": round(new_shortfall, 6),
            "min_achievable": round(minimum_achievable(values, constraints.single_name_cap) or 0.0, 6),
            "method": method,
            "iterations": iterations,
        },
    )
    return current, state, trace, exceptions
