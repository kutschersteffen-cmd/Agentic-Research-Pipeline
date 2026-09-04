from __future__ import annotations

from arp.config import Settings
from arp.schemas.rd_exposure import RDExposureResult
from arp.schemas.revenue_exposure import RevenueExposureResult
from arp.schemas.thematic import CompanyRole, ExposureEstimate, MatchVerdict


def derive_company_role(
    *,
    verdict: MatchVerdict,
    exposure_estimate: ExposureEstimate,
    revenue_exposure: RevenueExposureResult | None,
    rd_exposure: RDExposureResult | None,
    settings: Settings,
) -> CompanyRole | None:
    """Deterministic pure-player/diversified/innovator tag, derived purely
    from fields other methods already computed -- no LLM call, no new
    evidence gathering. Called explicitly with the caller's locally-known
    verdict/exposure_estimate/revenue_exposure/rd_exposure (mirroring
    arp.research.arbitration.compute_arbitration's calling convention)
    rather than reading them off an already-built CompanyMatch, since it's
    invoked before CompanyMatch construction at each match_graph.py finalize
    site.

    None unless verdict is INCLUDE -- the tag describes a company's role
    *within* the theme, which is meaningless for a company judged to lack
    credible exposure (EXCLUDE) or whose inclusion itself is unresolved
    (UNCERTAIN).
    """
    if verdict != MatchVerdict.INCLUDE:
        return None

    if exposure_estimate == ExposureEstimate.PURE_PLAY:
        return CompanyRole.PURE_PLAYER

    revenue_pct = revenue_exposure.revenue.value_pct if revenue_exposure is not None else None
    if revenue_pct is not None and revenue_pct >= settings.revenue_exposure_pure_play_threshold:
        return CompanyRole.PURE_PLAYER

    has_rd_signal = rd_exposure is not None and (
        rd_exposure.rd_intensity.source == "extracted" or rd_exposure.news_mentions.source == "news"
    )
    weak_revenue = revenue_pct is None or revenue_pct < settings.revenue_exposure_minor_threshold
    if has_rd_signal and weak_revenue:
        return CompanyRole.INNOVATOR

    return CompanyRole.DIVERSIFIED
