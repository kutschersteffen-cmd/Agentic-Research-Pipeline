"""Unit tests for the OpenSearch live-indexing hook -- no real cluster
required: index_document (the real work) is monkeypatched out, so these
tests only verify index_document_if_enabled's own contract (gating,
exception-swallowing), not OpenSearch's behavior."""

from __future__ import annotations

import numpy as np
import pytest

from arp.ingestion.indexing_config import IndexingConfig
from arp.retrieval import search_indexer
from arp.schemas.common import DocType


def _kwargs(**overrides):
    base = dict(doc_id="doc_1", company_id="acme", doc_type=DocType.ANNUAL_REPORT_10K, title="Annual Report", full_text="hello world")
    base.update(overrides)
    return base


def test_noop_when_opensearch_url_unset(monkeypatch):
    calls = []
    monkeypatch.setattr(search_indexer, "index_document", lambda *a, **k: calls.append((a, k)))

    search_indexer.index_document_if_enabled(IndexingConfig(opensearch_url=None, search_live_indexing_enabled=True), **_kwargs())

    assert calls == []


def test_noop_when_live_indexing_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(search_indexer, "index_document", lambda *a, **k: calls.append((a, k)))

    search_indexer.index_document_if_enabled(
        IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=False), **_kwargs()
    )

    assert calls == []


def test_calls_index_document_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(search_indexer, "index_document", lambda config, **k: calls.append(k))

    config = IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=True)
    search_indexer.index_document_if_enabled(config, **_kwargs())

    assert len(calls) == 1
    assert calls[0]["doc_id"] == "doc_1"


def test_swallows_and_logs_exceptions(monkeypatch, caplog):
    def _raise(*a, **k):
        raise RuntimeError("cluster unreachable")

    monkeypatch.setattr(search_indexer, "index_document", _raise)
    config = IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=True)

    with caplog.at_level("WARNING"):
        search_indexer.index_document_if_enabled(config, **_kwargs())  # must not raise

    assert "doc_1" in caplog.text


def test_index_document_builds_bulk_actions_from_chunks(monkeypatch):
    """index_document itself (the unconditional path arp db reindex
    opensearch calls directly) -- mocks the opensearch client/bulk helper
    (no real cluster) and embed_texts (no real model download/load, which
    fails offline anyway) since neither is available in unit tests."""
    fake_module = pytest.importorskip("opensearchpy")  # only meaningful with the extra installed
    del fake_module

    bulk_calls = []
    monkeypatch.setattr("arp.storage.opensearch_client.get_client", lambda url: "fake-client")
    monkeypatch.setattr("opensearchpy.helpers.bulk", lambda client, actions: bulk_calls.append((client, list(actions))))
    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", lambda texts: np.zeros((len(texts), 384), dtype=np.float32))

    config = IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=True)
    search_indexer.index_document(config, **_kwargs(full_text="a" * 10))

    assert len(bulk_calls) == 1
    client, actions = bulk_calls[0]
    assert client == "fake-client"
    # one arp-documents action plus at least one arp-chunks action
    assert any(a["_index"] == "arp-documents" and a["_id"] == "doc_1" for a in actions)
    chunk_actions = [a for a in actions if a["_index"] == "arp-chunks"]
    assert chunk_actions
    assert all(len(a["_source"]["embedding"]) == 384 for a in chunk_actions)


def test_index_document_skips_embedding_call_when_no_chunks(monkeypatch):
    """An empty full_text produces zero chunks -- embed_texts must not be
    called with an empty list (fastembed rejects/mishandles that)."""
    pytest.importorskip("opensearchpy")
    embed_calls = []
    monkeypatch.setattr("arp.storage.opensearch_client.get_client", lambda url: "fake-client")
    monkeypatch.setattr("opensearchpy.helpers.bulk", lambda client, actions: None)
    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", lambda texts: embed_calls.append(texts) or np.zeros((len(texts), 384)))

    config = IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=True)
    search_indexer.index_document(config, **_kwargs(full_text=""))

    assert embed_calls == []
