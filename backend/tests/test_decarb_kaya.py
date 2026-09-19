"""Firm-level Kaya decomposition and the tiered label constructor.

The decomposition is an identity, so most of these tests are exactness checks.
The substantive ones are the two that encode what the module is for: a firm
whose emissions fell only because the grid cleaned up, and one whose emissions
fell only because it shrank, must both be credited with zero abatement.
"""

from __future__ import annotations

import pytest

from arp.decarb import kaya
from arp.decarb.kaya import Tier
from arp.decarb.schemas import EmissionsBasis, FirmYear, Panel
from arp.decarb.synthetic import make_panel


def fy(firm, year, **kw) -> FirmYear:
    base = dict(scope1=60.0, scope2=20.0, output=100.0, fuel_energy=100.0,
                electricity_mwh=50.0, grid_factor=0.40)
    base.update(kw)
    return FirmYear(firm, year, **base)


# --------------------------------------------------------------------------
# the point of the module
# --------------------------------------------------------------------------

def test_a_cleaning_grid_earns_the_firm_no_credit():
    """Scope 2 falls, the firm did nothing."""
    before = fy("A", 2019)
    after = fy("A", 2024, scope2=20.0 * 0.5, grid_factor=0.20)
    res = kaya.decompose_firm(before, after)
    assert res.total_change < 0
    assert res.attributable == pytest.approx(0.0, abs=1e-9)
    assert res.grid == pytest.approx(res.total_change, abs=1e-9)


def test_shrinking_earns_the_firm_no_credit():
    """Output halves, every intensity unchanged."""
    before = fy("A", 2019)
    after = fy("A", 2024, scope1=30.0, scope2=10.0, output=50.0,
               fuel_energy=50.0, electricity_mwh=25.0)
    res = kaya.decompose_firm(before, after)
    assert res.total_change < 0
    assert res.attributable == pytest.approx(0.0, abs=1e-9)
    assert res.output == pytest.approx(res.total_change, abs=1e-9)


def test_real_efficiency_is_fully_credited():
    """Energy per unit output falls, nothing else moves."""
    before = fy("A", 2019)
    after = fy("A", 2024, scope1=30.0, fuel_energy=50.0)
    res = kaya.decompose_firm(before, after)
    assert res.energy_intensity == pytest.approx(res.total_change, abs=1e-9)
    assert res.attributable == pytest.approx(res.total_change, abs=1e-9)
    assert res.passive == pytest.approx(0.0, abs=1e-9)


def test_fuel_switch_is_credited_separately_from_efficiency():
    """Same energy, cleaner fuel."""
    before = fy("A", 2019)
    after = fy("A", 2024, scope1=40.0)  # fuel_energy unchanged, so fuel mix improved
    res = kaya.decompose_firm(before, after)
    assert res.fuel_mix == pytest.approx(res.total_change, abs=1e-9)
    assert res.energy_intensity == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tier", list(Tier))
def test_decomposition_is_exactly_additive_at_every_tier(tier):
    before = fy("A", 2019)
    after = fy("A", 2024, scope1=46.8, scope2=15.6, fuel_energy=78.0,
               electricity_mwh=39.0)
    res = kaya.decompose_firm(before, after, tier=tier)
    assert res.residual == pytest.approx(0.0, abs=1e-9)


def test_identity_holds_across_the_calibrated_panel():
    panel = make_panel(n_firms=200, seed=5)
    start, end = panel.by_year(2016), panel.by_year(2023)
    checked = 0
    for firm_id in sorted(set(start) & set(end)):
        try:
            res = kaya.decompose_firm(start[firm_id], end[firm_id])
        except ValueError:
            continue
        assert abs(res.residual) < 1e-6 * max(1.0, abs(res.start_emissions))
        checked += 1
    assert checked > 100


def test_data_gap_catches_scope2_disagreeing_with_the_activity_data():
    """Reported Scope 2 inconsistent with electricity x grid factor.

    The Scope 1 factors are derived from reported Scope 1, so they reconcile
    by construction. The one place the identity can genuinely break is Scope 2,
    where the reported figure and the electricity-times-grid product are two
    independent measurements of the same thing. A firm on a market-based basis,
    or one whose grid factor is mismatched to where it actually draws power,
    shows up here.
    """
    before = fy("A", 2019)
    consistent = fy("A", 2024, scope1=46.8, scope2=15.6, fuel_energy=78.0,
                    electricity_mwh=39.0)  # 39.0 * 0.40 == 15.6
    assert kaya.decompose_firm(before, consistent).data_gap == pytest.approx(0.0, abs=1e-9)

    # Report 10 tonnes of Scope 2 that the activity data cannot account for.
    inconsistent = fy("A", 2024, scope1=46.8, scope2=25.6, fuel_energy=78.0,
                      electricity_mwh=39.0)
    broken = kaya.decompose_firm(before, inconsistent)
    assert broken.data_gap == pytest.approx(10.0, abs=1e-6)
    assert broken.residual == pytest.approx(0.0, abs=1e-9)


def test_data_gap_detects_market_based_scope2_reporting():
    """A procurement reduction with unchanged grid draw is credited to nobody.

    Reported Scope 2 falls while electricity and the grid factor are flat, so
    the reduction cannot be attributed to any physical driver and lands wholly
    in the data gap. This is the review's procurement-against-abatement
    argument appearing at firm level without being coded for.
    """
    before = fy("M", 2019)
    after = fy("M", 2024, scope2=5.0)  # market-based claim, same power, same grid
    res = kaya.decompose_firm(before, after)
    assert res.total_change < 0
    assert res.attributable == pytest.approx(0.0, abs=1e-9)
    assert res.passive == pytest.approx(0.0, abs=1e-9)
    assert res.data_gap == pytest.approx(res.total_change, abs=1e-9)


# --------------------------------------------------------------------------
# tiers
# --------------------------------------------------------------------------

def test_tier_selection_degrades_with_missing_activity_data():
    full = (fy("A", 2019), fy("A", 2024, scope1=50.0))
    assert kaya.available_tier(*full) is Tier.FULL_KAYA

    no_output = (fy("A", 2019, output=None), fy("A", 2024, output=None, scope1=50.0))
    assert kaya.available_tier(*no_output) is Tier.CONSTANT_GRID

    emissions_only = (
        FirmYear("A", 2019, scope1=60.0, scope2=20.0),
        FirmYear("A", 2024, scope1=50.0, scope2=20.0),
    )
    assert kaya.available_tier(*emissions_only) is Tier.CHAINED


def test_weaker_tiers_over_credit_a_firm_that_only_shrank():
    """The contamination each tier leaves in, on one firm."""
    before = fy("A", 2019)
    after = fy("A", 2024, scope1=30.0, scope2=10.0, output=50.0,
               fuel_energy=50.0, electricity_mwh=25.0)
    t1 = kaya.decompose_firm(before, after, tier=Tier.FULL_KAYA).attributable_rate
    t2 = kaya.decompose_firm(before, after, tier=Tier.CONSTANT_GRID).attributable_rate
    t3 = kaya.decompose_firm(before, after, tier=Tier.CHAINED).attributable_rate
    assert t1 == pytest.approx(0.0, abs=1e-9)
    assert t2 < -0.4  # the shrinkage is miscredited as abatement
    assert t3 < -0.4


def test_tier_ranking_is_ordered():
    assert Tier.FULL_KAYA.rank < Tier.CONSTANT_GRID.rank < Tier.CHAINED.rank
    assert all(t.describe() for t in Tier)


def test_contamination_diagnostic_reports_both_weaker_tiers():
    panel = make_panel(n_firms=400, seed=9)
    report = kaya.tier_contamination(panel, 2016, 2023)
    assert Tier.CONSTANT_GRID.value in report
    assert Tier.CHAINED.value in report
    for stats in report.values():
        assert stats["n"] > 10
        # The absolute gap is the honest measure; signed gaps can cancel.
        assert stats["mean_abs_gap"] >= abs(stats["mean_gap"])


def test_tier_coverage_partitions_the_panel():
    panel = make_panel(n_firms=300, seed=13)
    cov = kaya.tier_coverage(panel, 2016, 2023)
    start, end = panel.by_year(2016), panel.by_year(2023)
    assert sum(cov.values()) == len(set(start) & set(end))


# --------------------------------------------------------------------------
# label constructor
# --------------------------------------------------------------------------

def test_attributable_labels_annualise_and_record_the_tier():
    panel = make_panel(n_firms=300, seed=21)
    labels = kaya.attributable_labels(panel, start_year=2016, end_year=2023)
    assert labels
    for rate, is_dec, tier in labels.values():
        assert -1.0 < rate < 1.0
        assert is_dec == (rate < 0.0)
        assert isinstance(tier, Tier)


def test_restated_firms_are_excluded_by_default():
    rows = [
        fy("A", 2019), fy("A", 2024, scope1=50.0),
        fy("B", 2019), FirmYear("B", 2024, scope1=50.0, scope2=20.0, output=100.0,
                                fuel_energy=100.0, electricity_mwh=50.0,
                                grid_factor=0.40, restated=True),
    ]
    panel = Panel(rows)
    strict = kaya.attributable_labels(panel, start_year=2019, end_year=2024)
    loose = kaya.attributable_labels(panel, start_year=2019, end_year=2024, exclude_restated=False)
    assert set(strict) == {"A"}
    assert set(loose) == {"A", "B"}


def test_min_tier_filters_rather_than_silently_downgrading():
    panel = make_panel(n_firms=300, seed=23)
    everything = kaya.attributable_labels(panel, start_year=2016, end_year=2023)
    tier1_only = kaya.attributable_labels(panel, start_year=2016, end_year=2023, min_tier=Tier.FULL_KAYA)
    assert 0 < len(tier1_only) < len(everything)
    assert all(t is Tier.FULL_KAYA for _, _, t in tier1_only.values())


def test_estimated_emissions_are_excluded_by_default():
    rows = [
        fy("A", 2019), fy("A", 2024, scope1=50.0),
        fy("B", 2019, basis=EmissionsBasis.ESTIMATED),
        fy("B", 2024, scope1=50.0, basis=EmissionsBasis.ESTIMATED),
    ]
    labels = kaya.attributable_labels(Panel(rows), start_year=2019, end_year=2024)
    assert set(labels) == {"A"}
