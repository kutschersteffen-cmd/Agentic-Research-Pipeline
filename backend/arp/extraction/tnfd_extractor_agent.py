from __future__ import annotations

from pydantic import BaseModel, Field

from arp.extraction.extractor_agent import format_evidence
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import Citation, DocType, DocumentChunk

# TNFD disclosures typically live in a standalone "nature"/TNFD report, or a
# dedicated section of the sustainability report; occasionally summarized in
# an investor presentation or (for a US filer that treats nature risk as
# material) the 10-K itself.
TNFD_DOC_TYPES = [
    DocType.SUSTAINABILITY_REPORT,
    DocType.ANNUAL_REPORT_10K,
    DocType.INVESTOR_PRESENTATION,
    DocType.OTHER,
]

TNFD_KEYWORDS = [
    "TNFD",
    "nature-related",
    "nature related",
    "biodiversity",
    "natural capital",
    "LEAP approach",
    "locate, evaluate, assess, prepare",
    "dependencies and impacts",
    "nature risk",
    "nature-related risk",
    "nature-related opportunity",
    "ecosystem services",
    "deforestation",
    "land use change",
    "freshwater use",
    "ocean use",
    "invasive species",
    "governance of nature",
    "board oversight of nature",
    "sensitive locations",
    "value chain screening",
]

TNFD_GUIDANCE = """\
TNFD (Taskforce on Nature-related Financial Disclosures) recommendations, \
organized into 4 pillars and 14 recommendations. For EVERY recommendation \
below, attempt extraction; if the evidence doesn't address it, set \
disclosed=false and leave summary/citations empty rather than guessing.

=== Governance ===
governance.A: Board oversight of nature-related dependencies, impacts, \
risks and opportunities.
governance.B: Management's role in assessing and managing nature-related \
dependencies, impacts, risks and opportunities.
governance.C: The organization's human rights policies and engagement \
activities with affected stakeholders (incl. Indigenous Peoples and local \
communities, "IPLC") in relation to nature.

=== Strategy ===
strategy.A: Nature-related dependencies, impacts, risks and opportunities \
identified over the short, medium and long term.
strategy.B: Effect of nature-related dependencies, impacts, risks and \
opportunities on business model, value chain, strategy and financial \
planning.
strategy.C: Resilience of strategy to nature-related risks and \
opportunities.
strategy.D: Locations of assets/activities material to nature-related \
issues (direct operations, and where possible upstream/downstream value \
chain).

=== Risk and impact management ===
risk.A_direct_ops: Processes for identifying, assessing and prioritizing \
nature-related dependencies, impacts, risks and opportunities in direct \
operations.
risk.A_value_chain: Same, for the upstream/downstream value chain.
risk.B: Processes for managing nature-related dependencies, impacts, risks \
and opportunities (incl. mitigation hierarchy application).
risk.C: How the above processes are integrated into overall risk \
management.

=== Metrics and targets ===
metrics.A: Metrics used to assess and manage material nature-related \
risks and opportunities, per the LEAP approach.
metrics.B: Metrics used to assess and manage dependencies and impacts on \
nature.
metrics.C: Targets and goals used to manage nature-related dependencies, \
impacts, risks and opportunities, and performance against them.

For each recommendation also record, when the evidence supports it:
- materiality_basis: "single" (financial materiality only), "double" \
  (financial + impact materiality), "dynamic" (double materiality that \
  evolves as risks crystallize), or "unstated" if the issuer doesn't say.
- disclosure_scope: how far into the value chain the disclosure extends \
  ("direct_operations", "direct_operations_and_upstream", \
  "full_value_chain", or "financed_activities" for a financial \
  institution's portfolio).
- leap_stage_reference: if the issuer explicitly frames the disclosure in \
  terms of its own LEAP assessment (Locate/Evaluate/Assess/Prepare), which \
  stage. Leave null otherwise -- LEAP is a methodology reference, not \
  itself a recommendation.

=== Core global metrics ===
For each of the 6 categories (land_use_change, freshwater_use_change, \
ocean_use_change, pollution, resource_use_and_replenishment, \
invasive_species_introduction), extract every core global metric \
disclosed, tagged as either dependency_impact (pressure the company puts \
on nature) or risk_opportunity (financial risk/opportunity metric). Only \
report figures explicitly disclosed -- never estimate or compute.

=== Sector metrics ===
If the issuer's primary sector matches one of TNFD's 16 covered sectors \
(electric_utilities_and_power_generation, financial_institutions, \
metals_and_mining, oil_and_gas, food_and_agriculture, chemicals, \
forestry_pulp_and_paper, aquaculture, biotechnology_and_pharmaceuticals, \
apparel_accessories_and_footwear, beverages, \
engineering_construction_and_real_estate, fishing, \
marine_transportation_and_cruise_lines, water_utilities_and_services, \
alternative_fuels), extract sector-specific metrics disclosed against that \
sector's additional guidance, with the guidance's own metric_no where \
identifiable (e.g. "OG.C1.0", "MM.A23.1") and whether the issuer/guidance \
frames it as a core (comply-or-explain) or additional metric.

=== Sector LEAP considerations ===
Any qualitative, sector-specific guidance the issuer describes applying \
when running its own LEAP assessment (e.g. "prioritized upstream \
deforestation screening for this sector") -- not a metric value.

=== General requirements ===
Cross-cutting qualifiers that apply across all recommendations rather than \
being a recommendation themselves: overall materiality_approach and \
disclosure_scope, location_specificity (how precisely asset/activity \
locations are disclosed), cross_framework_links (e.g. references to TCFD, \
ESRS E4, GRI 101), time_horizons_defined (short/medium/long-term \
definitions used), and whether IPLC engagement is described.

General rules (apply throughout):
- Only report what is explicitly disclosed in the evidence. NEVER \
  estimate, infer, back into, or compute a figure or claim that isn't \
  itself stated.
- Every citation's `quote` must be an EXACT, VERBATIM substring copied \
  from the evidence block, tagged with the matching doc_id.
- confidence (0-1) should reflect your overall certainty across the whole \
  extraction."""

_SYSTEM_PROMPT = f"""\
You are a precise sustainability disclosure analyst extracting a company's \
TNFD (nature-related financial disclosure) reporting from its filings.

{TNFD_GUIDANCE}"""


class DisclosureDraft(BaseModel):
    recommendation_id: str
    disclosed: bool
    summary: str | None = None
    summary_citations: list[Citation] = Field(default_factory=list)
    materiality_basis: str = "unstated"
    disclosure_scope: str | None = None
    leap_stage_reference: str | None = None


class CoreGlobalMetricDraft(BaseModel):
    category: str
    metric_kind: str
    metric_name: str
    value: float | None = None
    unit: str | None = None
    baseline_year: int | None = None
    citations: list[Citation] = Field(default_factory=list)


class SectorMetricDraft(BaseModel):
    sector_name: str
    sector_guidance_status: str
    sector_guidance_version: str
    metric_no: str | None = None
    is_core_sector_metric: bool
    metric_name: str
    value: float | None = None
    unit: str | None = None
    baseline_year: int | None = None
    citations: list[Citation] = Field(default_factory=list)


class SectorLeapConsiderationDraft(BaseModel):
    sector_name: str
    leap_stage: str
    consideration: str
    citations: list[Citation] = Field(default_factory=list)


class GeneralRequirementsDraft(BaseModel):
    materiality_approach: str
    disclosure_scope: str
    location_specificity: str
    cross_framework_links: list[str] = Field(default_factory=list)
    time_horizons_defined: dict[str, str] = Field(default_factory=dict)
    iplc_engagement_described: bool
    citations: list[Citation] = Field(default_factory=list)


class TNFDExtractionDraft(BaseModel):
    disclosures: list[DisclosureDraft] = Field(default_factory=list)
    core_global_metrics: list[CoreGlobalMetricDraft] = Field(default_factory=list)
    sector_metrics: list[SectorMetricDraft] = Field(default_factory=list)
    sector_leap_considerations: list[SectorLeapConsiderationDraft] = Field(default_factory=list)
    general_requirements: GeneralRequirementsDraft | None = None
    confidence: float = Field(ge=0.0, le=1.0)


async def extract_tnfd(
    company_name: str, sector_name: str | None, chunks: list[DocumentChunk], llm: LLMClient
) -> tuple[TNFDExtractionDraft, LLMUsage]:
    sector_line = f"Primary sector: {sector_name}\n" if sector_name else ""
    prompt = f"Company: {company_name}\n{sector_line}\nEvidence:\n{format_evidence(chunks)}"
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=TNFDExtractionDraft)
