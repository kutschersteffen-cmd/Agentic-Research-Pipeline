"""Reference documents (rfp-approved-answers-first-design §5): PDF and Word files auto-fill falls back to, in priority
order, when the approved answers do not answer a question."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePath

from sqlalchemy import select

from arp.db import models as m
from arp.errors import ClientInputError
from arp.ingestion import local_files
from arp.rfp.draft import DRAFTED, EDITED, STALE_SOURCE
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.rfp import RfpDocumentOut

SUFFIXES = (".pdf", ".docx")


@dataclass(frozen=True)
class RefDoc:
    id: int
    title: str
    file: str
    priority: int
    review_by: date
    retired: bool
    source: SourceDocument  # doc_id `rfpdoc-<id>`, with full_text and page_breaks


def parse(name: str, data: bytes) -> tuple[str, list[int]]:
    """(text, page starts; empty for Word). Never OCR: a misread digit would pass every later check."""
    name = PurePath(name).name
    suffix = PurePath(name).suffix.lower()
    if suffix not in SUFFIXES:
        raise ClientInputError(f"{name} is not a .pdf or .docx file.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(data)
        if suffix == ".pdf" and not local_files._has_text_layer(path):
            raise ClientInputError(f"{name} has no text layer; upload the original document.")
        try:
            text, page_breaks, _ = local_files.parse_file_to_text_with_pages(path)
        except Exception:  # a damaged or renamed file is the uploader's to fix, not a server error
            raise ClientInputError(f"{name} could not be read; upload the original document.") from None
    return text, page_breaks


def doc_out(d: m.RfpReferenceDocument) -> RfpDocumentOut:
    return RfpDocumentOut(id=d.id, title=d.title, filename=d.filename, document_date=d.document_date,
                          review_by=d.review_by, priority=d.priority, status=d.status, uploaded_by=d.uploaded_by,
                          pages=len(d.page_breaks) if d.filename.lower().endswith(".pdf") else None)


def ref_doc(d: m.RfpReferenceDocument) -> RefDoc:
    source = SourceDocument(doc_id=f"rfpdoc-{d.id}", company_id="rfp", doc_type=DocType.OTHER, title=d.title,
                            full_text=d.full_text, page_breaks=d.page_breaks)
    return RefDoc(d.id, d.title, d.filename, d.priority, d.review_by, d.status == "retired", source)


def active(s) -> list[RefDoc]:
    """The documents auto-fill may show the model: retired ones never are."""
    rows = s.scalars(select(m.RfpReferenceDocument).where(m.RfpReferenceDocument.status == "active")
                     .order_by(m.RfpReferenceDocument.priority, m.RfpReferenceDocument.id))
    return [ref_doc(d) for d in rows]


def flag_stale(s, document_id: int) -> None:
    """Adds `stale source` to every drafted or edited question citing the document."""
    for q in s.scalars(select(m.RfpQuestion).where(m.RfpQuestion.status.in_((DRAFTED, EDITED)),
                                                   m.RfpQuestion.sources.contains([{"document_id": document_id}]))):
        if STALE_SOURCE not in q.flags:
            q.flags = [*q.flags, STALE_SOURCE]
