from __future__ import annotations

import re
from dataclasses import dataclass

from arp.config import Settings
from arp.extraction.pipeline import _extract_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.revenue_exposure.catalogue import CatalogueDataPoint, total_value
from arp.research.taxonomy_schema import field_id_for
from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractedField
from arp.schemas.revenue_exposure import (
    ActivityCatalogueMapping,
    ExposureCitation,
    MetricExposure,
    RevenueCapexMetric,
    RevenueExposureResult,
)
from arp.schemas.thematic import ActivityDefinition, ExposureEstimate
from arp.xbrl_pipeline.store import XbrlStore


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


def to_exposure(extracted: ExtractedField | None, schema_version: str) -> MetricExposure:
    """An extracted percentage as a 0-1 exposure, its citation naming `schema_version`, or unresolved."""
    if extracted is None or extracted.value is None:
        return MetricExposure(source="unresolved")
    try:
        pct = float(extracted.value)
    except (TypeError, ValueError):
        return MetricExposure(source="unresolved", notes="Extracted value was not numeric.")

    if not 0 <= pct <= 100:  # also rejects nan; the extractor contract is 0-100
        return MetricExposure(source="unresolved", notes=f"Extracted value {extracted.value} is outside 0-100.")
    citation = (
        ExposureCitation(**extracted.citations[0].model_dump(), schema_version=schema_version) if extracted.citations else None
    )
    return MetricExposure(
        value_pct=pct / 100,
        source="extracted",
        confidence=extracted.confidence,
        citation=citation,
        notes=extracted.raw_value_text or "",
    )


async def extract_schema_fields(
    company: CompanyRef,
    schema: DataPointSchema,
    field_ids: list[str],
    *,
    documents: list[SourceDocument],
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
) -> tuple[dict[str, MetricExposure], LLMUsage]:
    """Path 2: the same Extractor -> independent Verifier -> programmatic
    grounding check the Extraction Engine runs for every other data point,
    over only `field_ids` of the run's released taxonomy schema. The subset
    keeps the schema's id, version and release flag, so every citation
    names the released schema."""
    subset = schema.model_copy(update={"fields": [f for f in schema.fields if f.field_id in field_ids]})
    result = await _extract_company(
        company, subset, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings, documents=documents
    )
    first = {}
    for f in result.record.fields:
        first.setdefault(f.field_id, f)
    return {fid: to_exposure(first.get(fid), f"{schema.schema_id}:v{schema.version}") for fid in field_ids}, result.usage


def _kw_match(keyword: str, text: str) -> bool:
    return bool(keyword.strip()) and re.search(
        r"(?<!\w)" + r"\s+".join(map(re.escape, keyword.split())) + r"(?!\w)", text, re.IGNORECASE
    ) is not None


def _activity_match(activity: ActivityDefinition, text: str) -> bool:
    return any(_kw_match(k, text) for k in activity.seed_keywords) and not any(
        _kw_match(k, text) for k in activity.exclusion_keywords
    )


def resolve_from_segments(
    company: CompanyRef, activity: ActivityDefinition, store: XbrlStore, settings: Settings
) -> tuple[MetricExposure, MetricExposure]:
    """The `reported` and `modelled` revenue shares from the company's XBRL
    segment rows and segment note (spec theme-revenue-share). No LLM call."""
    unresolved = MetricExposure(source="unresolved")
    keys = store.ciks()
    key = company.cik.zfill(10) if company.cik and company.cik.zfill(10) in keys else None
    key = key or next((k for k in keys if company.company_id in store.company_ids(k)), None)
    if key is None:
        return unresolved, unresolved
    revenue = [r for r in store.read_segments(key) if r.metric == "revenue"]
    if not revenue:
        return unresolved, unresolved
    year = max(r.fiscal_year for r in revenue)
    rows = [r for r in revenue if r.fiscal_year == year]

    def group(kind: str, level: str | None) -> list:
        return [r for r in rows if r.axis_kind == kind and r.level == level]

    total_group = next(
        (g for g in (group("segment", None), group("product", "standard"), group("product", "company"), group("geography", None))
         if g and all(r.sum_matches_total for r in g)),
        None,
    )
    total = sum(r.value for r in total_group) + (total_group[0].reconciling or 0) if total_group else 0
    if total <= 0:
        return unresolved, unresolved

    for g in (group("product", "company"), group("segment", None)):
        hits = [r for r in g if _activity_match(activity, r.segment)]
        if hits:
            reported = MetricExposure(
                value_pct=min(sum(r.value for r in hits) / total, 1.0), source="reported",
                notes=f"Reported segments (FY{year}): {', '.join(r.segment for r in hits)}",
            )
            return reported, unresolved

    note = store.read_segment_note(key)
    if not note:
        return unresolved, unresolved
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", note) if x.strip()]
    hits = [r for r in group("segment", None) if any(_kw_match(r.segment, x) and _activity_match(activity, x) for x in sentences)]
    if not hits:
        return unresolved, unresolved
    share = min(sum(r.value for r in hits) / total, 1.0)
    lo, hi = settings.revenue_share_modelled_low_factor, settings.revenue_share_modelled_high_factor
    modelled = MetricExposure(
        value_pct=(share * lo + share * hi) / 2, low_pct=share * lo, high_pct=share * hi, source="modelled",
        notes=f"Modelled from segment descriptions (FY{year}): {', '.join(r.segment for r in hits)}; "
        f"counted at {lo * 100:g}-{hi * 100:g}% of segment revenue.",
    )
    return unresolved, modelled


@dataclass
class RevenueResolverContext:
    """Bundles the run-scoped inputs the resolver needs, so
    `_match_company`'s signature doesn't balloon with individual params --
    None means the revenue-exposure tier is off (the default)."""

    catalogue_by_company: dict[str, list[CatalogueDataPoint]]
    mappings: list[ActivityCatalogueMapping]
    registry: DocumentSourceRegistry
    settings: Settings
    schema: DataPointSchema
    """The run's released taxonomy schema: path 2 extracts only its fields."""
    isic_model: LeontiefModel | None = None
    """Used to resolve a company's ISIC code for the sector-relevance gate
    on path 2, independent of whether the indirect-exposure tier itself is
    enabled -- if the caller already resolved a company's ISIC code via
    `indirect_model` for that tier, pass it into `resolve_company_activity_exposure`
    directly instead and this field can stay None."""
    xbrl_store: XbrlStore | None = None
    """None: the reported/modelled steps are off."""
    extract_enabled: bool = True


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
    catalogue first for revenue and CapEx, then one extraction call (gated
    by sector relevance) for whichever of revenue, CapEx and OpEx is still
    unresolved. The caller
    (`research/pipeline.py::_match_company`) decides whether an unresolved
    `revenue` share falls through to the qualitative debate (path 3);
    this function only ever resolves via paths 1/2 or reports unresolved.
    """
    company_rows = ctx.catalogue_by_company.get(company.company_id, [])
    relevant = is_sector_relevant(company_isic, activity.core_isic_codes)
    usage = LLMUsage()

    metrics: dict[str, MetricExposure] = {
        m: resolve_from_catalogue(activity.activity_id, m, company_rows, ctx.mappings) for m in ("revenue", "capex")
    }
    metrics["opex"] = MetricExposure(source="unresolved")  # no catalogue mapping for OpEx: extraction only
    modelled = None
    if ctx.xbrl_store is not None and metrics["revenue"].source == "unresolved":
        reported, modelled = resolve_from_segments(company, activity, ctx.xbrl_store, ctx.settings)
        if reported.source == "reported":
            metrics["revenue"] = reported
    todo = {field_id_for(ctx.schema, activity.activity_id, m): m for m, e in metrics.items() if e.source == "unresolved"}
    if todo and relevant and ctx.extract_enabled:
        extracted, usage = await extract_schema_fields(
            company, ctx.schema, list(todo), documents=documents, registry=ctx.registry,
            llm=llm, verifier_llm=verifier_llm, settings=ctx.settings,
        )
        for fid, m in todo.items():
            metrics[m] = extracted[fid]
    if modelled is not None and modelled.source == "modelled" and metrics["revenue"].source == "unresolved":
        metrics["revenue"] = modelled

    result = RevenueExposureResult(
        activity_id=activity.activity_id, revenue=metrics["revenue"], capex=metrics["capex"], opex=metrics["opex"],
        sector_relevant=relevant,
    )
    return result, usage
