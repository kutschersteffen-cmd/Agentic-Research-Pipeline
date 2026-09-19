"""Red-flag construction rules (Brown, Hsu & Manya 2026, Methods).

Each rule is tested at its boundary, because the rules are asymmetric in ways
that are easy to get backwards: some flag on missing data and one explicitly
does not.
"""

from __future__ import annotations

import pytest

from arp.decarb.flags import (
    NET_ZERO_END_TARGETS,
    CDPRecord,
    LobbyBand,
    NZTRecord,
    ambition,
    assess,
    has_climate_claim,
    peta,
)
from arp.decarb.schemas import RED_FLAGS


def _clean_nzt(**overrides) -> NZTRecord:
    base = dict(
        end_target="Net zero",
        has_implementation_plan=True,
        has_interim_target=True,
        scope_coverage="scope 1+2+3",
        ghg_coverage="all ghgs",
        offsets_used=False,
    )
    base.update(overrides)
    return NZTRecord(**base)


def _clean_cdp(**overrides) -> CDPRecord:
    base = dict(
        target_scopes=["scope 1+2", "scope 3"],
        target_years=[2030, 2040],
        base_year=2019,
        base_year_emissions=100.0,
        reporting_year=2022,
        reporting_year_emissions=80.0,
        target_year=2030,
        target_year_emissions=50.0,
    )
    base.update(overrides)
    return CDPRecord(**base)


# --------------------------------------------------------------------------
# gate
# --------------------------------------------------------------------------

def test_climate_claim_gate():
    assert has_climate_claim(NZTRecord(end_target="Net zero"), None)
    assert has_climate_claim(None, CDPRecord(target_scopes=["scope 1"]))
    assert not has_climate_claim(None, None)
    assert not has_climate_claim(NZTRecord(), CDPRecord())


def test_no_claim_means_framework_does_not_apply():
    a = assess("X")
    assert not a.made_climate_claim
    assert a.n_flags == 0
    assert "not applicable" in a.explain()


def test_flag_keys_match_the_schema_constant():
    a = assess("X", nzt=_clean_nzt(), cdp=_clean_cdp(), lobby_band="A")
    assert set(a.flags) == set(RED_FLAGS)


def test_a_fully_compliant_company_raises_nothing():
    a = assess("GOOD", nzt=_clean_nzt(), cdp=_clean_cdp(), lobby_band="B+")
    assert a.n_flags == 0, a.explain()


# --------------------------------------------------------------------------
# individual rules
# --------------------------------------------------------------------------

def test_interim_target_falls_back_to_two_distinct_cdp_target_years():
    """Their documented fallback when NZT has no interim-target data."""
    nzt = _clean_nzt(has_interim_target=None)
    two_years = assess("A", nzt=nzt, cdp=_clean_cdp(target_years=[2030, 2040]))
    one_year = assess("B", nzt=nzt, cdp=_clean_cdp(target_years=[2030, 2030]))
    assert not two_years.flags["no_interim_targets"]
    assert one_year.flags["no_interim_targets"]


def test_missing_plan_data_counts_as_no_plan():
    a = assess("A", nzt=_clean_nzt(has_implementation_plan=None), cdp=_clean_cdp())
    assert a.flags["no_implementation_plan"]
    assert "nzt.has_implementation_plan" in a.missing_inputs


def test_partial_scope3_coverage_passes():
    """Their rule is permissive: partial coverage counts as coverage."""
    partial = assess("A", nzt=_clean_nzt(scope_coverage="partial scope 3"), cdp=_clean_cdp(target_scopes=[]))
    assert not partial.flags["no_scope3_coverage"]
    neither = assess("B", nzt=_clean_nzt(scope_coverage="scope 1+2"), cdp=_clean_cdp(target_scopes=["scope 1+2"]))
    assert neither.flags["no_scope3_coverage"]


def test_cdp_target_referencing_scope3_rescues_a_narrow_pledge():
    a = assess("A", nzt=_clean_nzt(scope_coverage="scope 1+2"), cdp=_clean_cdp(target_scopes=["scope 3"]))
    assert not a.flags["no_scope3_coverage"]


@pytest.mark.parametrize(
    "used,conditions,expected",
    [
        (False, None, False),          # explicit non-use passes
        (True, "with safeguards", False),  # conditional use passes
        (True, None, True),            # unconditional use fails
        (None, None, True),            # undisclosed fails
    ],
)
def test_offset_rule_is_asymmetric(used, conditions, expected):
    nzt = _clean_nzt(offsets_used=used, offsets_conditions=conditions)
    assert assess("A", nzt=nzt, cdp=_clean_cdp()).flags["questionable_offsets"] is expected


def test_ghg_coverage_rule_is_about_gases_not_scopes():
    """Fires only when a neutrality claim sits on a CO2-only inventory."""
    co2_only = assess("A", nzt=_clean_nzt(end_target="Net zero", ghg_coverage="co2 only"), cdp=_clean_cdp())
    assert co2_only.flags["incomplete_ghg_coverage"]
    unspecified = assess("B", nzt=_clean_nzt(end_target="Climate neutral", ghg_coverage=None), cdp=_clean_cdp())
    assert unspecified.flags["incomplete_ghg_coverage"]
    # A plain percentage target makes no neutrality claim, so the test does not bite.
    plain = assess("C", nzt=_clean_nzt(end_target="50% reduction", ghg_coverage="co2 only"), cdp=_clean_cdp())
    assert not plain.flags["incomplete_ghg_coverage"]


def test_every_neutrality_wording_triggers_the_ghg_test():
    for wording in NET_ZERO_END_TARGETS:
        a = assess("A", nzt=_clean_nzt(end_target=wording, ghg_coverage="co2 only"), cdp=_clean_cdp())
        assert a.flags["incomplete_ghg_coverage"], wording


def test_lobbying_threshold_is_c_or_lower():
    assert LobbyBand.C.is_negative()
    assert LobbyBand.C_MINUS.is_negative()
    assert LobbyBand.F.is_negative()
    assert not LobbyBand.C_PLUS.is_negative()
    assert not LobbyBand.A_PLUS.is_negative()


def test_absence_from_lobbymap_is_not_a_flag():
    """Only ~600 of 4,131 companies are rated; absence must not manufacture a flag."""
    a = assess("A", nzt=_clean_nzt(), cdp=_clean_cdp(), lobby_band=None)
    assert not a.flags["misaligned_lobbying"]
    assert "lobbymap.band" in a.missing_inputs
    unparseable = assess("B", nzt=_clean_nzt(), cdp=_clean_cdp(), lobby_band="not-a-band")
    assert not unparseable.flags["misaligned_lobbying"]


# --------------------------------------------------------------------------
# PETA and ambition
# --------------------------------------------------------------------------

def test_peta_is_one_when_exactly_on_the_linear_path():
    # 2019 base 100, 2030 target 50. By 2022, 3/11 of the way, required cut is
    # 50 * 3/11 = 13.64, so emissions of 86.36 sit exactly on the trajectory.
    cdp = _clean_cdp(reporting_year=2022, reporting_year_emissions=100 - 50 * 3 / 11)
    assert peta(cdp) == pytest.approx(1.0, abs=1e-9)


def test_peta_flags_behind_and_clears_ahead():
    behind = _clean_cdp(reporting_year_emissions=98.0)
    ahead = _clean_cdp(reporting_year_emissions=70.0)
    assert peta(behind) < 1.0
    assert peta(ahead) > 1.0
    assert assess("A", nzt=_clean_nzt(), cdp=behind).flags["off_track_vs_target"]
    assert not assess("B", nzt=_clean_nzt(), cdp=ahead).flags["off_track_vs_target"]


def test_peta_returns_none_rather_than_guessing():
    assert peta(None) is None
    assert peta(CDPRecord()) is None
    # Target year before base year is not a trajectory.
    assert peta(_clean_cdp(base_year=2030, target_year=2019)) is None


def test_missing_progress_data_is_not_a_flag():
    a = assess("A", nzt=_clean_nzt(), cdp=CDPRecord(target_scopes=["scope 1"]))
    assert not a.flags["off_track_vs_target"]
    assert "cdp.peta_inputs" in a.missing_inputs


def test_ambition_is_an_annualised_reduction_rate():
    # 100 -> 50 by 2030, measured from 2022: 50% cut over 8 remaining years.
    value = ambition(_clean_cdp(), as_of_year=2022)
    assert value == pytest.approx(100 * 0.5 / 8, abs=1e-9)
    assert ambition(_clean_cdp(), as_of_year=2031) is None  # target already due


def test_ambition_is_negative_for_a_target_that_permits_growth():
    growing = _clean_cdp(target_year_emissions=120.0)
    assert ambition(growing, as_of_year=2022) < 0
