"""Theme research (dossier step 3): a source plan the owner approves, then a note written only from those sources.

One JSON record per dossier under `runs_dir/_dossiers/research/`, holding rounds of plan -> approval -> note ->
approval (docs/superpowers/specs/2026-10-25-theme-research-note-design.md). Uploaded source files live in
`research/<dossier_id>/<source_id>/`, so a source carried into a new round keeps its file."""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends
from pydantic import BaseModel, Field

from arp.api.deps import get_run_store, settings_dep
from arp.config import Settings
from arp.discovery.site_finder import SearchResult, WebSearchClient
from arp.grounding import ground_citations
from arp.ingestion.html_text import extract_html_text
from arp.llm.base import LLMClient
from arp.orchestration.jobs import run_alive
from arp.research.taxonomy_sources.fetch import _MAX_CHARS, fetch_source_text_or_empty
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.taxonomy import Taxonomy
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.locks import KeyedLock
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

logger = logging.getLogger(__name__)

Category = Literal["intergovernmental", "official_statistics", "central_bank_regulator", "academic"]
SECTIONS = ("risks", "opportunities", "financial_relevance", "growth_potential", "transmission_channels")
UPLOAD_SUFFIXES = (".pdf", ".html", ".htm", ".txt")
MAX_SOURCES = 12
_QUERY_TEMPLATES = (
    "{theme} IEA report",
    "{theme} OECD",
    "{theme} IMF World Bank",
    "{theme} official statistics",
    "{theme} central bank",
    "{theme} regulator",
    "{theme} journal article",
)


class SourceFile(BaseModel):
    filename: str
    uploaded_by: str
    uploaded_at: str


class ResearchSource(BaseModel):
    source_id: str = Field(default_factory=lambda: f"src_{uuid4().hex[:12]}")
    title: str
    publisher: str
    url: str
    category: Category
    why: str
    how: str
    added_by: str
    file: SourceFile | None = None


class NoteCitation(BaseModel):
    source_id: str
    quote: str
    page: int | None = None


class NoteItem(BaseModel):
    item_id: str = Field(default_factory=lambda: f"itm_{uuid4().hex[:12]}")
    title: str
    text: str
    channel: Literal["economic", "financial"] | None = None
    citations: list[NoteCitation]


class NoteSections(BaseModel):
    risks: list[NoteItem] = []
    opportunities: list[NoteItem] = []
    financial_relevance: list[NoteItem] = []
    growth_potential: list[NoteItem] = []
    transmission_channels: list[NoteItem] = []


class UnreadSource(BaseModel):
    source_id: str
    reason: Literal["fetch failed", "no text extracted"]


class ResearchNote(BaseModel):
    status: Literal["writing", "write_failed", "written", "approved", "rejected"] = "writing"
    sections: NoteSections = NoteSections()
    unread_sources: list[UnreadSource] = []
    dropped_items: int = 0
    written_at: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    reject_reason: str | None = None
    error: str | None = None


class ResearchRound(BaseModel):
    round: int
    taxonomy_version: int
    plan_status: Literal["proposing", "proposal_failed", "proposed", "approved"] = "proposing"
    proposal_run_id: str | None = None
    plan_approved_by: str | None = None
    plan_approved_at: str | None = None
    sources: list[ResearchSource] = []
    note: ResearchNote | None = None
    note_run_id: str | None = None


class ResearchRecord(BaseModel):
    dossier_id: str
    rounds: list[ResearchRound] = []

    @property
    def latest(self) -> ResearchRound | None:
        return self.rounds[-1] if self.rounds else None

    @property
    def approved_round(self) -> int | None:
        return max((r.round for r in self.rounds if r.note and r.note.status == "approved"), default=None)


# The model's outputs. Their class names are the stand-in contract (model/<ClassName>.json): keep them.
class _ClassifiedSource(BaseModel):
    url: str
    category: Category | Literal["none"]
    publisher: str = ""
    why: str = ""
    how: str = ""


class SourceClassificationDraft(BaseModel):
    sources: list[_ClassifiedSource] = []


class _DraftCitation(BaseModel):
    source_id: str
    quote: str


class _DraftItem(BaseModel):
    title: str
    text: str
    channel: Literal["economic", "financial"] | None = None
    citations: list[_DraftCitation] = []


class ResearchNoteDraft(BaseModel):
    risks: list[_DraftItem] = []
    opportunities: list[_DraftItem] = []
    financial_relevance: list[_DraftItem] = []
    growth_potential: list[_DraftItem] = []
    transmission_channels: list[_DraftItem] = []


class Refused(Exception):
    """A refused transition; the API answers it with `status` and the message as `detail`."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


class ResearchStore:
    """`alive(run_id)` says whether a run still has a worker; a round whose run died reads as failed (`recover`)."""

    def __init__(self, research_dir: Path, alive: Callable[[str | None], bool] = lambda _run_id: True) -> None:
        self.research_dir, self.alive = research_dir, alive
        self._lock = KeyedLock(lambda key: research_dir / f".{key}.lock")

    def _key(self, dossier_id: str) -> str:
        return safe_id(dossier_id, label="dossier id")

    def get(self, dossier_id: str) -> ResearchRecord:
        try:
            path = self.research_dir / f"{self._key(dossier_id)}.json"
        except UnsafeIdentifierError:
            return ResearchRecord(dossier_id=dossier_id)
        if not path.is_file():
            return ResearchRecord(dossier_id=dossier_id)
        return recover(ResearchRecord.model_validate_json(read_text_utf8(path)), self.alive)

    def update(self, dossier_id: str, fn: Callable[[ResearchRecord], object]):
        """Runs `fn` on the record under the dossier's lock and saves it, unless `fn` raises. Returns `fn`'s result."""
        key = self._key(dossier_id)
        self.research_dir.mkdir(parents=True, exist_ok=True)
        with self._lock.acquire(key):
            record = self.get(dossier_id)
            result = fn(record)
            atomic_write_text(self.research_dir / f"{key}.json", record.model_dump_json(indent=2))
            return result

    def _file_path(self, dossier_id: str, source_id: str, file: SourceFile) -> Path:
        # One folder per upload: a replacement in a later round must not delete the file an earlier round's note read.
        upload = re.sub(r"[^0-9A-Za-z]", "", file.uploaded_at)
        return self.research_dir / self._key(dossier_id) / safe_id(source_id, label="source id") / upload / file.filename

    def file_path(self, dossier_id: str, source: ResearchSource) -> Path | None:
        return self._file_path(dossier_id, source.source_id, source.file) if source.file else None

    def save_file(self, dossier_id: str, source_id: str, file: SourceFile, data: bytes) -> None:
        path = self._file_path(dossier_id, source_id, file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def get_research_store(settings: Settings = Depends(settings_dep), run_store: RunStore = Depends(get_run_store)) -> ResearchStore:
    return ResearchStore(settings.runs_dir / "_dossiers" / "research", lambda run_id: run_alive(run_store, run_id))


def recover(record: ResearchRecord, alive: Callable[[str | None], bool]) -> ResearchRecord:
    """A proposal or note whose run no longer has a worker (a restart, a crash before it recorded its outcome) reads
    as failed, so the existing retry paths open again. Derived on read; saved with the next write."""
    r = record.latest
    if r and r.plan_status == "proposing" and not alive(r.proposal_run_id):
        r.plan_status = "proposal_failed"
    if r and r.note and r.note.status == "writing" and not alive(r.note_run_id):
        r.note.status, r.note.error = "write_failed", "the run stopped before the note was written"
    return record


# --- transitions (each runs inside ResearchStore.update) ---

def open_round(record: ResearchRecord) -> ResearchRound:
    """The latest round when it is proposed, else Refused."""
    r = record.latest
    if r is None or r.plan_status != "proposed":
        raise Refused(409, "the source plan is not open for edits")
    return r


def start_proposal(record: ResearchRecord, taxonomy_version: int, run_id: str) -> ResearchRound:
    r = record.latest
    if r is not None and r.plan_status == "proposal_failed":
        r.plan_status, r.proposal_run_id, r.taxonomy_version = "proposing", run_id, taxonomy_version
        return r
    if r is not None and not (r.note and r.note.status == "approved"):
        raise Refused(409, f"round {r.round} is in progress")
    carried = [s.model_copy() for s in r.sources] if r else []
    new = ResearchRound(round=len(record.rounds) + 1, taxonomy_version=taxonomy_version, proposal_run_id=run_id,
                        sources=carried)
    record.rounds.append(new)
    return new


def start_note(record: ResearchRecord, run_id: str) -> None:
    r = record.latest
    if r is None or r.plan_status != "approved":
        raise Refused(409, "approve the source plan first")
    if r.note and r.note.status not in ("write_failed", "rejected"):
        raise Refused(409, "the note is already written")
    r.note, r.note_run_id = ResearchNote(), run_id


def written_note(record: ResearchRecord) -> ResearchRound:
    r = record.latest
    if r is None or r.note is None or r.note.status != "written":
        raise Refused(409, "there is no written note")
    return r


# --- step 1: propose sources ---

_CLASSIFY_SYSTEM = """\
You sort web search results for a research note on an investment theme. Classify each result by its publisher \
into exactly one category:
- intergovernmental: an intergovernmental agency (e.g. IEA, OECD, IMF, World Bank, UN bodies, IPCC, BIS);
- official_statistics: a government department or official statistics office (e.g. Eurostat, national \
statistics offices, ministries);
- central_bank_regulator: a central bank or a financial or sector regulator;
- academic: peer-reviewed academic research or a university research publication;
- none: anything else. Think tanks, non-profit initiatives, industry bodies, consultancies, media, company and \
fund publications are always none, as is a result whose publisher you cannot tell.
For every result not classified none, give the publisher's name, `why`: one sentence on why the source is \
relevant to the theme, and `how`: which note sections it can feed (risks, opportunities, financial relevance, \
growth potential, transmission channels) and what to take from it. Answer with one entry per result, using the \
result's exact URL."""


def search_queries(theme_name: str) -> list[str]:
    return [t.format(theme=theme_name) for t in _QUERY_TEMPLATES]


async def search_results(theme_name: str, search_client: WebSearchClient) -> list[SearchResult]:
    """Every query's results in query order, de-duplicated by URL. Raises when every query failed."""
    results: dict[str, SearchResult] = {}
    errors: list[Exception] = []
    queries = search_queries(theme_name)
    for query in queries:
        try:
            found = await search_client.search(query, max_results=5)
        except Exception as exc:  # noqa: BLE001 - one bad query must not sink the others
            errors.append(exc)
            continue
        for r in found:
            results.setdefault(r.url, r)
    if len(errors) == len(queries):
        raise RuntimeError(f"web search failed: {errors[0]}")
    return list(results.values())


async def propose_sources(taxonomy: Taxonomy, search_client: WebSearchClient, llm: LLMClient) -> list[ResearchSource]:
    """The first MAX_SOURCES search results the model puts in one of the four categories, in search order."""
    results = await search_results(taxonomy.theme.name, search_client)
    if not results:
        return []
    listing = "\n\n".join(f"URL: {r.url}\nTitle: {r.title}\nSnippet: {r.snippet or '(none)'}" for r in results)
    prompt = f"Theme: {taxonomy.theme.name}\nDescription: {taxonomy.theme.description}\n\nSearch results:\n{listing}"
    draft, _ = await llm.complete_structured(system=_CLASSIFY_SYSTEM, prompt=prompt, output_model=SourceClassificationDraft)
    by_url = {s.url: s for s in draft.sources}
    kept = []
    for r in results:
        c = by_url.get(r.url)
        if c is None or c.category == "none" or not (c.why.strip() and c.how.strip()):
            continue
        kept.append(ResearchSource(title=r.title, publisher=c.publisher.strip() or r.title, url=r.url,
                                   category=c.category, why=c.why.strip(), how=c.how.strip(), added_by="model"))
    return kept[:MAX_SOURCES]


def merge_proposals(r: ResearchRound, proposed: list[ResearchSource]) -> None:
    seen = {s.url for s in r.sources}
    r.sources += [s for s in proposed if s.url not in seen]
    r.plan_status = "proposed"


# --- step 3: write the note ---

_NOTE_SYSTEM = """\
You write a fact-based research note on an investment theme, using ONLY the source texts given. Each source is \
labelled with its source_id. Write items in five sections: risks, opportunities, financial_relevance (why the \
theme matters financially for companies), growth_potential, and transmission_channels (the economic or financial \
channels through which the theme reaches company results; set `channel` to "economic" or "financial" for these, \
null elsewhere). Rules:
- Neutral, fact-based statements. No promotional language. No forecasts the sources do not make.
- Every risk and opportunity states its mechanism: how it affects companies.
- Every item cites at least one source with a quote copied VERBATIM from that source's text, with its source_id. \
Items without a verbatim quote are discarded.
- A short title per item (at most 120 characters).
- Leave a section empty rather than write anything the sources do not support."""


def _pdf_document(source_id: str, data: bytes) -> SourceDocument:
    from pypdf import PdfReader

    try:
        pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]
    except Exception as exc:  # noqa: BLE001 - a malformed PDF is an unreadable source, not a failed run
        logger.info("could not parse uploaded PDF for %s: %s", source_id, exc)
        pages = []
    starts, offset = [], 0
    for p in pages:
        starts.append(offset)
        offset += len(p) + 1  # the "\n" join
    return SourceDocument(doc_id=source_id, company_id="", doc_type=DocType.OTHER, title=source_id,
                          full_text="\n".join(pages)[:_MAX_CHARS], page_breaks=starts)


def _file_document(source_id: str, path: Path) -> SourceDocument:
    data = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        return _pdf_document(source_id, data)
    text = data.decode("utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        text = extract_html_text(text)
    return SourceDocument(doc_id=source_id, company_id="", doc_type=DocType.OTHER, title=source_id,
                          full_text=text[:_MAX_CHARS])


async def read_sources(sources: list[tuple[ResearchSource, Path | None]], user_agent: str
                       ) -> tuple[dict[str, SourceDocument], list[UnreadSource]]:
    """Each source's text: its uploaded file when it has one (and it can be read), else its fetched URL."""
    docs: dict[str, SourceDocument] = {}
    unread: list[UnreadSource] = []
    for source, path in sources:
        doc = None
        if path is not None:
            try:
                doc = _file_document(source.source_id, path)
            except OSError as exc:  # a lost upload falls back to the URL rather than failing the note
                logger.warning("could not read the upload for %s: %s", source.source_id, exc)
        if doc is None:
            text = await fetch_source_text_or_empty(source.url, user_agent)
            if text is None:
                unread.append(UnreadSource(source_id=source.source_id, reason="fetch failed"))
                continue
            doc = SourceDocument(doc_id=source.source_id, company_id="", doc_type=DocType.OTHER, title=source.title,
                                 full_text=text)
        if doc.full_text.strip():
            docs[source.source_id] = doc
        else:
            unread.append(UnreadSource(source_id=source.source_id, reason="no text extracted"))
    return docs, unread


def ground_note(draft: ResearchNoteDraft, docs: dict[str, SourceDocument]) -> tuple[NoteSections, int]:
    """Keeps only citations whose quote is found in their source's text; drops and counts items left with none."""
    sections, dropped = NoteSections(), 0
    for name in SECTIONS:
        for item in getattr(draft, name):
            cites = [Citation(doc_id=c.source_id, doc_type=DocType.OTHER, quote=c.quote) for c in item.citations
                     if c.source_id in docs]
            grounded = [c for c in ground_citations(cites, docs, 0.92) if c.grounded]
            if not grounded:
                dropped += 1
                continue
            getattr(sections, name).append(NoteItem(
                title=item.title[:120], text=item.text, channel=item.channel if name == "transmission_channels" else None,
                citations=[NoteCitation(source_id=c.doc_id, quote=c.span_text or c.quote, page=c.page) for c in grounded],
            ))
    return sections, dropped


async def write_note(taxonomy: Taxonomy, docs: dict[str, SourceDocument], llm: LLMClient) -> tuple[NoteSections, int]:
    blocks = "\n\n".join(f'<source source_id="{sid}">\n{doc.full_text}\n</source>' for sid, doc in docs.items())
    prompt = f"Theme: {taxonomy.theme.name}\nDescription: {taxonomy.theme.description}\n\nSources:\n{blocks}"
    draft, _ = await llm.complete_structured(system=_NOTE_SYSTEM, prompt=prompt, output_model=ResearchNoteDraft)
    return ground_note(draft, docs)
