"""`arp documents warm --embed` precomputes the theme funnel's chunk embeddings (spec theme-funnel AC-30)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.cli import documents as documents_cli
from arp.ingestion.parsing import chunk_document
from arp.research import funnel
from arp.schemas.common import DocType, SourceDocument

DOCS = [SourceDocument(doc_id=f"d{i}", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="AR",
                       full_text=f"Document {i} about electrolysers.") for i in range(2)]


class _Registry:
    async def fetch_all(self, company, doc_types=None):
        return DOCS


class FakeStore:
    def __init__(self):
        self.vectors = {}

    def lookup_embeddings(self, chunk_ids, embed_model):
        return {k: self.vectors[k] for k in chunk_ids if k in self.vectors}

    def store_embeddings(self, vectors_by_chunk_id, embed_model):
        self.vectors.update(vectors_by_chunk_id)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("arp.db.session.require_postgres", lambda s: None)
    monkeypatch.setattr("arp.db.session.require_cutover", lambda s: None)
    monkeypatch.setattr(documents_cli, "_registry", lambda: _Registry())
    store = FakeStore()
    monkeypatch.setattr(documents_cli, "_funnel_content_store", lambda settings: store)
    embedded = []

    def embed(texts, load=None):
        embedded.extend(texts)
        return np.ones((len(texts), 2), dtype=np.float32), {}

    monkeypatch.setattr(funnel.models, "embed", embed)
    universe = tmp_path / "u.json"
    universe.write_text(json.dumps([{"company_id": "c1", "name": "Co"}]))
    return store, embedded, universe


def _warm(universe, *extra):
    return CliRunner().invoke(app, ["documents", "warm", "--universe", str(universe), *extra])


def test_warm_embed_stores_every_chunk(env):
    store, _, universe = env
    r = _warm(universe, "--embed")
    assert r.exit_code == 0, r.output
    assert set(store.vectors) == {c.chunk_id for d in DOCS for c in chunk_document(d)}
    assert "Embedded 2 new chunks (0 already stored)." in r.output


def test_warm_embed_rerun_embeds_nothing(env):
    _, embedded, universe = env
    _warm(universe, "--embed")
    embedded.clear()
    r = _warm(universe, "--embed")
    assert embedded == []
    assert "Embedded 0 new chunks (2 already stored)." in r.output


def test_warm_without_embed_unchanged(env):
    store, embedded, universe = env
    r = _warm(universe)
    assert r.exit_code == 0
    assert embedded == [] and store.vectors == {}
    assert "Embedded" not in r.output
    assert "Warmed 2 documents across 1 companies." in r.output


def test_warm_embed_without_dsn_exits_1(env, monkeypatch):
    _, _, universe = env
    monkeypatch.setattr(documents_cli, "_funnel_content_store", lambda settings: None)
    r = _warm(universe, "--embed")
    assert r.exit_code == 1
    assert "--embed needs ARP_POSTGRES_DSN" in r.output


def test_warm_embed_failure_is_reported_not_fatal(env, monkeypatch):  # review: embed error aborted the whole warm
    _, _, universe = env

    def boom(texts, load=None):
        raise RuntimeError("model down")

    monkeypatch.setattr(funnel.models, "embed", boom)
    r = _warm(universe, "--embed")
    assert "c1: embedding: model down" in r.output
    assert "Warmed 2 documents across 1 companies." in r.output
