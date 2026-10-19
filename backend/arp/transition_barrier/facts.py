"""Checks on an analyst-entered fact: its value, unit, quote and optional uploaded PDF."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date

from pypdf import PdfReader

from arp.checks.numeric import candidates, parse_number
from arp.config import get_settings
from arp.grounding import ground_citations
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.transition_barrier.rule_book import FactDef

DOC_ID = "upload"


class FactRefused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class UploadMeta:
    title: str
    publisher: str
    as_of: date | None
    tier: str


@dataclass(frozen=True)
class CheckedFact:
    value: float | bool | str | date
    page: int | None
    machine_checked: bool
    pages: list[str] = field(default_factory=list)  # the uploaded PDF's text per page, for storage


def pdf_pages(data: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]


def _parse_value(fact_def: FactDef, raw: str):
    raw = raw.strip()
    if fact_def.type == "boolean":
        if raw.lower() not in ("yes", "no"):
            raise FactRefused(422, "Value must be Yes or No.")
        return raw.lower() == "yes"
    if fact_def.type == "enum":
        if raw not in (fact_def.allowed_values or []):
            raise FactRefused(422, f"Value must be one of: {', '.join(fact_def.allowed_values or [])}.")
        return raw
    if fact_def.type == "date":
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise FactRefused(422, "Value must be a date (YYYY-MM-DD).") from None
    number = parse_number(raw)
    if number is None or not math.isfinite(number):
        raise FactRefused(422, "Value must be a number.")
    return number


def _page_found(pages: list[str], quote: str) -> int | None:
    """The 1-indexed page where the quote grounds in the PDF text, or None."""
    starts, text = [], ""
    for page in pages:
        starts.append(len(text))
        text += page + "\n"
    source = SourceDocument(
        doc_id=DOC_ID, company_id="", doc_type=DocType.OTHER, title="", full_text=text, page_breaks=starts
    )
    cite = Citation(doc_id=DOC_ID, doc_type=DocType.OTHER, quote=quote)
    [grounded] = ground_citations([cite], {DOC_ID: source}, get_settings().grounding_fuzzy_threshold)
    return grounded.page if grounded.grounded else None


def check_fact(
    fact_def: FactDef,
    *,
    value: str,
    unit: str | None,
    quote: str,
    page: int | None,
    upload: UploadMeta | None,
    pdf: bytes | None,
) -> CheckedFact:
    """Order: required upload fields, tier, unit, number in quote, quote in the uploaded document."""
    parsed = _parse_value(fact_def, value)
    if upload is not None:
        if not (upload.title and upload.publisher and upload.as_of and upload.tier):
            raise FactRefused(422, "An uploaded document needs a title, publisher, as-of date and tier.")
        if upload.tier == "news":
            raise FactRefused(422, "News cannot ground a fact.")
        if upload.tier not in ("primary", "secondary"):
            raise FactRefused(422, "Tier must be primary, secondary or news.")
    numeric = fact_def.type == "number"
    if numeric and unit and unit != fact_def.unit:
        raise FactRefused(422, f"Unit not convertible: {unit}")
    if not quote.strip():
        raise FactRefused(422, "A quote is required.")
    if numeric and not any(math.isclose(abs(parsed), abs(n), rel_tol=1e-9) for n in candidates(quote)):
        raise FactRefused(422, "Number not in quote.")
    if upload is None or pdf is None:
        return CheckedFact(parsed, page, False)
    try:
        pages = pdf_pages(pdf)
    except Exception:  # noqa: BLE001 - any unreadable PDF is the caller's bad upload
        raise FactRefused(422, "Upload a PDF document.") from None
    found = _page_found(pages, quote)
    if found is None:
        raise FactRefused(422, "Quote not found in the uploaded document.")
    return CheckedFact(parsed, found, True, pages)
