"""Spec tree-context-for-chunks: the stored tree node's summary and key terms in the index text."""

from __future__ import annotations

import asyncio

import pytest

from arp.config import Settings, get_settings
from arp.ingestion import doc_tree
from arp.ingestion.parsing import chunk_document
from arp.retrieval.index_text import index_text
from tests.test_section_chunks_headers_tree import _answer, _calls, _tree_doc


@pytest.fixture
def standins(tmp_path, monkeypatch):
    folder = tmp_path / "standins"
    (folder / "model").mkdir(parents=True)
    monkeypatch.setenv("ARP_STANDINS_DIR", str(folder))
    monkeypatch.delenv("ARP_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ARP_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ARP_DOCUMENT_STORE_DIR", str(tmp_path / "store"))
    get_settings.cache_clear()
    yield folder
    get_settings.cache_clear()


TITLES = {"0000": "A", "0001": "A1", "0002": "t1", "0003": "A2", "0004": "B"}


def _on(**kw) -> Settings:
    return get_settings().model_copy(update={"tree_context_enabled": True, **kw})


def _headers_only(chunk, doc):
    return index_text(chunk, doc, get_settings().model_copy(update={"tree_context_enabled": False}))


def _with_tree(chunk, doc, node_id):
    head = _headers_only(chunk, doc)[: -len(chunk.text)]
    return f"{head}Summary: about {node_id}\nTerms: {node_id}, t\n{chunk.text}"


def test_index_text_adds_the_chunks_node_lines(standins):
    doc = _tree_doc()
    _answer(standins, list(TITLES))
    doc_tree.build_doc_tree(doc, get_settings())
    a1 = doc.full_text.index("## A1")
    table = next(c for c in chunk_document(doc) if c.table_id == "t1")
    in_a1 = table.model_copy(update={"table_id": None, "char_start": a1 + 1, "char_end": doc.full_text.index("## A2") + 3})
    in_a = table.model_copy(update={"table_id": None, "char_start": 1})
    assert index_text(in_a1, doc, _on()) == _with_tree(in_a1, doc, "0001")  # runs into A2, gets only A1's lines
    assert index_text(table, doc, _on()) == _with_tree(table, doc, "0002")
    assert index_text(in_a, doc, _on()) == _with_tree(in_a, doc, "0000")
    assert index_text(in_a1, doc, _on(context_headers_enabled=False)) == in_a1.text
    assert index_text(in_a1, doc, get_settings()) == _headers_only(in_a1, doc)  # off by default


def test_no_summary_no_tree_or_old_version_is_headers_only(standins, monkeypatch):
    doc = _tree_doc()
    chunks = chunk_document(doc)
    assert [index_text(c, doc, _on()) for c in chunks] == [_headers_only(c, doc) for c in chunks]
    assert _calls(standins) == []  # retrieval never builds a tree

    _answer(standins, ["0000", "0002", "0003", "0004"])  # A1 fails
    doc_tree.build_doc_tree(doc, get_settings())  # stored after the miss above: picked up now
    a1 = next(c for c in chunks if c.table_id is None).model_copy(update={"char_start": doc.full_text.index("## A1") + 1})
    assert index_text(a1, doc, _on()) == _headers_only(a1, doc)  # A1 has no summary; A's is not used
    a = a1.model_copy(update={"char_start": 1})
    assert "Summary: about 0000" in index_text(a, doc, _on())

    monkeypatch.setattr(doc_tree, "TREE_VERSION", doc_tree.TREE_VERSION + 1)
    assert index_text(a, doc, _on()) == _headers_only(a, doc)


def test_registry_builds_trees_with_tree_context(standins, tmp_path):
    from arp.ingestion.base import DocumentSource
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.schemas.common import CompanyRef

    doc = _tree_doc()

    class _One(DocumentSource):
        name = "one"

        async def fetch(self, company, doc_types=None):
            return [doc]

    _answer(standins, list(TITLES))
    company = CompanyRef(company_id="c1", name="c1")
    asyncio.run(DocumentSourceRegistry([_One()], get_settings()).fetch_all(company))
    assert _calls(standins) == [] and doc_tree.tree_for(doc, get_settings()) is None
    asyncio.run(DocumentSourceRegistry([_One()], _on()).fetch_all(company))
    assert doc_tree.tree_for(doc, get_settings()) is not None


def test_input_hash_changes_only_with_tree_context_on():
    from arp.extraction.pipeline import input_settings

    off = input_settings(Settings(anthropic_api_key="x"))
    assert "tree_context_enabled" not in off
    assert input_settings(Settings(anthropic_api_key="x", tree_context_enabled=True)) != off
    assert input_settings(Settings(anthropic_api_key="x", tree_context_enabled=True, context_headers_enabled=False)) == \
        input_settings(Settings(anthropic_api_key="x", context_headers_enabled=False))


def test_unreadable_tree_falls_back_to_headers_only(standins, monkeypatch):
    from arp.retrieval import index_text as module

    doc = _tree_doc()
    chunk = chunk_document(doc)[0]
    monkeypatch.setattr(module, "tree_for", lambda *a: (_ for _ in ()).throw(RuntimeError("database is locked")))
    assert index_text(chunk, doc, _on()) == _headers_only(chunk, doc)


def test_switching_tree_context_embeds_each_text_once(standins, monkeypatch):
    import numpy as np

    from arp.extraction import field_graph
    from arp.retrieval import content_store_factory, embeddings
    from arp.schemas.datapoints import FieldDefinition

    class _Store:
        rows: dict = {}  # one store across the selections, like the Postgres cache

        def lookup_embeddings(self, ids, model):
            return {i: self.rows[i] for i in ids if i in self.rows}

        def store_embeddings(self, vectors, model):
            self.rows.update(vectors)

    monkeypatch.setattr(content_store_factory, "build_hybrid_content_store", lambda s: _Store())
    embedded: list[str] = []
    monkeypatch.setattr(embeddings, "embed_texts", lambda t: embedded.extend(t) or np.ones((len(t), 3), dtype=np.float32))
    doc = _tree_doc()
    _answer(standins, list(TITLES))
    doc_tree.build_doc_tree(doc, get_settings())
    field = FieldDefinition(name="f", description="d", data_type="number", extraction_instructions="x", seed_keywords=["text"])
    off = get_settings().model_copy(update={"hybrid_retrieval_enabled": True, "small_to_big_enabled": False})
    field_graph.field_evidence(field, [doc], off)
    embedded.clear()
    for _ in range(2):
        field_graph.field_evidence(field, [doc], _on(hybrid_retrieval_enabled=True, small_to_big_enabled=False))
    assert sorted(embedded) == sorted(index_text(c, doc, _on()) for c in chunk_document(doc, keywords=["text"]))
    embedded.clear()
    field_graph.field_evidence(field, [doc], off)
    assert embedded == []  # headers-only vectors and the query's are reused
