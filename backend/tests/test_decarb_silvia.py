"""Silvia et al. (2026) replication package.

The substantive test is `test_estimator_is_unbiased_for_the_true_coefficient`:
the simulated panel is built with a known coefficient, so the estimator can be
checked against ground truth rather than against its own output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arp.decarb.research import silvia

pytestmark = pytest.mark.filterwarnings("ignore")


# --------------------------------------------------------------------------
# instrument
# --------------------------------------------------------------------------

def test_instrument_matches_the_published_dimension_counts():
    items = silvia.load_items()
    assert len(items) == 24
    counts: dict[str, int] = {}
    for it in items:
        counts[it.dimension] = counts.get(it.dimension, 0) + 1
    assert counts == silvia.DIMENSIONS


def test_every_item_carries_a_question_and_a_coding_rule():
    for it in silvia.load_items():
        assert it.question.endswith("?")
        assert len(it.coding_rule) > 20


def test_ctpci_is_disclosed_over_applicable_items():
    items = silvia.load_items()
    all_yes = {i.item_id: True for i in items}
    all_no = {i.item_id: False for i in items}
    assert silvia.score_ctpci(all_yes) == pytest.approx(1.0)
    assert silvia.score_ctpci(all_no) == pytest.approx(0.0)
    half = {i.item_id: (n < 12) for n, i in enumerate(items)}
    assert silvia.score_ctpci(half) == pytest.approx(0.5)


def test_not_applicable_items_shrink_the_denominator():
    """Their formula divides by applicable items, so NA is not a failure."""
    items = silvia.load_items()
    coded = {i.item_id: True for i in items[:12]}
    coded.update({i.item_id: None for i in items[12:]})
    assert silvia.score_ctpci(coded) == pytest.approx(1.0)


def test_equal_dimension_weighting_changes_the_score():
    """Their robustness variant: item-rich dimensions stop dominating."""
    items = silvia.load_items()
    # Satisfy only the 5-item target dimension.
    coded = {i.item_id: (i.dimension == "target_credibility") for i in items}
    plain = silvia.score_ctpci(coded)
    weighted = silvia.score_ctpci(coded, equal_dimension_weight=True)
    assert plain == pytest.approx(5 / 24)
    assert weighted == pytest.approx(1 / 6)
    assert plain != weighted


def test_unknown_item_ids_are_rejected():
    with pytest.raises(ValueError, match="unknown CTPCI item"):
        silvia.score_ctpci({"NOT_AN_ITEM": True})


# --------------------------------------------------------------------------
# dependent variable
# --------------------------------------------------------------------------

def test_carbon_change_is_scaled_by_lagged_revenue():
    frame = pd.DataFrame(
        {
            "firm_id": ["A", "A", "A"],
            "year": [2018, 2019, 2020],
            "co2e": [100.0, 90.0, 85.0],
            "revenue": [1000.0, 1100.0, 1200.0],
        }
    )
    cc = silvia.carbon_change(frame)
    # Indexed on base year t: (90-100)/1000 at 2018, (85-90)/1100 at 2019.
    assert cc.iloc[0] == pytest.approx(-0.01)
    assert cc.iloc[1] == pytest.approx(-5 / 1100)
    assert pd.isna(cc.iloc[2])  # no t+1


def test_carbon_change_skips_non_consecutive_years():
    """A gap in the panel is not a one-year change."""
    frame = pd.DataFrame(
        {
            "firm_id": ["A", "A"],
            "year": [2018, 2021],
            "co2e": [100.0, 50.0],
            "revenue": [1000.0, 1000.0],
        }
    )
    assert pd.isna(silvia.carbon_change(frame).iloc[0])


def test_winsorising_clips_at_the_stated_percentiles():
    frame = pd.DataFrame({"CTPCI": [-99.0] + [0.5] * 98 + [99.0]})
    out = silvia.winsorise_frame(frame, ["CTPCI"])
    assert out["CTPCI"].max() < 99.0
    assert out["CTPCI"].min() > -99.0


# --------------------------------------------------------------------------
# estimation
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return silvia.simulate_panel(n_firms=120, seed=3)


def test_all_three_models_estimate(panel):
    for m in (1, 2, 3):
        res = silvia.estimate(panel, model=m)
        assert res.model == m
        assert np.isfinite(res.ctpci[0])
        assert res.nobs > 0


def test_moderator_terms_enter_models_2_and_3(panel):
    m1 = silvia.estimate(panel, model=1)
    m2 = silvia.estimate(panel, model=2)
    m3 = silvia.estimate(panel, model=3)
    assert "Assurance" not in m1.params.index
    assert "CTPCI:Assurance" in m2.params.index
    assert "CTPCI:Regulatory" in m3.params.index


def test_firm_invariant_controls_are_dropped_not_left_to_go_singular(panel):
    """Collinear-with-firm-FE controls must be removed with a warning."""
    res = silvia.estimate(panel, model=1)
    assert any("firm-invariant" in w for w in res.warnings)
    assert "SOE" not in res.params.index


def test_clustered_errors_exceed_unclustered(panel):
    import statsmodels.formula.api as smf

    work = panel.dropna(subset=["CarbonChange", "CTPCI"])
    naive = smf.ols("CarbonChange ~ CTPCI + Size", data=work).fit()
    clustered = smf.ols("CarbonChange ~ CTPCI + Size", data=work).fit(
        cov_type="cluster", cov_kwds={"groups": work["firm_id"]}
    )
    assert clustered.bse["CTPCI"] > naive.bse["CTPCI"]


def test_invalid_model_number_is_rejected(panel):
    with pytest.raises(ValueError, match="model must be"):
        silvia.estimate(panel, model=4)


def test_missing_columns_are_named(panel):
    with pytest.raises(ValueError, match="missing columns"):
        silvia.estimate(panel.drop(columns=["Leverage"]), model=1)


def test_country_year_fixed_effects_specification_runs(panel):
    res = silvia.estimate(panel, model=1, country_year_fe=True)
    assert np.isfinite(res.ctpci[0])


# --------------------------------------------------------------------------
# the substantive check
# --------------------------------------------------------------------------

def test_estimator_is_unbiased_for_the_true_coefficient():
    """Averaged over panels, the estimate must recover the coefficient used
    to build them, and interval coverage must be near nominal.

    One panel proves nothing here: firm fixed effects absorb most of the
    between-firm variation in CTPCI, so a correct estimator lands well away
    from the truth on individual draws.
    """
    mc = silvia.monte_carlo_check(n_seeds=25, n_firms=150)
    assert abs(mc["bias"]) < 3 * mc["mc_se"] + 0.01
    assert 0.80 <= mc["coverage_95"] <= 1.0


def test_simulated_panel_carries_the_published_correlation_signs():
    panel = silvia.simulate_panel(seed=11)
    assert panel["CTPCI"].corr(panel["CarbonChange"]) < 0      # published -0.183
    assert panel["CTPCI"].corr(panel["Assurance"]) > 0.15      # published +0.273
    assert panel["CTPCI"].corr(panel["Regulatory"]) > 0.25     # published +0.428
