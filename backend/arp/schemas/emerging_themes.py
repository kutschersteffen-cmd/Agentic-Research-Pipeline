from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import new_id, now_iso


class MentionSourceType(StrEnum):
    EDGAR_FTS = "edgar_fts"  # SEC EDGAR full-text search API (efts.sec.gov)
    GDELT = "gdelt"  # GDELT DOC 2.0 API
    REGULATORY_RSS = "regulatory_rss"  # Fed/ECB/BoE/FCA press releases + SEC rule releases


class RawMention(BaseModel):
    """One raw hit from an Ingest-layer source -- a GDELT article, an EDGAR
    full-text-search filing excerpt, or a regulatory RSS item. Deliberately
    not a `SourceDocument`: these are short, ephemeral snippets fetched for
    discovery, not full disclosure documents that go through the Extraction
    Engine's chunking/document-store machinery.
    """

    mention_id: str = Field(default_factory=lambda: new_id("mention"))
    source_type: MentionSourceType
    title: str
    text: str = Field(description="Snippet/summary text -- headline+snippet, filing excerpt, or RSS summary.")
    url: str
    raw_entity_names: list[str] = Field(
        default_factory=list, description="Company/issuer names as reported by the source itself, if any (e.g. GDELT entity tags, an EDGAR filer name)."
    )
    published_at: str | None = Field(
        default=None,
        description="True publish time when the source reports one (EDGAR filing date, RSS pubDate); None when "
        "it doesn't (GDELT's seendate is closer to crawl time). Callers needing a bucket to sort into should use "
        "fetched_at and the run's own period cadence rather than assume this is always populated.",
    )
    fetched_at: str = Field(default_factory=now_iso)


class ExtractedTag(BaseModel):
    """One Extract-layer output: a short topic label plus a claim, both
    traceable to a verbatim, grounding-checked quote from the mention that
    produced them -- same discipline as `portfolio/news/classifier.py`,
    generalized beyond climate/ESG controversy screening.
    """

    tag_id: str = Field(default_factory=lambda: new_id("tag"))
    mention_id: str
    label: str = Field(description="Short 2-5 word topic label, e.g. 'solid-state battery commercialization'.")
    claim: str = Field(description="The specific factual claim this mention makes, in one sentence.")
    entity_names: list[str] = Field(default_factory=list, description="Company/issuer names the LLM identified in the claim.")
    quote: str = Field(description="Verbatim excerpt from the mention's own text backing label+claim.")
    grounded: bool = Field(default=False, description="Set by grounding.is_grounded, never the LLM's self-report.")


class LineageTransition(StrEnum):
    BIRTH = "birth"  # no lineage edge back to the prior period -- the only transition eligible to become a candidate
    GROWTH = "growth"  # continues a prior-period cluster, larger
    SPLIT = "split"  # a prior-period cluster fragmented into this one plus others
    MERGE = "merge"  # multiple prior-period clusters converged into this one
    DEATH = "death"  # a prior-period cluster with no successor this period (recorded for the history, not emitted as a candidate)


class TopicCluster(BaseModel):
    """One Detect-layer output for a single run/period: a group of
    `ExtractedTag`s judged to be about the same underlying topic by
    embedding similarity, stable across reseeded clustering reruns.
    """

    cluster_id: str = Field(default_factory=lambda: new_id("cluster"))
    period: str = Field(description="The run's period key (e.g. the run's ISO week), for lineage linking across runs.")
    representative_label: str = Field(description="Top c-TF-IDF term(s) for this cluster, used for labeling and lineage matching.")
    member_tag_ids: list[str] = Field(default_factory=list)
    member_labels: list[str] = Field(default_factory=list)
    company_ids: list[str] = Field(default_factory=list, description="Distinct companies resolved from this cluster's member mentions.")
    mention_count: int = 0
    source_types: list[MentionSourceType] = Field(default_factory=list)
    centroid: list[float] = Field(default_factory=list, description="Mean embedding vector of member tags, for lineage/centroid-similarity linking.")
    stability_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Fraction of reseeded clustering reruns in which this cluster's membership held together.")


class LineageEvent(BaseModel):
    cluster_id: str
    period: str
    transition: LineageTransition
    prior_cluster_ids: list[str] = Field(default_factory=list, description="Empty for BIRTH and (trivially) DEATH.")
    overlap_score: float = Field(default=0.0, description="Member-overlap/centroid-similarity score driving the classification.")


class MentionCitation(BaseModel):
    """A corroborating-source citation for an EmergingThemeCandidate --
    lighter than `schemas/common.py::Citation` deliberately: that type is
    bound to a `SourceDocument` resolved through the document store's
    grounding.ground_citations, which these ephemeral, non-stored mentions
    never go through. Grounding here is the same `grounding.is_grounded`
    check, just applied directly against the mention's own text.
    """

    mention_id: str
    source_type: MentionSourceType
    url: str
    quote: str
    grounded: bool = False


class CandidateStatus(StrEnum):
    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class EmergingThemeCandidate(BaseModel):
    """The Output-layer schema -- the fixed handoff contract into Tool 1
    (the Thematic Universe Builder), field-for-field per the source
    development plan's Section "A fixed schema is the handoff contract
    with Tool 1"."""

    theme_id: str = Field(default_factory=lambda: new_id("emergtheme"))
    theme_name: str
    description: str = ""
    first_detected_date: str = Field(description="Date this cluster's underlying signal was first classified as a BIRTH (no lineage back).")
    signal_velocity: float = Field(description="This period's mention count for the cluster; velocity vs. baseline is implicit in it being a BIRTH.")
    corroborating_sources: list[MentionCitation] = Field(default_factory=list)
    candidate_sectors_companies: list[str] = Field(default_factory=list, description="Resolved company_ids, for analyst orientation -- not a substitute for Tool 1's universe construction.")
    rationale: str = Field(default="", description="Grounded narrative explanation, source-linked.")
    economic_rationale: str = Field(
        default="", description="Why this pattern would move markets, not just that mention volume is rising -- required, not optional, per the source plan's Safeguards section."
    )
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Phase 1 interim proxy: the cluster's HDBSCAN stability_score. Superseded by a real Bayesian "
        "(Isolation-Forest-prior, Beta-Bernoulli-updated) posterior in Phase 2 -- see docs.",
    )
    status: CandidateStatus = CandidateStatus.CANDIDATE
    promoted_to_taxonomy_id: str | None = None
    promoted_to_taxonomy_version: int | None = None
    cluster_id: str
    run_id: str
    created_at: str = Field(default_factory=now_iso)


class EmergingThemesScheduleConfig(BaseModel):
    """Mirrors `schemas/discovery.py::DiscoveryScheduleConfig`."""

    enabled: bool = False
    interval_hours: float = 168.0
    universe_path: str | None = None
    last_run_id: str | None = None
    next_run_at: str | None = None
