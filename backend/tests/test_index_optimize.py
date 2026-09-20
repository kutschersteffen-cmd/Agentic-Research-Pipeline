"""Tests for the optional least-squares constraint projection.

Skipped wholesale when cvxpy is absent, except the tests that specifically
exercise what happens *without* it -- those matter most, because the engine
has to degrade to the deterministic path rather than fail a review.
"""

from __future__ import annotations

from math import fsum, sqrt

import pytest

from arp.index import optimize
from arp.index.capping import apply_constraints
from arp.index.mock_data import demo_universe
from arp.index.optimize import LinearConstraint, ProjectionResult
from arp.index.pipeline import run_review
from arp.index.presets import build_preset
from arp.index.weighting import base_weights
from arp.schemas.index import (
    BaseWeighting,
    ConstraintSet,
    ConstraintSolver,
    GroupCap,
    IndexCandidate,
)

TOL = 1e-6


def _universe(n: int = 40) -> list[IndexCandidate]:
    return demo_universe(n)


def _base(universe: list[IndexCandidate]) -> dict[str, float]:
    return base_weights(universe, BaseWeighting(scheme="free_float_mcap"))


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    return sqrt(fsum((a[k] - b[k]) ** 2 for k in sorted(b)))


def _least_squares(**kwargs) -> ConstraintSet:
    return ConstraintSet(solver=ConstraintSolver(method="least_squares"), **kwargs)


# ------------------------------------------------- degrading without cvxpy


def test_without_cvxpy_the_review_still_runs_and_says_why(monkeypatch):
    """A missing optional dependency must not fail a review -- it degrades to
    the deterministic path and records the reason as an exception."""
    monkeypatch.setattr(optimize, "available", lambda: False)
    monkeypatch.setattr("arp.index.capping.optimizer_available", lambda: False)
    universe = _universe()
    weights = _base(universe)

    result, trace, exceptions = apply_constraints(weights, universe, _least_squares(single_name_cap=0.05))

    assert max(result.values()) <= 0.05 + TOL
    assert fsum(result[k] for k in sorted(result)) == pytest.approx(1.0, abs=1e-9)
    assert any("cvxpy is not installed" in e for e in exceptions)
    assert trace.rule_type == "constraint_set"  # the waterfall's trace, not the projection's


def test_extra_linear_under_the_waterfall_is_an_error_not_a_silent_drop():
    """Quietly ignoring a methodology constraint produces a plausible, wrong
    index -- the worst failure mode available."""
    universe = _universe()
    with pytest.raises(ValueError, match="must not silently ignore"):
        apply_constraints(
            _base(universe),
            universe,
            ConstraintSet(single_name_cap=0.05),
            extra_linear=[LinearConstraint(label="x", coefficients={"demo000": 1.0}, rhs=0.0)],
        )


# --------------------------------------------------------- the projection

cvxpy = pytest.importorskip("cvxpy", reason="the least-squares path needs the `optimize` extra")


def test_projection_is_feasible():
    universe = _universe()
    weights = _base(universe)
    constraints = _least_squares(single_name_cap=0.05, group_caps=[GroupCap(dimension="sector", max_weight=0.2)])

    result, trace, exceptions = apply_constraints(weights, universe, constraints)

    assert exceptions == []
    assert trace.rule_type == "convex_projection"
    assert fsum(result[k] for k in sorted(result)) == pytest.approx(1.0, abs=1e-8)
    assert max(result.values()) <= 0.05 + TOL
    assert min(result.values()) >= -TOL
    by_sector: dict[str, float] = {}
    for candidate in universe:
        by_sector[candidate.sector or ""] = by_sector.get(candidate.sector or "", 0.0) + result[candidate.company_id]
    assert max(by_sector.values()) <= 0.2 + TOL


def test_projection_is_strictly_closer_to_the_target_than_the_waterfall():
    """The waterfall is feasible; the projection is optimal. On a problem
    where the constraint actually binds, optimal must be closer."""
    universe = _universe()
    weights = _base(universe)

    waterfall, _, _ = apply_constraints(weights, universe, ConstraintSet(single_name_cap=0.05))
    projected, _, _ = apply_constraints(weights, universe, _least_squares(single_name_cap=0.05))

    assert _distance(projected, weights) < _distance(waterfall, weights)


def test_projection_leaves_an_unconstrained_problem_alone():
    universe = _universe()
    weights = _base(universe)
    projected, _, _ = apply_constraints(weights, universe, _least_squares())
    assert _distance(projected, weights) < 1e-7


def test_ucits_5_10_40_holds_under_the_projection():
    universe = [
        c.model_copy(update={"price": 1000.0 if i < 6 else 1.0, "shares_outstanding": 1_000_000, "free_float_factor": 1.0})
        for i, c in enumerate(_universe(20))
    ]
    weights = _base(universe)
    assert fsum(v for v in weights.values() if v > 0.05) > 0.40  # the problem is real

    projected, _, exceptions = apply_constraints(weights, universe, _least_squares(single_name_cap=0.10, ucits_5_10_40=True))

    assert exceptions == []
    assert max(projected.values()) <= 0.10 + TOL
    assert fsum(v for v in projected.values() if v > 0.05 + 1e-9) <= 0.40 + 1e-5


def test_linear_constraint_is_met_in_one_solve():
    universe = _universe()
    weights = _base(universe)
    values = {c.company_id: c.metrics["ghg_intensity"] for c in universe}
    target = 0.5 * fsum(weights[k] * values[k] for k in sorted(weights))

    projected, trace, exceptions = apply_constraints(
        weights,
        universe,
        _least_squares(single_name_cap=0.05),
        extra_linear=[LinearConstraint(label="intensity", coefficients={k: v - target for k, v in values.items()}, rhs=0.0)],
    )

    assert exceptions == []
    achieved = fsum(projected[k] * values[k] for k in sorted(projected))
    assert achieved <= target * (1 + 1e-6)
    assert trace.detail["extra_linear"] == 1


def test_repeated_solves_are_identical():
    universe = _universe()
    weights = _base(universe)
    constraints = _least_squares(single_name_cap=0.05, group_caps=[GroupCap(dimension="sector", max_weight=0.25)])
    first, _, _ = apply_constraints(weights, universe, constraints)
    for _ in range(4):
        again, _, _ = apply_constraints(weights, universe, constraints)
        assert again == first


def test_input_ordering_does_not_change_the_projection():
    universe = _universe()
    weights = _base(universe)
    constraints = _least_squares(single_name_cap=0.05)
    ordered, _, _ = apply_constraints(weights, universe, constraints)
    reversed_, _, _ = apply_constraints(dict(reversed(list(weights.items()))), list(reversed(universe)), constraints)
    assert ordered == reversed_


# ------------------------------------------------------ failure handling


def test_a_failed_verification_falls_back_rather_than_shipping_the_solution(monkeypatch):
    """A solver reporting `optimal` proves nothing about our constraints.
    When our own check disagrees, the solution is discarded."""
    monkeypatch.setattr(
        "arp.index.capping.project",
        lambda *a, **k: ProjectionResult(weights=None, status="verification_failed (optimal)", violations=["demo000 exceeds its cap"]),
    )
    universe = _universe()
    result, trace, exceptions = apply_constraints(_base(universe), universe, _least_squares(single_name_cap=0.05))

    assert max(result.values()) <= 0.05 + TOL  # the waterfall answered instead
    assert trace.rule_type == "constraint_set"
    assert any("did not produce a usable solution" in e for e in exceptions)


def test_fallback_can_be_disabled_for_a_calibration_that_must_not_degrade(monkeypatch):
    monkeypatch.setattr("arp.index.capping.project", lambda *a, **k: ProjectionResult(weights=None, status="infeasible"))
    universe = _universe()
    constraints = ConstraintSet(
        single_name_cap=0.05, solver=ConstraintSolver(method="least_squares", fallback_to_waterfall=False)
    )
    with pytest.raises(ValueError, match="fallback is disabled"):
        apply_constraints(_base(universe), universe, constraints)


def test_an_infeasible_cap_is_reported_by_the_projection_path_too():
    universe = _universe(5)
    constraints = _least_squares(single_name_cap=0.10)  # 5 names x 10% cannot reach 100%
    _, _, exceptions = apply_constraints(_base(universe), universe, constraints)
    assert exceptions != []


# --------------------------------------------------- end-to-end behaviour


@pytest.mark.parametrize("preset", ["eu_ctb", "eu_pab"])
def test_both_methods_hit_the_regulated_reduction(preset):
    universe = demo_universe()
    results = {}
    for method in ("waterfall", "least_squares"):
        spec = build_preset(preset)
        spec.constraints.solver.method = method
        result = run_review(spec, universe, index_id="x", review_date="2026-03-31")
        diagnostics = result.diagnostics
        results[method] = diagnostics.weighted_metrics["ghg_intensity"] / diagnostics.universe_weighted_metrics["ghg_intensity"]
        assert result.exceptions == []
        assert diagnostics.max_weight <= spec.constraints.single_name_cap + TOL

    expected = 1 - (0.30 if preset == "eu_ctb" else 0.50)
    assert results["waterfall"] == pytest.approx(expected, abs=1e-3)
    assert results["least_squares"] == pytest.approx(expected, abs=1e-3)


def test_the_projection_reaches_the_target_in_one_pass():
    """The tilt search bisects; the projection solves once. Fewer moving
    parts, and the trace says which was used."""
    universe = demo_universe()
    spec = build_preset("eu_pab")
    spec.constraints.solver.method = "least_squares"
    result = run_review(spec, universe, index_id="x", review_date="2026-03-31")
    trajectory = next(t for t in result.trace if t.stage == "trajectory")
    assert trajectory.detail["method"] == "least_squares"
    assert trajectory.detail["iterations"] == 1


def test_the_method_is_part_of_the_calibration_hash():
    """Swapping solver method changes the numbers, so it must change the
    config hash -- otherwise two different indices share an identity."""
    waterfall = build_preset("eu_pab")
    projected = build_preset("eu_pab")
    projected.constraints.solver.method = "least_squares"
    assert waterfall.content_hash() != projected.content_hash()


# =========================================================== stage 2: risk


def _risk_universe(n: int = 40):
    from arp.index.mock_data import demo_returns_panel

    universe = demo_universe(n)
    return universe, demo_returns_panel(universe, 260)


def _model(source: str = "ledoit_wolf", **kwargs):
    from arp.index.risk import build_risk_model
    from arp.schemas.index import RiskModelSpec

    universe, panel = _risk_universe()
    return universe, build_risk_model(RiskModelSpec(source=source, **kwargs), universe, panel)


def test_every_estimator_produces_a_usable_covariance():
    from arp.index.risk import build_risk_model
    from arp.schemas.index import RiskModelSpec

    universe, panel = _risk_universe()
    for spec in (
        RiskModelSpec(source="sample"),
        RiskModelSpec(source="ledoit_wolf"),
        RiskModelSpec(source="factor", factor_fields=["sector", "float_mcap"]),
    ):
        model = build_risk_model(spec, universe, panel)
        covariance = model.covariance()
        assert covariance.shape == (len(universe), len(universe))
        # Annualised volatilities in a plausible equity range, and symmetric.
        volatility = [covariance[i, i] ** 0.5 for i in range(len(universe))]
        assert 0.02 < min(volatility) and max(volatility) < 2.0
        assert abs(covariance - covariance.T).max() < 1e-12


def test_ledoit_wolf_shrinks_toward_the_identity_and_reports_how_much():
    _, model = _model("ledoit_wolf")
    assert model.shrinkage is not None
    assert 0.0 <= model.shrinkage <= 1.0


def test_factor_model_keeps_its_factor_form_for_the_optimiser():
    _, model = _model("factor", factor_fields=["sector"])
    assert model.factor_form
    assert model.loadings.shape[0] == len(model.names)
    assert "market" in model.factor_names


def test_a_short_history_is_refused_rather_than_estimated_badly():
    from arp.index.mock_data import demo_returns_panel
    from arp.index.risk import RiskModelError, build_risk_model
    from arp.schemas.index import RiskModelSpec

    universe = demo_universe(10)
    panel = demo_returns_panel(universe, 20)
    with pytest.raises(RiskModelError, match="at least"):
        build_risk_model(RiskModelSpec(source="ledoit_wolf", min_observations=60), universe, panel)


def test_a_ragged_panel_is_refused_rather_than_zero_filled():
    from arp.index.mock_data import demo_returns_panel
    from arp.index.risk import RiskModelError, build_risk_model
    from arp.schemas.index import RiskModelSpec

    universe = demo_universe(10)
    panel = demo_returns_panel(universe, 100)
    for period in panel:
        panel[period].pop(universe[0].company_id)
    with pytest.raises(RiskModelError, match="covers every name"):
        build_risk_model(RiskModelSpec(source="ledoit_wolf"), universe, panel)


def test_a_supplied_vendor_factor_model_uses_the_same_interface():
    """The licensed path: loadings, factor covariance and specific risk from a
    vendor file, with nothing downstream changing."""
    from arp.index.risk import supplied_factor_model

    model = supplied_factor_model(
        names=["a", "b"],
        loadings=[[1.0, 0.5], [1.0, -0.5]],
        factor_covariance=[[0.04, 0.0], [0.0, 0.01]],
        specific_var=[0.01, 0.02],
        factor_names=["market", "value"],
    )
    assert model.factor_form and model.source == "supplied"
    assert model.tracking_error({"a": 1.0}, {"a": 0.5, "b": 0.5}) > 0


def test_tracking_error_counts_a_benchmark_name_the_index_does_not_hold():
    """An exclusion is a full active underweight. Measuring active risk over
    the index's own names would drop exactly the positions a screen creates."""
    from arp.index.risk import supplied_factor_model

    model = supplied_factor_model(
        names=["a", "b"],
        loadings=[[1.0], [1.0]],
        factor_covariance=[[0.04]],
        specific_var=[0.09, 0.09],
    )
    excluded = model.tracking_error({"a": 1.0}, {"a": 0.5, "b": 0.5})
    identical = model.tracking_error({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5})
    assert identical == pytest.approx(0.0, abs=1e-12)
    assert excluded > 0.1


# ----------------------------------------------- tracking-error objectives


def _solver(method: str, **kwargs):
    from arp.schemas.index import ConstraintSolver

    return ConstraintSolver(method=method, **kwargs)


def test_each_objective_wins_at_its_own_metric():
    """min_tracking_error has the lowest tracking error; least_squares has the
    smallest weight-space distance. Neither dominates the other."""
    from arp.schemas.index import ConstraintSet

    universe, model = _model()
    weights = _base(universe)
    solved = {}
    for method in ("waterfall", "least_squares", "min_tracking_error"):
        constraints = ConstraintSet(single_name_cap=0.05, solver=_solver(method))
        out, _, exceptions = apply_constraints(weights, universe, constraints, risk_model=model, benchmark=weights)
        assert exceptions == []
        solved[method] = out

    tracking = {m: model.tracking_error(w, weights) for m, w in solved.items()}
    distance = {m: _distance(w, weights) for m, w in solved.items()}
    assert tracking["min_tracking_error"] == min(tracking.values())
    assert distance["least_squares"] == min(distance.values())


def test_closest_weights_are_not_the_lowest_tracking_error():
    """The methodological point of stage 2. Euclidean distance in weight space
    and distance in risk space are different metrics, so the least-squares
    projection can sit *above* even the waterfall on tracking error. Anyone
    assuming "closest weights" means "lowest risk" is wrong, and the engine
    should demonstrate it rather than let the assumption stand."""
    from arp.schemas.index import ConstraintSet

    universe, model = _model()
    weights = _base(universe)
    projected, _, _ = apply_constraints(
        weights, universe, ConstraintSet(single_name_cap=0.05, solver=_solver("least_squares")), risk_model=model, benchmark=weights
    )
    minimised, _, _ = apply_constraints(
        weights, universe, ConstraintSet(single_name_cap=0.05, solver=_solver("min_tracking_error")), risk_model=model, benchmark=weights
    )
    assert _distance(projected, weights) < _distance(minimised, weights)
    assert model.tracking_error(minimised, weights) < model.tracking_error(projected, weights)


def test_a_binding_budget_is_respected_and_an_unbinding_one_changes_nothing():
    from arp.schemas.index import ConstraintSet

    universe, model = _model()
    weights = _base(universe)
    unbudgeted, _, _ = apply_constraints(
        weights, universe, ConstraintSet(single_name_cap=0.05, solver=_solver("least_squares")), risk_model=model, benchmark=weights
    )
    free_te = model.tracking_error(unbudgeted, weights)

    loose, _, exceptions = apply_constraints(
        weights,
        universe,
        ConstraintSet(single_name_cap=0.05, solver=_solver("least_squares", tracking_error_budget=free_te * 2)),
        risk_model=model,
        benchmark=weights,
    )
    assert exceptions == []
    assert model.tracking_error(loose, weights) == pytest.approx(free_te, abs=1e-6)

    # A budget between the feasibility frontier and the unconstrained result,
    # so it binds without being impossible.
    from arp.schemas.index import ConstraintSet as _CS

    floor_weights, _, _ = apply_constraints(
        weights, universe, _CS(single_name_cap=0.05, solver=_solver("min_tracking_error")), risk_model=model, benchmark=weights
    )
    frontier = model.tracking_error(floor_weights, weights)
    tight_budget = (frontier + free_te) / 2
    tight, _, exceptions = apply_constraints(
        weights,
        universe,
        ConstraintSet(single_name_cap=0.05, solver=_solver("least_squares", tracking_error_budget=tight_budget)),
        risk_model=model,
        benchmark=weights,
    )
    assert exceptions == []
    assert model.tracking_error(tight, weights) <= tight_budget * (1 + 1e-4)


def test_max_score_raises_the_score_and_spends_the_budget():
    from arp.schemas.index import ConstraintSet

    universe, model = _model()
    weights = _base(universe)
    scores = {c.company_id: c.metrics["esg_score"] for c in universe}

    def weighted(w):
        return fsum(w[k] * scores[k] for k in sorted(w))

    baseline, _, _ = apply_constraints(
        weights, universe, ConstraintSet(single_name_cap=0.05, solver=_solver("least_squares")), risk_model=model, benchmark=weights
    )
    budget = model.tracking_error(baseline, weights) * 1.5
    maximised, _, exceptions = apply_constraints(
        weights,
        universe,
        ConstraintSet(single_name_cap=0.05, solver=_solver("max_score", score_field="esg_score", tracking_error_budget=budget)),
        risk_model=model,
        benchmark=weights,
    )
    assert exceptions == []
    assert weighted(maximised) > weighted(baseline)
    assert model.tracking_error(maximised, weights) <= budget * (1 + 1e-4)


def test_a_budget_without_a_risk_model_falls_back_and_says_so():
    from arp.schemas.index import ConstraintSet

    universe = demo_universe(30)
    weights = _base(universe)
    result, trace, exceptions = apply_constraints(
        weights, universe, ConstraintSet(single_name_cap=0.05, solver=_solver("min_tracking_error"))
    )
    assert max(result.values()) <= 0.05 + TOL
    assert trace.rule_type == "constraint_set"
    assert any("needs a risk model" in e for e in exceptions)


def test_poor_risk_model_coverage_refuses_the_budget():
    """A budget measured over part of the index is an understatement wearing
    the costume of a control."""
    from arp.schemas.index import ConstraintSet

    universe, model = _model()
    weights = _base(universe)
    model.names = model.names[: len(model.names) // 2]
    model.dense = model.dense[: len(model.names), : len(model.names)]

    _, _, exceptions = apply_constraints(
        weights,
        universe,
        ConstraintSet(single_name_cap=0.05, solver=_solver("least_squares", tracking_error_budget=0.02, min_risk_coverage=0.98)),
        risk_model=model,
        benchmark=weights,
    )
    assert any("covers" in e and "below the required" in e for e in exceptions)


def test_osqp_with_a_budget_is_rejected_at_calibration_time():
    """A second-order cone constraint on a QP-only solver should fail when the
    calibration is written, not opaquely inside the solver at review time."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="second-order cone"):
        _solver("least_squares", solver="OSQP", tracking_error_budget=0.02)


def test_tracking_error_is_reported_on_the_published_weights():
    universe, model = _model()
    spec = build_preset("esg_tilt")
    spec.constraints.solver.method = "least_squares"
    result = run_review(spec, universe, index_id="x", review_date="2026-03-31", risk_model=model)
    assert result.diagnostics.tracking_error is not None
    # The pipeline's benchmark is the *eligible* universe, not the parent.
    from arp.index.screens import apply_screens

    eligible, _ = apply_screens(sorted(universe, key=lambda c: c.company_id), spec.screens)
    recomputed = model.tracking_error({c.company_id: c.weight for c in result.constituents}, _base(eligible))
    assert result.diagnostics.tracking_error == pytest.approx(recomputed, abs=1e-6)


def test_a_budget_that_conflicts_with_the_trajectory_keeps_the_budget():
    """Documented precedence: the risk limit is the harder of the two, and the
    decarbonisation shortfall is recorded rather than the budget being blown."""
    universe, model = _model()
    spec = build_preset("eu_pab")
    spec.constraints.solver.method = "least_squares"
    spec.constraints.solver.tracking_error_budget = 0.005
    result = run_review(spec, universe, index_id="x", review_date="2026-03-31", risk_model=model)
    assert result.diagnostics.tracking_error <= 0.005 * (1 + 1e-3) or result.exceptions
    assert result.state.shortfall_carry > 0
    assert any("not reached" in e or "did not produce a usable solution" in e for e in result.exceptions)


# ====================================================== stage 3: integers

scip = pytest.importorskip("pyscipopt", reason="the integer path needs a MIP backend (SCIP)")


def _integer_spec(**constraint_kwargs):
    spec = build_preset("exclusion_only")
    spec.constraints.solver.method = "least_squares"
    for key, value in constraint_kwargs.items():
        if hasattr(spec.constraints, key):
            setattr(spec.constraints, key, value)
        else:
            setattr(spec.constraints.solver, key, value)
    return spec


def _held(result):
    return [c for c in result.constituents if c.weight > 0]


def test_cardinality_is_exact_not_approximate():
    universe = demo_universe()
    for limit in (15, 25):
        result = run_review(_integer_spec(max_constituents=limit), universe, index_id="x", review_date="2026-03-31")
        assert len(_held(result)) == limit
        assert fsum(c.weight for c in result.constituents) == pytest.approx(1.0, abs=1e-6)
        assert result.diagnostics.integer_constraints is True


def test_unheld_names_are_not_published_as_constituents():
    """A solver declines a name by setting its weight to exactly zero. An
    index that lists it at 0.000000% with zero index shares is a list of
    names, not an index."""
    universe = demo_universe()
    result = run_review(_integer_spec(max_constituents=20), universe, index_id="x", review_date="2026-03-31")
    assert len(result.constituents) == 20
    assert all(c.weight > 0 and c.index_shares > 0 for c in result.constituents)


def test_a_minimum_weight_floor_lifts_names_rather_than_dropping_them():
    """The whole point of stage 3. The prune heuristic answers "which small
    names do we drop"; the semi-continuous constraint answers the real
    question, "hold this name at the floor or not at all" -- and gives a
    materially different index."""
    universe = demo_universe()
    heuristic = run_review(_integer_spec(min_weight=0.02), universe, index_id="x", review_date="2026-03-31")
    enforced = run_review(
        _integer_spec(min_weight=0.02, enforce_semicontinuous=True), universe, index_id="x", review_date="2026-03-31"
    )

    assert min(c.weight for c in _held(enforced)) >= 0.02 - 1e-9
    assert min(c.weight for c in _held(heuristic)) >= 0.02 - 1e-9
    # The constraint keeps names the heuristic throws away.
    assert len(_held(enforced)) > len(_held(heuristic))
    assert any("dropped" in e for e in heuristic.exceptions)
    assert enforced.exceptions == []


def test_a_cardinality_floor_holds_too():
    universe = demo_universe()
    result = run_review(
        _integer_spec(min_constituents=40, min_weight=0.01, enforce_semicontinuous=True),
        universe,
        index_id="x",
        review_date="2026-03-31",
    )
    assert len(_held(result)) >= 40
    assert min(c.weight for c in _held(result)) >= 0.01 - 1e-9


def test_arithmetically_impossible_limits_are_caught_before_a_solver_runs():
    """`max_constituents x cap < 1` cannot hold whatever the solver does.
    Saying so in a sentence beats an `infeasible` status ten seconds later."""
    universe = demo_universe()
    spec = _integer_spec(max_constituents=10)
    spec.constraints.single_name_cap = 0.05
    result = run_review(spec, universe, index_id="x", review_date="2026-03-31")
    assert any("can hold only" in e for e in result.exceptions)


def test_contradictory_cardinality_bounds_are_named():
    from arp.index.optimize import integer_feasibility
    from arp.schemas.index import ConstraintSet

    blocker = integer_feasibility(ConstraintSet(min_constituents=30, max_constituents=10), universe_size=100)
    assert blocker is not None and "exceeds max_constituents" in blocker


def test_a_floor_that_cannot_fit_the_minimum_count_is_named():
    from arp.index.optimize import integer_feasibility
    from arp.schemas.index import ConstraintSet

    blocker = integer_feasibility(ConstraintSet(min_constituents=60, min_weight=0.02), universe_size=100)
    assert blocker is not None and "would need" in blocker


def test_the_waterfall_refuses_integer_constraints_rather_than_ignoring_them():
    from arp.schemas.index import ConstraintSet

    universe = demo_universe(20)
    with pytest.raises(ValueError, match="integer variables"):
        apply_constraints(_base(universe), universe, ConstraintSet(max_constituents=10))


def test_integer_solves_repeat_identically():
    """Branch-and-bound has no unique-optimum guarantee, so the tie-break on a
    fixed name ordering is doing real work here."""
    universe = demo_universe()
    spec = _integer_spec(max_constituents=20)
    first = run_review(spec, universe, index_id="x", review_date="2026-03-31")
    for _ in range(3):
        again = run_review(spec, universe, index_id="x", review_date="2026-03-31")
        assert [(c.company_id, c.weight) for c in again.constituents] == [
            (c.company_id, c.weight) for c in first.constituents
        ]


def test_cardinality_composes_with_a_tracking_error_budget():
    """A mixed-integer second-order cone problem -- the hardest shape the
    engine produces."""
    from arp.index.mock_data import demo_risk_model

    universe = demo_universe()
    model = demo_risk_model(universe)
    spec = _integer_spec(max_constituents=20, tracking_error_budget=0.06)
    result = run_review(spec, universe, index_id="x", review_date="2026-03-31", risk_model=model)
    assert result.exceptions == []
    assert len(_held(result)) == 20
    assert result.diagnostics.tracking_error <= 0.06 * (1 + 1e-4)


def test_cardinality_composes_with_score_maximisation():
    from arp.index.mock_data import demo_risk_model

    universe = demo_universe()
    model = demo_risk_model(universe)
    spec = _integer_spec(max_constituents=20, tracking_error_budget=0.08)
    spec.constraints.solver.method = "max_score"
    spec.constraints.solver.score_field = "esg_score"
    result = run_review(spec, universe, index_id="x", review_date="2026-03-31", risk_model=model)
    assert result.exceptions == []
    assert len(_held(result)) <= 20
    assert result.diagnostics.weighted_metrics["esg_score"] > result.diagnostics.universe_weighted_metrics["esg_score"]


def test_a_cardinality_ceiling_is_not_a_target():
    """Easy to misread. A linear objective concentrates into the fewest names
    the caps allow, so `max_constituents` alone does not give a fixed-size
    index -- a quadratic objective happens to fill the ceiling, a linear one
    does not. Pin both bounds to the same number to fix the count."""
    from arp.index.mock_data import demo_risk_model

    universe = demo_universe()
    model = demo_risk_model(universe)

    scoring = _integer_spec(max_constituents=20, tracking_error_budget=0.08)
    scoring.constraints.solver.method = "max_score"
    scoring.constraints.solver.score_field = "esg_score"
    concentrated = run_review(scoring, universe, index_id="x", review_date="2026-03-31", risk_model=model)
    assert len(_held(concentrated)) < 20

    exact = _integer_spec(min_constituents=20, max_constituents=20)
    fixed = run_review(exact, universe, index_id="x", review_date="2026-03-31")
    assert len(_held(fixed)) == 20


def test_a_truncated_integer_solve_is_a_failure_not_an_answer():
    """A time-limited branch-and-bound returns whatever incumbent it had when
    the clock ran out, which depends on how fast the machine is. Only a proven
    optimum is reproducible, so a truncation must fall back rather than
    publish."""
    universe = demo_universe()
    spec = _integer_spec(max_constituents=20, mip_time_limit_seconds=0.001)
    result = run_review(spec, universe, index_id="x", review_date="2026-03-31")
    assert any("did not produce a usable solution" in e for e in result.exceptions)


def test_integer_verification_is_independent_of_the_solver(monkeypatch):
    """The floor is re-checked on the returned weights, because a solver can
    satisfy its linking constraints to its own tolerance and still leave a
    name below the published floor."""
    from arp.index.optimize import IntegerSpec, _verify_integer

    spec = IntegerSpec(min_weight=0.02, max_constituents=3, min_constituents=None, tie_break_epsilon=0.0)
    violations = _verify_integer({"a": 0.5, "b": 0.49, "c": 0.005, "d": 0.005}, spec, 1e-9)
    assert any("below the" in v for v in violations)
    assert any("exceeds the maximum" in v for v in violations)
