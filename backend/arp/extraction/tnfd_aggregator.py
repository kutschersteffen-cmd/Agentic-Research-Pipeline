from __future__ import annotations

from arp.extraction.tnfd_extractor_agent import (
    CoreGlobalMetricDraft,
    DisclosureDraft,
    GeneralRequirementsDraft,
    SectorLeapConsiderationDraft,
    SectorMetricDraft,
    TNFDExtractionDraft,
)
from arp.extraction.tnfd_verifier_agent import TNFDVerifierOutput
from arp.grounding import ground_citations
from arp.schemas.common import SourceDocument
from arp.schemas.tnfd import (
    KNOWN_SECTOR_NAMES,
    SECTOR_GUIDANCE_STATUS,
    SECTOR_METRIC_REGISTRY,
    CoreGlobalMetricExtraction,
    DisclosureExtraction,
    GeneralRequirementsExtraction,
    RecommendationId,
    ReviewFlag,
    Sector,
    SectorLeapConsideration,
    SectorMetricExtraction,
    TNFDExtractionRecord,
)


def _build_disclosure(
    draft: DisclosureDraft, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float
) -> DisclosureExtraction:
    citations = ground_citations(draft.summary_citations, documents_by_id, fuzzy_threshold)
    grounded = all(c.grounded for c in citations) if citations else not draft.disclosed
    review_flags: list[ReviewFlag] = []
    if draft.disclosed and not draft.summary:
        review_flags.append(ReviewFlag.disclosure_claimed_without_supporting_chunk)
    return DisclosureExtraction(
        recommendation_id=draft.recommendation_id,
        disclosed=draft.disclosed,
        summary=draft.summary,
        summary_citations=citations,
        materiality_basis=draft.materiality_basis,
        disclosure_scope=draft.disclosure_scope,
        leap_stage_reference=draft.leap_stage_reference,
        grounded=grounded,
        review_flags=review_flags,
    )


def _build_core_metric(
    draft: CoreGlobalMetricDraft, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float
) -> CoreGlobalMetricExtraction:
    citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    grounded = all(c.grounded for c in citations) if citations else (draft.value is None)
    review_flags: list[ReviewFlag] = []
    if draft.value is not None and (draft.unit is None or draft.baseline_year is None):
        review_flags.append(ReviewFlag.metric_missing_unit_or_baseline)
    return CoreGlobalMetricExtraction(
        category=draft.category,
        metric_kind=draft.metric_kind,
        metric_name=draft.metric_name,
        value=draft.value,
        unit=draft.unit,
        baseline_year=draft.baseline_year,
        citations=citations,
        grounded=grounded,
        review_flags=review_flags,
    )


def _sector_review_flags(draft: SectorMetricDraft) -> list[ReviewFlag]:
    """Ports the draft schema's _flag_unmapped_or_stale_sector and
    _validate_metric_no_against_registry model_validators as a plain
    function -- see schemas/tnfd.py for why this lives here rather than
    on the model.
    """
    flags: list[ReviewFlag] = []
    if draft.sector_name not in KNOWN_SECTOR_NAMES:
        flags.append(ReviewFlag.sector_unmapped_to_sics)
        return flags

    sector = Sector(draft.sector_name)
    known_status = SECTOR_GUIDANCE_STATUS[sector]
    if known_status.value != draft.sector_guidance_status:
        # Sector exists but the extractor's claimed status (final/draft)
        # disagrees with our last-known taxonomy snapshot -- likely means
        # the sector's status has moved since sources.yaml was last synced.
        flags.append(ReviewFlag.sector_unmapped_to_sics)

    if draft.metric_no is None:
        return flags
    registry = SECTOR_METRIC_REGISTRY.get(sector)
    if not registry:
        # Registry not yet populated for this sector (see
        # schemas.tnfd.SECTOR_METRIC_REGISTRY / SECTOR_REGISTRY_PROVENANCE
        # for which sectors are populated, and how reliably) -- can't
        # validate, so don't flag either way.
        return flags
    matches = [m for m in registry if m.metric_no == draft.metric_no]
    if not matches:
        flags.append(ReviewFlag.metric_no_not_in_registry)
    elif matches[0].is_core != draft.is_core_sector_metric:
        # Extractor's core/additional classification disagrees with the
        # published guidance (e.g. metric was marked core but the sector
        # PDF has it in Section 3.3, additional metrics).
        flags.append(ReviewFlag.metric_core_flag_mismatch)
    return flags


def _build_sector_metric(
    draft: SectorMetricDraft, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float
) -> SectorMetricExtraction:
    citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    grounded = all(c.grounded for c in citations) if citations else (draft.value is None)
    review_flags = _sector_review_flags(draft)
    if draft.value is not None and (draft.unit is None or draft.baseline_year is None):
        review_flags.append(ReviewFlag.metric_missing_unit_or_baseline)
    return SectorMetricExtraction(
        sector_name=draft.sector_name,
        sector_guidance_status=draft.sector_guidance_status,
        sector_guidance_version=draft.sector_guidance_version,
        metric_no=draft.metric_no,
        is_core_sector_metric=draft.is_core_sector_metric,
        metric_name=draft.metric_name,
        value=draft.value,
        unit=draft.unit,
        baseline_year=draft.baseline_year,
        citations=citations,
        grounded=grounded,
        review_flags=review_flags,
    )


def _build_leap_consideration(
    draft: SectorLeapConsiderationDraft, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float
) -> SectorLeapConsideration:
    citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    review_flags: list[ReviewFlag] = []
    if draft.sector_name not in KNOWN_SECTOR_NAMES:
        review_flags.append(ReviewFlag.sector_unmapped_to_sics)
    return SectorLeapConsideration(
        sector_name=draft.sector_name,
        leap_stage=draft.leap_stage,
        consideration=draft.consideration,
        citations=citations,
        review_flags=review_flags,
    )


def _build_general_requirements(
    draft: GeneralRequirementsDraft | None, documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float
) -> GeneralRequirementsExtraction | None:
    if draft is None:
        return None
    citations = ground_citations(draft.citations, documents_by_id, fuzzy_threshold)
    return GeneralRequirementsExtraction(
        materiality_approach=draft.materiality_approach,
        disclosure_scope=draft.disclosure_scope,
        location_specificity=draft.location_specificity,
        cross_framework_links=draft.cross_framework_links,
        time_horizons_defined=draft.time_horizons_defined,
        iplc_engagement_described=draft.iplc_engagement_described,
        citations=citations,
    )


def _missing_recommendations(disclosures: list[DisclosureExtraction]) -> list[RecommendationId]:
    seen = {d.recommendation_id for d in disclosures}
    return sorted(set(RecommendationId) - seen, key=lambda r: r.value)


def _conflicting_materiality_flag(disclosures: list[DisclosureExtraction]) -> list[ReviewFlag]:
    stated_bases = {d.materiality_basis for d in disclosures if d.materiality_basis.value != "unstated"}
    if len(stated_bases) > 1:
        # Issuer appears to invoke different materiality bases (e.g.
        # "single" for Governance, "double" for Strategy) across pillars
        # without reconciling them -- surface for human review rather than
        # silently picking one.
        return [ReviewFlag.conflicting_materiality_across_pillars]
    return []


def build_tnfd_record(
    company_id: str,
    ticker: str | None,
    name: str,
    run_id: str,
    as_of: str,
    draft: TNFDExtractionDraft,
    verifier: TNFDVerifierOutput,
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[TNFDExtractionRecord, bool]:
    """Merges the combined extractor draft and combined independent-verifier
    pass into a final TNFDExtractionRecord, applying the hard programmatic
    grounding check to every citation across all five sections. Returns
    (record, needs_review).
    """
    final_confidence = min(draft.confidence, verifier.confidence)
    needs_review = final_confidence < confidence_review_threshold

    disclosure_drafts = draft.disclosures if verifier.disclosures_agree else (
        verifier.corrected_disclosures or draft.disclosures
    )
    disclosures = [_build_disclosure(d, documents_by_id, fuzzy_threshold) for d in disclosure_drafts]
    if not verifier.disclosures_agree or any(not d.grounded or d.review_flags for d in disclosures):
        needs_review = True

    core_metric_drafts = draft.core_global_metrics if verifier.core_global_metrics_agree else (
        verifier.corrected_core_global_metrics or draft.core_global_metrics
    )
    core_global_metrics = [_build_core_metric(m, documents_by_id, fuzzy_threshold) for m in core_metric_drafts]
    if not verifier.core_global_metrics_agree or any(not m.grounded or m.review_flags for m in core_global_metrics):
        needs_review = True

    sector_metric_drafts = draft.sector_metrics if verifier.sector_metrics_agree else (
        verifier.corrected_sector_metrics or draft.sector_metrics
    )
    sector_metrics = [_build_sector_metric(m, documents_by_id, fuzzy_threshold) for m in sector_metric_drafts]
    if not verifier.sector_metrics_agree or any(not m.grounded or m.review_flags for m in sector_metrics):
        needs_review = True

    leap_drafts = draft.sector_leap_considerations if verifier.sector_leap_considerations_agree else (
        verifier.corrected_sector_leap_considerations or draft.sector_leap_considerations
    )
    sector_leap_considerations = [_build_leap_consideration(c, documents_by_id, fuzzy_threshold) for c in leap_drafts]
    if not verifier.sector_leap_considerations_agree or any(c.review_flags for c in sector_leap_considerations):
        needs_review = True

    general_requirements_draft = draft.general_requirements if verifier.general_requirements_agree else (
        verifier.corrected_general_requirements or draft.general_requirements
    )
    general_requirements = _build_general_requirements(general_requirements_draft, documents_by_id, fuzzy_threshold)
    if not verifier.general_requirements_agree:
        needs_review = True

    missing_recommendations = _missing_recommendations(disclosures)
    record_review_flags = _conflicting_materiality_flag(disclosures)
    if record_review_flags:
        needs_review = True

    record = TNFDExtractionRecord(
        company_id=company_id,
        ticker=ticker,
        name=name,
        run_id=run_id,
        as_of=as_of,
        disclosures=disclosures,
        core_global_metrics=core_global_metrics,
        sector_metrics=sector_metrics,
        sector_leap_considerations=sector_leap_considerations,
        general_requirements=general_requirements,
        missing_recommendations=missing_recommendations,
        overall_confidence=final_confidence,
        needs_review=needs_review,
        record_review_flags=record_review_flags,
    )
    return record, needs_review
