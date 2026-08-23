from __future__ import annotations

from arp.config import Settings
from arp.schemas.arbitration import ArbitrationContribution, ArbitrationResult
from arp.schemas.exposure import IndirectExposureResult
from arp.schemas.rd_exposure import RDExposureResult
from arp.schemas.revenue_exposure import RevenueExposureResult
from arp.schemas.thematic import ExposureEstimate

_ESTIMATE_TO_SCALAR: dict[ExposureEstimate, float] = {
    ExposureEstimate.PURE_PLAY: 1.0,
    ExposureEstimate.SIGNIFICANT: 0.6,
    ExposureEstimate.MINOR: 0.3,
    ExposureEstimate.NONE: 0.0,
}


def _collect_contributions(
    *,
    qualitative_estimate: ExposureEstimate | None,
    revenue_exposure: RevenueExposureResult | None,
    indirect_exposure: IndirectExposureResult | None,
    rd_exposure: RDExposureResult | None,
    settings: Settings,
) -> list[ArbitrationContribution]:
    contributions: list[ArbitrationContribution] = []

    if qualitative_estimate is not None:
        contributions.append(
            ArbitrationContribution(
                method="qualitative_debate",
                signal=_ESTIMATE_TO_SCALAR[qualitative_estimate],
                weight=settings.arbitration_weight_qualitative_debate,
                detail=qualitative_estimate.value,
            )
        )

    if revenue_exposure is not None and revenue_exposure.revenue.source in ("catalogue", "extracted"):
        revenue = revenue_exposure.revenue
        method = "revenue_catalogue" if revenue.source == "catalogue" else "revenue_extracted"
        weight = settings.arbitration_weight_revenue_catalogue if revenue.source == "catalogue" else settings.arbitration_weight_revenue_extracted
        contributions.append(
            ArbitrationContribution(
                method=method, signal=min(max(revenue.value_pct or 0.0, 0.0), 1.0), weight=weight,
                detail=f"{revenue.value_pct:.1%}" if revenue.value_pct is not None else "",
            )
        )

    if indirect_exposure is not None:
        upstream, downstream = indirect_exposure.upstream_exposure, indirect_exposure.downstream_exposure
        stronger = "upstream" if upstream >= downstream else "downstream"
        contributions.append(
            ArbitrationContribution(
                method="indirect", signal=max(upstream, downstream), weight=settings.arbitration_weight_indirect, detail=stronger
            )
        )

    if rd_exposure is not None:
        if rd_exposure.rd_intensity.source == "extracted":
            contributions.append(
                ArbitrationContribution(
                    method="rd_intensity",
                    signal=min(max(rd_exposure.rd_intensity.value_pct or 0.0, 0.0), 1.0),
                    weight=settings.arbitration_weight_rd_intensity,
                )
            )
        if rd_exposure.news_mentions.source == "news":
            contributions.append(
                ArbitrationContribution(
                    method="news_mentions",
                    signal=min(max(rd_exposure.news_mentions.value_pct or 0.0, 0.0), 1.0),
                    weight=settings.arbitration_weight_news_mentions,
                )
            )

    return contributions


def compute_arbitration(
    *,
    qualitative_estimate: ExposureEstimate | None,
    revenue_exposure: RevenueExposureResult | None,
    indirect_exposure: IndirectExposureResult | None,
    rd_exposure: RDExposureResult | None,
    settings: Settings,
) -> ArbitrationResult:
    """Combines whichever exposure signals are actually available for one
    (company, activity) match into a single weighted composite score, and
    flags -- rather than silently averages away -- meaningful disagreement
    between them. Pure function: no LLM call, no I/O.

    `qualitative_estimate` must be None when the caller's exposure_estimate
    was itself mechanically derived from `revenue_exposure` (the
    revenue-short-circuit path) -- including it too would double-count the
    same underlying fact as if two independent methods had agreed. See the
    three call sites in match_graph.py for exactly when each passes None.
    """
    contributions = _collect_contributions(
        qualitative_estimate=qualitative_estimate,
        revenue_exposure=revenue_exposure,
        indirect_exposure=indirect_exposure,
        rd_exposure=rd_exposure,
        settings=settings,
    )

    if contributions:
        weighted_sum = sum(c.signal * c.weight for c in contributions)
        weight_total = sum(c.weight for c in contributions)
        composite_score = weighted_sum / weight_total if weight_total > 0 else 0.0
    else:
        composite_score = 0.0

    signals = [c.signal for c in contributions]
    disagreement_spread = (max(signals) - min(signals)) if len(signals) >= 2 else 0.0
    methods_disagree = disagreement_spread > settings.arbitration_disagreement_threshold
    mid_band = settings.arbitration_mid_band_low <= composite_score <= settings.arbitration_mid_band_high

    if contributions:
        summary = ", ".join(f"{c.method} ({c.signal:.2f}, weight {c.weight:.2f})" for c in contributions)
        rationale = f"Combined {len(contributions)} signal(s): {summary}. Composite {composite_score:.2f}."
        rationale += (
            f" Signals disagree (spread {disagreement_spread:.2f} > {settings.arbitration_disagreement_threshold:.2f})."
            if methods_disagree
            else f" Signals agree (spread {disagreement_spread:.2f} <= {settings.arbitration_disagreement_threshold:.2f})."
        )
    else:
        rationale = "No signals available to combine."

    return ArbitrationResult(
        composite_score=composite_score,
        methods_disagree=methods_disagree,
        disagreement_spread=disagreement_spread,
        mid_band=mid_band,
        contributions=contributions,
        rationale=rationale,
    )
