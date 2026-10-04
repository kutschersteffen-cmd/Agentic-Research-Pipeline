"""Lineage gate and re-grounding (E74). The gate re-reads the stored
original and checks its sha256 against the blob's key; the re-grounding
check grounds the quote again against the stored text and changes
nothing."""

from __future__ import annotations

import hashlib
import random

from arp.grounding import ground_citations
from arp.publish.facts import Fact
from arp.schemas.common import Citation, DocumentChunk, SourceDocument
from arp.storage.document_store import DocumentContentStore

SPAN_MARGIN = 200


def blob_key(citation: Citation, content_store: DocumentContentStore | None) -> str:
    """Key of the stored original. Local files are stored under their
    content_key. EDGAR documents hash the accession for content_key, but
    the original bytes are stored under sha256(raw bytes); ingestion
    records that blob's storage_uri on the registry row, whose last path
    segment is the blob key (LocalBlobStore and DocumentBlobStore both end
    the uri with it). Without such a row the content_key is used, so an
    unmapped EDGAR document fails closed as original_missing."""
    try:
        ref = content_store.resolve_document(citation.doc_id) if content_store is not None else None
    except Exception:
        ref = None
    if ref is not None and ref.content_key == citation.content_key and ref.storage_uri:
        return ref.storage_uri.rsplit("/", 1)[-1]
    return citation.content_key


def lineage_error(citation: Citation | None, blob_store, *, content_store: DocumentContentStore | None = None) -> str | None:
    if citation is None or not citation.grounded or not citation.content_key:
        return "no_grounded_citation"
    key = blob_key(citation, content_store)
    try:
        if not blob_store.exists(key):
            return "original_missing"
        data = blob_store.get(key)
        digest = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else None
    except Exception:
        return "original_missing"
    if digest is None:
        return "original_missing"
    return "hash_mismatch" if digest != key else None


def reground(fact: Fact, *, blob_store, content_store: DocumentContentStore | None, fuzzy_threshold: float) -> str:
    c = fact.citation
    if err := lineage_error(c, blob_store, content_store=content_store):
        return err
    if content_store is None:
        return "text_unavailable"
    try:
        parsed = content_store.lookup(c.content_key, c.parser_version)
        if parsed is None:
            return "text_unavailable"
        text = parsed.full_text
        doc = SourceDocument(
            doc_id=c.doc_id, company_id=c.company_id or "", doc_type=c.doc_type, title=c.source_filename or c.doc_id,
            full_text=text, page_breaks=parsed.page_breaks, table_spans=parsed.table_spans, content_key=c.content_key, parser_version=c.parser_version,
        )
        probe = [Citation(doc_id=c.doc_id, doc_type=c.doc_type, quote=c.quote)]
        # The stored span first, so a quote that repeats earlier in the text still re-grounds where it was.
        if c.char_start is not None and c.char_end is not None:
            lo, hi = max(0, c.char_start - SPAN_MARGIN), min(len(text), c.char_end + SPAN_MARGIN)
            span = DocumentChunk(
                chunk_id="stored_span", doc_id=c.doc_id, company_id=doc.company_id, doc_type=c.doc_type,
                text=text[lo:hi], char_start=lo, char_end=hi,
            )
            [g] = ground_citations(probe, {c.doc_id: doc}, fuzzy_threshold, passages={span.chunk_id: span})
            if g.grounded and g.char_start == c.char_start:
                return "ok"
        [g] = ground_citations(probe, {c.doc_id: doc}, fuzzy_threshold)
    except Exception:
        return "text_unavailable"
    if not g.grounded:
        return "not_grounded"
    return "offset_moved" if g.char_start != c.char_start else "ok"


def sample(facts: list[Fact], n: int, *, seed: str) -> list[Fact]:
    return random.Random(seed).sample(sorted(facts, key=lambda f: f.fact_id), max(0, min(n, len(facts))))
