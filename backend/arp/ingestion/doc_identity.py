"""Document identity (E27): which reporting-year family a document belongs to,
its version within the family, and what it supersedes. Deterministic; no model
call -- ambiguity is flagged for review instead."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from arp.schemas.discovery import CaptureRecord
from arp.storage.document_registry import StoredDocumentRef

REVIEW_BELOW = 0.6
CORRECTION_MARKERS = ("corrected", "correction", "amended", "amendment", "revised", "restated", "10-k/a")
_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")


@dataclass(frozen=True)
class IdentityDecision:
    family_id: str
    version: int
    supersedes: str | None
    confidence: float
    needs_review: bool
    reason: str


def reporting_year(title: str, text: str) -> int | None:
    in_title = set(_YEAR.findall(title))
    if len(in_title) == 1:
        return int(in_title.pop())
    if len(in_title) > 1:
        return None
    m = _YEAR.search(text[:3000])
    return int(m.group(1)) if m else None


def family_id_for(company_id: str, doc_type: str, year: int) -> str:
    return "fam_" + hashlib.sha256(f"{company_id}\x00{doc_type}\x00{year}".encode()).hexdigest()[:16]


def _iso_date(dt: datetime) -> str:
    return dt.date().isoformat()


def published_at_for(path: Path, capture: CaptureRecord | None) -> str | None:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            created = PdfReader(str(path)).metadata.creation_date  # parses /CreationDate
            if created is not None:
                return _iso_date(created)
        except Exception:  # noqa: BLE001 - unreadable metadata just means unknown
            pass
    if capture is not None:
        header = next((v for k, v in capture.headers.items() if k.lower() == "last-modified"), None)
        if header:
            try:
                return _iso_date(parsedate_to_datetime(header))
            except (TypeError, ValueError):
                pass
    return None


def assign_identity(
    *,
    doc_id: str,
    company_id: str,
    doc_type: str,
    title: str,
    text: str,
    published_at: str | None,
    family: Callable[[str], list[StoredDocumentRef]],
) -> IdentityDecision:
    year = reporting_year(title, text)
    if year is None:
        return IdentityDecision(f"fam_{doc_id[4:]}", 1, None, 0.3, True, "no reporting year found")
    fid = family_id_for(company_id, doc_type, year)
    members = [m for m in family(fid) if m.doc_id != doc_id]
    if not members:
        return IdentityDecision(fid, 1, None, 0.9, False, "first document for the reporting year")
    prev = max(members, key=lambda m: m.version or 1)
    version = (prev.version or 1) + 1
    marker = any(k in title.lower() for k in CORRECTION_MARKERS)
    later = bool(published_at and prev.published_at and published_at > prev.published_at)
    confidence = 0.9 if marker or later else 0.5
    reason = "correction marker in title" if marker else "published later" if later else "same year, no evidence of order"
    return IdentityDecision(fid, version, prev.doc_id, confidence, confidence < REVIEW_BELOW, reason)
