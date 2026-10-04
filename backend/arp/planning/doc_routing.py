"""Field-to-document routing and the unchanged-input hash (E66). No model call."""

from __future__ import annotations

import hashlib
import json

from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.datapoints import FieldDefinition


def route_documents(field: FieldDefinition, documents: list[SourceDocument]) -> list[SourceDocument]:
    r = field.document_routing
    if r is None:
        return [d for d in documents if not field.source_doc_types or d.doc_type in field.source_doc_types]
    for t in r.doc_types:
        hit = [d for d in documents if d.doc_type == t]
        if hit:
            return hit
    return list(documents) if r.fallback else []


def section_filter(field: FieldDefinition, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    r = field.document_routing
    if r is None or not r.sections:
        return chunks
    needles = [s.lower() for s in r.sections]
    kept = [c for c in chunks if c.section and any(n in c.section.lower() for n in needles)]
    return kept or (chunks if r.fallback else [])


def input_hash(
    field: FieldDefinition, documents: list[SourceDocument], planned_periods: list[str], run_settings: dict | None = None
) -> str | None:
    """`run_settings`: the effective settings that change extraction output (models, thresholds, retrieval mode)."""
    keys = [d.content_key or d.sha256 for d in documents]
    if not keys or not all(keys):
        return None
    payload = [field.field_id, field.version, sorted(keys), planned_periods, run_settings or {}]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()
