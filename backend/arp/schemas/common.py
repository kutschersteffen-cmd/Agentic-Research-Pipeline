from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DocType(StrEnum):
    ANNUAL_REPORT_10K = "10-K"
    PROXY_DEF14A = "DEF-14A"
    SUSTAINABILITY_REPORT = "sustainability_report"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    PRODUCT_PAGE = "product_page"
    OTHER = "other"


class CompanyRef(BaseModel):
    """Minimal identity for a company, as supplied by the user's universe file."""

    company_id: str = Field(description="Stable identifier, e.g. ticker or internal ID.")
    name: str
    ticker: str | None = None
    website: str | None = Field(default=None, description="Known corporate/IR homepage, if supplied.")
    cik: str | None = Field(default=None, description="SEC CIK, if known (enables direct EDGAR lookup).")
    country: str | None = None
    sector: str | None = None
    isic_code: str | None = Field(
        default=None, description="ISIC Rev.4 industry code, if known (enables indirect/structural exposure scoring)."
    )


class SourceDocument(BaseModel):
    doc_id: str = Field(default_factory=lambda: new_id("doc"))
    company_id: str
    doc_type: DocType
    title: str
    source_url: str | None = None
    local_path: str | None = None
    fiscal_period: str | None = None
    fetched_at: str = Field(default_factory=now_iso)
    full_text: str = Field(repr=False)
    sha256: str | None = None
    page_breaks: list[int] = Field(
        default_factory=list,
        description=(
            "Char offsets in full_text where PDF page N+1 begins (page_breaks[i] = start of page i+1). "
            "Empty for non-paginated formats (html/txt/xlsx) or non-local sources."
        ),
    )


class DocumentChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: new_id("chk"))
    doc_id: str
    company_id: str
    doc_type: DocType
    section: str | None = None
    speaker: str | None = None
    text: str
    char_start: int
    char_end: int
    keyword_hits: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    doc_id: str
    doc_type: DocType
    quote: str = Field(description="Verbatim substring copied from the source chunk. Must be checkable.")
    location: str | None = Field(default=None, description="Section/page/speaker-turn hint, as reported by the LLM.")
    grounded: bool = Field(default=False, description="Set by the programmatic grounding checker, not the LLM.")
    page: int | None = Field(
        default=None,
        description="1-indexed PDF page, resolved programmatically from the verified match position -- never LLM-reported. Set only when grounded.",
    )
    sheet: str | None = Field(
        default=None, description="xlsx sheet name, resolved the same way as `page`. Set only when grounded."
    )
    company_id: str | None = Field(
        default=None, description="Resolved from the cited SourceDocument by grounding, so a citation is self-contained for building a 'view source' link."
    )
    source_filename: str | None = Field(default=None, description="On-disk filename, resolved by grounding.")


class ProvenanceInfo(BaseModel):
    """Which model and which system-prompt version produced a persisted
    extraction/verification, so a later prompt or model change is
    detectable against previously persisted output instead of silently
    mixing results from different pipeline versions. `*_prompt_version` is
    a short hash of the agent's system prompt text (see
    `LangChainAnthropicClient.complete_structured`), not a manually
    maintained version number -- it changes automatically the moment the
    prompt does, so it can't go stale the way a hand-bumped constant would.
    """

    extractor_model: str | None = None
    extractor_prompt_version: str | None = None
    verifier_model: str | None = None
    verifier_prompt_version: str | None = None


class RunManifest(BaseModel):
    run_id: str
    run_type: str  # "theme" | "extraction" | "discovery"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    status: JobStatus = JobStatus.PENDING
    params: dict = Field(default_factory=dict)
    company_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    review_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model: str | None = None
    verifier_model: str | None = Field(
        default=None, description="Model used for the independent Verifier/Kritiker pass, when this run type has one."
    )
    error: str | None = None
    cancel_requested: bool = Field(
        default=False, description="Set by POST /api/runs/{id}/cancel; checked cooperatively before each new item starts. In-flight items still finish."
    )
