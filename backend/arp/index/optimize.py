"""Stage 1 of the optimiser path: a least-squares projection onto the
constraint set.

The deterministic waterfall in `capping.py` satisfies the constraints but
makes no claim about *how far* it moves the weights to do so, and it applies
the constraints in sequence -- cap, then group, then UCITS, then loop. This
module instead solves

    minimise    || w - b ||^2
    subject to  sum(w) = 1,  0 <= w <= cap,  group sums <= cap_g,
                and any extra linear constraint (the decarbonisation target)

as one convex programme, so every constraint binds simultaneously and the
result is the *closest* feasible portfolio to what the methodology asked
for, not merely a feasible one.

With a risk model supplied, two further objectives become available:
minimising ex-ante tracking error against the benchmark, and maximising an
index-weighted score subject to a tracking-error budget. Tracking error
enters as `sum_squares` of a factorised covariance rather than a quadratic
form, which keeps the problem provably convex even when an estimated
covariance is a hair non-PSD, and -- in factor form -- costs K + N terms
rather than N**2.

Three deliberate properties:

- **The objective is strictly convex**, so the optimum is unique. There is
  no degenerate-optimum tie-break to specify, which is the usual first
  reproducibility problem with a solver in an index.
- **Nothing here trusts the solver.** Every constraint is re-checked in
  plain Python after the solve, and a violated or failed solve falls back to
  the waterfall with an exception recorded -- never a silently wrong index.
- **The non-convex constraints stay out.** UCITS 5/10/40 is handled by
  bisecting a uniform cap around the programme (each solve is convex), and
  `min_weight` remains the caller's pruning heuristic. Both are
  semi-continuous in truth and belong to the mixed-integer stage; see
  `docs/OPTIMIZATION_TOOLING.md` section 2.

cvxpy is an optional dependency (`pip install -e ".[optimize]"`). Without
it, `available()` is False and the engine keeps using the waterfall.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import fsum

import numpy as np

from arp.index.risk import RiskModel
from arp.schemas.index import ConstraintSet, IndexCandidate

# Solver output below this magnitude is numerical noise, not a weight.
# Rounding at a fixed precision before the constraint check keeps the result
# stable across BLAS builds, where a solver's last few digits are not.
SOLUTION_DECIMALS = 9
_ROUND_TOL = 10.0 ** -SOLUTION_DECIMALS


@dataclass(frozen=True)
class LinearConstraint:
    """`sum_i coefficients[i] * w_i <= rhs`.

    A weighted-average target expresses cleanly in this form even when the
    metric is missing for part of the index: `avg over covered <= tau` is
    `sum_covered w_i * (x_i - tau) <= 0`, which stays linear rather than
    needing a ratio constraint.
    """

    label: str
    coefficients: dict[str, float]
    rhs: float = 0.0


@dataclass
class ProjectionResult:
    weights: dict[str, float] | None
    status: str
    objective: float | None = None
    solver: str = ""
    solver_version: str = ""
    iterations: int = 0
    violations: list[str] = field(default_factory=list)
    tracking_error: float | None = None


def available() -> bool:
    try:
        import cvxpy  # noqa: F401
    except ImportError:
        return False
    return True


def _solver_options(solver: str) -> dict:
    """Explicit tolerances and a fixed thread count, never the defaults.

    A solver's default tolerance is chosen for speed on generic problems;
    an index weight vector wants the tightest the solver will give. Thread
    count is pinned because parallel floating-point accumulation reorders,
    and reordering moves the last digits.
    """
    if solver == "CLARABEL":
        # Roughly two orders tighter than Clarabel's defaults. 1e-12 was
        # tried and is counter-productive: on a second-order cone problem it
        # returns "solution may be inaccurate" without improving the answer.
        return {"tol_gap_abs": 1e-10, "tol_gap_rel": 1e-10, "tol_feas": 1e-10, "max_iter": 1000}
    if solver == "OSQP":
        return {"eps_abs": 1e-10, "eps_rel": 1e-10, "max_iter": 100_000, "polish": True, "polish_refine_iter": 10}
    if solver == "SCS":
        return {"eps_abs": 1e-10, "eps_rel": 1e-10, "max_iters": 100_000}
    return {}


def _verify(
    weights: dict[str, float],
    names: list[str],
    upper: dict[str, float],
    group_caps: list[tuple[str, list[str], float]],
    extra_linear: list[LinearConstraint],
    tolerance: float,
    *,
    risk_model: RiskModel | None = None,
    benchmark: dict[str, float] | None = None,
    tracking_error_budget: float | None = None,
) -> list[str]:
    """Re-checks every constraint in plain Python.

    A solver reporting `optimal` is a statement about its own convergence
    criteria, not a guarantee about ours -- and a first-order solver can
    report success at a tolerance that would breach a published cap. This is
    the check that decides whether the solution is used.
    """
    violations: list[str] = []
    total = fsum(weights[n] for n in names)
    if abs(total - 1.0) > tolerance:
        violations.append(f"weights sum to {total:.12f}, not 1")
    for name in names:
        if weights[name] < -tolerance:
            violations.append(f"{name} has negative weight {weights[name]:.12f}")
        if weights[name] > upper[name] + tolerance:
            violations.append(f"{name} exceeds its cap: {weights[name]:.12f} > {upper[name]:.12f}")
    for dimension, members, cap in group_caps:
        group_total = fsum(weights[n] for n in members)
        if group_total > cap + tolerance:
            violations.append(f"group {dimension} sums to {group_total:.12f} > {cap:.12f}")
    for constraint in extra_linear:
        value = fsum(weights[n] * coefficient for n, coefficient in sorted(constraint.coefficients.items()) if n in weights)
        # Scale the tolerance to the constraint's own magnitude. A GHG
        # intensity constraint carries coefficients in the hundreds, so an
        # absolute tolerance calibrated for weights (which are O(1)) rejects
        # solutions that are correct to twelve significant figures.
        scale = max(1.0, max((abs(c) for c in constraint.coefficients.values()), default=1.0))
        if value > constraint.rhs + tolerance * scale:
            violations.append(f"{constraint.label}: {value:.12f} > {constraint.rhs:.12f} (tolerance {tolerance * scale:.3e})")
    if risk_model is not None and benchmark is not None and tracking_error_budget is not None:
        # Recomputed from the covariance directly, not read back off the
        # solver: a budget nobody re-derived is not a control.
        realised = risk_model.tracking_error(weights, benchmark)
        if realised > tracking_error_budget * (1.0 + 1e-4) + tolerance:
            violations.append(f"tracking error {realised:.8f} exceeds the budget {tracking_error_budget:.8f}")
    return violations


def _group_rows(candidates: list[IndexCandidate], names: list[str], constraints: ConstraintSet) -> list[tuple[str, list[str], float]]:
    by_id = {c.company_id: c for c in candidates}
    rows: list[tuple[str, list[str], float]] = []
    for group_cap in constraints.group_caps:
        groups: dict[str, list[str]] = {}
        for name in names:
            groups.setdefault(by_id[name].group_value(group_cap.dimension), []).append(name)
        for label, members in sorted(groups.items()):
            rows.append((f"{group_cap.dimension}={label}", members, group_cap.max_weight))
    return rows


def _active_risk_expression(risk_model: RiskModel, names: list[str], w, benchmark_weights: dict[str, float]):
    """A cvxpy expression whose 2-norm is annualised tracking error.

    The active vector spans the *union* of the index and the benchmark, not
    just the index: a benchmark constituent the index does not hold is a
    full active underweight and carries risk. Computing it over the index's
    own names alone would silently drop exactly the positions an exclusion
    policy creates, understating tracking error by the most interesting part.

    Built from a factorisation rather than `quad_form`, for two reasons: an
    estimated covariance that is a hair non-PSD cannot then fail a
    convexity check, and in factor form the expression has K + N terms
    instead of N**2, which is what makes the problem tractable at index
    scale.
    """
    import cvxpy as cp

    index_of = risk_model.index_of()
    benchmark_names = [n for n, weight in benchmark_weights.items() if abs(weight) > 0.0]
    union = sorted(set(names) | set(benchmark_names))
    missing = [n for n in union if n not in index_of]
    if missing:
        raise RiskModelCoverageError(missing)

    rows = [index_of[n] for n in union]
    position = {name: i for i, name in enumerate(union)}

    # active = S w - b, where S places each index weight at its row in the union.
    selector = np.zeros((len(union), len(names)))
    for column, name in enumerate(names):
        selector[position[name], column] = 1.0
    benchmark_vector = np.array([benchmark_weights.get(n, 0.0) for n in union], dtype=float)
    active = selector @ w - benchmark_vector

    if risk_model.factor_form:
        loadings = risk_model.loadings[rows, :]
        factor_covariance = risk_model.factor_covariance
        eigenvalues, eigenvectors = np.linalg.eigh((factor_covariance + factor_covariance.T) / 2.0)
        factor_root = (eigenvectors * np.sqrt(np.clip(eigenvalues, 0.0, None))).T
        specific_root = np.sqrt(np.clip(risk_model.specific_var[rows], 0.0, None))
        return cp.hstack([factor_root @ (loadings.T @ active), cp.multiply(specific_root, active)])

    covariance = risk_model.covariance()[np.ix_(rows, rows)]
    eigenvalues, eigenvectors = np.linalg.eigh((covariance + covariance.T) / 2.0)
    root = (eigenvectors * np.sqrt(np.clip(eigenvalues, 0.0, None))).T
    return root @ active


class RiskModelCoverageError(ValueError):
    def __init__(self, missing: list[str]) -> None:
        shown = ", ".join(missing[:5])
        super().__init__(
            f"the risk model does not cover {len(missing)} constituent(s) ({shown}...); "
            "a tracking-error budget computed over a partial universe understates risk"
        )
        self.missing = missing


def _solve_once(
    names: list[str],
    base: np.ndarray,
    upper: np.ndarray,
    group_rows: list[tuple[str, list[str], float]],
    extra_linear: list[LinearConstraint],
    solver: str,
    *,
    objective: str = "least_squares",
    risk_model: RiskModel | None = None,
    benchmark: dict[str, float] | None = None,
    tracking_error_budget: float | None = None,
    score: np.ndarray | None = None,
) -> tuple[np.ndarray | None, str, float | None]:
    import cvxpy as cp

    index_of = {name: i for i, name in enumerate(names)}
    w = cp.Variable(len(names))
    conditions = [cp.sum(w) == 1, w >= 0, w <= upper]
    for _label, members, cap in group_rows:
        selector = np.zeros(len(names))
        for member in members:
            selector[index_of[member]] = 1.0
        conditions.append(selector @ w <= cap)
    for constraint in extra_linear:
        row = np.zeros(len(names))
        for name, coefficient in constraint.coefficients.items():
            if name in index_of:
                row[index_of[name]] = coefficient
        conditions.append(row @ w <= constraint.rhs)

    risk_expression = None
    if risk_model is not None and benchmark is not None:
        risk_expression = _active_risk_expression(risk_model, names, w, benchmark)
        if tracking_error_budget is not None:
            # A second-order cone constraint. OSQP cannot express one, which
            # the calibration validator rejects up front rather than letting
            # the solver fail opaquely here.
            conditions.append(cp.norm(risk_expression, 2) <= tracking_error_budget)

    if objective == "min_tracking_error":
        if risk_expression is None:
            return None, "min_tracking_error needs a risk model and a benchmark", None
        goal = cp.Minimize(cp.sum_squares(risk_expression))
    elif objective == "max_score":
        if score is None:
            return None, "max_score needs a score vector", None
        goal = cp.Maximize(score @ w)
    else:
        goal = cp.Minimize(cp.sum_squares(w - base))

    problem = cp.Problem(goal, conditions)
    try:
        problem.solve(solver=solver, **_solver_options(solver))
    except Exception as exc:  # cvxpy raises a variety of solver-specific errors
        return None, f"solver_error: {type(exc).__name__}: {exc}", None
    if w.value is None:
        return None, str(problem.status), None
    return np.asarray(w.value, dtype=float), str(problem.status), float(problem.value)


def project(
    weights: dict[str, float],
    candidates: list[IndexCandidate],
    constraints: ConstraintSet,
    *,
    extra_linear: list[LinearConstraint] | None = None,
    risk_model: RiskModel | None = None,
    benchmark: dict[str, float] | None = None,
) -> ProjectionResult:
    """Closest feasible weight vector to `weights`, or a result carrying why not.

    Never raises on a solver problem: an infeasible or failed solve comes
    back as a `ProjectionResult` with `weights=None` and a reason, so the
    caller decides whether to fall back rather than the exception type
    deciding for it.
    """
    if not available():
        return ProjectionResult(weights=None, status="cvxpy_not_installed")

    import cvxpy as cp

    extra_linear = list(extra_linear or [])
    names = sorted(weights)
    if not names:
        return ProjectionResult(weights=None, status="empty_universe")

    base = np.array([weights[n] for n in names], dtype=float)
    base = base / base.sum()
    cap = constraints.single_name_cap if constraints.single_name_cap is not None else 1.0
    group_rows = _group_rows(candidates, names, constraints)
    settings = constraints.solver
    solver = settings.solver
    tolerance = settings.verify_tolerance
    objective = settings.method if settings.method in ("min_tracking_error", "max_score") else "least_squares"
    budget = settings.tracking_error_budget

    needs_risk = objective in ("min_tracking_error", "max_score") or budget is not None
    if needs_risk and risk_model is None:
        return ProjectionResult(weights=None, status="risk_model_required", solver=solver)

    benchmark_weights = benchmark if benchmark is not None else weights

    score_vector = None
    if objective == "max_score":
        from arp.index.fields import metric_value

        by_id = {c.company_id: c for c in candidates}
        raw = [metric_value(by_id[n], settings.score_field or "") for n in names]
        if any(v is None for v in raw):
            return ProjectionResult(weights=None, status=f"score_field {settings.score_field!r} is missing for some constituents", solver=solver)
        score_vector = np.array(raw, dtype=float)

    def attempt(uniform_cap: float) -> tuple[dict[str, float] | None, str, float | None]:
        upper = np.full(len(names), min(cap, uniform_cap))
        try:
            raw, status, value = _solve_once(
                names,
                base,
                upper,
                group_rows,
                extra_linear,
                solver,
                objective=objective,
                risk_model=risk_model,
                benchmark=benchmark_weights if risk_model is not None else None,
                tracking_error_budget=budget,
                score=score_vector,
            )
        except RiskModelCoverageError as exc:
            return None, str(exc), None
        if raw is None:
            return None, status, None
        solution = {name: round(float(value), SOLUTION_DECIMALS) for name, value in zip(names, raw)}
        # Rounding can nudge a name a hair over its cap; clamp, then push the
        # residual back through the free names so the vector still sums to 1.
        upper_by_name = {name: float(u) for name, u in zip(names, upper)}
        for name in names:
            solution[name] = min(max(solution[name], 0.0), upper_by_name[name])
        residual = 1.0 - fsum(solution[n] for n in names)
        free = [n for n in names if solution[n] < upper_by_name[n] - _ROUND_TOL]
        if abs(residual) > _ROUND_TOL and free:
            free_total = fsum(solution[n] for n in free)
            for name in free:
                share = solution[name] / free_total if free_total > _ROUND_TOL else 1.0 / len(free)
                solution[name] = round(min(solution[name] + residual * share, upper_by_name[name]), SOLUTION_DECIMALS)
        return solution, status, value

    solution, status, value = attempt(1.0)
    iterations = 1

    if solution is not None and constraints.ucits_5_10_40:
        # 5/10/40 is a disjunction, so it is not a convex constraint. Bisecting
        # a uniform cap keeps every individual solve convex and the search
        # deterministic: the aggregate above 5% is monotone in the cap, and at
        # a 5% cap it is zero, so a feasible point always exists.
        def aggregate(candidate: dict[str, float]) -> float:
            return fsum(v for v in candidate.values() if v > 0.05 + tolerance)

        if aggregate(solution) > 0.40 + tolerance:
            low, high, best = 0.05, min(cap, 0.10), None
            for _ in range(20):
                mid = (low + high) / 2.0
                trial, trial_status, trial_value = attempt(mid)
                iterations += 1
                if trial is not None and aggregate(trial) <= 0.40 + tolerance:
                    best, status, value, low = trial, trial_status, trial_value, mid
                else:
                    high = mid
            solution = best if best is not None else solution

    if solution is None:
        return ProjectionResult(weights=None, status=status, solver=solver, iterations=iterations)

    upper_by_name = {n: min(cap, 1.0) for n in names}
    violations = _verify(
        solution,
        names,
        upper_by_name,
        group_rows,
        extra_linear,
        tolerance,
        risk_model=risk_model,
        benchmark=benchmark_weights if risk_model is not None else None,
        tracking_error_budget=budget,
    )
    if violations:
        return ProjectionResult(
            weights=None,
            status=f"verification_failed ({status})",
            solver=solver,
            iterations=iterations,
            violations=violations,
        )
    return ProjectionResult(
        weights=solution,
        status=status,
        objective=value,
        solver=solver,
        solver_version=cp.__version__,
        iterations=iterations,
        tracking_error=risk_model.tracking_error(solution, benchmark_weights) if risk_model is not None else None,
    )
