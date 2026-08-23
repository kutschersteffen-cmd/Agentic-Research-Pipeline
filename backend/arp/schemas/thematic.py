from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from arp.schemas.arbitration import ArbitrationResult
from arp.schemas.common import Citation, now_iso, new_id
from arp.schemas.exposure import IndirectExposureResult
from arp.schemas.rd_exposure import RDExposureResult
from arp.schemas.revenue_exposure import RevenueExposureResult
from arp.schemas.standards import ActivityStandardsMapping

_MIN_APPROVED_RATIONALE_WORDS = 15


class ActivityTier(StrEnum):
    """Where an activity sits in the theme's value chain -- mirrors the
    core/enabling/critical-input tiering used by supply-chain-anchored
    taxonomy construction (see docs/METHODOLOGY.md's indirect-exposure
    discussion). Most activities are LLM-drafted directly from the theme
    description and are the theme's own core business, hence the CORE
    default; ENABLING/CRITICAL_INPUT are for activities surfaced by
    supply-chain analysis or an authority source rather than invented
    freeform.
    """

    CORE = "core"
    ENABLING = "enabling"
    CRITICAL_INPUT = "critical_input"


class LifecycleStage(StrEnum):
    """Where an activity sits on the technology/commercialization curve.
    Ideation/innovation-stage activities have little to no revenue yet and
    need R&D- or patent-based exposure scoring instead of revenue-percentage
    scoring; commercialization/mature activities are revenue-scoreable
    today. None (the field's default) means not yet classified.
    """

    IDEATION = "ideation"
    INNOVATION = "innovation"
    COMMERCIALIZATION = "commercialization"
    MATURE = "mature"


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
    tier: ActivityTier = Field(
        default=ActivityTier.CORE,
        description="core (the theme's own activities), enabling (supports core activities without being the "
        "theme itself), or critical_input (a scarce/bottleneck input core activities depend on).",
    )
    lifecycle_stage: LifecycleStage | None = Field(
        default=None, description="ideation/innovation/commercialization/mature; None means not yet classified."
    )
    criticality_flag: bool = Field(
        default=False,
        description="Set when this activity represents a scarce or geopolitically concentrated input whose "
        "importance a pure input-output linkage-strength ranking would understate (e.g. a USGS/IEA-flagged "
        "critical mineral). Populated by the criticality overlay, not by hand.",
    )
    human_approved: bool = Field(
        default=False,
        description="Per-activity curation sign-off, distinct from the taxonomy-level Taxonomy.status/"
        "ratified_by -- lets a reviewer approve individual activities within an otherwise-draft taxonomy. "
        "Requires a source_citation and a substantive in_scope_description; see the validator below.",
    )

    @model_validator(mode="after")
    def _approved_activities_must_be_sourced(self) -> "ActivityDefinition":
        """An activity marked human_approved is asserting 'a person checked
        this and it's traceable to a specific disclosed fact' -- so it must
        actually carry a source and a real rationale, not just a label.
        Unapproved (draft) activities are unaffected, since most activities
        start life as an LLM's freeform or industry-anchored draft with no
        source_citation yet.
        """
        if not self.human_approved:
            return self
        if self.source_citation is None or not self.source_citation.quote.strip():
            raise ValueError(
                f"Activity '{self.name}' cannot be human_approved without a source_citation carrying a real quote."
            )
        if len(self.in_scope_description.split()) < _MIN_APPROVED_RATIONALE_WORDS:
            raise ValueError(
                f"Activity '{self.name}' cannot be human_approved with an in_scope_description under "
                f"{_MIN_APPROVED_RATIONALE_WORDS} words -- that isn't a real rationale, just a label."
            )
        return self


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
    rd_exposure: RDExposureResult | None = Field(
        default=None,
        description=(
            "R&D-spend-intensity + news-mention exposure (Method C, arp/research/rd_exposure/), computed only "
            "for pre-revenue/emerging activities (lifecycle_stage ideation/innovation) when the tier is enabled "
            "for this run. None otherwise -- kept separate from revenue_exposure/indirect_exposure, never "
            "blended into exposure_estimate."
        ),
    )
    arbitration: ArbitrationResult | None = Field(
        default=None,
        description=(
            "Weighted cross-method composite score (Step 4, arp/research/arbitration.py), combining whichever "
            "of exposure_estimate/revenue_exposure/indirect_exposure/rd_exposure were actually computed. An "
            "ADDITIONAL ranking signal -- never blended into or overwriting those fields. Always populated by "
            "match_graph.py (no opt-in flag; it's free, no LLM call)."
        ),
    )
    flagged_for_review: bool = False
    generated_at: str = Field(default_factory=now_iso)


class ThematicUniverseResult(BaseModel):
    run_id: str
    theme: ThemeDefinition
    matches: list[CompanyMatch] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)
