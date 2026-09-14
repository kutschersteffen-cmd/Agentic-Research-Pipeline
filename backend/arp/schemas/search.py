from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SearchResultType(StrEnum):
    COMPANY = "company"
    DOCUMENT = "document"
    TAXONOMY = "taxonomy"


class SearchHit(BaseModel):
    type: SearchResultType
    id: str = Field(description="company_id / doc_id / taxonomy entry_id, depending on `type`.")
    title: str
    snippet: str = Field(default="", description="Plain-text excerpt from OpenSearch's highlight response (tags stripped server-side).")
    score: float = Field(description="Raw OpenSearch _score for this hit, not normalized across types.")
    company_id: str | None = Field(default=None, description="Owning company, when the hit has one -- always set for company/document hits, None for taxonomy hits.")
    link: str | None = Field(default=None, description="Best-effort relative API path to view/pivot into this result; None when no such endpoint exists yet.")


class SearchResponse(BaseModel):
    query: str
    total: int = Field(description="Number of hits returned across all queried types (not each index's total-match count).")
    hits: list[SearchHit] = Field(default_factory=list)
