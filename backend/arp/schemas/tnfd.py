"""TNFD extraction schema -- final record shapes for the Claude-based
extraction stage.

Mirrors the segments/spend/financials pattern (see schemas/segments.py,
schemas/financials.py): every leaf carries a shared Citation/ProvenanceInfo
(schemas/common.py), grounding/review-flagging happens programmatically in
extraction/tnfd_aggregator.py, not via model validators here -- this module
defines the *shape* of extraction output only.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, ProvenanceInfo, now_iso

TNFD_FRAMEWORK_VERSION = "v1.1 (October 2023, incl. Additional Guidance)"


# ---------------------------------------------------------------------------
# Enumerations tied to the sources.yaml config
# ---------------------------------------------------------------------------

class Pillar(StrEnum):
    governance = "governance"
    strategy = "strategy"
    risk_and_impact_management = "risk_and_impact_management"
    metrics_and_targets = "metrics_and_targets"


class RecommendationId(StrEnum):
    governance_a = "governance.A"
    governance_b = "governance.B"
    governance_c = "governance.C"
    strategy_a = "strategy.A"
    strategy_b = "strategy.B"
    strategy_c = "strategy.C"
    strategy_d = "strategy.D"
    risk_a_direct_ops = "risk.A_direct_ops"
    risk_a_value_chain = "risk.A_value_chain"
    risk_b = "risk.B"
    risk_c = "risk.C"
    metrics_a = "metrics.A"
    metrics_b = "metrics.B"
    metrics_c = "metrics.C"


PILLAR_BY_RECOMMENDATION: dict[RecommendationId, Pillar] = {
    RecommendationId.governance_a: Pillar.governance,
    RecommendationId.governance_b: Pillar.governance,
    RecommendationId.governance_c: Pillar.governance,
    RecommendationId.strategy_a: Pillar.strategy,
    RecommendationId.strategy_b: Pillar.strategy,
    RecommendationId.strategy_c: Pillar.strategy,
    RecommendationId.strategy_d: Pillar.strategy,
    RecommendationId.risk_a_direct_ops: Pillar.risk_and_impact_management,
    RecommendationId.risk_a_value_chain: Pillar.risk_and_impact_management,
    RecommendationId.risk_b: Pillar.risk_and_impact_management,
    RecommendationId.risk_c: Pillar.risk_and_impact_management,
    RecommendationId.metrics_a: Pillar.metrics_and_targets,
    RecommendationId.metrics_b: Pillar.metrics_and_targets,
    RecommendationId.metrics_c: Pillar.metrics_and_targets,
}


class LeapStage(StrEnum):
    locate = "locate"
    evaluate = "evaluate"
    assess = "assess"
    prepare = "prepare"


class CoreGlobalMetricCategory(StrEnum):
    land_use_change = "land_use_change"
    freshwater_use_change = "freshwater_use_change"
    ocean_use_change = "ocean_use_change"
    pollution = "pollution"
    resource_use_and_replenishment = "resource_use_and_replenishment"
    invasive_species_introduction = "invasive_species_introduction"


class MetricKind(StrEnum):
    dependency_impact = "dependency_impact"
    risk_opportunity = "risk_opportunity"


class SectorGuidanceStatus(StrEnum):
    final = "final"
    draft = "draft"


class Sector(StrEnum):
    """The 16 sectors currently covered by TNFD additional sector guidance.

    This mirrors sector_guidance.sectors in sources.yaml and must be kept in
    sync with it manually -- TNFD's sector list is still expanding (13 final
    sectors as of Jan 2025, 15 final + 1 draft as of mid-2026), so re-check
    the published list at discovery time rather than assuming this enum is
    exhaustive. SectorMetricExtraction below does NOT hard-fail on an
    off-taxonomy sector name; it soft-flags it for review instead (see
    ReviewFlag.sector_unmapped_to_sics), since a genuinely new or renamed
    sector shouldn't crash extraction.
    """
    electric_utilities_and_power_generation = "electric_utilities_and_power_generation"
    financial_institutions = "financial_institutions"
    metals_and_mining = "metals_and_mining"
    oil_and_gas = "oil_and_gas"
    food_and_agriculture = "food_and_agriculture"
    chemicals = "chemicals"
    forestry_pulp_and_paper = "forestry_pulp_and_paper"
    aquaculture = "aquaculture"
    biotechnology_and_pharmaceuticals = "biotechnology_and_pharmaceuticals"
    apparel_accessories_and_footwear = "apparel_accessories_and_footwear"
    beverages = "beverages"
    engineering_construction_and_real_estate = "engineering_construction_and_real_estate"
    fishing = "fishing"
    marine_transportation_and_cruise_lines = "marine_transportation_and_cruise_lines"
    water_utilities_and_services = "water_utilities_and_services"
    alternative_fuels = "alternative_fuels"


SECTOR_GUIDANCE_STATUS: dict[Sector, SectorGuidanceStatus] = {
    Sector.electric_utilities_and_power_generation: SectorGuidanceStatus.final,
    Sector.financial_institutions: SectorGuidanceStatus.final,
    Sector.metals_and_mining: SectorGuidanceStatus.final,
    Sector.oil_and_gas: SectorGuidanceStatus.final,
    Sector.food_and_agriculture: SectorGuidanceStatus.final,
    Sector.chemicals: SectorGuidanceStatus.final,
    Sector.forestry_pulp_and_paper: SectorGuidanceStatus.final,
    Sector.aquaculture: SectorGuidanceStatus.final,
    Sector.biotechnology_and_pharmaceuticals: SectorGuidanceStatus.final,
    Sector.apparel_accessories_and_footwear: SectorGuidanceStatus.final,
    Sector.beverages: SectorGuidanceStatus.final,
    Sector.engineering_construction_and_real_estate: SectorGuidanceStatus.final,
    Sector.fishing: SectorGuidanceStatus.final,
    Sector.marine_transportation_and_cruise_lines: SectorGuidanceStatus.final,
    Sector.water_utilities_and_services: SectorGuidanceStatus.final,
    Sector.alternative_fuels: SectorGuidanceStatus.draft,
}

KNOWN_SECTOR_NAMES: set[str] = {s.value for s in Sector}


class SectorMetricDefinition(NamedTuple):
    """A single known TNFD sector metric, as published in a sector guidance doc.

    is_core distinguishes Section 3.2 (core, comply-or-explain) from Section 3.3
    (additional, optional) metrics per the TNFD disclosure measurement architecture.
    metric_category/metric_subcategory mirror each sector guidance's own taxonomy
    verbatim (these differ across sectors -- e.g. oil & gas organizes by "driver of
    nature change", metals & mining organizes by "Response"/"Strategy" -- so don't
    assume a shared taxonomy across sectors).
    """
    metric_no: str
    indicator: str
    is_core: bool
    metric_category: str
    metric_subcategory: str
    source: str


# Registries populated per sector, at varying confidence -- see
# SECTOR_REGISTRY_PROVENANCE below for which. An empty list/absent key for a
# sector means "not yet populated", not "no metrics exist" -- tnfd_aggregator.py
# only validates metric_no against sectors present here.
SECTOR_METRIC_REGISTRY: dict[Sector, list[SectorMetricDefinition]] = {
    Sector.oil_and_gas: [
        SectorMetricDefinition("OG.C1.0", "Site location in Indigenous territories", True,
                                "Impact driver", "Land/freshwater/ocean-use change", "TNFD"),
        SectorMetricDefinition("OG.C2.0", "Volume of hydrocarbon spills", True,
                                "Impact driver", "Pollution/pollution removal", "SASB EM-MD-160a.4"),
        SectorMetricDefinition("OG.A4.0", "Invasive alien species management", False,
                                "Impact driver", "Invasive alien species and other", "TNFD"),
        SectorMetricDefinition("OG.A1.0", "Operations where Indigenous Peoples present/affected", False,
                                "Impact driver", "Land/freshwater/ocean-use change", "GRI 11.17.3"),
        SectorMetricDefinition("OG.A1.1", "Reserves' location in proximity to Indigenous territories", False,
                                "Impact driver", "Land/freshwater/ocean-use change", "SASB EM-EP210a.2"),
        SectorMetricDefinition("OG.A1.2", "Reserves in sensitive locations", False,
                                "Impact driver", "Land/freshwater/ocean-use change", "SASB EM-EP160a.3"),
        SectorMetricDefinition("OG.A1.3", "Spatial footprint in sensitive locations", False,
                                "Impact driver", "Land/freshwater/ocean-use change", "TNFD"),
        SectorMetricDefinition("OG.A2.0", "Decommissioned structures remaining in place", False,
                                "Impact driver", "Pollution/pollution removal", "GRI 11.7.5"),
        SectorMetricDefinition("OG.A2.1", "Decommissioning and remediation projects", False,
                                "Impact driver", "Pollution/pollution removal", "Ipieca ENV-8, A1"),
        SectorMetricDefinition("OG.A23.0", "Process safety events", False,
                                "Response", "Dependency/impact/risk/opportunity management: mitigation hierarchy",
                                "GRI 11 (2021)"),
    ],
    Sector.metals_and_mining: [
        SectorMetricDefinition("MM.C23.0", "Area of sites with plans to manage impacts on sensitive locations", True,
                                "Response",
                                "Dependency/impact/risk/opportunity management: mitigation hierarchy steps",
                                "Adapted from GRI 101 Biodiversity (2024); TNFD"),
        SectorMetricDefinition("MM.A23.0", "Additional conservation and restoration activities", False,
                                "Response",
                                "Dependency/impact/risk/opportunity management: mitigation hierarchy steps",
                                "Adapted from GRI 101-2; CDP Biodiversity 11.18; ESRS S3-2"),
        SectorMetricDefinition("MM.A23.1", "Circular economy", False,
                                "Response",
                                "Dependency/impact/risk/opportunity management: mitigation hierarchy steps",
                                "Pace (2022)"),
        SectorMetricDefinition("MM.A25.0", "Extent of site-level ecosystem service assessments", False,
                                "Response",
                                "Dependency/impact/risk/opportunity management: dependency/impact/risk/opportunity assessment",
                                "Adapted from GRI 101 Biodiversity 101-8; ESRS 2 IRO-1(b)"),
        SectorMetricDefinition("MM.A23.2", "Extent of transformative actions taken", False,
                                "Response",
                                "Dependency/impact/risk/opportunity management: mitigation hierarchy steps",
                                "Adapted from TNFD based on ICMM (2024) Nature Position Statement; Booth et al. (2024)"),
        SectorMetricDefinition("MM.A23.3", "Impact management (mine closure/rehab status)", False,
                                "Response",
                                "Dependency/impact/risk/opportunity management: mitigation hierarchy steps",
                                "Adapted from GRI 14: Mining Sector (2024)"),
        SectorMetricDefinition("MM.A23.4", "Suppliers screened for nature-related risks", False,
                                "Response",
                                "Dependency/impact/risk/opportunity management: mitigation hierarchy steps",
                                "Based on ICMM Nature Position Statement (2024); ESRS G1-2(c)"),
        SectorMetricDefinition("MM.A21.0", "Capital allocation (closure/rehabilitation provisions)", False,
                                "Response", "Strategy: capital allocation/investment",
                                "Adapted from GRI 12: Coal sector (2023); GRI 14: Mining Sector (2024)"),
        SectorMetricDefinition("MM.A19.0", "Water impacts and state of nature", False,
                                "Response", "Strategy: policies, commitments & targets",
                                "ICMM Water Reporting Guide (2nd ed.); ICMM (2017) Water Stewardship Position Statement"),
    ],
    # PROVISIONAL -- see SECTOR_REGISTRY_PROVENANCE. Reconstructed from
    # general knowledge of TNFD's "Additional guidance for Food and
    # Agriculture" and the sector-standard sources it draws on (GRI 13,
    # SASB Agricultural Products/Meat/Dairy, CDP Forests/Water, the
    # Accountability Framework Initiative), NOT read from the primary PDF.
    # metric_no values, exact indicator wording, and core/additional
    # classification are best-effort and must be checked against TNFD's
    # published guidance before being relied on for compliance decisions.
    Sector.food_and_agriculture: [
        SectorMetricDefinition("FA.C1.0", "Land area under management in or near sensitive/protected/high biodiversity-value locations", True,
                                "Impact driver", "Land/freshwater/ocean-use change", "Adapted from GRI 13.3; SASB FB-AG-160a.2"),
        SectorMetricDefinition("FA.C2.0", "Volume of water withdrawn and consumed in water-stressed areas", True,
                                "Impact driver", "Freshwater-use change", "Adapted from SASB FB-AG-140a.1"),
        SectorMetricDefinition("FA.C3.0", "Quantity of priority/hazardous pesticides used or sold", True,
                                "Impact driver", "Pollution/pollution removal", "Adapted from SASB FB-AG-430a.2; GRI 13.6"),
        SectorMetricDefinition("FA.A1.0", "Volume/percentage of production sourced from deforestation- and conversion-free areas", False,
                                "Impact driver", "Land-use change",
                                "Adapted from the Accountability Framework Initiative; CDP Forests"),
        SectorMetricDefinition("FA.A2.0", "Fertilizer/nutrient application intensity (nitrogen/phosphorus)", False,
                                "Impact driver", "Pollution/pollution removal", "Adapted from GRI 13.6"),
        SectorMetricDefinition("FA.A3.0", "Soil health and erosion management practices", False,
                                "Impact driver", "Resource use and replenishment", "Adapted from GRI 13"),
        SectorMetricDefinition("FA.A4.0", "Adoption of biodiversity-supportive/regenerative farming practices", False,
                                "Response", "Dependency/impact/risk/opportunity management: mitigation hierarchy",
                                "Adapted from GRI 13; TNFD"),
        SectorMetricDefinition("FA.A5.0", "Supplier screening/engagement on deforestation and land-conversion risk", False,
                                "Response", "Dependency/impact/risk/opportunity management: mitigation hierarchy",
                                "Adapted from the Accountability Framework Initiative; CDP Forests"),
        SectorMetricDefinition("FA.A6.0", "Area under active habitat/ecosystem restoration or regeneration", False,
                                "Response", "Dependency/impact/risk/opportunity management: mitigation hierarchy",
                                "Adapted from GRI 101 Biodiversity (2024)"),
    ],
}

# How each sector's SECTOR_METRIC_REGISTRY entry was sourced, so a reviewer
# knows which registries are safe to trust as-is (read from the primary TNFD
# guidance PDF in full) vs. which are a provisional reconstruction that still
# needs verification against the primary source before compliance use.
SECTOR_REGISTRY_PROVENANCE: dict[Sector, str] = {
    Sector.oil_and_gas: "verified: read from the primary TNFD sector guidance PDF in full",
    Sector.metals_and_mining: "verified: read from the primary TNFD sector guidance PDF in full",
    Sector.food_and_agriculture: "PROVISIONAL: reconstructed from general domain knowledge, not read from "
                                  "the primary TNFD sector guidance PDF -- verify before compliance use",
}

SECTOR_METRIC_NOS: dict[Sector, set[str]] = {
    sector: {m.metric_no for m in metrics} for sector, metrics in SECTOR_METRIC_REGISTRY.items()
}


class MaterialityBasis(StrEnum):
    single = "single"
    double = "double"
    dynamic = "dynamic"
    unstated = "unstated"


class DisclosureScope(StrEnum):
    direct_operations = "direct_operations"
    direct_operations_and_upstream = "direct_operations_and_upstream"
    full_value_chain = "full_value_chain"
    financed_activities = "financed_activities"


class ReviewFlag(StrEnum):
    sector_unmapped_to_sics = "sector_unmapped_to_sics"
    conflicting_materiality_across_pillars = "conflicting_materiality_across_pillars"
    metric_missing_unit_or_baseline = "metric_missing_unit_or_baseline"
    disclosure_claimed_without_supporting_chunk = "disclosure_claimed_without_supporting_chunk"
    metric_no_not_in_registry = "metric_no_not_in_registry"
    metric_core_flag_mismatch = "metric_core_flag_mismatch"


# ---------------------------------------------------------------------------
# Core disclosure extraction (one per recommendation, per issuer, per as_of)
# ---------------------------------------------------------------------------

class DisclosureExtraction(BaseModel):
    """`pillar` is deliberately not a field here -- it's fully derivable from
    recommendation_id via PILLAR_BY_RECOMMENDATION, so it's resolved in
    tnfd_aggregator.py rather than trusted from the LLM (the same discipline
    Citation.grounded/.page follow)."""

    recommendation_id: RecommendationId
    disclosed: bool = Field(..., description="Whether the issuer addressed this "
                                              "recommendation at all, independent of quality.")
    summary: str | None = Field(
        None, description="Extractor's paraphrase of the disclosed content. "
                           "Not evidence on its own -- always paired with summary_citations."
    )
    summary_citations: list[Citation] = Field(default_factory=list)
    materiality_basis: MaterialityBasis = MaterialityBasis.unstated
    disclosure_scope: DisclosureScope | None = None
    leap_stage_reference: LeapStage | None = Field(
        None, description="LEAP stage the disclosure is grounded in, if the issuer "
                           "references its own LEAP assessment. Context only -- LEAP "
                           "is not a disclosure recommendation itself."
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = Field(default=False, description="True only if every citation in "
                                                        "summary_citations grounded.")
    verifier_notes: str | None = None
    review_flags: list[ReviewFlag] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class CoreGlobalMetricExtraction(BaseModel):
    category: CoreGlobalMetricCategory
    metric_kind: MetricKind
    metric_name: str
    value: float | None = None
    unit: str | None = None
    baseline_year: int | None = None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = False
    verifier_notes: str | None = None
    review_flags: list[ReviewFlag] = Field(default_factory=list)


class SectorMetricExtraction(BaseModel):
    sector_name: str = Field(..., description="Should resolve to a SICS-derived sector "
                                               "name from sources.yaml (see Sector enum); "
                                               "if not, soft-flagged rather than rejected.")
    sector_guidance_status: SectorGuidanceStatus
    sector_guidance_version: str = Field(..., description="Publication date of the "
                                                           "specific sector addendum used.")
    metric_no: str | None = Field(
        None, description="The sector guidance's own metric ID (e.g. 'OG.C1.0', "
                           "'MM.A23.1'), where the extractor could identify one. "
                           "Only validated against SECTOR_METRIC_REGISTRY for sectors "
                           "where that registry has been populated from the source PDF; "
                           "absence of a match there is soft-flagged, not rejected."
    )
    is_core_sector_metric: bool
    metric_name: str
    value: float | None = None
    unit: str | None = None
    baseline_year: int | None = None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    grounded: bool = False
    verifier_notes: str | None = None
    review_flags: list[ReviewFlag] = Field(default_factory=list)


class SectorLeapConsideration(BaseModel):
    """Narrative sector-specific guidance on applying the LEAP approach.

    Distinct from SectorMetricExtraction: this is qualitative methodology
    guidance (e.g. "prioritise upstream deforestation screening for this
    sector"), not a metric value, so it doesn't fit the metric shape.
    """
    sector_name: str
    leap_stage: LeapStage
    consideration: str
    citations: list[Citation] = Field(default_factory=list)
    review_flags: list[ReviewFlag] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# General requirements (cross-cutting qualifiers, not separate recommendations)
# ---------------------------------------------------------------------------

class GeneralRequirementsExtraction(BaseModel):
    materiality_approach: MaterialityBasis
    disclosure_scope: DisclosureScope
    location_specificity: str
    cross_framework_links: list[str] = Field(
        default_factory=list, description="e.g. ['TCFD', 'ESRS E4', 'GRI 101']"
    )
    time_horizons_defined: dict[str, str] = Field(
        default_factory=dict, description="e.g. {'short': '0-3y', 'medium': '3-10y', 'long': '10y+'}"
    )
    iplc_engagement_described: bool
    citations: list[Citation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level extraction record -- one per issuer per run
# ---------------------------------------------------------------------------

class TNFDExtractionRecord(BaseModel):
    company_id: str
    ticker: str | None = None
    name: str
    run_id: str
    as_of: str = Field(..., description="Reporting period / publication date the "
                                         "disclosure pertains to. No 'latest' default.")
    framework_version: str = TNFD_FRAMEWORK_VERSION
    disclosures: list[DisclosureExtraction] = Field(default_factory=list)
    core_global_metrics: list[CoreGlobalMetricExtraction] = Field(default_factory=list)
    sector_metrics: list[SectorMetricExtraction] = Field(default_factory=list)
    sector_leap_considerations: list[SectorLeapConsideration] = Field(default_factory=list)
    general_requirements: GeneralRequirementsExtraction | None = None

    # Record-level fields: these arise from cross-checking multiple fields
    # against each other, so they're computed in tnfd_aggregator.py rather
    # than living on any single leaf.
    missing_recommendations: list[RecommendationId] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_review: bool = False
    record_review_flags: list[ReviewFlag] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)
    provenance: ProvenanceInfo | None = Field(
        default=None, description="Which extractor/verifier model+prompt version produced this record."
    )
