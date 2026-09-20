from arp.config import Settings
from arp.research.company_role import derive_company_role
from arp.schemas.rd_exposure import RDExposureResult
from arp.schemas.revenue_exposure import MetricExposure, RevenueExposureResult
from arp.schemas.thematic import CompanyRole, ExposureEstimate, MatchVerdict


def _settings(**overrides) -> Settings:
    return Settings(anthropic_api_key="unused", **overrides)


def _revenue(value_pct=None, source="unresolved") -> RevenueExposureResult:
    return RevenueExposureResult(
        activity_id="act1", revenue=MetricExposure(value_pct=value_pct, source=source),
        capex=MetricExposure(source="unresolved"), sector_relevant=True,
    )


def _rd(rd_pct=None, rd_source="unresolved", news_pct=None, news_source="unresolved") -> RDExposureResult:
    return RDExposureResult(
        activity_id="act1", rd_intensity=MetricExposure(value_pct=rd_pct, source=rd_source),
        news_mentions=MetricExposure(value_pct=news_pct, source=news_source), sector_relevant=True,
    )


def test_excluded_verdict_returns_none():
    role = derive_company_role(
        verdict=MatchVerdict.EXCLUDE, exposure_estimate=ExposureEstimate.NONE,
        revenue_exposure=None, rd_exposure=None, settings=_settings(),
    )
    assert role is None


def test_uncertain_verdict_returns_none():
    role = derive_company_role(
        verdict=MatchVerdict.UNCERTAIN, exposure_estimate=ExposureEstimate.SIGNIFICANT,
        revenue_exposure=None, rd_exposure=None, settings=_settings(),
    )
    assert role is None


def test_pure_play_exposure_estimate_yields_pure_player():
    role = derive_company_role(
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.PURE_PLAY,
        revenue_exposure=None, rd_exposure=None, settings=_settings(),
    )
    assert role == CompanyRole.PURE_PLAYER


def test_high_revenue_pct_yields_pure_player_even_if_estimate_is_lower():
    settings = _settings(revenue_exposure_pure_play_threshold=0.5)
    role = derive_company_role(
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT,
        revenue_exposure=_revenue(0.6, "extracted"), rd_exposure=None, settings=settings,
    )
    assert role == CompanyRole.PURE_PLAYER


def test_rd_signal_with_weak_revenue_yields_innovator():
    settings = _settings(revenue_exposure_minor_threshold=0.05)
    role = derive_company_role(
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.MINOR,
        revenue_exposure=None, rd_exposure=_rd(rd_pct=0.3, rd_source="extracted"), settings=settings,
    )
    assert role == CompanyRole.INNOVATOR


def test_rd_signal_with_strong_revenue_does_not_yield_innovator():
    settings = _settings(revenue_exposure_minor_threshold=0.05, revenue_exposure_pure_play_threshold=0.9)
    role = derive_company_role(
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT,
        revenue_exposure=_revenue(0.3, "extracted"), rd_exposure=_rd(rd_pct=0.3, rd_source="extracted"), settings=settings,
    )
    assert role == CompanyRole.DIVERSIFIED


def test_meaningful_exposure_with_no_special_signals_yields_diversified():
    role = derive_company_role(
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.MINOR,
        revenue_exposure=None, rd_exposure=None, settings=_settings(),
    )
    assert role == CompanyRole.DIVERSIFIED


def test_unresolved_rd_signals_do_not_trigger_innovator():
    role = derive_company_role(
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.MINOR,
        revenue_exposure=None, rd_exposure=_rd(rd_source="unresolved", news_source="unresolved"), settings=_settings(),
    )
    assert role == CompanyRole.DIVERSIFIED
