"""Does a downloaded PDF name the company it was found for? Flags only; never drops a document."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from pypdf import PdfReader

from arp.discovery.names import clean_name
from arp.ingestion.doc_identity import reporting_year
from arp.schemas.common import CompanyRef

PAGES_HEAD = 5
PAGES_TAIL = 10
MIN_TEXT_CHARS = 200


class DocCheck(NamedTuple):
    company_match: str
    page_count: int | None
    reporting_year: int | None


def check_document(path: Path, company: CompanyRef) -> DocCheck:
    try:
        reader = PdfReader(path)
        n = len(reader.pages)
        read = sorted(set(range(min(PAGES_HEAD, n))) | set(range(max(0, n - PAGES_TAIL), n)))
        texts = {i: reader.pages[i].extract_text() or "" for i in read}
        title = reader.metadata.title if reader.metadata else None
        title = title if isinstance(title, str) else ""  # pypdf returns the raw object for a numeric/array /Title
    except Exception:  # noqa: BLE001 - an unreadable PDF has no text we can check
        return DocCheck("no_text", None, None)

    text = "\n".join(texts.values())
    year = reporting_year(title, texts.get(0, ""))
    upper = text.upper()
    if any(ident and ident.strip().upper() in upper for ident in (company.lei, company.isin)):
        match = "identifier"
    elif _contains_name(text, company.name):
        match = "name"
    elif len("".join(text.split())) < MIN_TEXT_CHARS:
        match = "no_text"
    else:
        match = "none"
    return DocCheck(match, n, year)


def _contains_name(text: str, name: str) -> bool:
    # clean_name folds case, accents and punctuation; applied to the text it gives whole-word containment
    cleaned = clean_name(name)
    return bool(cleaned) and f" {cleaned} " in f" {clean_name(text)} "
