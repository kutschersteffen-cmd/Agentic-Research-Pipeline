from __future__ import annotations

from dataclasses import dataclass

from arp.config import Settings
from arp.discovery.site_finder import WebSearchClient
from arp.extraction.pipeline import _extract_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.cost_tracker import combine_usage
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.rd_exposure.news_scoring import score_news_mentions
from arp.research.revenue_exposure.resolver import is_sector_relevant
from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.rd_exposure import RDExposureResult
from arp.schemas.revenue_exposure import MetricExposure
from arp.schemas.thematic import ActivityDefinition, LifecycleStage

_PRE_REVENUE_STAGES = {LifecycleStage.IDEATION, LifecycleStage.INNOVATION}
_MAX_NEWS_RESULTS = 8


async def resolve_rd_intensity(
    company: CompanyRef,
    activity: ActivityDefinition,
    *,
    documents: list[SourceDocument],
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
) -> tuple[MetricExposure, LLMUsage]:
    """Extracts an R&D-spend-intensity signal for this activity from the
    same disclosures already gathered for evidence-gathering -- the same
    Extractor -> Verifier -> grounding engine
    revenue_exposure/resolver.py::resolve_from_extraction uses for its own
    ad hoc single-field schema.

    Companies rarely break out R&D spend per thematic activity, so the
    extraction instructions accept a company-wide R&D-as-%-of-revenue
    figure when it's accompanied by explicit commentary tying R&D effort
    to this specific activity -- noted as company-wide in `notes`, not
    silently presented as activity-specific precision the disclosure
    doesn't actually support.
    """
    field = FieldDefinition(
        name="rd_intensity_pct",
        description=f"R&D spend intensity related to {company.name}'s investment in: {activity.name} ({activity.in_scope_description})",
        data_type=FieldDataType.PERCENTAGE,
        unit="%",
        extraction_instructions=(
            "Extract an EXPLICITLY stated R&D-spend-as-percentage-of-revenue figure, but only when the "
            "disclosure also names or clearly describes R&D effort specifically tied to this activity (a named "
            "program, product line, or research focus area) -- not just a bare company-wide R&D % with no "
            "connection to this activity. If the company discloses a company-wide R&D % alongside explicit "
            "commentary on this activity's R&D effort, extract the company-wide % and note in raw_value_text "
            "that it is company-wide, not activity-specific. NEVER estimate, infer, or compute a figure that "
            "isn't explicitly stated."
        ),
        seed_keywords=[*activity.seed_keywords, "research and development", "R&D"],
    )
    schema = DataPointSchema(name=f"{activity.name} R&D intensity", fields=[field])
    result = await _extract_company(company, schema, registry=registry, llm=llm, settings=settings, documents=documents)
    extracted = result.record.fields[0] if result.record.fields else None

    if extracted is None or extracted.value is None:
        return MetricExposure(source="unresolved"), result.usage
    try:
        pct = float(extracted.value)
    except (TypeError, ValueError):
        return MetricExposure(source="unresolved", notes="Extracted value was not numeric."), result.usage

    pct_fraction = pct / 100 if pct > 1 else pct
    citation = extracted.citations[0] if extracted.citations else None
    return (
        MetricExposure(
            value_pct=min(max(pct_fraction, 0.0), 1.0),
            source="extracted",
            confidence=extracted.confidence,
            citation=citation,
            notes=extracted.raw_value_text or "",
        ),
        result.usage,
    )


async def resolve_news_mentions(
    company: CompanyRef,
    activity: ActivityDefinition,
    *,
    search_client: WebSearchClient | None,
    llm: LLMClient,
) -> tuple[MetricExposure, LLMUsage]:
    """Web-search-based recency/momentum signal -- unresolved (not zero)
    when no search client is configured, since absence of a search
    capability isn't evidence of absence of momentum. A failed search
    (network error, rate limit) degrades to unresolved the same way,
    rather than failing the whole company x activity match.
    """
    if search_client is None:
        return MetricExposure(source="unresolved", notes="No search client configured."), LLMUsage()

    query = f"{company.name} {activity.name}"
    try:
        results = await search_client.search(query, max_results=_MAX_NEWS_RESULTS)
    except Exception:  # noqa: BLE001 -- a flaky search shouldn't fail the whole run
        return MetricExposure(source="unresolved", notes="Search failed."), LLMUsage()

    if not results:
        return MetricExposure(value_pct=0.0, source="news", notes="No search results found."), LLMUsage()

    score, relevant_results, usage = await score_news_mentions(company.name, activity, results, llm)
    notes = f"{len(relevant_results)}/{len(results)} search result(s) judged relevant."
    if relevant_results:
        notes += " " + "; ".join(r.url for r in relevant_results[:3])
    return MetricExposure(value_pct=score, source="news", confidence=0.5, notes=notes), usage


@dataclass
class RDResolverContext:
    """Bundles the run-scoped inputs Method C needs -- None means the
    tier is off (the default)."""

    registry: DocumentSourceRegistry
    settings: Settings
    isic_model: LeontiefModel | None = None
    """Used to resolve a company's ISIC code for the sector-relevance gate
    on rd_intensity extraction, independent of whether the indirect-
    exposure tier itself is enabled -- see RevenueResolverContext.isic_model
    for the identical precedent."""
    search_client: WebSearchClient | None = None
    """None disables just the news_mentions sub-signal, not the whole
    tier -- rd_intensity still runs for pre-revenue/emerging activities."""


async def resolve_company_activity_rd_exposure(
    company: CompanyRef,
    activity: ActivityDefinition,
    company_isic: str | None,
    *,
    documents: list[SourceDocument],
    ctx: RDResolverContext,
    llm: LLMClient,
) -> tuple[RDExposureResult | None, LLMUsage]:
    """Method C: R&D-spend-intensity + news-mention scoring for pre-revenue/
    emerging-stage activities.

    Returns (None, zero usage) entirely unless activity.lifecycle_stage is
    ideation or innovation -- this tier exists specifically because
    Method B's revenue-percentage scoring doesn't work for an activity
    with no meaningful revenue yet; running it for a commercialization/
    mature activity would just add cost for a signal that activity
    doesn't need.
    """
    if activity.lifecycle_stage not in _PRE_REVENUE_STAGES:
        return None, LLMUsage()

    relevant = is_sector_relevant(company_isic, activity.core_isic_codes)
    usages: list[LLMUsage] = []

    rd_intensity = MetricExposure(source="unresolved")
    if relevant:
        rd_intensity, usage = await resolve_rd_intensity(
            company, activity, documents=documents, registry=ctx.registry, llm=llm, settings=ctx.settings
        )
        usages.append(usage)

    news_mentions, usage = await resolve_news_mentions(company, activity, search_client=ctx.search_client, llm=llm)
    usages.append(usage)

    result = RDExposureResult(
        activity_id=activity.activity_id, rd_intensity=rd_intensity, news_mentions=news_mentions, sector_relevant=relevant
    )
    return result, combine_usage(*usages)
