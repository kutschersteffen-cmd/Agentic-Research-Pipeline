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
    assert trace.rule_type == "least_squares_projection"
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
