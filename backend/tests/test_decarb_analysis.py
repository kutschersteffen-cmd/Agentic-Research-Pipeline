"""Analysis modules: identities, edge cases, and the guardrails that matter.

The most important assertions here are the ones that would catch a silent
methodological error rather than a crash: the LMDI identity holding exactly,
the Scope 2 basis check firing, and the predictive design refusing a split
that would leak.
"""

from __future__ import annotations

import math

import pytest

from arp.decarb import attribution, divergence, labels, predict, redflags, saturation, scope2
from arp.decarb.schemas import EmissionsBasis, FirmYear, Panel, Scope2Basis
from arp.decarb.synthetic import GOVERNANCE_INDICATORS, make_panel


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------

def test_panel_rejects_mixed_scope2_basis():
    """The single most consequential data error this codebase can prevent."""
    rows = [
        FirmYear("A", 2020, scope1=10, scope2=2, scope2_basis=Scope2Basis.LOCATION),
        FirmYear("B", 2020, scope1=10, scope2=2, scope2_basis=Scope2Basis.MARKET),
    ]
    with pytest.raises(ValueError, match="mixes Scope 2 accounting bases"):
        Panel(rows)


def test_scope12_and_intensity_handle_missing_inputs():
    assert FirmYear("A", 2020, scope1=None).scope12 is None
    assert FirmYear("A", 2020, scope1=10).scope12 == 10  # absent Scope 2 treated as zero
    assert FirmYear("A", 2020, scope1=10, revenue=0).intensity() is None
    assert FirmYear("A", 2020, scope1=10, revenue=5).intensity() == pytest.approx(2.0)


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------

def test_chained_change_isolates_the_perimeter_effect():
    """A firm leaving the sample must not register as decarbonisation."""
    rows = [
        FirmYear("A", 2019, scope1=100, revenue=10),
        FirmYear("A", 2024, scope1=100, revenue=10),
        FirmYear("B", 2019, scope1=900, revenue=90),  # exits
    ]
    result = labels.chained_change(Panel(rows), 2019, 2024)
    assert result.chained_pct == pytest.approx(0.0)      # no firm emitted less
    assert result.aggregate_pct == pytest.approx(-0.9)   # sample total fell 90%
    assert result.composition_pct == pytest.approx(-0.9)
    assert result.n_exited == 1


def test_annualised_change_and_non_positive_inputs():
    assert labels.annualised_change(100, 121, 2) == pytest.approx(0.1)
    assert math.isnan(labels.annualised_change(0, 100, 2))
    assert math.isnan(labels.annualised_change(100, -5, 2))


def test_decarboniser_labels_exclude_estimated_by_default():
    rows = [
        FirmYear("A", 2019, scope1=100, basis=EmissionsBasis.REPORTED),
        FirmYear("A", 2022, scope1=80, basis=EmissionsBasis.REPORTED),
        FirmYear("B", 2019, scope1=100, basis=EmissionsBasis.ESTIMATED),
        FirmYear("B", 2022, scope1=80, basis=EmissionsBasis.ESTIMATED),
    ]
    panel = Panel(rows)
    strict = labels.decarboniser_labels(panel, start_year=2019, end_year=2022, winsor=None)
    assert set(strict) == {"A"}
    loose = labels.decarboniser_labels(
        panel, start_year=2019, end_year=2022, disclosed_only=False, winsor=None
    )
    assert set(loose) == {"A", "B"}


def test_forward_labels_are_keyed_by_base_year_and_look_ahead():
    rows = [FirmYear("A", y, scope1=100 * (0.9 ** (y - 2018))) for y in range(2018, 2024)]
    fwd = labels.forward_labels(Panel(rows), horizon=2)
    assert ("A", 2018) in fwd
    rate, is_dec = fwd[("A", 2018)]
    assert rate == pytest.approx(-0.1, abs=1e-9)
    assert is_dec
    # No label where the horizon runs off the end of the series.
    assert ("A", 2023) not in fwd


# --------------------------------------------------------------------------
# attribution
# --------------------------------------------------------------------------

def test_lmdi_identity_holds_exactly():
    """emissions + normalisation + allocation must reconstruct the change."""
    panel = make_panel(n_firms=120, seed=7)
    years = panel.years
    attr = attribution.decompose_waci(panel.by_year(years[0]), panel.by_year(years[-1]))
    assert attr.residual == pytest.approx(0.0, abs=1e-9)
    assert attr.explained == pytest.approx(attr.total_change, abs=1e-9)


def test_attribution_assigns_pure_revenue_growth_to_normalisation():
    start = {"A": FirmYear("A", 2019, scope1=100, revenue=10, weight=1.0)}
    end = {"A": FirmYear("A", 2024, scope1=100, revenue=20, weight=1.0)}
    attr = attribution.decompose_waci(start, end)
    assert attr.emissions == pytest.approx(0.0, abs=1e-12)
    assert attr.allocation == pytest.approx(0.0, abs=1e-12)
    assert attr.normalisation == pytest.approx(attr.total_change, abs=1e-12)
    assert attr.total_change < 0  # intensity halved


def test_attribution_assigns_entries_and_exits_to_allocation():
    start = {"A": FirmYear("A", 2019, scope1=100, revenue=10, weight=1.0)}
    end = {
        "A": FirmYear("A", 2024, scope1=100, revenue=10, weight=0.5),
        "B": FirmYear("B", 2024, scope1=100, revenue=10, weight=0.5),
    }
    attr = attribution.decompose_waci(start, end)
    assert attr.n_entered == 1
    assert attr.emissions == pytest.approx(0.0, abs=1e-12)
    assert attr.residual == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# scope2
# --------------------------------------------------------------------------

def test_scope2_wedge_detects_procurement_driven_progress():
    """Location flat, market falling: progress is contractual, not physical."""
    rows = [
        FirmYear("A", 2020, scope1=1, scope2_location=100, scope2_market=100),
        FirmYear("A", 2024, scope1=1, scope2_location=100, scope2_market=50),
    ]
    w = scope2.wedge_summary(Panel(rows), 2020, 2024)
    assert w.n_firms == 1
    assert w.location_change_pct == pytest.approx(0.0)
    assert w.market_change_pct == pytest.approx(-0.5)
    assert w.wedge_pct == pytest.approx(0.5)


def test_dual_reporters_requires_both_bases_in_both_years():
    rows = [
        FirmYear("A", 2020, scope2_location=10, scope2_market=10),
        FirmYear("A", 2024, scope2_location=10),  # market missing
    ]
    assert scope2.dual_reporters(Panel(rows), 2020, 2024) == []


def test_technology_shows_the_widest_wedge_in_the_calibrated_panel():
    panel = make_panel(n_firms=400, seed=11)
    by_sector = scope2.wedge_by_group(panel, 2020, 2024, key="sector")
    assert "Technology" in by_sector
    widest = max(by_sector.items(), key=lambda kv: kv[1].wedge_pct)[0]
    assert widest == "Technology"


# --------------------------------------------------------------------------
# saturation
# --------------------------------------------------------------------------

def test_rarity_weight_is_information_content():
    entry = saturation.IndicatorYear("x", 2020, prevalence=0.5, n=100)
    assert entry.rarity_weight == pytest.approx(math.log(2))
    assert not entry.is_saturated
    assert saturation.IndicatorYear("x", 2020, prevalence=0.95, n=100).is_saturated
    # Universally satisfied indicators carry no information.
    assert saturation.IndicatorYear("x", 2020, prevalence=1.0, n=100).rarity_weight == pytest.approx(0.0)


def test_common_indicators_saturate_and_rare_ones_do_not():
    panel = make_panel(n_firms=400, seed=3)
    first, last = panel.years[0], panel.years[-1]
    common = saturation.prevalence_by_year(panel, "board_oversight")
    rare = saturation.prevalence_by_year(panel, "scope3_supplier_program")
    assert common[last].prevalence > common[first].prevalence
    assert common[last].is_saturated
    assert not rare[last].is_saturated


def test_rarity_weighting_beats_a_raw_count_on_average():
    """The Dietz & Hastreiter result: weighting recovers signal a count loses.

    Asserted as a mean over seeds rather than on a single panel. The effect is
    real but small relative to cross-firm dispersion in emissions growth, so
    any one simulated panel can invert it. That is also true of the real data,
    which is why the review treats this as one good study rather than a
    settled result.
    """
    from arp.decarb.stats import auc_stratified

    weighted_scores, count_scores = [], []
    for seed in range(12):
        panel = make_panel(n_firms=400, seed=seed)
        first, last = panel.years[0], panel.years[-1]
        lab = labels.decarboniser_labels(panel, start_year=first, end_year=last)
        binary = {f: d for f, (_, d) in lab.items()}
        weighted = saturation.weighted_score(panel, GOVERNANCE_INDICATORS, year=first)
        counts = saturation.raw_count(panel, GOVERNANCE_INDICATORS, year=first)
        rows = {r.firm_id: r for r in panel.rows if r.year == first}
        common = sorted(set(weighted) & set(counts) & set(binary))
        if len(common) < 50:
            continue
        ys = [binary[f] for f in common]
        strata = [rows[f].sector for f in common]
        weighted_scores.append(auc_stratified([weighted[f] for f in common], ys, strata))
        count_scores.append(auc_stratified([float(counts[f]) for f in common], ys, strata))

    assert len(weighted_scores) >= 10
    mean_weighted = sum(weighted_scores) / len(weighted_scores)
    mean_count = sum(count_scores) / len(count_scores)
    assert mean_weighted > mean_count


def test_stratified_auc_removes_a_sector_confound():
    """A dominant sector trend can invert a pooled AUC; stratifying fixes it."""
    from arp.decarb.stats import auc, auc_stratified

    scores, ys, strata = [], [], []
    # Inside both sectors, a high score goes with the positive label. But
    # sector B is mostly negative and has systematically higher scores, which
    # drags the pooled statistic below 0.5.
    for _ in range(40):
        scores += [1.0, 0.0]
        ys += [True, False]
        strata += ["A", "A"]
    for _ in range(40):
        scores += [11.0, 10.0]
        ys += [False, False]
        strata += ["B", "B"]
    for _ in range(3):
        scores += [11.0]
        ys += [True]
        strata += ["B"]
    assert auc_stratified(scores, ys, strata) > auc(scores, ys)
    assert auc_stratified(scores, ys, strata) > 0.5


# --------------------------------------------------------------------------
# redflags
# --------------------------------------------------------------------------

def test_orthogonal_flags_are_reported_as_not_summable():
    panel = make_panel(n_firms=500, seed=13)
    verdict = redflags.profile_is_multidimensional(panel, year=panel.years[-1])
    assert verdict.n_pairs == 21  # 7 choose 2
    assert not verdict.composite_defensible
    assert "orthogonal" in verdict.explain()


def test_perfectly_correlated_flags_are_reported_as_summable():
    rows = []
    for i in range(80):
        bad = i % 2 == 0
        rows.append(FirmYear(f"F{i}", 2024, scope1=1.0, red_flags={k: bad for k in ("no_scope3_coverage", "questionable_offsets")}))
    verdict = redflags.profile_is_multidimensional(Panel(rows), year=2024)
    assert verdict.composite_defensible
    assert verdict.mean_abs_phi == pytest.approx(1.0)


def test_prevalence_tracks_the_published_benchmark():
    panel = make_panel(n_firms=800, seed=17)
    warnings = redflags.compare_to_published_prevalence(panel, year=panel.years[-1], tolerance=0.10)
    assert warnings == []  # generator is calibrated to Brown, Hsu & Manya


# --------------------------------------------------------------------------
# divergence
# --------------------------------------------------------------------------

def test_metric_families_agree_internally_and_not_across():
    panel = make_panel(n_firms=400, seed=19)
    report = divergence.divergence_report(panel, year=panel.years[-1])
    assert report.within_group_mean > report.between_group_mean
    assert report.separation > 0.2


def test_rank_disagreement_identifies_the_worst_offenders():
    panel = make_panel(n_firms=200, seed=23)
    gaps = divergence.rank_disagreement(
        panel, year=panel.years[-1], metric_a="taxonomy_capex", metric_b="emission_intensity", top_n=5
    )
    assert len(gaps) == 5
    assert all(isinstance(v, int) for v in gaps.values())


# --------------------------------------------------------------------------
# predict
# --------------------------------------------------------------------------

def test_design_refuses_overlapping_or_look_ahead_splits():
    with pytest.raises(ValueError, match="overlap"):
        predict.Design(train_years=[2018, 2019], test_years=[2019, 2020])
    with pytest.raises(ValueError, match="no look-ahead"):
        predict.Design(train_years=[2020, 2021], test_years=[2019])


def test_level_target_emits_a_warning_about_interpretation():
    n = 60
    base = [[float(i % 7), 1.0] for i in range(n)]
    extra = [[float(i % 3)] for i in range(n)]
    y_num = [float(i % 7) for i in range(n)]
    y_bin = [i % 2 == 0 for i in range(n)]
    years = [2018 + (i % 4) for i in range(n)]
    result = predict.evaluate(
        baseline_features=base,
        extra_features=extra,
        outcome_numeric=y_num,
        outcome_binary=y_bin,
        years=years,
        design=predict.Design(train_years=[2018, 2019], test_years=[2020, 2021], target=predict.Target.LEVEL),
    )
    assert any("not whether it is" in w for w in result.warnings)


def test_evaluate_rejects_misaligned_inputs():
    with pytest.raises(ValueError, match="row-aligned"):
        predict.evaluate(
            baseline_features=[[1.0]],
            extra_features=[[1.0], [2.0]],
            outcome_numeric=[1.0],
            outcome_binary=[True],
            years=[2020],
            design=predict.Design(train_years=[2019], test_years=[2020]),
        )


def test_sector_region_dummies_drop_first_level():
    rows = predict.sector_region_dummies(["A", "B", "C"], ["X", "Y", "X"])
    # 3 sectors -> 2 columns, 2 regions -> 1 column
    assert all(len(r) == 3 for r in rows)
    assert rows[0] == [0.0, 0.0, 0.0]  # both first levels
