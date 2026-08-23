from arp.config import Settings
from arp.research.arbitration import compute_arbitration
from arp.schemas.exposure import IndirectExposureResult
from arp.schemas.rd_exposure import RDExposureResult
from arp.schemas.revenue_exposure import MetricExposure, RevenueExposureResult
from arp.schemas.thematic import ExposureEstimate


def _settings(**overrides) -> Settings:
    return Settings(anthropic_api_key="unused", **overrides)


def _revenue(value_pct=None, source="unresolved") -> RevenueExposureResult:
    return RevenueExposureResult(
        activity_id="act1",
        revenue=MetricExposure(value_pct=value_pct, source=source),
        capex=MetricExposure(source="unresolved"),
        sector_relevant=True,
    )


def _indirect(upstream=0.0, downstream=0.0) -> IndirectExposureResult:
    return IndirectExposureResult(
        company_id="c1", isic_code="27", upstream_exposure=upstream, downstream_exposure=downstream,
        core_sector=False, icio_edition="test",
    )


def _rd(rd_pct=None, rd_source="unresolved", news_pct=None, news_source="unresolved") -> RDExposureResult:
    return RDExposureResult(
        activity_id="act1",
        rd_intensity=MetricExposure(value_pct=rd_pct, source=rd_source),
        news_mentions=MetricExposure(value_pct=news_pct, source=news_source),
        sector_relevant=True,
    )


def test_no_signals_available_gives_zero_composite_and_no_disagreement():
    result = compute_arbitration(
        qualitative_estimate=None, revenue_exposure=None, indirect_exposure=None, rd_exposure=None, settings=_settings()
    )
    assert result.composite_score == 0.0
    assert result.contributions == []
    assert result.methods_disagree is False
    assert result.disagreement_spread == 0.0


def test_single_qualitative_signal_is_composite_alone():
    result = compute_arbitration(
        qualitative_estimate=ExposureEstimate.PURE_PLAY, revenue_exposure=None, indirect_exposure=None, rd_exposure=None,
        settings=_settings(),
    )
    assert result.composite_score == 1.0
    assert len(result.contributions) == 1
    assert result.contributions[0].method == "qualitative_debate"
    assert result.methods_disagree is False  # only one signal -- nothing to disagree with


def test_revenue_short_circuit_excludes_qualitative_to_avoid_double_counting():
    """When exposure_estimate IS band_exposure(revenue.value_pct) (the
    _finalize_from_revenue case), the caller passes qualitative_estimate=None
    -- confirm the resulting composite reflects only the revenue signal."""
    revenue = _revenue(value_pct=0.6, source="catalogue")
    result = compute_arbitration(
        qualitative_estimate=None, revenue_exposure=revenue, indirect_exposure=None, rd_exposure=None, settings=_settings()
    )
    assert len(result.contributions) == 1
    assert result.contributions[0].method == "revenue_catalogue"
    assert result.composite_score == 0.6


def test_catalogue_and_extracted_revenue_use_different_weights():
    settings = _settings(arbitration_weight_revenue_catalogue=1.0, arbitration_weight_revenue_extracted=0.5)
    catalogue_result = compute_arbitration(
        qualitative_estimate=None, revenue_exposure=_revenue(0.5, "catalogue"), indirect_exposure=None, rd_exposure=None, settings=settings
    )
    extracted_result = compute_arbitration(
        qualitative_estimate=None, revenue_exposure=_revenue(0.5, "extracted"), indirect_exposure=None, rd_exposure=None, settings=settings
    )
    assert catalogue_result.contributions[0].weight == 1.0
    assert extracted_result.contributions[0].weight == 0.5


def test_indirect_uses_max_of_upstream_downstream():
    result = compute_arbitration(
        qualitative_estimate=None, revenue_exposure=None, indirect_exposure=_indirect(upstream=0.7, downstream=0.2),
        rd_exposure=None, settings=_settings(),
    )
    assert result.contributions[0].signal == 0.7
    assert result.contributions[0].detail == "upstream"


def test_unresolved_signals_are_excluded():
    result = compute_arbitration(
        qualitative_estimate=None,
        revenue_exposure=_revenue(source="unresolved"),
        indirect_exposure=None,
        rd_exposure=_rd(rd_source="unresolved", news_source="unresolved"),
        settings=_settings(),
    )
    assert result.contributions == []
    assert result.composite_score == 0.0


def test_rd_signals_included_only_when_resolved():
    result = compute_arbitration(
        qualitative_estimate=None,
        revenue_exposure=None,
        indirect_exposure=None,
        rd_exposure=_rd(rd_pct=0.4, rd_source="extracted", news_pct=0.8, news_source="news"),
        settings=_settings(),
    )
    methods = {c.method for c in result.contributions}
    assert methods == {"rd_intensity", "news_mentions"}


def test_weighted_composite_score_arithmetic():
    settings = _settings(arbitration_weight_qualitative_debate=0.6, arbitration_weight_indirect=0.3)
    result = compute_arbitration(
        qualitative_estimate=ExposureEstimate.SIGNIFICANT,  # 0.6 signal
        revenue_exposure=None,
        indirect_exposure=_indirect(upstream=0.0, downstream=1.0),  # 1.0 signal
        rd_exposure=None,
        settings=settings,
    )
    expected = (0.6 * 0.6 + 1.0 * 0.3) / (0.6 + 0.3)
    assert abs(result.composite_score - expected) < 1e-9


def test_agreeing_signals_do_not_flag_disagreement():
    settings = _settings(arbitration_disagreement_threshold=0.4)
    result = compute_arbitration(
        qualitative_estimate=ExposureEstimate.SIGNIFICANT,  # 0.6
        revenue_exposure=_revenue(0.55, "extracted"),  # 0.55 -- close
        indirect_exposure=None, rd_exposure=None, settings=settings,
    )
    assert result.methods_disagree is False


def test_diverging_signals_flag_disagreement():
    settings = _settings(arbitration_disagreement_threshold=0.4)
    result = compute_arbitration(
        qualitative_estimate=ExposureEstimate.NONE,  # 0.0
        revenue_exposure=None,
        indirect_exposure=_indirect(upstream=0.9, downstream=0.0),  # 0.9 -- far apart
        rd_exposure=None, settings=settings,
    )
    assert result.methods_disagree is True
    assert result.disagreement_spread == 0.9


def test_mid_band_flagged_when_composite_in_range():
    settings = _settings(arbitration_mid_band_low=0.3, arbitration_mid_band_high=0.7)
    result = compute_arbitration(
        qualitative_estimate=ExposureEstimate.SIGNIFICANT,  # 0.6 -> within [0.3, 0.7]
        revenue_exposure=None, indirect_exposure=None, rd_exposure=None, settings=settings,
    )
    assert result.mid_band is True


def test_mid_band_not_flagged_outside_range():
    settings = _settings(arbitration_mid_band_low=0.3, arbitration_mid_band_high=0.7)
    result = compute_arbitration(
        qualitative_estimate=ExposureEstimate.PURE_PLAY,  # 1.0 -> outside [0.3, 0.7]
        revenue_exposure=None, indirect_exposure=None, rd_exposure=None, settings=settings,
    )
    assert result.mid_band is False


def test_rationale_mentions_signal_count_and_agreement():
    result = compute_arbitration(
        qualitative_estimate=ExposureEstimate.NONE, revenue_exposure=None, indirect_exposure=None, rd_exposure=None,
        settings=_settings(),
    )
    assert "1 signal" in result.rationale
    assert "agree" in result.rationale
