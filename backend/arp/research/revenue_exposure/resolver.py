from __future__ import annotations

from dataclasses import dataclass

from arp.config import Settings
from arp.extraction.pipeline import _extract_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.revenue_exposure.catalogue import CatalogueDataPoint, total_value
from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.revenue_exposure import ActivityCatalogueMapping, MetricExposure, RevenueCapexMetric, RevenueExposureResult
from arp.schemas.thematic import ActivityDefinition, ExposureEstimate


def is_sector_relevant(company_isic: str | None, activity_core_isic_codes: list[str]) -> bool:
    """Whether an activity is plausible for a company given their resolved
    ISIC codes -- gates path 2 (extraction) as a cost control, not a hard
    filter: absent information (no company ISIC, or the activity has no
    core_isic_codes at all) defaults to relevant=True rather than silently
    skipping an activity we simply can't judge.

    Matches by digit-prefix containment in either direction (a coarser
    company classification vs. a finer activity code, or vice versa) --
    the same relationship `standards_mapping/crosswalk.py::CrosswalkTable`
    relies on, since ISIC's hierarchical codes only guarantee that.
    """
    if not company_isic or not activity_core_isic_codes:
        return True
    return any(company_isic.startswith(code) or code.startswith(company_isic) for code in activity_core_isic_codes)


def band_exposure(revenue_pct: float, settings: Settings) -> ExposureEstimate:
    if revenue_pct >= settings.revenue_exposure_pure_play_threshold:
        return ExposureEstimate.PURE_PLAY
    if revenue_pct >= settings.revenue_exposure_significant_threshold:
        return ExposureEstimate.SIGNIFICANT
    if revenue_pct >= settings.revenue_exposure_minor_threshold:
        return ExposureEstimate.MINOR
    return ExposureEstimate.NONE


def resolve_from_catalogue(
    activity_id: str, metric: RevenueCapexMetric, company_rows: list[CatalogueDataPoint], mappings: list[ActivityCatalogueMapping]
) -> MetricExposure:
    """Path 1: pure computation against the reviewed activity->catalogue-
    label mapping. No LLM call, no judgment -- a row either matches a
    confirmed label or it doesn't."""
    mapping = next((m for m in mappings if m.activity_id == activity_id and m.metric == metric), None)
    if mapping is None or not mapping.matched_labels:
        return MetricExposure(source="unresolved")

    matched_rows = [r for r in company_rows if r.metric == metric and r.label in mapping.matched_labels]
    if not matched_rows:
        return MetricExposure(source="unresolved")

    denominator = total_value(company_rows, metric)
    share = 0.0
    resolved_any = False
    for row in matched_rows:
        if row.as_pct_of_total is not None:
            share += row.as_pct_of_total
            resolved_any = True
        elif row.value is not None and denominator:
            share += row.value / denominator
            resolved_any = True

    if not resolved_any:
        return MetricExposure(source="unresolved", notes="Matched catalogue rows had neither as_pct_of_total nor a computable share against a total row.")
    return MetricExposure(
        value_pct=min(max(share, 0.0), 1.0),
        source="catalogue",
        matched_catalogue_labels=mapping.matched_labels,
        notes=f"Matched catalogue labels: {', '.join(mapping.matched_labels)}",
    )


async def resolve_from_extraction(
    company: CompanyRef,
    activity: ActivityDefinition,
    metric: RevenueCapexMetric,
    *,
    documents: list[SourceDocument],
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
) -> tuple[MetricExposure, LLMUsage]:
    """Path 2: the same Extractor -> independent Verifier -> programmatic
    grounding check the Extraction Engine already runs for every other
    data point, applied to an ad hoc field built for this (activity,
    metric) pair -- see `taxonomy_sources/empirical.py::
    _activity_description_schema` for the precedent of building a field on
    the fly rather than requiring a pre-authored schema.
    """
    metric_label = "revenue" if metric == "revenue" else "capital expenditure (CapEx)"
    field = FieldDefinition(
        name=f"{metric}_share_pct",
        description=f"The percentage of {company.name}'s total {metric_label} attributable to: {activity.name} ({activity.in_scope_description})",
        data_type=FieldDataType.PERCENTAGE,
        unit="%",
        extraction_instructions=(
            f"Extract an EXPLICITLY stated percentage of total {metric_label} attributable to this specific "
            f"activity, as disclosed by the company (e.g. a stated segment revenue share, a 'X% of revenue came "
            f"from...' statement). Express `value` as a number between 0 and 100 (e.g. 18.5 for 18.5%). If only a "
            f"dollar figure is stated with no percentage and no computable total, leave `value` null and put the "
            f"raw figure in raw_value_text -- NEVER estimate, infer, or compute a percentage from unrelated totals."
        ),
        seed_keywords=[*activity.seed_keywords, metric],
    )
    schema = DataPointSchema(name=f"{activity.name} {metric} share", fields=[field])
    result = await _extract_company(
        company, schema, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings, documents=documents
    )
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


@dataclass
class RevenueResolverContext:
    """Bundles the run-scoped inputs the resolver needs, so
    `_match_company`'s signature doesn't balloon with individual params --
    None means the revenue-exposure tier is off (the default)."""

    catalogue_by_company: dict[str, list[CatalogueDataPoint]]
    mappings: list[ActivityCatalogueMapping]
    registry: DocumentSourceRegistry
    settings: Settings
    isic_model: LeontiefModel | None = None
    """Used to resolve a company's ISIC code for the sector-relevance gate
    on path 2, independent of whether the indirect-exposure tier itself is
    enabled -- if the caller already resolved a company's ISIC code via
    `indirect_model` for that tier, pass it into `resolve_company_activity_exposure`
    directly instead and this field can stay None."""


async def resolve_company_activity_exposure(
    company: CompanyRef,
    activity: ActivityDefinition,
    company_isic: str | None,
    *,
    documents: list[SourceDocument],
    ctx: RevenueResolverContext,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
) -> tuple[RevenueExposureResult, LLMUsage]:
    """Orchestrates the full cascade for one company x activity pair:
    catalogue first for both metrics, then extraction (gated by sector
    relevance) for whichever metric is still unresolved. The caller
    (`research/pipeline.py::_match_company`) decides whether an unresolved
    `revenue` share falls through to the qualitative debate (path 3);
    this function only ever resolves via paths 1/2 or reports unresolved.
    """
    company_rows = ctx.catalogue_by_company.get(company.company_id, [])
    relevant = is_sector_relevant(company_isic, activity.core_isic_codes)
    total_usage = LLMUsage()

    metrics: dict[RevenueCapexMetric, MetricExposure] = {}
    for metric in ("revenue", "capex"):
        exposure = resolve_from_catalogue(activity.activity_id, metric, company_rows, ctx.mappings)
        if exposure.source == "unresolved" and relevant:
            exposure, usage = await resolve_from_extraction(
                company,
                activity,
                metric,
                documents=documents,
                registry=ctx.registry,
                llm=llm,
                verifier_llm=verifier_llm,
                settings=ctx.settings,
            )
            total_usage = LLMUsage(input_tokens=total_usage.input_tokens + usage.input_tokens, output_tokens=total_usage.output_tokens + usage.output_tokens)
        metrics[metric] = exposure

    result = RevenueExposureResult(activity_id=activity.activity_id, revenue=metrics["revenue"], capex=metrics["capex"], sector_relevant=relevant)
    return result, total_usage
