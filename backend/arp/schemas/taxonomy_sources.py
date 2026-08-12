from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import new_id, now_iso


class SourceCandidateType(StrEnum):
    AUTHORITY = "authority"
    THEMATIC_FUND = "thematic_fund"


class SourceCandidate(BaseModel):
    """One result of the source-discovery research step -- a named external
    reference the user can choose to ground a taxonomy derivation in.
    Presented for selection, never used automatically.
    """

    candidate_id: str = Field(default_factory=lambda: new_id("src"))
    source_type: SourceCandidateType
    name: str
    url: str
    snippet: str = ""
    authority_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="LLM-assessed authoritativeness, set by rank_authority_sources."
    )
    authority_reasoning: str | None = Field(
        default=None, description="Why this source is (or isn't) a credible reference for the theme, in plain language."
    )
    discovered_at: str = Field(default_factory=now_iso)


class HoldingRow(BaseModel):
    """One row of a fund/index holdings export, weight included -- the
    input to overlap computation. See CorpusSnippet below for the lighter
    text-only projection of the same underlying rows used for taxonomy
    synthesis.
    """

    ticker: str
    name: str | None = None
    weight: float | None = Field(default=None, description="Portfolio weight as a fraction (0-1) or percent, as reported by the source file.")
    sector: str | None = None


class HoldingsOverlapResult(BaseModel):
    """Deterministic overlap analysis across two or more funds' holdings --
    no LLM involved, pure set/weight computation."""

    fund_names: list[str]
    core_tickers: list[str] = Field(description="Tickers present in every fund.")
    union_tickers: list[str] = Field(description="Tickers present in at least one fund.")
    ticker_presence: dict[str, list[str]] = Field(description="ticker -> list of fund names holding it.")
    pairwise_overlap_pct: dict[str, float] = Field(
        description="'fund_a|fund_b' -> weight-adjusted overlap percentage between that pair."
    )


class CorpusSourceType(StrEnum):
    EXTRACTION_ENGINE = "extraction_engine"
    NEWS = "news"
    TRANSCRIPT = "transcript"
    ETF_HOLDINGS = "etf_holdings"


class CorpusSnippet(BaseModel):
    """One piece of real-world text gathered as raw material for bottom-up
    taxonomy synthesis -- a company's extracted business-activity
    description, a news excerpt, a transcript passage, or a fund holding's
    metadata. Every synthesized activity should be traceable back to
    snippets like these, not invented independently of them.
    """

    text: str
    source_type: CorpusSourceType
    source_ref: str = Field(description="What this snippet came from: a company_id, a URL, a doc_id, a ticker.")
