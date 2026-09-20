from __future__ import annotations

import json
from math import fsum

import pytest

from arp.index.calc import adjust_divisor, divisor_for_level, index_shares, level_series, market_cap, one_way_turnover
from arp.index.capping import apply_constraints
from arp.index.fields import DataQualityBlock
from arp.index.mock_data import demo_price_panel, demo_universe
from arp.index.pipeline import run_review
from arp.index.presets import PRESETS, build_preset
from arp.index.screens import apply_screens
from arp.index.selection import apply_selection
from arp.index.trajectory import minimum_achievable, required_metric_value
from arp.index.weighting import apply_tilts, base_weights
from arp.schemas.index import (
    AbsoluteThreshold,
    BaseWeighting,
    BestInClassCoverage,
    BucketTilt,
    CategoryScreen,
    ConstraintSet,
    ConstructionSpec,
    DecarbonisationTrajectory,
    FlagExclusionScreen,
    GroupCap,
    IndexCandidate,
    IndexState,
    MetricThresholdScreen,
    MetricTilt,
    RoundingPolicy,
    TopN,
)
from arp.storage.index_store import IndexStore

TOL = 1e-9


def _candidate(company_id, *, price=100.0, shares=1_000_000, sector="Industrials", country="DE", **metrics):
    flags = {k: v for k, v in metrics.items() if isinstance(v, bool)}
    categories = {k: v for k, v in metrics.items() if isinstance(v, str)}
    numbers = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return IndexCandidate(
        company_id=company_id,
        name=company_id.upper(),
        sector=sector,
        country=country,
        price=price,
        shares_outstanding=shares,
        metrics=numbers,
        flags=flags,
        categories=categories,
    )


# --------------------------------------------------------------- screens


def test_metric_threshold_screen_applies_both_bounds():
    candidates = [_candidate("a", esg_score=8.0), _candidate("b", esg_score=2.0), _candidate("c", esg_score=5.0)]
    kept, traces = apply_screens(candidates, [MetricThresholdScreen(field="esg_score", min_value=4.0, max_value=7.0)])
    assert [c.company_id for c in kept] == ["c"]
    assert traces[0].candidates_in == 3 and traces[0].candidates_out == 1


def test_flag_and_category_screens_compose_in_order():
    candidates = [
        _candidate("a", norms_violation=False, lct_category="solutions"),
        _candidate("b", norms_violation=True, lct_category="solutions"),
        _candidate("c", norms_violation=False, lct_category="asset_stranding"),
    ]
    kept, traces = apply_screens(
        candidates,
        [
            FlagExclusionScreen(field="norms_violation"),
            CategoryScreen(field="lct_category", deny=["asset_stranding"]),
        ],
    )
    assert [c.company_id for c in kept] == ["a"]
    assert [t.candidates_out for t in traces] == [2, 1]


def test_missing_value_blocks_the_run_by_default():
    candidates = [_candidate("a", esg_score=8.0), _candidate("b")]
    with pytest.raises(DataQualityBlock, match="missing value"):
        apply_screens(candidates, [MetricThresholdScreen(field="esg_score", min_value=1.0)])


def test_missing_policy_pass_is_a_deliberate_documented_override():
    candidates = [_candidate("a", esg_score=8.0), _candidate("b")]
    kept, _ = apply_screens(candidates, [MetricThresholdScreen(field="esg_score", min_value=1.0, missing="pass")])
    assert [c.company_id for c in kept] == ["a", "b"]


def test_disabled_rule_is_traced_not_silently_skipped():
    candidates = [_candidate("a", esg_score=1.0)]
    kept, traces = apply_screens(candidates, [MetricThresholdScreen(field="esg_score", min_value=5.0, enabled=False)])
    assert len(kept) == 1
    assert traces[0].detail["skipped"] == "rule disabled"


# ------------------------------------------------------------- selection


def test_best_in_class_selects_to_a_market_cap_coverage_target():
    # Four equal-cap names in one sector: a 50% float-cap target takes two.
    candidates = [_candidate(c, esg_score=score, sector="Tech") for c, score in [("a", 9.0), ("b", 7.0), ("c", 5.0), ("d", 3.0)]]
    selected, trace, _ = apply_selection(candidates, BestInClassCoverage(score_field="esg_score", group_by="sector", target_pct=0.5))
    assert [c.company_id for c in selected] == ["a", "b"]
    assert trace.detail["coverage_Tech"] >= 0.5


def test_coverage_target_by_count_is_a_different_rule_from_by_market_cap():
    candidates = [
        _candidate("big", price=1000.0, esg_score=1.0, sector="Tech"),
        _candidate("mid", price=100.0, esg_score=5.0, sector="Tech"),
        _candidate("small", price=10.0, esg_score=9.0, sector="Tech"),
    ]
    by_count, _, _ = apply_selection(candidates, BestInClassCoverage(score_field="esg_score", target_pct=0.6, basis="count"))
    by_cap, _, _ = apply_selection(candidates, BestInClassCoverage(score_field="esg_score", target_pct=0.6, basis="float_mcap"))
    assert [c.company_id for c in by_count] == ["mid", "small"]
    # By market cap the two small high-scorers cannot reach 67% of the
    # sector's cap, so the laggard is pulled in too.
    assert "big" in [c.company_id for c in by_cap]


def test_buffer_retains_an_incumbent_just_past_the_target():
    candidates = [_candidate(c, esg_score=score, sector="Tech") for c, score in [("a", 9.0), ("b", 7.0), ("c", 5.0), ("d", 3.0)]]
    rule = BestInClassCoverage(score_field="esg_score", target_pct=0.5, buffer_pct=0.30)
    without, _, _ = apply_selection(candidates, rule, incumbents=set())
    with_incumbent, _, _ = apply_selection(candidates, rule, incumbents={"c"})
    assert "c" not in [x.company_id for x in without]
    assert "c" in [x.company_id for x in with_incumbent]


def test_absolute_threshold_can_empty_a_group_and_says_so():
    candidates = [_candidate("a", esg_score=9.0, sector="Tech"), _candidate("b", esg_score=1.0, sector="Energy")]
    selected, _, exceptions = apply_selection(candidates, AbsoluteThreshold(score_field="esg_score", threshold=5.0))
    assert [c.company_id for c in selected] == ["a"]
    assert any("left empty" in e for e in exceptions)


def test_absolute_threshold_fallback_keeps_the_group_represented():
    candidates = [
        _candidate("a", esg_score=9.0, sector="Tech"),
        _candidate("b", esg_score=2.0, sector="Energy"),
        _candidate("c", esg_score=1.0, sector="Energy"),
    ]
    selected, _, exceptions = apply_selection(
        candidates,
        AbsoluteThreshold(score_field="esg_score", threshold=5.0, on_empty_group="fallback_relative", fallback_target_pct=0.5),
    )
    assert "b" in [c.company_id for c in selected]
    assert any("fell back" in e for e in exceptions)


def test_top_n_breaks_ties_deterministically():
    candidates = [_candidate(c, esg_score=5.0) for c in ("c", "a", "b")]
    first, _, _ = apply_selection(candidates, TopN(score_field="esg_score", n=2))
    second, _, _ = apply_selection(list(reversed(candidates)), TopN(score_field="esg_score", n=2))
    assert [c.company_id for c in first] == [c.company_id for c in second]


# ------------------------------------------------------- weighting/tilts


def test_base_weighting_schemes():
    candidates = [_candidate("a", price=100.0, shares=1_000_000), _candidate("b", price=100.0, shares=3_000_000)]
    cap = base_weights(candidates, BaseWeighting(scheme="free_float_mcap"))
    equal = base_weights(candidates, BaseWeighting(scheme="equal"))
    assert cap["a"] == pytest.approx(0.25) and cap["b"] == pytest.approx(0.75)
    assert equal["a"] == pytest.approx(0.5)


def test_metric_tilt_respects_floor_and_ceiling():
    candidates = [_candidate("a", esg_score=10.0), _candidate("b", esg_score=0.0)]
    weights = base_weights(candidates, BaseWeighting(scheme="equal"))
    _, multipliers, _ = apply_tilts(weights, candidates, [MetricTilt(field="esg_score", floor=0.8, ceiling=1.2)])
    assert multipliers["a"] == pytest.approx(1.2)
    assert multipliers["b"] == pytest.approx(0.8)


def test_tilt_floor_stops_a_tilt_becoming_an_exclusion():
    """The MSCI Climate Change floor: a worst-in-class name is underweighted,
    never zeroed, because zeroing it is an exclusion nobody approved."""
    candidates = [_candidate("a", esg_score=10.0), _candidate("b", esg_score=0.0)]
    weights = base_weights(candidates, BaseWeighting(scheme="equal"))
    tilted, _, _ = apply_tilts(weights, candidates, [MetricTilt(field="esg_score", floor=0.5, ceiling=1.5)])
    assert tilted["b"] > 0.0


def test_bucket_tilt_is_a_readable_multiplier_table():
    candidates = [_candidate("a", lct_category="solutions"), _candidate("b", lct_category="asset_stranding")]
    weights = base_weights(candidates, BaseWeighting(scheme="equal"))
    tilted, _, _ = apply_tilts(weights, candidates, [BucketTilt(field="lct_category", multipliers={"solutions": 2.0, "asset_stranding": 0.5})])
    assert tilted["a"] == pytest.approx(0.8)
    assert tilted["b"] == pytest.approx(0.2)


def test_tilts_compose_multiplicatively_in_order():
    candidates = [_candidate("a", esg_score=10.0, esg_trend=10.0), _candidate("b", esg_score=10.0, esg_trend=0.0)]
    weights = base_weights(candidates, BaseWeighting(scheme="equal"))
    _, multipliers, traces = apply_tilts(
        weights,
        candidates,
        [MetricTilt(field="esg_score", floor=1.0, ceiling=2.0), MetricTilt(field="esg_trend", floor=0.5, ceiling=1.0)],
    )
    assert multipliers["a"] == pytest.approx(2.0)
    assert multipliers["b"] == pytest.approx(1.0)
    assert len(traces) == 2


# -------------------------------------------------------------- capping


def test_waterfall_never_breaches_the_cap_and_always_fully_invests():
    candidates = [_candidate(f"c{i}", price=float(10 * (i + 1))) for i in range(12)]
    weights = base_weights(candidates, BaseWeighting(scheme="free_float_mcap"))
    capped, trace, exceptions = apply_constraints(weights, candidates, ConstraintSet(single_name_cap=0.12))
    assert max(capped.values()) <= 0.12 + TOL
    assert fsum(capped[k] for k in sorted(capped)) == pytest.approx(1.0, abs=1e-9)
    assert exceptions == []
    assert trace.detail["max_weight"] <= 0.12 + TOL


def test_infeasible_cap_is_reported_rather_than_silently_renormalised():
    candidates = [_candidate("a"), _candidate("b")]
    weights = base_weights(candidates, BaseWeighting(scheme="equal"))
    _, _, exceptions = apply_constraints(weights, candidates, ConstraintSet(single_name_cap=0.10))
    assert any("not satisfiable" in e for e in exceptions)


def test_ucits_5_10_40_holds_where_a_single_name_cap_alone_would_not():
    candidates = [_candidate(f"c{i}", price=100.0 if i < 6 else 1.0) for i in range(20)]
    weights = base_weights(candidates, BaseWeighting(scheme="free_float_mcap"))
    uncapped_aggregate = fsum(v for v in weights.values() if v > 0.05)
    capped, _, _ = apply_constraints(weights, candidates, ConstraintSet(single_name_cap=0.10, ucits_5_10_40=True))
    assert uncapped_aggregate > 0.40
    assert max(capped.values()) <= 0.10 + TOL
    assert fsum(v for v in capped.values() if v > 0.05 + 1e-10) <= 0.40 + 1e-6


def test_group_cap_limits_aggregate_sector_weight():
    candidates = (
        [_candidate(f"t{i}", sector="Tech") for i in range(6)]
        + [_candidate(f"e{i}", sector="Energy") for i in range(2)]
        + [_candidate(f"h{i}", sector="Health") for i in range(2)]
    )
    weights = base_weights(candidates, BaseWeighting(scheme="equal"))
    capped, _, _ = apply_constraints(weights, candidates, ConstraintSet(group_caps=[GroupCap(dimension="sector", max_weight=0.4)]))
    tech = fsum(v for k, v in capped.items() if k.startswith("t"))
    assert tech <= 0.40 + 1e-6
    assert fsum(capped[k] for k in sorted(capped)) == pytest.approx(1.0, abs=1e-9)


def test_infeasible_group_caps_are_reported_not_oscillated():
    """Two sectors capped at 40% each can hold at most 80% of the index.
    The engine says so instead of alternating between them forever."""
    candidates = [_candidate(f"t{i}", sector="Tech") for i in range(6)] + [_candidate(f"e{i}", sector="Energy") for i in range(2)]
    weights = base_weights(candidates, BaseWeighting(scheme="equal"))
    _, _, exceptions = apply_constraints(candidates=candidates, weights=weights, constraints=ConstraintSet(group_caps=[GroupCap(dimension="sector", max_weight=0.4)]))
    assert any("infeasible" in e for e in exceptions)


def test_min_weight_prunes_and_redistributes():
    candidates = [_candidate("big", price=1000.0), _candidate("tiny", price=1.0)]
    weights = base_weights(candidates, BaseWeighting(scheme="free_float_mcap"))
    capped, _, exceptions = apply_constraints(weights, candidates, ConstraintSet(min_weight=0.01))
    assert "tiny" not in capped
    assert capped["big"] == pytest.approx(1.0)
    assert any("min_weight" in e for e in exceptions)


# ----------------------------------------------------------- trajectory


def test_universe_relative_target_is_measured_against_the_current_universe():
    target, binding = required_metric_value(
        DecarbonisationTrajectory(enabled=True, universe_reduction_pct=0.5),
        review_date="2026-03-31",
        base_date=None,
        base_value=None,
        universe_value=100.0,
        shortfall_carry=0.0,
    )
    assert target == pytest.approx(50.0)
    assert binding == "universe_relative"


def test_trajectory_target_is_geometric_from_a_fixed_base():
    rule = DecarbonisationTrajectory(enabled=True, annual_reduction_rate=0.07)
    target, binding = required_metric_value(
        rule, review_date="2029-06-30", base_date="2026-06-30", base_value=100.0, universe_value=None, shortfall_carry=0.0
    )
    assert target == pytest.approx(100.0 * 0.93**3)
    assert binding == "trajectory"


def test_the_tighter_of_the_two_reductions_binds():
    rule = DecarbonisationTrajectory(enabled=True, annual_reduction_rate=0.07, universe_reduction_pct=0.5)
    # Year 0: the universe floor is tighter than an untouched base.
    target, binding = required_metric_value(
        rule, review_date="2026-01-01", base_date="2026-01-01", base_value=100.0, universe_value=100.0, shortfall_carry=0.0
    )
    assert binding == "universe_relative" and target == pytest.approx(50.0)
    # Years later, with the universe unchanged, the trajectory overtakes it.
    target, binding = required_metric_value(
        rule, review_date="2036-01-01", base_date="2026-01-01", base_value=50.0, universe_value=100.0, shortfall_carry=0.0
    )
    assert binding == "trajectory" and target < 50.0


def test_a_missed_target_tightens_the_next_one():
    rule = DecarbonisationTrajectory(enabled=True, annual_reduction_rate=0.07)
    clean, _ = required_metric_value(rule, review_date="2027-01-01", base_date="2026-01-01", base_value=100.0, universe_value=None, shortfall_carry=0.0)
    owed, _ = required_metric_value(rule, review_date="2027-01-01", base_date="2026-01-01", base_value=100.0, universe_value=None, shortfall_carry=0.10)
    assert owed < clean


def test_minimum_achievable_is_the_feasibility_frontier():
    values = {f"c{i}": float(i) for i in range(10)}
    # At a 20% cap only the five lowest can be held, at 20% each.
    assert minimum_achievable(values, 0.20) == pytest.approx((0 + 1 + 2 + 3 + 4) / 5)


def test_pab_preset_hits_the_reduction_exactly_and_ratchets_year_on_year():
    universe = demo_universe()
    spec = build_preset("eu_pab")

    first = run_review(spec, universe, index_id="pab", review_date="2026-03-31")
    achieved = first.diagnostics.weighted_metrics["ghg_intensity"]
    universe_value = first.diagnostics.universe_weighted_metrics["ghg_intensity"]
    assert achieved / universe_value == pytest.approx(0.5, abs=1e-3)
    assert first.state.binding_constraint == "universe_relative"
    assert first.exceptions == []

    second = run_review(spec, universe, index_id="pab", review_date="2027-03-31", prior_state=first.state)
    assert second.state.binding_constraint == "trajectory"
    assert second.state.required_metric_value == pytest.approx(first.state.base_metric_value * 0.93)
    assert second.diagnostics.weighted_metrics["ghg_intensity"] < achieved


def test_an_unreachable_target_carries_a_shortfall_and_names_the_frontier():
    universe = demo_universe()
    spec = build_preset("eu_pab")
    # A base far below what a 5% cap can reach on this universe.
    prior = IndexState(index_id="pab", review_date="2032-03-31", base_date="2026-03-31", base_metric_value=10.0)
    result = run_review(spec, universe, index_id="pab", review_date="2033-03-31", prior_state=prior)
    assert result.state.shortfall_carry > 0
    assert any("minimum achievable" in e for e in result.exceptions)
    assert any("carried forward" in e for e in result.exceptions)


def test_ctb_and_pab_differ_by_the_fossil_exclusions():
    universe = demo_universe()
    ctb = run_review(build_preset("eu_ctb"), universe, index_id="ctb", review_date="2026-03-31")
    pab = run_review(build_preset("eu_pab"), universe, index_id="pab", review_date="2026-03-31")
    assert ctb.diagnostics.eligible_size > pab.diagnostics.eligible_size


# ---------------------------------------------------------------- calc


def test_index_shares_and_divisor_reproduce_the_level_exactly():
    candidates = [_candidate("a", price=50.0), _candidate("b", price=200.0)]
    weights = {"a": 0.4, "b": 0.6}
    rounding = RoundingPolicy()
    shares = index_shares(weights, candidates, index_market_cap=1_000_000.0, rounding=rounding)
    realised = market_cap(shares, candidates)
    divisor = divisor_for_level(realised, 100.0)
    assert realised / divisor == pytest.approx(100.0, abs=1e-9)


def test_divisor_adjustment_keeps_the_level_continuous():
    before, after = 1_000_000.0, 1_250_000.0
    divisor_before = divisor_for_level(before, 100.0)
    divisor_after = adjust_divisor(divisor_before, before, after)
    assert after / divisor_after == pytest.approx(before / divisor_before)


def test_weights_drift_with_price_between_rebalances():
    """Index shares are fixed between reviews, so a name that outperforms
    gains weight without any trading -- which is what makes a cap-weighted
    index self-maintaining rather than a daily-rebalanced portfolio."""
    candidates = [_candidate("a", price=100.0), _candidate("b", price=100.0)]
    shares = index_shares({"a": 0.5, "b": 0.5}, candidates, index_market_cap=1_000_000.0, rounding=RoundingPolicy())
    panel = {"2026-01-01": {"a": 100.0, "b": 100.0}, "2026-01-02": {"a": 120.0, "b": 100.0}}
    points = level_series(shares, panel, divisor=divisor_for_level(market_cap(shares, candidates), 100.0))
    assert points[0].level == pytest.approx(100.0, abs=1e-6)
    assert points[1].level == pytest.approx(110.0, abs=1e-3)


def test_stale_prices_are_carried_and_counted():
    candidates = [_candidate("a", price=100.0), _candidate("b", price=100.0)]
    shares = index_shares({"a": 0.5, "b": 0.5}, candidates, index_market_cap=1_000_000.0, rounding=RoundingPolicy())
    panel = {"2026-01-01": {"a": 100.0, "b": 100.0}, "2026-01-02": {"a": 110.0}}
    points = level_series(shares, panel, divisor=divisor_for_level(market_cap(shares, candidates), 100.0))
    assert points[1].constituents_priced == 1
    assert points[1].level > points[0].level


def test_one_way_turnover_is_half_the_absolute_weight_change():
    assert one_way_turnover({"a": 0.5, "b": 0.5}, {"a": 0.6, "b": 0.4}) == pytest.approx(0.1)
    assert one_way_turnover({"a": 1.0}, {"b": 1.0}) == pytest.approx(1.0)


# -------------------------------------------------------- determinism


def test_identical_inputs_produce_identical_output():
    universe = demo_universe()
    spec = build_preset("esg_tilt")
    first = run_review(spec, universe, index_id="d", review_date="2026-03-31")
    second = run_review(spec, universe, index_id="d", review_date="2026-03-31")
    assert [c.model_dump() for c in first.constituents] == [c.model_dump() for c in second.constituents]


def test_input_ordering_does_not_change_the_index():
    universe = demo_universe()
    spec = build_preset("best_in_class")
    ordered = run_review(spec, universe, index_id="d", review_date="2026-03-31")
    shuffled = run_review(spec, list(reversed(universe)), index_id="d", review_date="2026-03-31")
    assert [c.model_dump() for c in ordered.constituents] == [c.model_dump() for c in shuffled.constituents]


def test_config_hash_ignores_labels_but_not_parameters():
    a = ConstructionSpec(screens=[MetricThresholdScreen(field="esg_score", min_value=5.0)])
    relabelled = ConstructionSpec(screens=[MetricThresholdScreen(field="esg_score", min_value=5.0, label="quality floor")])
    changed = ConstructionSpec(screens=[MetricThresholdScreen(field="esg_score", min_value=6.0)])
    assert a.content_hash() == relabelled.content_hash()
    assert a.content_hash() != changed.content_hash()


def test_every_preset_builds_and_runs():
    universe = demo_universe()
    for name in PRESETS:
        result = run_review(build_preset(name), universe, index_id="p", review_date="2026-03-31")
        assert result.diagnostics.final_size > 0
        assert fsum(c.weight for c in result.constituents) == pytest.approx(1.0, abs=1e-6)
        assert result.trace[0].stage == "universe"


def test_demo_universe_and_price_panel_are_reproducible():
    assert [c.model_dump() for c in demo_universe(10)] == [c.model_dump() for c in demo_universe(10)]
    universe = demo_universe(5)
    dates = ["2026-01-01", "2026-01-02"]
    assert demo_price_panel(universe, dates) == demo_price_panel(universe, dates)


# --------------------------------------------------------------- store


def test_calibration_versions_are_append_only_and_effective_dated(tmp_path):
    store = IndexStore(tmp_path)
    v1 = store.create_calibration("DWS PAB", build_preset("eu_ctb"), effective_from="2026-01-01", notes="initial")
    v2 = store.new_calibration_version(v1.calibration_id, build_preset("eu_pab"), effective_from="2026-07-01", notes="tightened")

    assert v2.version == 2 and v2.based_on_version == 1
    assert store.resolve_for_date(v1.calibration_id, "2026-03-31").version == 1
    assert store.resolve_for_date(v1.calibration_id, "2026-09-30").version == 2
    assert store.resolve_for_date(v1.calibration_id, "2025-12-31") is None
    # v1 is still byte-for-byte what was approved, with its window closed.
    stored_v1 = store.get_calibration(v1.calibration_id, 1)
    assert stored_v1.config_hash == v1.config_hash
    assert stored_v1.effective_to == "2026-07-01"


def test_calibration_versions_are_forward_only(tmp_path):
    store = IndexStore(tmp_path)
    v1 = store.create_calibration("c", build_preset("eu_ctb"), effective_from="2026-06-01")
    with pytest.raises(ValueError, match="forward-only"):
        store.new_calibration_version(v1.calibration_id, build_preset("eu_pab"), effective_from="2026-01-01")


def test_reviews_chain_state_through_the_store(tmp_path):
    store = IndexStore(tmp_path)
    universe = demo_universe()
    spec = build_preset("eu_pab")
    first = run_review(spec, universe, index_id="pab", review_date="2026-03-31")
    store.save_review(first)

    prior = store.latest_state_before("pab", "2027-03-31")
    assert prior is not None and prior.review_date == "2026-03-31"
    second = run_review(spec, universe, index_id="pab", review_date="2027-03-31", prior_state=prior)
    store.save_review(second)

    assert store.list_review_dates("pab") == ["2026-03-31", "2027-03-31"]
    assert store.list_indices() == ["pab"]
    # Strictly-before, so re-running a review reads the same prior state
    # rather than compounding its own output.
    assert store.latest_state_before("pab", "2027-03-31").review_date == "2026-03-31"


def test_saved_review_round_trips(tmp_path):
    store = IndexStore(tmp_path)
    result = run_review(build_preset("best_in_class"), demo_universe(), index_id="bic", review_date="2026-03-31")
    store.save_review(result)
    loaded = store.get_review("bic", "2026-03-31")
    assert json.loads(loaded.model_dump_json()) == json.loads(result.model_dump_json())


def test_index_shares_are_replicable_sized_at_inception():
    """At inception the index is capitalised at its constituents' real float
    market cap, not at the bare base level -- otherwise index shares come out
    as hundredths of a share, which is arithmetically fine and useless to
    anyone replicating the index."""
    result = run_review(build_preset("exclusion_only"), demo_universe(), index_id="i", review_date="2026-03-31")
    assert min(c.index_shares for c in result.constituents) > 1.0
    # And the divisor still reproduces the base level exactly.
    assert result.state.index_level == pytest.approx(100.0)
    assert result.state.divisor > 0


def test_a_continuing_index_keeps_its_level_across_a_rebalance(tmp_path):
    store = IndexStore(tmp_path)
    spec = build_preset("exclusion_only")
    first = run_review(spec, demo_universe(), index_id="i", review_date="2026-03-31")
    store.save_review(first)
    second = run_review(spec, demo_universe(), index_id="i", review_date="2026-06-30", prior_state=first.state)
    assert second.state.index_level == pytest.approx(first.state.index_level)
