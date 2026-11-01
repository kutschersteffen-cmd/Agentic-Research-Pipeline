"""The document tree: one node per outline heading (nested by level) plus one leaf per whole table, each
with a short model-written summary and key terms. Built once per document version and stored next to
parsed_content in content.db. Never evidence: nothing here reaches grounding or a citation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from arp.config import Settings
from arp.ingestion.outline import OutlineEntry, outline, page_at, page_count, page_starts
from arp.schemas.common import SourceDocument, now_iso
from arp.storage.parsed_content_cache import DOC_TREE_SCHEMA

logger = logging.getLogger(__name__)

TREE_VERSION = 1
_NODES_PER_CALL = 20
_WINDOW_PAGES = 5
_MIN_HEADINGS = 3

_SYSTEM = (
    "You summarise sections of a company report so a reader can find where a topic is covered. For each node "
    "give `summary`: 2-3 sentences on what it covers, and `key_terms`: 5-10 terms (metric names, years, scope "
    "words, named programmes). For German text give the German terms plus their English forms. Answer for every "
    "node_id you are given, and only those."
)


class TreeNode(BaseModel):
    node_id: str
    title: str
    heading_path: list[str] = Field(default_factory=list)
    level: int
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    table_id: str | None = None
    summary: str | None = None
    key_terms: list[str] = Field(default_factory=list)
    children: list[TreeNode] = Field(default_factory=list)


class DocTree(BaseModel):
    doc_id: str
    content_key: str
    parser_version: str
    tree_version: int
    incomplete: bool = False
    root: TreeNode


class NodeSummary(BaseModel):
    node_id: str
    summary: str
    key_terms: list[str] = Field(default_factory=list)


class TreeSummaries(BaseModel):
    nodes: list[NodeSummary] = Field(default_factory=list)


# --- structure (no model) -------------------------------------------------


def _node(doc: SourceDocument, starts: list[int], title: str, path: list[str], level: int, start: int, end: int, **kw) -> TreeNode:
    return TreeNode(
        node_id="", title=title, heading_path=path, level=level, page_start=page_at(starts, start),
        page_end=page_at(starts, max(start, end - 1)), char_start=start, char_end=end, **kw,
    )


def _walk(node: TreeNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def _structure(doc: SourceDocument) -> TreeNode:
    starts = page_starts(doc)
    root = _node(doc, starts, "", [], 0, 0, len(doc.full_text))
    root.node_id = "root"
    entries = outline(doc)
    if len(entries) < _MIN_HEADINGS:
        n = page_count(doc)
        bounds = [0, *starts, len(doc.full_text)]
        for first in range(1, n + 1, _WINDOW_PAGES):
            last = min(first + _WINDOW_PAGES - 1, n)
            title = f"Pages {first}–{last}"
            root.children.append(_node(doc, starts, title, [title], 1, bounds[first - 1], bounds[last]))
    else:
        stack: list[tuple[OutlineEntry, TreeNode]] = []
        for i, e in enumerate(entries):
            # a section runs to the next heading of its level or shallower
            end = next((f.char_start for f in entries[i + 1 :] if f.level <= e.level), len(doc.full_text))
            while stack and stack[-1][0].level >= e.level:
                stack.pop()
            parent = stack[-1][1] if stack else root
            node = _node(doc, starts, e.title, [*parent.heading_path, e.title], e.level, e.char_start, end)
            parent.children.append(node)
            stack.append((e, node))
    for t in doc.table_spans:  # a leaf in the deepest node holding the table
        parent = root
        while (inner := next((c for c in parent.children if c.table_id is None and c.char_start <= t.char_start < c.char_end), None)):
            parent = inner
        title = t.caption or f"Table {t.table_id}"
        parent.children.append(
            _node(doc, starts, title, list(parent.heading_path), parent.level + 1, t.char_start, t.char_end, table_id=t.table_id)
        )
        parent.children.sort(key=lambda c: c.char_start)
    for i, node in enumerate(n for n in _walk(root) if n is not root):
        node.node_id = f"{i:04d}"  # pre-order, as PageIndex numbers its nodes
    return root


# --- summaries (model) ----------------------------------------------------


def _height(node: TreeNode) -> int:
    return 1 + max(map(_height, node.children)) if node.children else 0


def _leaf_block(doc: SourceDocument, node: TreeNode, leaf_chars: int) -> str:
    return f"node_id: {node.node_id}\ntitle: {node.title}\ntext:\n{doc.full_text[node.char_start:node.char_end][:leaf_chars]}"


def _parent_block(node: TreeNode) -> str:
    # children by title and summary only: a prompt names just the node_ids it asks for
    parts = "\n".join(f"- {c.title}: {c.summary or '(no summary)'}" for c in node.children)
    return f"node_id: {node.node_id}\ntitle: {node.title}\nsubsections:\n{parts}"


async def _summarise(doc: SourceDocument, root: TreeNode, settings: Settings) -> None:
    from arp.llm.factory import build_llm_client

    client = build_llm_client(settings, model=settings.tree_summary_model)
    todo = [n for n in _walk(root) if n is not root and n.summary is None]
    for height in sorted({_height(n) for n in todo}):  # bottom-up: a parent reads its children's summaries
        level = [n for n in todo if _height(n) == height]
        batches = [level[i : i + _NODES_PER_CALL] for i in range(0, len(level), _NODES_PER_CALL)]
        await asyncio.gather(*(_summarise_batch(client, doc, b, settings) for b in batches))


async def _summarise_batch(client, doc: SourceDocument, batch: list[TreeNode], settings: Settings) -> None:
    blocks = [_parent_block(n) if n.children else _leaf_block(doc, n, settings.tree_leaf_chars) for n in batch]
    prompt = f"Document: {doc.title}\n\n" + "\n\n---\n\n".join(blocks)
    try:
        answer, usage = await client.complete_structured(system=_SYSTEM, prompt=prompt, output_model=TreeSummaries)
    except Exception:  # noqa: BLE001 - the nodes stay unsummarised; the next build retries them
        logger.warning("Tree summaries failed for %s (%d nodes)", doc.doc_id, len(batch), exc_info=True)
        return
    logger.info(
        "Tree summaries for %s: %d nodes, model=%s, input_tokens=%d, output_tokens=%d",
        doc.doc_id, len(batch), usage.model or settings.tree_summary_model, usage.input_tokens, usage.output_tokens,
    )
    by_id = {s.node_id: s for s in answer.nodes}
    for n in batch:
        if (s := by_id.get(n.node_id)) is not None:
            n.summary, n.key_terms = s.summary, list(s.key_terms)


# --- storage ----------------------------------------------------------------


def _connect(settings: Settings) -> sqlite3.Connection:
    settings.document_store_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.document_store_dir / "content.db", timeout=5.0)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(DOC_TREE_SCHEMA)
    return conn


def _key(doc: SourceDocument) -> tuple[str, str]:
    content_key = doc.content_key or doc.sha256 or hashlib.sha256(doc.full_text.encode("utf-8")).hexdigest()
    return content_key, doc.parser_version or ""


def _load(conn: sqlite3.Connection, content_key: str, parser_version: str) -> DocTree | None:
    row = conn.execute(
        "SELECT tree_json FROM doc_tree WHERE content_key = ? AND parser_version = ? AND tree_version = ?",
        (content_key, parser_version, TREE_VERSION),
    ).fetchone()
    return DocTree.model_validate_json(row[0]) if row else None


def stored_tree(doc_id: str, settings: Settings) -> DocTree | None:
    """The latest tree stored for `doc_id`, any version."""
    conn = _connect(settings)
    try:
        row = conn.execute("SELECT tree_json FROM doc_tree WHERE doc_id = ? ORDER BY rowid DESC LIMIT 1", (doc_id,)).fetchone()
    finally:
        conn.close()
    return DocTree.model_validate_json(row[0]) if row else None


async def _abuild(doc: SourceDocument, settings: Settings) -> DocTree:
    content_key, parser_version = _key(doc)
    conn = _connect(settings)
    try:
        tree = _load(conn, content_key, parser_version)
    finally:
        conn.close()
    if tree is not None and not tree.incomplete:
        return tree
    if tree is None:
        tree = DocTree(
            doc_id=doc.doc_id, content_key=content_key, parser_version=parser_version,
            tree_version=TREE_VERSION, root=_structure(doc),
        )
    await _summarise(doc, tree.root, settings)
    tree.incomplete = any(n.summary is None for n in _walk(tree.root) if n is not tree.root)
    conn = _connect(settings)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO doc_tree (content_key, parser_version, tree_version, doc_id, tree_json, incomplete, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (content_key, parser_version, TREE_VERSION, doc.doc_id, tree.model_dump_json(), int(tree.incomplete), now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return tree


def build_doc_tree(doc: SourceDocument, settings: Settings) -> DocTree:
    """The stored tree for this document version, built (and stored) first when there is none; an
    incomplete stored tree retries only its unsummarised nodes."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_abuild(doc, settings))
    with ThreadPoolExecutor(max_workers=1) as pool:  # called from inside an event loop
        return pool.submit(asyncio.run, _abuild(doc, settings)).result()


def format_tree(tree: DocTree) -> list[str]:
    """One line per node, root omitted: `<indent><title> (p.<start>–<end>) [<n> terms]`."""
    lines: list[str] = []

    def visit(node: TreeNode, depth: int) -> None:
        lines.append(f"{'  ' * depth}{node.title} (p.{node.page_start}–{node.page_end}) [{len(node.key_terms)} terms]")
        for child in node.children:
            visit(child, depth + 1)

    for top in tree.root.children:
        visit(top, 0)
    return lines


def dumps(tree: DocTree) -> str:
    return json.dumps(tree.model_dump(), indent=2, ensure_ascii=False)
