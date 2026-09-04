from __future__ import annotations

from pydantic import BaseModel, Field


class ArbitrationContribution(BaseModel):
    """One signal that fed into an ArbitrationResult's composite score."""

    method: str = Field(
        description="qualitative_debate | revenue_catalogue | revenue_extracted | indirect | rd_intensity | news_mentions"
    )
    signal: float = Field(ge=0.0, le=1.0, description="This method's exposure signal, normalized to 0-1.")
    weight: float = Field(description="The weight this signal was given in the composite average.")
    detail: str = Field(default="", description="e.g. which of upstream/downstream was used for indirect, or a source note.")


class ArbitrationResult(BaseModel):
    """A weighted combination of whichever exposure signals were actually
    computed for one (company, activity) match -- an ADDITIONAL,
    clearly-labeled ranking score layered on top of exposure_estimate/
    revenue_exposure/indirect_exposure/rd_exposure, never blending into or
    overwriting them (see docs/METHODOLOGY.md's "two directions tracked
    separately" design). Computed by a pure function
    (arp.research.arbitration.compute_arbitration) with no LLM call --
    combination logic only, over signals other methods already produced.

    Weight/threshold defaults are documented, reasonable starting points,
    not empirically tuned against a labeled eval set -- see
    docs/METHODOLOGY.md's arbitration section.
    """

    composite_score: float = Field(ge=0.0, le=1.0, description="Weighted average of every included signal.")
    methods_disagree: bool = Field(
        description="True when included signals diverge by more than arbitration_disagreement_threshold -- "
        "surfaced explicitly (flagged_for_review), never silently averaged away."
    )
    disagreement_spread: float = Field(ge=0.0, le=1.0, description="max(signal) - min(signal) across included signals.")
    mid_band: bool = Field(
        description="True when composite_score falls within [arbitration_mid_band_low, arbitration_mid_band_high] "
        "-- routed for review the same way a per-method low-confidence result is, per the spec's original "
        "confidence-banding ask."
    )
    contributions: list[ArbitrationContribution] = Field(default_factory=list)
    rationale: str = Field(default="", description="Template-generated summary of what was combined and why.")
