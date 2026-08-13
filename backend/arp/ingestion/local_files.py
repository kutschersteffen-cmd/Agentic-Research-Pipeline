from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from arp.ingestion.base import DocumentSource
from arp.schemas.common import CompanyRef, DocType, SourceDocument

logger = logging.getLogger(__name__)

_TEXT_SUFFIXES = {".txt", ".md"}
_HTML_SUFFIXES = {".html", ".htm"}
_PDF_SUFFIXES = {".pdf"}
_XLSX_SUFFIXES = {".xlsx", ".xlsm"}


def _extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_html_text(path: Path) -> str:
    import trafilatura

    raw = path.read_text(errors="ignore")
    extracted = trafilatura.extract(raw, favor_recall=True)
    if extracted:
        return extracted
    from bs4 import BeautifulSoup

    return BeautifulSoup(raw, "lxml").get_text("\n")


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


def parse_file_to_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _PDF_SUFFIXES:
        return _extract_pdf_text(path)
    if suffix in _HTML_SUFFIXES:
        return _extract_html_text(path)
    if suffix in _TEXT_SUFFIXES:
        return path.read_text(errors="ignore")
    if suffix in _XLSX_SUFFIXES:
        return _extract_xlsx_text(path)
    raise ValueError(f"Unsupported document file type: {suffix}")


class LocalFileDocumentSource(DocumentSource):
    """Reads documents from `documents_dir/<company_id>/<doc_type>/*`.

    This is the convention used both by manual user uploads and by the
    discovery crawler's downloader, so anything the crawler finds is
    immediately visible to the extraction pipeline with no extra wiring.
    """

    name = "local_files"

    def __init__(self, documents_dir: Path) -> None:
        self.documents_dir = documents_dir

    async def fetch(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        company_dir = self.documents_dir / company.company_id
        if not company_dir.exists():
            return []
        wanted = set(doc_types) if doc_types else None
        docs: list[SourceDocument] = []
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
                if not file_path.is_file():
                    continue
                try:
                    text = parse_file_to_text(file_path)
                except Exception as exc:  # noqa: BLE001 - isolate one bad file from the whole fetch
                    logger.warning("Failed to parse %s: %s", file_path, exc)
                    continue
                if not text.strip():
                    continue
                docs.append(
                    SourceDocument(
                        company_id=company.company_id,
                        doc_type=doc_type,
                        title=file_path.name,
                        local_path=str(file_path),
                        full_text=text,
                        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )
        return docs
