"""What BM25 and the embedding ranking index for a chunk. Evidence, grounding and citations always use
`chunk.text`; only ranking sees the header and tree lines."""

from __future__ import annotations

from arp.config import Settings
from arp.ingestion.doc_tree import DocTree, node_for, tree_for
from arp.ingestion.outline import heading_path
from arp.schemas.common import DocumentChunk, SourceDocument


def index_text(chunk: DocumentChunk, doc: SourceDocument, settings: Settings) -> str:
    """`chunk.text`, or with `context_headers_enabled` a header line (title · fiscal period · heading path)
    and, for a table passage, a `Table:` line (caption · unit · column headers) before it; with
    `tree_context_enabled` too, its tree node's `Summary:` and `Terms:` lines after those."""
    return index_texts([chunk], doc, settings)[0]


def index_texts(chunks: list[DocumentChunk], doc: SourceDocument, settings: Settings) -> list[str]:
    """`index_text` for each chunk of one document, reading its stored tree once."""
    if not settings.context_headers_enabled:
        return [c.text for c in chunks]
    tree = tree_for(doc, settings) if settings.tree_context_enabled and chunks else None
    return [_index_text(c, doc, tree) for c in chunks]


def _index_text(chunk: DocumentChunk, doc: SourceDocument, tree: DocTree | None) -> str:
    path = " › ".join(heading_path(doc, chunk.char_start))
    lines = [" · ".join(v for v in (doc.title, doc.fiscal_period, path) if v)]
    table = next((t for t in doc.table_spans if t.table_id == chunk.table_id), None) if chunk.table_id else None
    if table is not None:
        cols = " | ".join(dict.fromkeys(c.col_label for c in table.cells if c.col_label))
        lines.append("Table: " + " · ".join(v for v in (table.caption, table.unit_note, cols) if v))
    node = node_for(tree, chunk.char_start, chunk.table_id) if tree is not None else None
    if node is not None and node.summary is not None:
        lines.append(f"Summary: {node.summary}")
        if node.key_terms:
            lines.append("Terms: " + ", ".join(node.key_terms))
    return "\n".join([*lines, chunk.text])
