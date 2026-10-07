from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import re
import threading
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from arp.ingestion import esef
from arp.ingestion.base import DocumentSource
from arp.ingestion.doc_identity import CORRECTION_MARKERS, assign_identity, published_at_for
from arp.ingestion.html_text import extract_html_text
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.intake import IntakeResult, IntakeState, append_intake, check_intake
from arp.normalise.locale import decimal_for, detect_language
from arp.normalise.units import lookup_scale
from arp.schemas.common import CompanyRef, DocType, SourceDocument, TableCell, TableSpan
from arp.storage.document_store import DocumentContentStore, derive_doc_id
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

logger = logging.getLogger(__name__)

_TEXT_SUFFIXES = {".txt", ".md"}
_HTML_SUFFIXES = {".html", ".htm"}
_PDF_SUFFIXES = {".pdf"}
_XLSX_SUFFIXES = {".xlsx", ".xlsm"}
_DOCX_SUFFIXES = {".docx"}

# Bump whenever the extraction logic here changes -- including the
# `cursor += len(text) + 2` page-join arithmetic in _extract_pdf_text --
# since that silently changes what a cached page_breaks means without
# changing any package version.
_PARSER_LOGIC_VERSION = 3  # bumped: table spans from Docling's table structure (E45)


@functools.lru_cache(maxsize=1)
def parser_version() -> str:
    """Identifies exactly what produced a DocumentContentStore row, so a
    library upgrade (or a bump to _PARSER_LOGIC_VERSION) orphans old cache
    entries instead of silently mixing parse outputs from two different
    parser behaviors under one key."""
    parts = [f"logic={_PARSER_LOGIC_VERSION}"]
    for pkg in ("docling", "docling-core", "trafilatura", "openpyxl"):
        try:
            parts.append(f"{pkg}={_pkg_version(pkg)}")
        except PackageNotFoundError:
            parts.append(f"{pkg}=unknown")
    return "|".join(parts)


@functools.lru_cache(maxsize=2)
def _docling_converter(ocr: bool = True):
    """One converter per OCR setting, reused for every document in the process. Docling's
    standard PDF pipeline loads a layout-detection (and, when tables are
    present, TableFormer) model, downloaded from Hugging Face Hub on first
    use anywhere on the machine -- paying that init cost per file instead
    of once per process would be prohibitive. Only call it through
    _convert(): concurrent conversions crash the process.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=ocr)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def _has_text_layer(path: Path, sample: int = 5, min_chars: int = 50) -> bool:
    """Most sampled pages carry extractable text, so OCR would only re-read what is already
    there (and costs most of the parse time). A scanned PDF has next to none."""
    import pypdfium2

    try:
        pdf = pypdfium2.PdfDocument(str(path))
    except pypdfium2.PdfiumError:
        return False  # unreadable here: docling decides, and reports it invalid as before
    try:
        pages = range(min(len(pdf), sample))
        texty = sum(len(pdf[i].get_textpage().get_text_range().strip()) >= min_chars for i in pages)
        return len(pages) > 0 and texty * 2 >= len(pages)
    finally:
        pdf.close()


# Concurrent docling conversions crash the whole process on Windows (access violation in
# docling_parse's native PDF reader), killing the API server mid-run. One at a time; pdfium
# (the text-layer check) is not thread-safe either.
# ponytail: process-wide lock; a parse worker process (or pool) if parse throughput matters
_DOCLING_LOCK = threading.Lock()


def _convert(path: Path):
    """OCR only for a PDF without a text layer (a scan). Text in images inside an otherwise
    digital PDF (e.g. a chart's labels) is not read; tables and body text are."""
    with _DOCLING_LOCK:
        ocr = path.suffix.lower() == ".pdf" and not _has_text_layer(path)
        return _docling_converter(ocr).convert(str(path)).document


_UNIT_NOTE = re.compile(r"\bin\s+[^()\n,;:]+", re.I)


def _unit_note(caption: str | None) -> str | None:
    """The "in EUR million" phrase of a caption: an "in ..." run holding a scale word."""
    for m in _UNIT_NOTE.finditer(caption or ""):
        if any(lookup_scale(w.strip(".")) for w in m.group().split()[1:]):
            return m.group().strip()
    return None


def _caption_before(text: str, start: int) -> str | None:
    """The last non-empty line before a table, for a table Docling found no caption for."""
    lines = [ln.strip() for ln in text[:start].splitlines() if ln.strip()]
    return lines[-1] if lines and not lines[-1].startswith("|") else None  # never another table's row


def table_spans_from_docling(doc, text: str) -> list[TableSpan]:
    """Locates each of `doc.tables` (Docling TableItems) in `text` by its own
    exported markdown, and each data cell inside that block by its text.
    A table whose markdown is not in `text` is skipped.

    Reads `table.export_to_markdown(doc)`, `table.caption_text(doc)` and
    `table.data.table_cells` (`text`, `start_row_offset_idx`,
    `start_col_offset_idx`, `row_header`, `column_header`). Row 0 and column
    0 count as headers too: markdown always prints row 0 as the header row,
    and TableFormer does not always flag row headers. A table with a caption
    item exports it above the grid; the span covers the grid only.
    """
    spans: list[TableSpan] = []
    cursor = 0
    for i, table in enumerate(doc.tables):
        md = table.export_to_markdown(doc)
        grid_at = 0 if md.startswith("|") else md.find("\n|") + 1  # 0 (not found) leaves md whole
        found = text.find(md, cursor) if md.strip() else -1
        if found == -1:
            continue
        cursor = found + len(md)
        start, md = found + grid_at, md[grid_at:]
        cells = sorted(table.data.table_cells, key=lambda c: (c.start_row_offset_idx, c.start_col_offset_idx))
        row_labels: dict[int, str] = {}
        col_labels: dict[int, str] = {}
        for c in cells:
            r, k, t = c.start_row_offset_idx, c.start_col_offset_idx, c.text.strip()
            if t and (c.row_header or k == 0):
                row_labels.setdefault(r, t)
            if t and (c.column_header or r == 0):
                col_labels[k] = t  # the lowest header row wins
        lines = md.split("\n")
        line_starts = [0]
        for ln in lines:
            line_starts.append(line_starts[-1] + len(ln) + 1)
        out_cells: list[TableCell] = []
        for c in cells:
            r, k, t = c.start_row_offset_idx, c.start_col_offset_idx, c.text.replace("\n", " ").strip()
            if not t or c.row_header or c.column_header or r == 0 or k == 0:
                continue
            li = r + 1  # line 1 is the |---| separator
            if li >= len(lines):
                continue
            pipes = [j for j, ch in enumerate(lines[li]) if ch == "|"]
            if k + 1 >= len(pipes):
                continue
            off = lines[li].find(t, pipes[k], pipes[k + 1])
            if off == -1:
                continue
            a = start + line_starts[li] + off
            out_cells.append(TableCell(row_label=row_labels.get(r), col_label=col_labels.get(k), char_start=a, char_end=a + len(t)))
        caption = table.caption_text(doc).strip() or _caption_before(text, start)
        spans.append(TableSpan(table_id=f"table_{i}", char_start=start, char_end=cursor, caption=caption,
                               unit_note=_unit_note(caption), cells=out_cells))
    return spans


def _extract_pdf_text(path: Path) -> tuple[str, list[int], list[TableSpan]]:
    """Renders each page as markdown via Docling's layout-aware PDF
    pipeline rather than plain reading-order text -- disclosure PDFs are
    table-heavy (segment breakdowns, GHG inventories, revenue tables), and
    Docling's TableFormer model turns those into real markdown tables
    instead of row/column-scrambled flat text. Still zero-LLM and
    deterministic, but a genuine ML pipeline runs over every page, so this
    is far slower and heavier per document than the old MuPDF-only path --
    accepted at the ~400-company scale this pipeline targets, on the
    strength of DocumentContentStore already making this a one-time cost
    per unique file rather than a per-run one.

    Docling's default backend auto-tries an empty user password, so an
    owner-password-only "no printing/copying" disclosure PDF (the common
    case) reads transparently; a genuinely user-password-locked PDF is
    reported invalid and raises, same as before, and is caught by the
    caller as a normal per-file parse error.
    """
    doc = _convert(path)
    parts: list[str] = []
    page_breaks: list[int] = []
    cursor = 0
    for page_no in sorted(doc.pages.keys()):
        text = doc.export_to_markdown(page_no=page_no)
        page_breaks.append(cursor)
        parts.append(text)
        cursor += len(text) + 2  # matches the "\n\n" join below
    text = "\n\n".join(parts)
    return text, page_breaks, table_spans_from_docling(doc, text)


def _extract_docx_text(path: Path) -> tuple[str, list[TableSpan]]:
    """A Word document as markdown via the same Docling converter as PDFs,
    so headings and tables come out the same way. Docling reads DOCX
    declaratively (no layout model), so this is fast. A .docx has no fixed
    pages, hence no page breaks: citations ground to the text, without a
    page number."""
    doc = _convert(path)
    text = doc.export_to_markdown()
    return text, table_spans_from_docling(doc, text)


def _extract_html_text(path: Path) -> str:
    return extract_html_text(path.read_text(errors="ignore"))


def _extract_xlsx_text(path: Path) -> str:
    """Renders every sheet as a pipe-delimited text table, in document
    order, prefixed by its sheet name -- this is disclosure data (e.g. EU
    Taxonomy revenue/capex/opex tables, GHG footprint statbooks), so
    row/column structure and cross-sheet labels carry the meaning; a naive
    cell dump loses which KPI a number belongs to. Empty rows are skipped;
    trailing empty cells on a row are dropped so ragged tables don't turn
    into walls of pipes."""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    sections = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        lines = [f"## Sheet: {sheet_name}"]
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            while cells and cells[-1] is None:
                cells.pop()
            if not cells:
                continue
            lines.append(" | ".join("" if c is None else str(c) for c in cells))
        if len(lines) > 1:
            sections.append("\n".join(lines))
    return "\n\n".join(sections)


def parse_file_to_text_with_pages(path: Path) -> tuple[str, list[int], list[TableSpan]]:
    """Like parse_file_to_text, but also returns PDF page-start char
    offsets (empty for every other format) -- the raw material for
    resolving a grounded citation's exact page number in grounding.py --
    and the Docling table spans (PDF and DOCX only)."""
    suffix = path.suffix.lower()
    if suffix in _PDF_SUFFIXES:
        return _extract_pdf_text(path)
    if suffix in _HTML_SUFFIXES:
        return _extract_html_text(path), [], []
    if suffix in esef.ESEF_SUFFIXES:  # iXBRL text with the same offsets the tagged facts cite
        return esef.parse_file(path)[0], [], []
    if suffix in _TEXT_SUFFIXES:
        return path.read_text(errors="ignore"), [], []
    if suffix in _XLSX_SUFFIXES:
        return _extract_xlsx_text(path), [], []
    if suffix in _DOCX_SUFFIXES:
        text, spans = _extract_docx_text(path)
        return text, [], spans
    raise ValueError(f"Unsupported document file type: {suffix}")


def parse_file_to_text(path: Path) -> str:
    return parse_file_to_text_with_pages(path)[0]


class LocalFileDocumentSource(DocumentSource):
    """Reads documents from `documents_dir/<company_id>/<doc_type>/*`.

    This is the convention used both by manual user uploads and by the
    discovery crawler's downloader, so anything the crawler finds is
    immediately visible to the extraction pipeline with no extra wiring.
    """

    name = "local_files"

    def __init__(
        self,
        documents_dir: Path,
        content_store: DocumentContentStore | None = None,
        max_concurrent_parses: int = 4,
        indexing_config: IndexingConfig | None = None,
    ) -> None:
        self.documents_dir = documents_dir
        self._content_store = content_store
        self._parse_sem = asyncio.Semaphore(max_concurrent_parses)
        self._indexing_config = indexing_config
        self._identity_lock = threading.Lock()  # family lookup + set_identity must not interleave
        # (content_key, suffix) of files intake already accepted: unchanged bytes aren't re-checked every fetch.
        self._accepted: set[tuple[str, str]] = set()

    @functools.cached_property
    def _blob_store(self):
        from arp.storage.document_blob_store import blob_store_for

        return blob_store_for(self._indexing_config)

    def _parse_and_identify(self, file_path: Path, company_id: str, doc_type: DocType) -> dict:
        """Blocking: stat + hash + SQLite + parse, called only via
        asyncio.to_thread so it never stalls the event loop. Returns the
        SourceDocument kwargs this parse determines; `doc_id` is absent when
        no content_store is configured, so SourceDocument falls back to its
        own random default -- exactly today's behavior.
        """
        if self._content_store is not None:
            parsed = self._content_store.get_or_parse(
                file_path, parser_version=parser_version(), parse=parse_file_to_text_with_pages
            )
            doc_id = derive_doc_id(company_id, doc_type.value, parsed.content_key)
            doc_id = self._content_store.register_document(
                doc_id=doc_id,
                company_id=company_id,
                doc_type=doc_type.value,
                content_key=parsed.content_key,
                title=file_path.name,
                local_path=str(file_path),
                source_url=None,
            )
            if self._indexing_config is not None:
                self._index_and_archive(doc_id, company_id, doc_type, file_path, parsed.content_key, parsed.full_text)
            return {
                "doc_id": doc_id,
                "full_text": parsed.full_text,
                "page_breaks": parsed.page_breaks,
                "table_spans": parsed.table_spans,
                "sha256": parsed.text_sha256,
                "content_key": parsed.content_key,
                "parser_version": parser_version(),
            }

        text, page_breaks, table_spans = parse_file_to_text_with_pages(file_path)
        return {"full_text": text, "page_breaks": page_breaks, "table_spans": table_spans, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}

    def _identify_batch(self, items: list[tuple[Path, DocType, SourceDocument]]) -> list[SourceDocument]:
        """Blocking, serial identity assignment after the concurrent parse, in a
        deterministic order so version numbers never depend on parse timing:
        known published_at ascending, originals before corrections, then path."""
        from arp.discovery.downloader import latest_capture

        keyed = []
        for file_path, doc_type, doc in items:
            ref = self._content_store.resolve_document(doc.doc_id)
            if ref is not None and ref.family_id is not None:  # identity is fixed; skip the capture-log scan
                published = ref.published_at
            else:
                published = published_at_for(file_path, latest_capture(self.documents_dir, doc.content_key))
            marker = any(k in file_path.name.lower() for k in CORRECTION_MARKERS)
            keyed.append(((published is None, published or "", marker, str(file_path)), published, doc_type, doc))
        out = []
        with self._identity_lock:
            for _, published, doc_type, doc in sorted(keyed, key=lambda k: k[0]):
                ident = self._identity_locked(doc.doc_id, Path(doc.local_path), doc.company_id, doc_type, published, doc.full_text)
                out.append(doc.model_copy(update=ident))
        return out

    def _identity_locked(
        self, doc_id: str, file_path: Path, company_id: str, doc_type: DocType, published_at: str | None, text: str
    ) -> dict:
        """Assigns family/version once per document: a row that already has a
        family_id keeps it, so re-fetching never renumbers versions."""
        store = self._content_store
        ref = store.resolve_document(doc_id)
        if ref is not None and ref.family_id is not None:
            return {k: getattr(ref, k) for k in ("family_id", "version", "supersedes", "published_at")}
        decision = assign_identity(
            doc_id=doc_id, company_id=company_id, doc_type=doc_type.value, title=file_path.name, text=text,
            published_at=published_at, family=store.list_family,
        )
        store.set_identity(
            doc_id, family_id=decision.family_id, version=decision.version, supersedes=decision.supersedes,
            published_at=published_at, confidence=decision.confidence, needs_review=decision.needs_review,
        )
        return {
            "family_id": decision.family_id, "version": decision.version,
            "supersedes": decision.supersedes, "published_at": published_at,
        }

    def _index_and_archive(
        self, doc_id: str, company_id: str, doc_type: DocType, file_path: Path, content_key: str, full_text: str
    ) -> None:
        """Best-effort OpenSearch indexing + mandatory blob-store archival, run
        synchronously here since this whole method (via _parse_and_identify)
        already executes off the event loop in a to_thread worker. Indexing
        is gated and best-effort (arp/retrieval/search_indexer.py); the blob
        store is mandatory and a failed or unverified copy raises."""
        from arp.retrieval.search_indexer import index_document_if_enabled

        index_document_if_enabled(
            self._indexing_config, doc_id=doc_id, company_id=company_id, doc_type=doc_type, title=file_path.name, full_text=full_text
        )

        from arp.storage.document_blob_store import upload_or_fail

        # CaptureStoreError propagates: _fetch_one drops the file this fetch.
        ref = self._content_store.resolve_document(doc_id) if self._content_store is not None else None
        if ref is not None and ref.content_key == content_key and ref.storage_uri and self._blob_store.exists(content_key):
            storage_uri = ref.storage_uri  # verified when it was stored; still there
        else:
            storage_uri = upload_or_fail(self._blob_store, content_key, file_path.read_bytes())
            if self._content_store is not None:
                self._content_store.set_storage_uri(doc_id, storage_uri)

        from arp.storage.document_registry import StoredDocumentRef
        from arp.storage.postgres_document_projection import sync_document_if_enabled

        sync_document_if_enabled(
            self._indexing_config,
            StoredDocumentRef(
                doc_id=doc_id, company_id=company_id, doc_type=doc_type.value, content_key=content_key,
                title=file_path.name, local_path=str(file_path), source_url=None, storage_uri=storage_uri,
            ),
        )

    def _intake_all(self, entries: list[tuple[Path, DocType]]) -> list[tuple[Path, DocType]]:
        """Blocking, sorted-order intake over one company's files. Non-accepted
        files stay on disk; the verdict is only recorded in _intake.jsonl."""
        seen: dict[str, str] = {}
        accepted = []
        for file_path, doc_type in entries:
            key = ""
            try:
                if self._content_store is not None:
                    key = self._content_store.content_key_for_file(file_path)
                else:
                    with file_path.open("rb") as f:
                        key = hashlib.file_digest(f, "sha256").hexdigest()
                cached = (key, file_path.suffix.lower()) in self._accepted
                if cached and seen.setdefault(key, str(file_path)) == str(file_path):
                    result = IntakeResult(IntakeState.ACCEPTED)
                else:
                    result = check_intake(file_path, key, seen=seen)
            except Exception as exc:  # noqa: BLE001 - one unreadable file must not abort the fetch
                logger.warning("Intake failed for %s: %s", file_path, exc)
                try:
                    append_intake(
                        self.documents_dir, file_path, key,
                        IntakeResult(IntakeState.QUARANTINED, f"intake error: {type(exc).__name__}: {exc}"),
                    )
                except Exception:  # noqa: BLE001 - the ledger must not break the fetch
                    logger.exception("Could not log intake error for %s", file_path)
                continue
            if result.state == IntakeState.ACCEPTED:
                self._accepted.add((key, file_path.suffix.lower()))
                accepted.append((file_path, doc_type))
            else:
                append_intake(self.documents_dir, file_path, key, result)
        return accepted

    async def fetch(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        try:
            company_dir = self.documents_dir / safe_id(company.company_id, label="company_id")
        except UnsafeIdentifierError:
            # A malformed company_id (e.g. containing "..") has no local
            # documents by definition -- fail this one company closed
            # rather than resolving outside documents_dir, and don't
            # abort the whole batch over one bad universe row.
            logger.warning("Rejected unsafe company_id in local document fetch: %r", company.company_id)
            return []
        if not company_dir.exists():
            return []
        wanted = set(doc_types) if doc_types else None
        file_entries: list[tuple[Path, DocType]] = []
        for doc_type_dir in sorted(company_dir.iterdir()):
            if not doc_type_dir.is_dir():
                continue
            try:
                doc_type = DocType(doc_type_dir.name)
            except ValueError:
                doc_type = DocType.OTHER
            if wanted and doc_type not in wanted:
                continue
            for file_path in sorted(doc_type_dir.iterdir()):
                if file_path.is_file():
                    file_entries.append((file_path, doc_type))

        async def _fetch_one(file_path: Path, doc_type: DocType) -> tuple[Path, DocType, SourceDocument] | None:
            async with self._parse_sem:
                try:
                    extra = await asyncio.to_thread(
                        self._parse_and_identify, file_path, company.company_id, doc_type
                    )
                except Exception as exc:  # noqa: BLE001 - isolate one bad file from the whole fetch
                    logger.warning("Failed to parse %s: %s", file_path, exc)
                    return None
            if not extra["full_text"].strip():
                return None
            language = detect_language(extra["full_text"])
            doc = SourceDocument(
                language=language,
                decimal=decimal_for(language),
                company_id=company.company_id,
                doc_type=doc_type,
                title=file_path.name,
                local_path=str(file_path),
                **extra,
            )
            return file_path, doc_type, doc

        accepted = await asyncio.to_thread(self._intake_all, file_entries)
        results = await asyncio.gather(*(_fetch_one(fp, dt) for fp, dt in accepted))
        items = [r for r in results if r is not None]
        if self._content_store is None:
            return [d for _, _, d in items]
        return await asyncio.to_thread(self._identify_batch, items)
