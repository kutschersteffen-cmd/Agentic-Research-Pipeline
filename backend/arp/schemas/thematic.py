from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, now_iso, new_id
from arp.schemas.exposure import IndirectExposureResult
from arp.schemas.revenue_exposure import RevenueExposureResult
from arp.schemas.standards import ActivityStandardsMapping


class ActivityDefinition(BaseModel):
    """A concrete, checkable business activity within a macro theme.

    Mirrors MSCI's plain-language in-scope/out-of-scope framing so the
    boundary of the theme is explicit and auditable rather than implicit
    in a keyword list.
    """

    activity_id: str = Field(default_factory=lambda: new_id("act"))
    name: str
    in_scope_description: str = Field(
        description="Plain-language description of what activity counts as in-scope."
    )
    out_of_scope_description: str = Field(
        description="Plain-language description of adjacent activities that do NOT count, to stop scope creep."
    )
    seed_keywords: list[str] = Field(
        default_factory=list, description="Seed keywords/bigrams for evidence-chunk retrieval (Sautner et al. style)."
    )
    core_isic_codes: list[str] = Field(
        default_factory=list,
        description=(
            "ISIC Rev.4 industry codes that make up this activity's core value-chain sectors, used for "
            "input-output-based indirect exposure scoring. Empty means the indirect-exposure tier is skipped "
            "for this activity. Populate via `arp theme classify-sectors` or supply by hand."
        ),
    )
    source_citation: Citation | None = Field(
        default=None,
        description="Verbatim, grounding-checked quote this activity was extracted from, when derived from an authority source.",
    )
    standards_mapping: ActivityStandardsMapping | None = Field(
        default=None,
        description="Cross-reference into NACE/NAICS/SIC/GICS, populated by `arp taxonomy map-standards`. None means mapping hasn't been run for this activity.",
    )


class ThemeDefinition(BaseModel):
    theme_id: str = Field(default_factory=lambda: new_id("theme"))
    name: str
    description: str
    activities: list[ActivityDefinition] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ExposureEstimate(StrEnum):
    PURE_PLAY = "pure_play"          # activity is the company's primary business
    SIGNIFICANT = "significant"       # material but not primary revenue/strategic exposure
    MINOR = "minor"                   # mentioned, minor or emerging exposure
    NONE = "none"                     # no credible exposure found


class MatchVerdict(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    UNCERTAIN = "uncertain"


class AgentOpinion(BaseModel):
    """Structured output of one side of the advocate/opposing debate."""

    stance: str
    rationale: str
    citations: list[Citation] = Field(default_factory=list)
    exposure_estimate: ExposureEstimate = ExposureEstimate.NONE


class CompanyMatch(BaseModel):
    company_id: str
    ticker: str | None = None
    name: str
    activity_id: str
    activity_name: str
    verdict: MatchVerdict
    exposure_estimate: ExposureEstimate
    confidence: float = Field(ge=0.0, le=1.0)
    advocate: AgentOpinion | None = Field(
        default=None, description="None when a hard revenue number (catalogue or extracted) resolved the match and the debate was skipped."
    )
    opposing: AgentOpinion | None = None
    adjudicator_rationale: str
    citations: list[Citation] = Field(default_factory=list, description="Adjudicator's final, grounding-checked citation set.")
    indirect_exposure: IndirectExposureResult | None = Field(
        default=None,
        description=(
            "Structural supply-chain exposure via input-output propagation, kept separate from exposure_estimate "
            "since it is a purely quantitative signal, not part of the Advocate/Opposing/Adjudicator judgment."
        ),
    )
    revenue_exposure: RevenueExposureResult | None = Field(
        default=None,
        description=(
            "Revenue/capex-based exposure resolved via the catalogue -> extraction -> qualitative-debate cascade "
            "(arp/research/revenue_exposure/). None when no revenue catalogue/mapping was supplied for this run."
        ),
    )
    flagged_for_review: bool = False
    generated_at: str = Field(default_factory=now_iso)


class ThematicUniverseResult(BaseModel):
    run_id: str
    theme: ThemeDefinition
    matches: list[CompanyMatch] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)
