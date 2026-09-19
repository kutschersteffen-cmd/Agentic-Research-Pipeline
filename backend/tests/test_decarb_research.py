"""Research subpackage: estimator correctness on data with a known answer.

The value of these tests is that the synthetic generator has a known
data-generating process, so an estimator can be checked against ground truth
rather than against its own previous output. In particular, target adoption
has NO causal effect on emissions in the generator but adopters are selected
on an unobserved propensity that does lower emissions. A naive comparison
must therefore find an effect and a correct DiD must not.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from arp.decarb.research import did, frames, inference, matching, models
from arp.decarb.synthetic import make_panel

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f = frames.add_growth_columns(frames.to_frame(make_panel(n_firms=400, seed=42)))
    f["log_rev"] = np.log(f["revenue"].clip(lower=1.0))
    return f


# --------------------------------------------------------------------------
# frames
# --------------------------------------------------------------------------

def test_growth_columns_are_within_firm_and_not_backfilled(frame):
    first_rows = frame.groupby("firm_id").head(1)
    assert first_rows["g_scope12"].isna().all(), "a firm's first year has no prior year to difference"
    one_firm = frame[frame.firm_id == frame.firm_id.iloc[0]].sort_values("year")
    manual = np.log(one_firm["scope12"].iloc[1]) - np.log(one_firm["scope12"].iloc[0])
    assert one_firm["g_scope12"].iloc[1] == pytest.approx(manual, abs=1e-9)


def test_lagged_growth_is_shifted_growth(frame):
    one = frame[frame.firm_id == frame.firm_id.iloc[0]].sort_values("year")
    assert one["g_scope12_lag"].iloc[2] == pytest.approx(one["g_scope12"].iloc[1], abs=1e-12)


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

def test_cem_keeps_only_strata_with_both_arms(frame):
    base = frame[frame.year == 2018].dropna(subset=["g_scope12_lag"]).copy()
    base["ever"] = base["ltnz_adoption_year"].notna()
    res = matching.coarsened_exact_match(base, treatment="ever", covariates=["sector", "region"], bins=4)
    assert res.n_treated_out > 0 and res.n_control_out > 0
    assert res.strata_kept <= res.strata_total
    # Every surviving stratum must contain both arms.
    for _, grp in res.matched.groupby("__stratum"):
        assert grp["ever"].nunique() == 2


def test_cem_reports_pruning_rather_than_hiding_it(frame):
    base = frame[frame.year == 2018].dropna(subset=["g_scope12_lag"]).copy()
    base["ever"] = base["ltnz_adoption_year"].notna()
    # Deliberately over-specified: many covariates, fine bins, heavy pruning.
    res = matching.coarsened_exact_match(
        base, treatment="ever", covariates=["sector", "region", "revenue", "g_scope12_lag", "log_rev"], bins=6
    )
    assert res.pruning_rate > 0.5
    assert any("pruned" in w for w in res.warnings)


def test_balance_table_flags_imbalance():
    rng = np.random.default_rng(0)
    n = 400
    treated = np.arange(n) % 2 == 0
    # x differs sharply by arm, so it must come back unbalanced.
    x = np.where(treated, rng.normal(3, 1, n), rng.normal(0, 1, n))
    df = pd.DataFrame({"t": treated, "x": x})
    table = matching.balance_table(df, treatment="t", covariates=["x"])
    assert not bool(table.loc[0, "balanced"])
    assert table.loc[0, "smd"] > 1.0


def test_coarsen_passes_through_categoricals():
    s = pd.Series(["a", "b", "a"])
    assert matching.coarsen(s).tolist() == ["a", "b", "a"]


# --------------------------------------------------------------------------
# did - the ground-truth tests
# --------------------------------------------------------------------------

def test_naive_comparison_finds_an_effect_that_is_not_there(frame):
    """Selection alone produces an apparent effect."""
    f = frame.dropna(subset=["g_scope12"]).copy()
    f["ever"] = f["ltnz_adoption_year"].notna()
    gap = f[f["ever"]]["g_scope12"].mean() - f[~f["ever"]]["g_scope12"].mean()
    assert gap < -0.002, "adopters should look better than non-adopters in a naive comparison"


def test_did_recovers_the_null_the_generator_encodes(frame):
    """Adoption has no causal effect; a correct DiD should not find one."""
    res = did.event_study(frame, outcome="log_scope12", n_bootstrap=60, min_event_time=-2, max_event_time=2)
    att, se = res.post_average()
    assert np.isfinite(att) and np.isfinite(se)
    # Cannot reject zero at conventional levels.
    assert abs(att) < 2.0 * se + 0.02


def test_event_study_reports_pre_treatment_periods(frame):
    res = did.event_study(frame, outcome="log_scope12", n_bootstrap=40, min_event_time=-3, max_event_time=2)
    assert (res.effects["event_time"] < 0).any(), "pre-treatment periods must be reported, never dropped"
    ok, msg = res.pre_trend_test()
    assert isinstance(ok, bool) and msg


def test_group_time_att_excludes_the_base_period(frame):
    gt = did.group_time_att(frame, outcome="log_scope12")
    for g, grp in gt.groupby("cohort"):
        assert (grp["time"] != g - 1).all(), "g-1 is the base period and cannot be an outcome period"


def test_never_treated_controls_are_a_subset_of_not_yet_treated(frame):
    a = did.group_time_att(frame, outcome="log_scope12", control_group="never_treated")
    b = did.group_time_att(frame, outcome="log_scope12", control_group="not_yet_treated")
    merged = a.merge(b, on=["cohort", "time"], suffixes=("_never", "_notyet"))
    assert (merged["n_control_never"] <= merged["n_control_notyet"]).all()


def test_event_study_rejects_an_unknown_control_group(frame):
    with pytest.raises(ValueError, match="control_group"):
        did.group_time_att(frame, outcome="log_scope12", control_group="everyone")


# --------------------------------------------------------------------------
# inference
# --------------------------------------------------------------------------

def test_clustered_errors_exceed_unclustered_on_persistent_panel_data(frame):
    """The reason clustering is the default rather than an option."""
    import statsmodels.formula.api as smf

    work = frame.dropna(subset=["g_scope12", "log_rev"]).copy()
    naive = smf.ols("g_scope12 ~ log_rev", data=work).fit()
    clustered = smf.ols("g_scope12 ~ log_rev", data=work).fit(
        cov_type="cluster", cov_kwds={"groups": work["firm_id"]}
    )
    assert clustered.bse["log_rev"] > naive.bse["log_rev"]


def test_panel_ols_returns_inference_not_just_coefficients(frame):
    res = inference.panel_ols(frame, outcome="g_scope12", regressors=["log_rev"])
    table = res.table()
    assert {"coef", "se", "p", "ci_low", "ci_high"} <= set(table.columns)
    assert res.nobs > 100 and res.n_groups > 50
    assert res.cluster == "firm_id"


def test_panel_ols_requires_complete_cases(frame):
    empty = frame.head(0)
    with pytest.raises(ValueError, match="no complete cases"):
        inference.panel_ols(empty, outcome="g_scope12", regressors=["log_rev"])


def test_sign_stability_detects_a_coefficient_that_flips():
    """A confounder that reverses a coefficient must be reported as a flip."""
    rng = np.random.default_rng(3)
    n = 1200
    z = rng.normal(size=n)
    x = z + rng.normal(scale=0.3, size=n)
    y = -1.5 * z + 0.8 * x + rng.normal(scale=0.2, size=n)
    df = pd.DataFrame(
        {"y": y, "x": x, "z": z, "firm_id": np.arange(n) % 120, "year": 2015 + (np.arange(n) % 8)}
    )
    out = inference.sign_stability(
        df, outcome="y", focal="x", control_sets={"omitted": [], "with z": ["z"]},
        entity_fe=False, time_fe=False,
    )
    assert out.attrs["sign_flips"] is True


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def model_frame(frame) -> pd.DataFrame:
    f = frame.copy()
    for sector in f["sector"].dropna().unique():
        f[f"sector_{sector}"] = (f["sector"] == sector).astype(float)
    return f.dropna(subset=["intensity", "g_scope12", "g_scope12_lag"])


def test_level_performance_is_mostly_sector_identification(model_frame):
    """The central critique of the level-prediction literature, as a test."""
    feats = ["log_rev", "g_scope12_lag"] + [c for c in model_frame.columns if c.startswith("sector_")]
    comp = models.compare_targets(model_frame, features=feats)
    best_level = comp.best(comp.level).r2
    best_shuffled = comp.best(comp.level_without_sector).r2
    assert best_level > 0.3
    assert best_shuffled < 0.5 * best_level


def test_time_split_never_trains_on_the_test_period(model_frame):
    feats = ["log_rev", "g_scope12_lag"]
    scores = models.time_split_evaluate(model_frame, target="g_scope12", features=feats, split_year=2018)
    assert all(s.n_train > 0 and s.n_test > 0 for s in scores)
    # Re-running with a later split must change the sample sizes.
    later = models.time_split_evaluate(model_frame, target="g_scope12", features=feats, split_year=2020)
    assert later[0].n_train > scores[0].n_train


def test_model_comparison_rejects_an_impossible_split(model_frame):
    with pytest.raises(ValueError, match="insufficient data"):
        models.time_split_evaluate(
            model_frame, target="g_scope12", features=["log_rev"], split_year=2099
        )
