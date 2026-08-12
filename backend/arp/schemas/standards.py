from __future__ import annotations

from pydantic import BaseModel, Field


class StandardCodeMatch(BaseModel):
    """One code from an external classification standard, derived via a
    deterministic crosswalk from an activity's core_isic_codes -- never
    LLM-guessed, since these are large fixed code lists a model can't be
    trusted to recall exactly."""

    code: str
    label: str = ""


class GicsMatch(BaseModel):
    """One GICS entry an activity was classified against. Unlike NACE/
    NAICS/SIC, there is no public official ISIC->GICS correspondence table,
    so this is LLM-classified against a fixed reference list -- the
    rationale is kept so the judgment is reviewable, the same discipline as
    the core-ISIC classifier."""

    code: str
    label: str = ""
    rationale: str = ""


class ActivityStandardsMapping(BaseModel):
    """An activity's cross-reference into external industry classification
    standards, derived from its core_isic_codes."""

    nace_codes: list[StandardCodeMatch] = Field(default_factory=list)
    naics_codes: list[StandardCodeMatch] = Field(default_factory=list)
    sic_codes: list[StandardCodeMatch] = Field(default_factory=list)
    gics: list[GicsMatch] = Field(default_factory=list)
    unmapped_isic_codes: list[str] = Field(
        default_factory=list,
        description="core_isic_codes with no entry in any loaded crosswalk table -- shown for transparency rather than silently dropped.",
    )
