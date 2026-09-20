from __future__ import annotations

from pathlib import Path

import pytest

from arp.decision.cluster import cluster_criteria, correlation_matrix
from arp.decision.dataset import build_dataset, dataset_from_file
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.normalise import normalise_column
from arp.decision.parsing import detect_decimal_comma, sniff_delimiter, to_bool, to_number
from arp.decision.profiling import profile_dataset
from arp.decision.scoring import compute_scores
from arp.decision.tree import derive_cuts, quantile_positions, tier_for_score
from arp.decision.weighting import breadth_adjusted_weight, effective_weights
from arp.schemas.decision import ColumnProfile, Criterion, Dimension, MechanismConfig

SAMPLE = Path(__file__).resolve().parents[1] / "arp" / "decision" / "sample_data" / "example_transition_universe.csv"


@pytest.fixture(scope="module")
def sample_dataset():
    return dataset_from_file(SAMPLE)


# --- parsing -------------------------------------------------------------


def test_semicolon_and_german_decimals_parse_without_cleaning():
    """A German-locale Excel export is the most common real input and the
    one most likely to be silently mis-parsed -- "1.234,5" read as 1.234 is
    a plausible-looking number, not an error."""
    text = "Firma;Intensitaet;Abdeckung\nAlpha;1.234,5;91,4\nBeta;887,25;88,0\n"
    assert sniff_delimiter(text) == ";"
    rows = build_dataset("de.csv", [r for r in __import__("arp.decision.parsing", fromlist=["x"]).parse_delimited(text)])
    profiles = profile_dataset(rows)
    assert profiles["Intensitaet"].decimal_comma is True
    assert to_number("1.234,5", True) == pytest.approx(1234.5)
    assert to_number("91,4", True) == pytest.approx(91.4)


def test_thousands_separated_dot_locale():
    assert to_number("1,234.5") == pytest.approx(1234.5)
    assert to_number("91.4") == pytest.approx(91.4)
    assert detect_decimal_comma(["1.234,5", "88,2"]) is True
    assert detect_decimal_comma(["1,234.5", "88.2"]) is False


def test_bilingual_booleans():
    assert to_bool("Ja") == 1 and to_bool("wahr") == 1 and to_bool("Yes") == 1
    assert to_bool("Nein") == 0 and to_bool("No") == 0
    assert to_bool("maybe") is None


def test_blank_conventions_are_missing_not_zero():
    assert to_number("n/a") is None
    assert to_number("N.A.") is None
    assert to_number("") is None


# --- profiling -----------------------------------------------------------


def test_types_come_from_values_not_headers(sample_dataset):
    profiles = profile_dataset(sample_dataset)
    assert profiles["Company"].type == "identifier", "one distinct value per row"
    assert profiles["ISIN"].type == "identifier"
    assert profiles["Sector"].type == "categorical"
    assert profiles["Scope3_Reported"].type == "boolean"
    assert profiles["Board_Climate_Oversight_0_3"].type == "ordinal"
    assert profiles["Scope12_Intensity_tCO2e_per_mEUR"].type == "numeric"


def test_coverage_is_reported_per_column(sample_dataset):
    profiles = profile_dataset(sample_dataset)
    assert profiles["Company"].coverage == 1.0
    assert profiles["Say_on_Climate_Support_pct"].coverage < 1.0


# --- direction and roles -------------------------------------------------


def test_direction_is_inferred_and_ambiguity_is_flagged(sample_dataset):
    config, audit = derive_mechanism(sample_dataset)
    directions = {c.column: c.direction for c in config.criteria}
    assert directions["Scope12_Intensity_tCO2e_per_mEUR"] == "lower"
    assert directions["Emissions_Data_Coverage_pct"] == "higher"
    assert directions["Green_Capex_Share_pct"] == "higher"
    flagged = [e for e in audit if e.stage == "Direction" and e.needs_check]
    assert all("worth checking" in e.why or "please confirm" in e.why for e in flagged)


def test_high_cardinality_text_becomes_the_label_not_a_reference(sample_dataset):
    config, _ = derive_mechanism(sample_dataset)
    assert config.label_column == "Company"
    assert "ISIN" not in {c.column for c in config.criteria}


def test_size_and_gate_columns_are_not_scored(sample_dataset):
    config, _ = derive_mechanism(sample_dataset)
    scored = {c.column for c in config.criteria}
    assert "Portfolio_Weight_bps" not in scored, "position size is not a quality indicator"
    assert config.size_column == "Portfolio_Weight_bps"
    gated = {g.column for g in config.gates}
    assert "Severe_Controversy_Flag" in gated
    assert next(g for g in config.gates if g.column == "Severe_Controversy_Flag").outcome == "exclude"
    assert next(g for g in config.gates if g.column == "Coal_Expansion_Flag").outcome == "demote"


# --- normalisation -------------------------------------------------------


def test_lone_present_value_maps_to_the_neutral_midpoint():
    """With nothing to compare against, neither extreme is defensible."""
    profile = ColumnProfile(name="x", type="numeric", coverage=0.2, unique=1, spread=False)
    out = normalise_column([None, 7.0, None], profile, method="percentile", winsor_pct=5, direction="higher")
    assert out == [None, 50.0, None]


def test_booleans_bypass_winsorising():
    profile = ColumnProfile(name="flag", type="boolean", coverage=1.0, unique=2, spread=True)
    out = normalise_column([1.0, 0.0, 1.0, None], profile, method="zscore", winsor_pct=20, direction="higher")
    assert out == [100.0, 0.0, 100.0, None]


def test_direction_lower_inverts_the_scale():
    profile = ColumnProfile(name="intensity", type="numeric", coverage=1.0, unique=3, spread=True)
    higher = normalise_column([1.0, 2.0, 3.0], profile, method="percentile", winsor_pct=5, direction="higher")
    lower = normalise_column([1.0, 2.0, 3.0], profile, method="percentile", winsor_pct=5, direction="lower")
    assert higher == [0.0, 50.0, 100.0]
    assert lower == [100.0, 50.0, 0.0]


def test_peer_cohort_normalisation_ranks_within_the_cohort():
    """Scoring an intensity across unlike sectors in one ranking is close to
    meaningless; within-cohort ranking is what makes it comparable."""
    profile = ColumnProfile(name="intensity", type="numeric", coverage=1.0, unique=6, spread=True)
    values = [10.0, 20.0, 30.0, 1000.0, 2000.0, 3000.0]
    cohorts = ["software"] * 3 + ["utilities"] * 3
    out = normalise_column(
        values, profile, method="percentile", winsor_pct=5, direction="higher", cohorts=cohorts, min_cohort_size=3
    )
    assert out == [0.0, 50.0, 100.0, 0.0, 50.0, 100.0]


def test_cohorts_below_the_floor_fall_back_to_whole_table():
    profile = ColumnProfile(name="intensity", type="numeric", coverage=1.0, unique=4, spread=True)
    values = [1.0, 2.0, 3.0, 4.0]
    out = normalise_column(
        values, profile, method="percentile", winsor_pct=5, direction="higher", cohorts=["a", "a", "b", "b"], min_cohort_size=3
    )
    assert out == [0.0, pytest.approx(33.333, abs=0.01), pytest.approx(66.667, abs=0.01), 100.0]


# --- clustering and weighting -------------------------------------------


def test_correlated_criteria_are_grouped_under_complete_linkage():
    """Complete, not single, linkage: every pair inside a dimension must
    clear the threshold, so a chain of moderate correlations cannot
    swallow the framework."""
    a = [float(i) for i in range(10)]
    normalised = {"a": a, "b": list(a), "c": [float(10 - i) for i in range(10)]}
    correlations = correlation_matrix(normalised)
    clusters = cluster_criteria(["a", "b", "c"], correlations, 0.72)
    grouped = sorted(sorted(c) for c in clusters)
    assert ["a", "b"] in grouped
    assert ["c"] in grouped


def test_breadth_adjusted_weight_is_sublinear():
    """A theme measured seven ways counts for more than one measured once,
    but not seven times more."""
    assert breadth_adjusted_weight(1) == 1.0
    assert breadth_adjusted_weight(4) == 2.0
    assert breadth_adjusted_weight(7) < 7


def test_dimension_weight_is_shared_by_its_criteria():
    config = MechanismConfig(
        dimensions=[Dimension(id="d0", name="Big", weight=1.0), Dimension(id="d1", name="Small", weight=1.0)],
        criteria=[
            Criterion(column="a", dimension_id="d0"),
            Criterion(column="b", dimension_id="d0"),
            Criterion(column="c", dimension_id="d1"),
        ],
    )
    weights = effective_weights(config, ["a", "b", "c"])
    assert weights["a"] == pytest.approx(0.25)
    assert weights["b"] == pytest.approx(0.25)
    assert weights["c"] == pytest.approx(0.5)
    assert sum(weights.values()) == pytest.approx(1.0)


# --- scoring -------------------------------------------------------------


def test_renormalise_invents_nothing_and_reports_coverage():
    normalised = {"a": [100.0, None], "b": [0.0, 50.0]}
    weights = {"a": 0.5, "b": 0.5}
    rows = compute_scores(normalised, weights, missing="renormalise", row_count=2)
    assert rows[0].score == pytest.approx(50.0)
    assert rows[0].coverage == pytest.approx(1.0)
    assert rows[1].score == pytest.approx(50.0), "scored on what is present, not on an invented value"
    assert rows[1].coverage == pytest.approx(0.5)


def test_neutral_policy_imputes_and_marks_the_contribution():
    normalised = {"a": [None], "b": [100.0]}
    rows = compute_scores(normalised, {"a": 0.5, "b": 0.5}, missing="neutral", row_count=1)
    assert rows[0].score == pytest.approx(75.0)
    assert [c.imputed for c in rows[0].contributions] == [True, False]


def test_grounded_coverage_separates_present_from_verified():
    """'Present' and 'independently verified' are different claims, and a
    score resting mostly on the latter's absence should say so."""
    normalised = {"a": [100.0], "b": [100.0]}
    confidence = {"a": [0.95], "b": [0.2]}
    rows = compute_scores(normalised, {"a": 0.5, "b": 0.5}, missing="renormalise", row_count=1, confidence=confidence)
    assert rows[0].coverage == pytest.approx(1.0)
    assert rows[0].grounded_coverage == pytest.approx(0.5)
    assert [c.low_confidence for c in rows[0].contributions] == [False, True]


def test_grounded_coverage_is_none_when_no_confidence_supplied():
    rows = compute_scores({"a": [100.0]}, {"a": 1.0}, missing="renormalise", row_count=1)
    assert rows[0].grounded_coverage is None


# --- decision tree -------------------------------------------------------


def test_quantile_positions_reproduce_the_80_50_20_split():
    assert quantile_positions(3) == [0.8, 0.5, 0.2]
    assert quantile_positions(1) == [0.5]


def test_tier_assignment_walks_the_cuts_in_order():
    assert tier_for_score(90, [80, 50, 20]) == 1
    assert tier_for_score(80, [80, 50, 20]) == 1
    assert tier_for_score(49, [80, 50, 20]) == 3
    assert tier_for_score(1, [80, 50, 20]) == 4


def test_pinned_cuts_survive_a_rerun_against_different_data():
    """The prototype wrote derived cuts back into the saved config on every
    recompute, so a 'saved' framework silently carried whatever dataset was
    last loaded. Pinned and derived are separate here."""
    config = MechanismConfig(cut_mode="absolute", pinned_cuts=[70.0, 50.0, 30.0])
    cuts, origin = derive_cuts([10.0, 20.0, 90.0, 95.0, 99.0], config)
    assert cuts == [70.0, 50.0, 30.0]
    assert origin == "absolute"
    assert config.pinned_cuts == [70.0, 50.0, 30.0], "applying a framework must not mutate it"


def test_breaks_mode_reports_the_mode_that_actually_produced_the_cuts():
    config = MechanismConfig(cut_mode="breaks")
    _cuts, origin = derive_cuts([10.0, 20.0, 30.0], config)
    assert origin == "quantile", "too little data for natural breaks -- and it says so rather than claiming otherwise"


# --- end to end ----------------------------------------------------------


def test_gates_resolve_before_the_average(sample_dataset):
    """A knockout is a decision, not a deduction: an excluded entity never
    reaches the score, where a strong dimension could dilute it."""
    config, audit = derive_mechanism(sample_dataset)
    result = apply_mechanism(sample_dataset, config, derivation_audit=audit)
    excluded = [e for e in result.entities if e.status == "excluded"]
    assert excluded, "the sample carries severe-controversy flags"
    assert all(e.tier is None and e.rank is None for e in excluded)
    assert all("Gate:" in "".join(e.notes) for e in excluded)


def test_insufficient_coverage_is_routed_not_scored(sample_dataset):
    config, audit = derive_mechanism(sample_dataset)
    result = apply_mechanism(sample_dataset, config, derivation_audit=audit)
    insufficient = [e for e in result.entities if e.status == "insufficient"]
    assert insufficient, "the sample carries a sparsely covered entity"
    assert all(e.tier is None for e in insufficient)
    assert all(e.coverage * 100 < config.min_coverage_pct for e in insufficient)


def test_cuts_are_drawn_over_the_eligible_field_only(sample_dataset):
    config, audit = derive_mechanism(sample_dataset)
    result = apply_mechanism(sample_dataset, config, derivation_audit=audit)
    eligible = sorted(e.score for e in result.entities if e.status == "scored")
    assert result.effective_cuts[0] <= max(eligible)
    assert result.effective_cuts[-1] >= min(eligible)
    entry = next(e for e in result.audit if e.stage == "Cut-points")
    assert str(len(eligible)) in entry.why


def test_rank_stability_band_widens_where_the_ranking_is_contested(sample_dataset):
    config, audit = derive_mechanism(sample_dataset)
    result = apply_mechanism(sample_dataset, config, derivation_audit=audit)
    scored = [e for e in result.entities if e.status == "scored"]
    assert all(e.rank_min <= e.rank <= e.rank_max for e in scored)
    assert any(e.rank_min != e.rank_max for e in scored), "some ranking must depend on the specification chosen"


def test_veto_only_applies_to_dimensions_with_two_or_more_criteria():
    """A dimension resting on one yes/no answer must not be able to demote
    on its own."""
    matrix = [
        ["Name", "Alpha_Score", "Beta_Score", "Solo_Flag"],
        ["A", "90", "95", "No"],
        ["B", "80", "85", "No"],
        ["C", "70", "75", "No"],
        ["D", "60", "65", "No"],
        ["E", "50", "55", "No"],
        ["F", "40", "45", "No"],
    ]
    dataset = build_dataset("veto.csv", matrix)
    config = MechanismConfig(
        dimensions=[Dimension(id="d0", name="Pair", weight=1.0), Dimension(id="d1", name="Solo", weight=1.0)],
        criteria=[
            Criterion(column="Alpha_Score", dimension_id="d0"),
            Criterion(column="Beta_Score", dimension_id="d0"),
            Criterion(column="Solo_Flag", dimension_id="d1"),
        ],
        label_column="Name",
        min_coverage_pct=0,
    )
    config.veto.min_score = 99
    result = apply_mechanism(dataset, config)
    demoted_by_solo = [e for e in result.entities if any("Solo" in n for n in e.notes)]
    assert not demoted_by_solo, "a one-criterion dimension cannot trigger the floor"


def test_leverage_orders_by_size_times_the_gap(sample_dataset):
    config, audit = derive_mechanism(sample_dataset)
    result = apply_mechanism(sample_dataset, config, derivation_audit=audit)
    leveraged = sorted((e for e in result.entities if e.leverage is not None), key=lambda e: e.leverage_rank)
    assert leveraged[0].leverage >= leveraged[-1].leverage
    for entity in leveraged:
        assert entity.leverage == pytest.approx(entity.size * (100 - entity.score) / 100)


def test_applying_a_framework_never_mutates_it(sample_dataset):
    config, _ = derive_mechanism(sample_dataset)
    before = config.model_dump_json()
    apply_mechanism(sample_dataset, config)
    assert config.model_dump_json() == before


def test_same_input_scores_identically_every_time(sample_dataset):
    config, _ = derive_mechanism(sample_dataset)
    first = apply_mechanism(sample_dataset, config)
    second = apply_mechanism(sample_dataset, config)
    assert [(e.name, e.score, e.tier) for e in first.entities] == [(e.name, e.score, e.tier) for e in second.entities]


def test_audit_log_states_the_threshold_it_actually_used(sample_dataset):
    """The audit log is the product here. The prototype's log claimed a 0.60
    grouping threshold while the code used 0.72."""
    config, audit = derive_mechanism(sample_dataset, cluster_threshold=0.8)
    standalone = [e for e in audit if e.stage == "Dimensions" and e.decision == "stands alone"]
    assert standalone
    assert all("0.80" in e.why for e in standalone)
    assert not any("0.60" in e.why for e in audit)
