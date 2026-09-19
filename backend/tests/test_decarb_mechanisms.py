"""Sector x region as measured mechanisms rather than dummies."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arp.decarb.research import mechanisms as M
from arp.decarb.research.frames import add_growth_columns, to_frame
from arp.decarb.synthetic import make_panel

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return add_growth_columns(to_frame(make_panel(n_firms=500, seed=4))).dropna(subset=["g_scope12"])


def test_variance_decomposition_is_nested_and_monotone(frame):
    v = M.variance_decomposition(frame)
    keys = ["year", "+ sector", "+ region", "+ sector x region"]
    vals = [v.nested[k] for k in keys]
    assert vals == sorted(vals), "adding terms cannot reduce R2"
    assert v.nested["+ firm"] > v.nested["+ sector x region"]


def test_between_and_within_shares_partition_the_variance(frame):
    v = M.variance_decomposition(frame)
    assert v.between_cell_share + v.within_cell_share == pytest.approx(1.0, abs=0.02)
    assert 0.0 <= v.between_cell_share <= 1.0
    assert v.n_cells > 1 and v.n_firms > 100


def test_verdict_switches_on_where_the_variance_sits(frame):
    v = M.variance_decomposition(frame)
    assert ("Firms dominate" in v.verdict()) == (v.between_cell_share < 0.40)
    assert "Cells dominate" in v.verdict(cell_dominant_threshold=0.01)


def test_cell_invariant_mechanisms_are_reported_as_degenerate(frame):
    """A lookup keyed on sector and region is not a measurement."""
    f = frame.copy()
    lookup = {s: i * 10.0 for i, s in enumerate(sorted(f["sector"].dropna().unique()))}
    f["regulation"] = f["sector"].map(lookup)
    f["technology"] = f["sector"].map(lookup) * -1.0
    f["demand"] = f["region"].map({r: i for i, r in enumerate(sorted(f["region"].dropna().unique()))})
    res = M.mechanism_sufficiency(f)
    assert any("cell-invariant" in w for w in res.warnings)
    assert "degenerate" in res.verdict()


def test_time_varying_mechanisms_give_a_usable_test(frame):
    """Mechanisms measured over time can be distinguished from the dummies."""
    rng = np.random.default_rng(0)
    f = frame.copy()
    base = {s: rng.uniform(5, 60) for s in f["sector"].dropna().unique()}
    # Carbon price rises over time, at a rate that differs by region.
    slope = {r: rng.uniform(0.5, 6.0) for r in f["region"].dropna().unique()}
    f["regulation"] = [base[s] + slope[r] * (y - 2010) for s, r, y in zip(f["sector"], f["region"], f["year"])]
    f["technology"] = [-150.0 * (0.94 ** (y - 2010)) for y in f["year"]]
    f["demand"] = [0.1 * (y - 2010) * (1.0 if r == "Developed Europe" else 0.3) for r, y in zip(f["region"], f["year"])]
    res = M.mechanism_sufficiency(f)
    assert not any("cell-invariant" in w for w in res.warnings)
    assert res.r2_mechanisms_plus_cells >= res.r2_mechanisms - 1e-9
    assert res.incremental_r2 >= -1e-9
    assert "degenerate" not in res.verdict()


def test_missing_mechanism_columns_point_at_the_sources_table(frame):
    with pytest.raises(ValueError, match="MECHANISM_SOURCES"):
        M.mechanism_sufficiency(frame)


def test_every_mechanism_documents_construction_source_and_caution():
    assert set(M.MECHANISM_SOURCES) == {"regulation", "technology", "demand"}
    for spec in M.MECHANISM_SOURCES.values():
        assert {"construct", "sources", "granularity", "caution"} <= set(spec)
        assert len(spec["caution"]) > 40


def test_cell_summary_flags_thin_cells_rather_than_dropping_them(frame):
    out = M.cell_summary(frame, min_firms=1000)  # nothing can clear this
    assert out["thin"].all()
    assert out["n_obs"].sum() == len(frame.dropna(subset=["g_scope12", "sector", "region"]))


def test_variance_decomposition_rejects_an_empty_frame(frame):
    with pytest.raises(ValueError, match="no complete cases"):
        M.variance_decomposition(frame.head(0))
