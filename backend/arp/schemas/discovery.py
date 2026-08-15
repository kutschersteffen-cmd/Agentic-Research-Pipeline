from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import DocType, now_iso, new_id


class DocumentEventType(StrEnum):
    NEW_DOCUMENT = "new_document"
    UPDATED_DOCUMENT = "updated_document"


class DiscoveredDocument(BaseModel):
    company_id: str
    doc_type: DocType
    url: str
    local_path: str | None = None
    sha256: str | None = None
    http_last_modified: str | None = None
    http_etag: str | None = None
    discovered_at: str = Field(default_factory=now_iso)


class DocumentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: DocumentEventType
    company_id: str
    company_name: str | None = None
    document: DiscoveredDocument
    created_at: str = Field(default_factory=now_iso)


class DiscoveryRunParams(BaseModel):
    universe_source: str = Field(description="Path or identifier of the company universe used for this run.")
    doc_types: list[DocType] = Field(default_factory=list, description="Empty = all supported types.")
    triggered_by: str = Field(default="manual", description="'manual' or 'schedule'.")


class DiscoveryCompanyResult(BaseModel):
    company_id: str
    name: str
    homepage_used: str | None = None
    homepage_unreachable: bool = Field(
        default=False,
        description=(
            "True when a homepage/IR URL was known but the crawl's root page couldn't be fetched (network "
            "failure, 4xx/5xx) -- distinct from homepage_used=None (no URL known at all) and from a normal "
            "empty result (fetched fine, nothing matched). Never silently reported as '0 documents found'."
        ),
    )
    crawl_error: str | None = Field(default=None, description="Why the homepage was unreachable, when homepage_unreachable is True.")
    documents_found: list[DiscoveredDocument] = Field(default_factory=list)
    new_events: list[DocumentEvent] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)


class DiscoveryScheduleConfig(BaseModel):
    enabled: bool = False
    interval_hours: float = 24.0
    universe_path: str | None = None
    doc_types: list[DocType] = Field(default_factory=list)
    last_run_id: str | None = None
    next_run_at: str | None = None


# --- Agentic company identity resolution -----------------------------------
#
# Given only a company name (no website/cik), resolves which real company it
# is via a propose -> resolve -> challenge -> adjudicate pipeline (see
# arp/discovery/identity_agents.py and identity_graph.py), mirroring the
# Advocate/Opposing/Adjudicator triad in arp/research/matcher_agents.py.
# Kept in its own run type (arp/discovery/identity_pipeline.py), separate
# from the discovery crawl pipeline -- see that module's docstring.


class IdentityVerdict(StrEnum):
    RESOLVED = "resolved"
    UNCERTAIN = "uncertain"
    UNRESOLVED = "unresolved"


class IdentityCandidate(BaseModel):
    """Structured output of the propose step -- the only place the LLM
    invents anything; it never touches the network itself."""

    legal_name_guesses: list[str] = Field(default_factory=list)
    ticker_guess: str | None = None
    search_queries: list[str] = Field(default_factory=list, description="2-3 web search queries to try.")


class EdgarNameMatch(BaseModel):
    """One row from EdgarDocumentSource.search_by_name -- a real,
    deterministic lookup against SEC's own ticker/CIK/company-title map,
    not an LLM guess."""

    ticker: str
    cik: str
    title: str


class WebSearchHit(BaseModel):
    """A raw web search result, kept as-is (title/url/snippet) rather than
    LLM-summarized, so the challenge/adjudicate steps reason over the real
    signal instead of a paraphrase of it."""

    title: str
    url: str
    snippet: str = ""


class IdentitySignals(BaseModel):
    """Deterministic (non-LLM) resolution signals gathered from real
    lookups for the challenge/adjudicate steps to reason over."""

    edgar_matches: list[EdgarNameMatch] = Field(default_factory=list)
    search_results: list[WebSearchHit] = Field(default_factory=list)


class IdentityChallenge(BaseModel):
    """Structured output of the adversarial challenge step."""

    concerns: list[str] = Field(
        default_factory=list, description="Specific, concrete reasons to doubt the candidate identity, if any."
    )
    lean: IdentityVerdict = Field(description="The challenger's own read of the verdict, before adjudication.")


class IdentityAdjudication(BaseModel):
    """Structured output of the final adjudicate step. resolved_website/
    resolved_cik are checked against IdentitySignals by code (never
    trusted from the LLM's self-report alone) before being accepted --
    see arp/discovery/identity_graph.py."""

    verdict: IdentityVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    resolved_website: str | None = None
    resolved_cik: str | None = None
    rationale: str


class IdentityResolutionResult(BaseModel):
    """Persisted result of resolving one company: written to the identity
    run's results.jsonl, and -- when flagged_for_review -- also queued via
    arp.orchestration.review_queue.queue_for_review."""

    company_id: str
    input_name: str
    verdict: IdentityVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    resolved_website: str | None = None
    resolved_cik: str | None = None
    signals: IdentitySignals
    rationale: str
    flagged_for_review: bool = False
    generated_at: str = Field(default_factory=now_iso)
