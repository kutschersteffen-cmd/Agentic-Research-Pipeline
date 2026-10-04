"""Lineage gate and re-grounding (E74). The gate re-reads the stored
original and checks its sha256 against the citation's content_key; the
re-grounding check grounds the quote again against the stored text and
changes nothing."""

from __future__ import annotations

import hashlib
import random

from arp.grounding import ground_citations
from arp.publish.facts import Fact
from arp.schemas.common import Citation, SourceDocument
from arp.storage.document_store import DocumentContentStore


def lineage_error(citation: Citation | None, blob_store) -> str | None:
    if citation is None or not citation.grounded or not citation.content_key:
        return "no_grounded_citation"
    key = citation.content_key
    try:
        if not blob_store.exists(key):
            return "original_missing"
        data = blob_store.get(key)
    except Exception:
        return "original_missing"
    if hashlib.sha256(data).hexdigest() != key:
        return "hash_mismatch"
    return None


def reground(fact: Fact, *, blob_store, content_store: DocumentContentStore | None, fuzzy_threshold: float) -> str:
    c = fact.citation
    if err := lineage_error(c, blob_store):
        return err
    parsed = content_store.lookup(c.content_key, c.parser_version) if content_store is not None else None
    if parsed is None:
        return "text_unavailable"
    doc = SourceDocument(
        doc_id=c.doc_id, company_id=c.company_id or "", doc_type=c.doc_type, title=c.source_filename or c.doc_id,
        full_text=parsed.full_text, page_breaks=parsed.page_breaks, content_key=c.content_key,
        parser_version=c.parser_version,
    )
    [g] = ground_citations([Citation(doc_id=c.doc_id, doc_type=c.doc_type, quote=c.quote)], {c.doc_id: doc}, fuzzy_threshold)
    if not g.grounded:
        return "not_grounded"
    return "offset_moved" if g.char_start != c.char_start else "ok"


def sample(facts: list[Fact], n: int, *, seed: str) -> list[Fact]:
    return random.Random(seed).sample(sorted(facts, key=lambda f: f.fact_id), min(n, len(facts)))
