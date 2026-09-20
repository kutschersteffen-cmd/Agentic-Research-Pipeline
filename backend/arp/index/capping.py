from __future__ import annotations

from collections import defaultdict
from math import fsum

from arp.index.fields import EPS
from arp.index.optimize import LinearConstraint, available as optimizer_available, project
from arp.index.risk import RiskModel
from arp.index.weighting import normalise
from arp.schemas.index import ConstraintSet, IndexCandidate, StageTrace

TOL = 1e-10


def _waterfall(weights: dict[str, float], caps: dict[str, float], max_iterations: int) -> tuple[dict[str, float], int, bool]:
    """The deterministic iterative capping waterfall.

    Pin every breaching name at its cap, then redistribute the freed weight
    pro-rata across the names still below theirs, repeat. Converges
    monotonically and produces identical output on every machine -- which
    is why it, and not a convex solver, is the default constraint path.

    Both conditions have to hold before it stops: no name above its cap
    *and* the weights summing to one. Checking only the first is a subtle
    way to return a short book, because clamping a redistribution at a
    name's cap leaves residual weight undistributed while no breach
    remains.

    Returns the capped weights, the iteration count, and whether it
    converged within `max_iterations`.
    """
    current = dict(weights)
    names = sorted(current)
    for iteration in range(1, max_iterations + 1):
        for k in names:
            if current[k] > caps.get(k, 1.0) + TOL:
                current[k] = caps[k]
        total = fsum(current[k] for k in names)
        residual = 1.0 - total
        if abs(residual) <= TOL:
            return current, iteration - 1, True
        if residual < 0:
            # Over-allocated -- possible after a group cap scales a group
            # up. Scaling everything down cannot create a breach.
            for k in names:
                current[k] /= total
            continue
        free = [k for k in names if current[k] < caps.get(k, 1.0) - TOL]
        if not free:
            # Every name sits at its cap and the caps do not reach 1: the
            # constraint set is infeasible. Renormalising is the only
            # continuation, and the caller records it as an exception
            # rather than letting it pass silently.
            return normalise(current), iteration, False
        headroom = fsum(caps.get(k, 1.0) - current[k] for k in free)
        if residual >= headroom - TOL:
            for k in free:
                current[k] = caps.get(k, 1.0)
            continue
        free_total = fsum(current[k] for k in free)
        if free_total > EPS:
            for k in free:
                current[k] = min(current[k] + residual * current[k] / free_total, caps.get(k, 1.0))
        else:
            share = residual / len(free)
            for k in free:
                current[k] = min(current[k] + share, caps.get(k, 1.0))
    return current, max_iterations, False


def _apply_group_caps(
    weights: dict[str, float], candidates: dict[str, IndexCandidate], dimension: str, max_weight: float
) -> tuple[dict[str, float], bool, str | None]:
    """Scales over-weight groups down to their cap and redistributes the
    freed weight across the under-weight ones **in proportion to their
    remaining headroom**.

    Distributing pro-rata to current weight instead would routinely push an
    under-weight group straight through its own cap, and the next pass would
    push it back -- an oscillation that never converges. Filling headroom
    can never create a new breach, so a single pass per dimension is enough.

    Returns (weights, changed, infeasibility message).
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for company_id in sorted(weights):
        groups[candidates[company_id].group_value(dimension)].append(company_id)
    totals = {g: fsum(weights[k] for k in members) for g, members in sorted(groups.items())}

    if len(groups) * max_weight < 1.0 - TOL:
        return (
            weights,
            False,
            f"group cap {max_weight:.2%} on '{dimension}' is infeasible: {len(groups)} group(s) can hold at most "
            f"{len(groups) * max_weight:.2%} of the index",
        )

    over = {g: t for g, t in totals.items() if t > max_weight + TOL}
    if not over:
        return weights, False, None

    current = dict(weights)
    freed = 0.0
    for group in sorted(over):
        scale = max_weight / totals[group]
        for k in groups[group]:
            freed += current[k] * (1.0 - scale)
            current[k] *= scale

    headroom = {g: max_weight - totals[g] for g in sorted(totals) if g not in over and totals[g] < max_weight - TOL}
    total_headroom = fsum(headroom[g] for g in sorted(headroom))
    if total_headroom <= EPS:
        return normalise(current), True, None
    for group, room in sorted(headroom.items()):
        share = freed * room / total_headroom
        members = groups[group]
        member_total = fsum(current[k] for k in members)
        for k in members:
            current[k] += share * (current[k] / member_total) if member_total > EPS else share / len(members)
    return current, True, None


def _ucits_cap(weights: dict[str, float], max_iterations: int) -> tuple[dict[str, float], bool]:
    """UCITS 5/10/40: no issuer above 10%, and issuers above 5% summing to
    at most 40%.

    Solved by bisecting a single uniform cap in [0.05, 0.10]. At 0.05 no
    name is above 5%, so the aggregate is 0 and the bound is always
    feasible; the aggregate is monotone in the cap, so bisection finds the
    loosest cap that satisfies the rule. Deterministic, and it terminates
    in a fixed number of steps.
    """
    capped, _, _ = _waterfall(weights, {k: 0.10 for k in weights}, max_iterations)
    if fsum(v for v in capped.values() if v > 0.05 + TOL) <= 0.40 + TOL:
        return capped, True
    low, high = 0.05, 0.10
    best = capped
    for _ in range(60):
        mid = (low + high) / 2.0
        trial, _, _ = _waterfall(weights, {k: mid for k in weights}, max_iterations)
        if fsum(v for v in trial.values() if v > 0.05 + TOL) <= 0.40 + TOL:
            best, low = trial, mid
        else:
            high = mid
    return best, fsum(v for v in best.values() if v > 0.05 + TOL) <= 0.40 + 1e-6


def apply_constraints(
    weights: dict[str, float],
    candidates: list[IndexCandidate],
    constraints: ConstraintSet,
    *,
    extra_linear: list[LinearConstraint] | None = None,
    risk_model: RiskModel | None = None,
    benchmark: dict[str, float] | None = None,
) -> tuple[dict[str, float], StageTrace, list[str]]:
    """Satisfies the constraint set, by whichever method the calibration picks.

    `waterfall` (the default) applies min-weight pruning, the single-name
    cap, group caps and UCITS 5/10/40 in sequence, looping until all hold
    simultaneously. The loop matters: capping every name to 8% can still
    leave the 5/10/40 aggregate breached, and scaling a sector down can push
    a single name back over its cap. Each pass is deterministic, so the loop
    is too.

    `least_squares` hands the same constraints to a convex programme that
    binds them simultaneously and returns the closest feasible portfolio.

    `extra_linear` carries constraints the sequential method cannot express
    -- today, the decarbonisation target. Passing one under the waterfall
    method is a programming error rather than a silent no-op, because
    dropping a methodology constraint is exactly the kind of failure that
    produces a plausible, wrong index.
    """
    by_id = {c.company_id: c for c in candidates}
    current = normalise({k: v for k, v in weights.items() if k in by_id})
    exceptions: list[str] = []
    iterations = 0
    extra_linear = list(extra_linear or [])
    if extra_linear and constraints.solver.method == "waterfall":
        raise ValueError(
            "extra_linear constraints require a convex solver method; "
            "the waterfall cannot express them and must not silently ignore them"
        )

    if constraints.min_weight:
        kept = {k: v for k, v in current.items() if v >= constraints.min_weight}
        if not kept:
            raise ValueError(f"min_weight={constraints.min_weight} removed every constituent")
        if len(kept) < len(current):
            exceptions.append(f"min_weight={constraints.min_weight:.4%} dropped {len(current) - len(kept)} constituent(s)")
        current = normalise(kept)

    if constraints.solver.method != "waterfall":
        projected, solver_exceptions, info = _least_squares(
            current, candidates, constraints, extra_linear, risk_model, benchmark
        )
        exceptions.extend(solver_exceptions)
        if projected is not None:
            trace = StageTrace(
                stage="constraints",
                rule_type="convex_projection",
                label=f"constraints ({_OBJECTIVE_LABELS[constraints.solver.method]})",
                candidates_in=len(weights),
                candidates_out=len(projected),
                detail={
                    "objective": constraints.solver.method,
                    "solver": constraints.solver.solver,
                    "max_weight": round(max(projected.values(), default=0.0), 6),
                    "single_name_cap": constraints.single_name_cap if constraints.single_name_cap is not None else "none",
                    "ucits_5_10_40": "on" if constraints.ucits_5_10_40 else "off",
                    "extra_linear": len(extra_linear),
                    **info,
                },
            )
            return projected, trace, exceptions
        # Fell through: _least_squares already recorded why. Continue into
        # the waterfall, which cannot honour extra_linear -- the caller is
        # told so rather than being handed a quietly weaker index.
        if extra_linear:
            exceptions.append(
                "the waterfall cannot express "
                + ", ".join(c.label for c in extra_linear)
                + "; not applied in this pass"
            )

    for _ in range(constraints.max_iterations):
        before = dict(current)

        if constraints.single_name_cap is not None:
            current, used, converged = _waterfall(current, {k: constraints.single_name_cap for k in current}, constraints.max_iterations)
            iterations += used
            if not converged:
                exceptions.append(
                    f"single-name cap {constraints.single_name_cap:.2%} not satisfiable with {len(current)} constituents "
                    f"(cap x count = {constraints.single_name_cap * len(current):.2f}); weights renormalised"
                )

        for group_cap in constraints.group_caps:
            current, changed, infeasible = _apply_group_caps(current, by_id, group_cap.dimension, group_cap.max_weight)
            if infeasible and infeasible not in exceptions:
                exceptions.append(infeasible)
            if changed:
                iterations += 1

        if constraints.ucits_5_10_40:
            current, ok = _ucits_cap(current, constraints.max_iterations)
            iterations += 1
            if not ok:
                exceptions.append("UCITS 5/10/40 could not be satisfied; the closest feasible cap was applied")

        if max(abs(current[k] - before[k]) for k in sorted(current)) <= TOL:
            break
    else:
        exceptions.append(f"constraint loop hit max_iterations={constraints.max_iterations} without a stable solution")

    trace = StageTrace(
        stage="constraints",
        rule_type="constraint_set",
        label="constraints",
        candidates_in=len(weights),
        candidates_out=len(current),
        detail={
            "iterations": iterations,
            "max_weight": round(max(current.values(), default=0.0), 6),
            "single_name_cap": constraints.single_name_cap if constraints.single_name_cap is not None else "none",
            "ucits_5_10_40": "on" if constraints.ucits_5_10_40 else "off",
        },
    )
    return current, trace, exceptions


_OBJECTIVE_LABELS = {
    "least_squares": "least-squares projection",
    "min_tracking_error": "minimum tracking error",
    "max_score": "score maximisation under a tracking-error budget",
}


def _least_squares(
    weights: dict[str, float],
    candidates: list[IndexCandidate],
    constraints: ConstraintSet,
    extra_linear: list[LinearConstraint],
    risk_model: RiskModel | None,
    benchmark: dict[str, float] | None,
) -> tuple[dict[str, float] | None, list[str], dict]:
    """Runs the convex programme and decides whether its answer is usable.

    Returns (weights, exceptions, trace detail). A None result means the
    caller should fall back; the exceptions say why, in the same register as
    every other relaxation the engine records.
    """
    exceptions: list[str] = []
    settings = constraints.solver
    label = _OBJECTIVE_LABELS[settings.method]
    if not optimizer_available():
        exceptions.append(
            f"solver.method='{settings.method}' but cvxpy is not installed; "
            'fell back to the deterministic waterfall (pip install -e ".[optimize]")'
        )
        return None, exceptions, {}

    needs_risk = settings.method in ("min_tracking_error", "max_score") or settings.tracking_error_budget is not None
    if needs_risk and risk_model is None:
        exceptions.append(
            f"solver.method='{settings.method}' needs a risk model and none was supplied; "
            "fell back to the deterministic waterfall"
        )
        return None, exceptions, {}

    if risk_model is not None and settings.tracking_error_budget is not None:
        coverage = risk_model.coverage_of(weights)
        if coverage < settings.min_risk_coverage:
            # A budget measured over part of the index is an understatement
            # wearing the costume of a control. Refuse it rather than publish
            # a number nobody can rely on.
            exceptions.append(
                f"the risk model covers {coverage:.2%} of index weight, below the required "
                f"{settings.min_risk_coverage:.2%}; the tracking-error budget was not applied and the "
                "review fell back to the deterministic waterfall"
            )
            return None, exceptions, {}

    result = project(weights, candidates, constraints, extra_linear=extra_linear, risk_model=risk_model, benchmark=benchmark)
    if result.weights is not None:
        info: dict = {}
        if result.tracking_error is not None:
            info["tracking_error"] = round(result.tracking_error, 8)
        if settings.tracking_error_budget is not None:
            info["te_budget"] = settings.tracking_error_budget
        if risk_model is not None:
            info["risk_model"] = f"{risk_model.source}/{len(risk_model.names)}n"
        return result.weights, exceptions, info

    detail = f"{result.status}" + (f" -- {'; '.join(result.violations[:3])}" if result.violations else "")

    if "infeasible" in result.status and settings.tracking_error_budget is not None and risk_model is not None:
        # Same principle as the decarbonisation frontier: when a budget cannot
        # be met, say what the lowest achievable tracking error actually is
        # under this constraint set, rather than leaving "infeasible" as the
        # whole answer. Solving for it is one extra convex programme.
        probe = constraints.model_copy(
            update={"solver": settings.model_copy(update={"method": "min_tracking_error", "tracking_error_budget": None})}
        )
        floor = project(weights, candidates, probe, extra_linear=extra_linear, risk_model=risk_model, benchmark=benchmark)
        if floor.tracking_error is not None:
            detail += (
                f"; the lowest tracking error reachable under these constraints is {floor.tracking_error:.4%} "
                f"against a budget of {settings.tracking_error_budget:.4%} -- widen the budget, loosen the caps, "
                "or relax the other constraints"
            )

    if not settings.fallback_to_waterfall:
        raise ValueError(f"{label} failed and fallback is disabled: {detail}")
    exceptions.append(f"{label} did not produce a usable solution ({detail}); fell back to the waterfall")
    return None, exceptions, {}
