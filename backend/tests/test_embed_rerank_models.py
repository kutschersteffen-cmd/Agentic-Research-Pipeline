"""Selectable embedders and rerankers on arp-models (spec embeddings-and-reranker-upgrade)."""

import json
import logging
from pathlib import Path

import httpx
import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arp.compute import client, server
from arp.config import Settings
from arp.models.registry import entry, model_header
from arp.retrieval import embeddings, rerank
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocType, DocumentChunk

E5 = "intfloat/multilingual-e5-large@3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
BGE = "BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181"
COLBERT = "lightonai/mLateOn@bbd883ae1fadb563056ff73b1061ae8172a3fcda"


def _chunk(text, start=0):
    return DocumentChunk(doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, text=text,
                         char_start=start, char_end=start + len(text))


CHUNKS = [_chunk(t, i * 100) for i, t in enumerate(["capex rose", "capex fell sharply", "unrelated words"])]


class _DictStore:
    def __init__(self):
        self.rows: dict[tuple[str, str], np.ndarray] = {}

    def lookup_embeddings(self, chunk_ids, model):
        return {c: self.rows[(c, model)] for c in chunk_ids if (c, model) in self.rows}

    def store_embeddings(self, vectors, model):
        self.rows.update({(c, model): v for c, v in vectors.items()})


class _LocalMiniLM:  # deterministic: a text's vector is its length in one of 384 slots
    def embed(self, texts):
        return [np.eye(384, dtype=np.float32)[len(t) % 384] + 0.01 for t in texts]


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(embeddings, "_get_model", lambda: _LocalMiniLM())
    monkeypatch.setattr(client, "_warned", set())
    monkeypatch.setattr(client, "models_configured", lambda: False)


@pytest.fixture
def cloud(local, monkeypatch):
    """A configured arp-models stand-in recording (texts, model) per embed call."""
    calls: list[tuple[list[str], str]] = []
    answer = {"dim": 1024, "query": "ok"}

    def fake_embed(texts, model_header=None, dim=None):
        calls.append((texts, model_header))
        if answer["query"] is None and len(texts) == 1 and texts[0].startswith(("query: ", "capex")):
            return None
        rng = np.random.default_rng(len(calls))
        return rng.random((len(texts), answer["dim"]), dtype=np.float32)

    monkeypatch.setattr(client, "models_configured", lambda: True)
    monkeypatch.setattr(client, "embed", fake_embed)
    return calls, answer


def _rank(embed_model="minilm", store=None, **kw):
    explain: dict = {}
    out = select_relevant_chunks(CHUNKS, ["capex"], max_chunks=3, hybrid_retrieval_enabled=True,
                                 content_store=store or _DictStore(), explain=explain, embed_model=embed_model, **kw)
    return [c.chunk_id for c in out], explain


def test_settings_defaults_and_validation(monkeypatch):  # AC-1, AC-2, AC-2b
    s = Settings()
    assert (s.embed_model, s.rerank_model, s.rerank_enabled) == ("minilm", "cross-encoder", False)
    monkeypatch.setenv("ARP_EMBED_MODEL", "e5-small")
    with pytest.raises(ValidationError, match="minilm.*e5-large.*bge-m3"):
        Settings()
    monkeypatch.delenv("ARP_EMBED_MODEL")
    monkeypatch.setenv("ARP_RERANK_MODEL", "foo")
    with pytest.raises(ValidationError, match="cross-encoder.*colbert"):
        Settings()


def test_registry_entries():  # AC-13
    assert model_header(entry("embed_e5_large")) == E5
    assert model_header(entry("embed_bge_m3")) == BGE
    assert model_header(entry("rerank_colbert")) == COLBERT
    assert "jinaai/jina-colbert-v2" not in Path("arp/models/allowed.txt").read_text().split()


def test_e5_prefixes_query_and_passages(cloud):  # AC-4, AC-8b
    calls, _ = cloud
    store = _DictStore()
    _, explain = _rank("e5-large", store)
    assert {m for _, m in calls} == {E5}
    passages, query = calls[0][0], calls[1][0]
    assert all(t.startswith("passage: ") for t in passages) and query[0].startswith("query: ")
    assert explain["embed_model"] == "embed_e5_large"
    _, ref = _rank("minilm", store)
    by_model = lambda m: {c for c, model in store.rows if model == m}  # noqa: E731
    assert by_model("intfloat/multilingual-e5-large") == by_model(embeddings.EMBED_MODEL_NAME) and len(by_model(embeddings.EMBED_MODEL_NAME)) == 3


def test_bge_m3_has_no_prefix(cloud):  # AC-5
    calls, _ = cloud
    _, explain = _rank("bge-m3")
    assert {m for _, m in calls} == {BGE}
    assert not any(t.startswith(("query: ", "passage: ")) for texts, _ in calls for t in texts)
    assert explain["embed_model"] == "embed_bge_m3"


def test_unconfigured_falls_back_to_minilm_and_warns_once(local, caplog):  # AC-6
    reference = _rank("minilm")[0]
    with caplog.at_level(logging.WARNING):
        first, ex1 = _rank("e5-large")
        second, ex2 = _rank("e5-large")
    assert first == second == reference
    assert ex1["embed_model"] == ex2["embed_model"] == "embed"
    assert caplog.text.count("arp-models unavailable; embedding with MiniLM") == 1


def test_failed_query_falls_back_but_keeps_chunk_vectors(cloud, monkeypatch):  # AC-7
    _, answer = cloud
    answer["query"] = None
    store = _DictStore()
    order, explain = _rank("e5-large", store)
    assert explain["embed_model"] == "embed"
    assert sum(model == "intfloat/multilingual-e5-large" for _, model in store.rows) == 3
    assert all(v.shape == (1024,) for (_, model), v in store.rows.items() if model == "intfloat/multilingual-e5-large")
    monkeypatch.setattr(client, "models_configured", lambda: False)
    assert order == _rank("minilm")[0]


def test_wrong_dim_or_error_falls_back(cloud, monkeypatch):  # AC-7c
    _, answer = cloud
    answer["dim"] = 384
    assert _rank("e5-large")[1]["embed_model"] == "embed"

    def boom(*a, **k):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(client, "embed", boom)
    assert _rank("e5-large")[1]["embed_model"] == "embed"


@pytest.fixture
def reranker(monkeypatch):
    monkeypatch.setattr(rerank, "_unavailable", False)
    received = []

    def fake(query, texts, model_header=client.CLOUD_RERANK_MODEL):
        received.append(model_header)
        return [0.1, 0.9, 0.5]

    monkeypatch.setattr(client, "rerank_scores", fake)
    return received


def test_colbert_reranks_on_arp_models(reranker, monkeypatch):  # AC-9
    monkeypatch.setattr(client, "models_configured", lambda: True)
    explain: dict = {}
    select_relevant_chunks(CHUNKS, ["capex", "unrelated"], max_chunks=3, rerank_candidates=3,
                           rerank_model="colbert", explain=explain)
    assert reranker == [COLBERT]
    assert explain["reranked"] is True and explain["rerank_model"] == "rerank_colbert"


def test_colbert_direct_order(reranker, monkeypatch):  # AC-9
    monkeypatch.setattr(client, "models_configured", lambda: True)
    assert rerank.rerank("q", CHUNKS, 3, model="colbert") == [CHUNKS[1], CHUNKS[2], CHUNKS[0]]


def test_colbert_without_or_failing_arp_models_keeps_order(reranker, monkeypatch):  # AC-10, AC-10b
    monkeypatch.setattr(client, "models_configured", lambda: False)
    explain: dict = {}
    out = select_relevant_chunks(CHUNKS, ["capex", "unrelated"], max_chunks=3, rerank_candidates=3,
                                 rerank_model="colbert", explain=explain)
    assert reranker == [] and explain["reranked"] is False and explain["rerank_model"] is None
    monkeypatch.setattr(client, "models_configured", lambda: True)

    def boom(*a, **k):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(client, "rerank_scores", boom)
    assert rerank.rerank("q", CHUNKS, 3, model="colbert") == CHUNKS
    assert out == select_relevant_chunks(CHUNKS, ["capex", "unrelated"], max_chunks=3)


def test_local_cross_encoder_trace(monkeypatch):  # AC-11
    monkeypatch.setattr(rerank, "_unavailable", False)
    monkeypatch.setattr(client, "models_configured", lambda: False)
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [0.2, 0.8, 0.5][: len(texts)])
    assert rerank.rerank("q", CHUNKS, 3) == [CHUNKS[1], CHUNKS[2], CHUNKS[0]]
    explain: dict = {}
    select_relevant_chunks(CHUNKS, ["capex", "unrelated"], max_chunks=3, rerank_candidates=3, explain=explain)
    assert explain["reranked"] is True and explain["rerank_model"] == "rerank"


class _Fake:
    def embed(self, texts):
        return [[0.5] * 1024 for _ in texts]

    def rerank(self, query, texts):
        return [float(i) for i, _ in enumerate(texts)]


def test_server_serves_every_registry_model(monkeypatch):  # AC-12, AC-12b, AC-12c
    monkeypatch.setattr(server, "_embedder", lambda *a: _Fake())
    monkeypatch.setattr(server, "_reranker", lambda *a: _Fake())
    c = TestClient(server.app)
    for name in (E5, BGE):
        r = c.post("/embed", json={"texts": ["a", "b"]}, headers={"X-ARP-Model": name})
        assert r.status_code == 200 and [len(v) for v in r.json()["vectors"]] == [1024, 1024]
    assert c.post("/embed", json={"texts": ["a"]}, headers={"X-ARP-Model": "jinaai/jina-colbert-v2@x"}).status_code == 409
    assert c.post("/rerank", json={"query": "q", "texts": ["a"]}, headers={"X-ARP-Model": E5}).status_code == 409
    r = c.post("/rerank", json={"query": "q", "texts": ["a", "b", "c"]}, headers={"X-ARP-Model": COLBERT})
    assert r.status_code == 200 and len(r.json()["scores"]) == 3


def test_maxsim_scores():
    class Late:
        model = object()

        def query_embed(self, q):
            yield np.array([[1.0, 0.0], [0.0, 1.0]])

        def embed(self, texts):
            yield from (np.array([[1.0, 0.0]]), np.array([[1.0, 0.0], [0.0, 2.0]]))

    assert server._MaxSim(Late()).rerank("q", ["a", "b"]) == [1.0, 3.0]


def test_postgres_column_takes_any_dimension(pg):  # AC-8
    from sqlalchemy import create_engine, text
    from typer.testing import CliRunner

    from arp.cli import app
    from arp.storage.postgres_schema import _MIGRATIONS_TABLE

    engine = create_engine(pg)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("DROP TABLE IF EXISTS chunk_embeddings"))
        conn.execute(text("CREATE TABLE chunk_embeddings (chunk_id varchar, embed_model varchar, embedding vector(384), "
                          "PRIMARY KEY (chunk_id, embed_model))"))
        conn.execute(text("INSERT INTO chunk_embeddings VALUES ('c1', :m, :v)"),
                     {"m": embeddings.EMBED_MODEL_NAME, "v": str([0.25] * 384)})
        conn.execute(text(f"DELETE FROM {_MIGRATIONS_TABLE} WHERE name = 'chunk_embeddings_any_dim'"))
    for _ in range(2):
        result = CliRunner().invoke(app, ["db", "init-postgres"])
        assert result.exit_code == 0, result.output
    from arp.storage.postgres_embeddings import PgVectorEmbeddingsStore

    store = PgVectorEmbeddingsStore(pg)
    store.store_embeddings({"c1": np.full(1024, 0.5, dtype=np.float32)}, "intfloat/multilingual-e5-large")
    assert store.lookup_embeddings(["c1"], embeddings.EMBED_MODEL_NAME)["c1"].tolist() == [0.25] * 384
    assert store.lookup_embeddings(["c1"], "intfloat/multilingual-e5-large")["c1"].shape == (1024,)


def test_ci_cache_key_hashes_the_embed_model_file():  # AC-17
    ci = yaml.safe_load(Path("../.github/workflows/ci.yml").read_text())
    steps = ci["jobs"]["retrieval-recall"]["steps"]
    key = next(s for s in steps if s.get("id") == "cache")["with"]["key"]
    assert "backend/.retrieval-embed-model.txt" in key and "backend/arp/retrieval/embeddings.py" not in key
    install = next(s for s in steps if s.get("name") == "Install backend package")["run"]
    assert ">.retrieval-embed-model.txt" in install
    run = next(s for s in steps if s.get("name") == "Run the retrieval gold set")["run"]
    assert "--min-recall 0.701" in run


def test_header_matches_ci_file_contents():
    assert model_header(entry("embed")) == f"{embeddings.EMBED_MODEL_NAME}@e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


def _write_cases(tmp_path):
    folder = tmp_path / "documents" / "a"
    folder.mkdir(parents=True)
    filler = "Our revenue grew strongly this year and the dividend was raised. " * 200
    gold = ["We commit to a net zero target for the whole group by 2045.", "Scope 1 GHG emissions were 1,234 tCO2e."]
    (folder / "report.txt").write_text(filler + " ".join(gold) + filler)
    cases = [{"case_id": f"a-{f}", "schema_id": "transition_plan_indicators", "field_id": f, "company_id": "a",
              "document": "report.txt", "gold": [{"span_text": g}], "labelled_by": "agent", "spot_checked": False}
             for f, g in zip(["tp_a_ambition_3", "tp_a_emissions_59"], gold, strict=True)]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    return path


def _cli(*args):
    from typer.testing import CliRunner

    from arp.cli import app

    return CliRunner().invoke(app, ["golden-set", "retrieval", *args])


def test_cli_compares_every_combination(pg, tmp_path, local, monkeypatch):  # AC-14, AC-15, AC-15b, AC-15d
    monkeypatch.setenv("ARP_DOCUMENT_STORE_DIR", str(tmp_path / "store"))
    cases, out = _write_cases(tmp_path), tmp_path / "out.json"
    result = _cli("--cases", str(cases), "--hybrid", "--embed-model", "minilm,e5-large", "--rerank-model", "off,colbert",
                  "--out", str(out))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    prefixes = ["embed=minilm rerank=off", "embed=minilm rerank=colbert", "embed=e5-large rerank=off",
                "embed=e5-large rerank=colbert"]
    assert [ln.split(":")[0] for ln in lines] == prefixes
    assert [ln.rsplit("; ", 1)[1] for ln in lines] == ["fallback 0 field(s).", "fallback 2 field(s).",
                                                       "fallback 2 field(s).", "fallback 2 field(s)."]
    reports = json.loads(out.read_text())
    assert [r["fallback_fields"] for r in reports] == [0, 2, 2, 2]
    assert [r["settings"]["rerank_model"] for r in reports] == [None, "colbert", None, "colbert"]

    bad = _cli("--cases", str(cases), "--embed-model", "foo")
    assert bad.exit_code == 2 and "--embed-model must be one of minilm, e5-large, bge-m3" in bad.stderr
    bad = _cli("--cases", str(cases), "--rerank-model", "foo")
    assert bad.exit_code == 2 and "--rerank-model must be one of off, cross-encoder, colbert" in bad.stderr


def test_batches_that_came_back_stay_stored(cloud, monkeypatch):  # review: spec section 4
    calls, _ = cloud
    real = client.embed

    def second_batch_fails(texts, model_header=None, dim=None):
        return None if len(calls) == 1 else real(texts, model_header, dim)

    monkeypatch.setattr(client, "EMBED_BATCH", 2)
    monkeypatch.setattr(client, "embed", second_batch_fails)
    store = _DictStore()
    assert _rank("e5-large", store)[1]["embed_model"] == "embed"
    assert sum(model == "intfloat/multilingual-e5-large" for _, model in store.rows) == 2


def test_409_for_one_model_keeps_the_cross_encoder(monkeypatch, tmp_path):  # review: per-model cooldown
    from tests.test_compute_client import Recorder, _settings

    rec = Recorder()
    rec.route(("POST", "/embed"), 409, json={"detail": "model not served"})
    rec.route(("POST", "/rerank"), 200, json={"scores": [0.1, 0.2]})
    monkeypatch.setattr(client, "_http", httpx.Client(transport=httpx.MockTransport(rec)))
    monkeypatch.setattr(client, "_cooldown_until", {})
    monkeypatch.setattr(client, "_id_token", lambda audience: "tok")
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    settings = _settings(tmp_path)
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    assert client.embed(["a"], E5, 1024) is None
    assert client.embed(["a"], E5, 1024) is None
    assert len(rec.calls(("POST", "/embed"))) == 1  # that model cools down
    assert client.rerank_scores("q", ["a", "b"]) == [0.1, 0.2]
