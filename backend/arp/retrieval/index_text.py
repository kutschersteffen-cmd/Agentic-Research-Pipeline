"""What BM25 and the embedding ranking index for a chunk. Evidence, grounding and citations always use
`chunk.text`; only ranking sees the header lines."""

from __future__ import annotations

from arp.config import Settings
from arp.ingestion.outline import heading_path
from arp.schemas.common import DocumentChunk, SourceDocument


def index_text(chunk: DocumentChunk, doc: SourceDocument, settings: Settings) -> str:
    """`chunk.text`, or with `context_headers_enabled` a header line (title · fiscal period · heading path)
    and, for a table passage, a `Table:` line (caption · unit · column headers) before it."""
    if not settings.context_headers_enabled:
        return chunk.text
    path = " › ".join(heading_path(doc, chunk.char_start))
    lines = [" · ".join(v for v in (doc.title, doc.fiscal_period, path) if v)]
    table = next((t for t in doc.table_spans if t.table_id == chunk.table_id), None) if chunk.table_id else None
    if table is not None:
        cols = " | ".join(dict.fromkeys(c.col_label for c in table.cells if c.col_label))
        lines.append("Table: " + " · ".join(v for v in (table.caption, table.unit_note, cols) if v))
    return "\n".join([*lines, chunk.text])
