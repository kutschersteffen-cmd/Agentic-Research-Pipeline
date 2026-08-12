from __future__ import annotations

from arp.schemas.common import DocumentChunk
from arp.schemas.datapoints import FieldDefinition


def select_chunks_for_field(
    chunks: list[DocumentChunk], field: FieldDefinition, max_chunks: int = 10
) -> list[DocumentChunk]:
    """Keyword-in-context prefilter + ranking, applied per field before any
    extraction LLM call. Keeps the extractor's context small (higher
    precision, lower cost) instead of dumping entire filings at it, and is
    what makes per-field extraction affordable across a 4000-company batch.
    """
    candidates = chunks
    if field.source_doc_types:
        candidates = [c for c in candidates if c.doc_type in field.source_doc_types]
    if field.seed_keywords:
        candidates = [c for c in candidates if c.keyword_hits]
        candidates.sort(key=lambda c: len(c.keyword_hits), reverse=True)
    return candidates[:max_chunks]
