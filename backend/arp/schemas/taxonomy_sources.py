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
    discovered_at: str = Field(default_factory=now_iso)


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
