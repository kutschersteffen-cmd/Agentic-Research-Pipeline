from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import new_id, now_iso
from arp.schemas.thematic import ThemeDefinition


class DerivationMethod(StrEnum):
    LLM_DRAFT = "llm_draft"  # LLM brainstorm from the theme name/description alone
    INDUSTRY_ANCHORED = "industry_anchored"  # LLM draft grounded against a real industry classification list
    AUTHORITY_SOURCE = "authority_source"  # grounded against a user-selected authoritative document (IEA, EU taxonomy, a standards body, ...)
    ETF_INDEX_HOLDINGS = "etf_index_holdings"  # synthesized bottom-up from an existing thematic ETF/index's holdings
    NEWS_TRANSCRIPT_MINING = "news_transcript_mining"  # synthesized bottom-up from news search + earnings-call transcript mining
    EMPIRICAL = "empirical"  # synthesized bottom-up from the Extraction Engine's readings of a sample company universe
    EMERGING_SIGNAL_DISCOVERY = "emerging_signal_discovery"  # promoted from a Tool 0 Emerging Themes Scanner candidate (see arp/emerging_themes/)
    MERGED = "merged"  # consolidated from two or more existing taxonomies
    MANUAL = "manual"  # hand-authored, no LLM involvement


class TaxonomyStatus(StrEnum):
    DRAFT = "draft"
    RATIFIED = "ratified"


class Taxonomy(BaseModel):
    """A named, versioned thematic taxonomy.

    A ThemeDefinition on its own is a one-off run parameter -- drafted,
    edited, used, forgotten. A Taxonomy is what that definition becomes
    once it's worth reusing across many runs: it carries a stable
    `taxonomy_id` across versions, records how each version was derived
    (`derivation_method`, `source_notes`) so the boundary decisions are
    auditable later, and supports an explicit ratification step so a
    domain expert's sign-off (the MSCI/GARI pattern) is a recorded fact,
    not an implicit assumption.
    """

    taxonomy_id: str = Field(default_factory=lambda: new_id("tax"))
    name: str
    version: int = 1
    theme: ThemeDefinition
    derivation_method: DerivationMethod
    source_notes: str = Field(
        default="", description="What grounded this version: prompt inputs, anchor list used, edits made, etc."
    )
    status: TaxonomyStatus = TaxonomyStatus.DRAFT
    ratified_by: str | None = None
    ratified_at: str | None = None
    based_on_version: int | None = Field(
        default=None, description="The prior version this one edits or supersedes, if any."
    )
    created_at: str = Field(default_factory=now_iso)


class TaxonomyRef(BaseModel):
    """Points at one specific version of a saved taxonomy."""

    taxonomy_id: str
    version: int | None = Field(default=None, description="None means the latest version.")


class ActivityDuplicateCandidate(BaseModel):
    activity_a_id: str
    activity_b_id: str
    similarity_note: str = Field(description="Why these two activities from different taxonomies look like the same thing.")


class TaxonomyComparison(BaseModel):
    """A structured diff between two taxonomies' activity sets."""

    unique_to_a: list[str] = Field(description="activity_ids present only in taxonomy A.")
    unique_to_b: list[str] = Field(description="activity_ids present only in taxonomy B.")
    likely_duplicates: list[ActivityDuplicateCandidate] = Field(default_factory=list)
