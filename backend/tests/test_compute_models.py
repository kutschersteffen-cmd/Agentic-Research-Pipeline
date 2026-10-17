import json
import sys
import types
from datetime import datetime, timedelta

import httpx
import numpy as np
import pytest

from arp.compute import client
from arp.config import Settings
from arp.extraction.field_graph import field_evidence
from arp.retrieval import embeddings, rerank
from arp.schemas.common import DocType, DocumentChunk, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition
from tests.test_compute_client import Recorder, _settings

RERANK = ("POST", "/rerank")
EMBED = ("POST", "/embed")


@pytest.fixture
def transport(monkeypatch, tmp_path):
    rec = Recorder()
    monkeypatch.setattr(client, "_http", httpx.Client(transport=httpx.MockTransport(rec)))
    monkeypatch.setattr(client, "_cooldown_until", {})
    monkeypatch.setattr(client, "last_error", {})
    monkeypatch.setattr(client, "_warned", set())
    monkeypatch.setattr(client, "_id_token", lambda audience: "tok")
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    monkeypatch.setattr(rerank, "_unavailable", False)
    settings = _settings(tmp_path)
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    return rec


def chunk(chunk_id):
    return DocumentChunk(
        chunk_id=chunk_id, doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K,
        text=chunk_id, char_start=0, char_end=1,
    )


class _FakeLocalEmbedder:
    def embed(self, texts):
        return [np.full(embeddings.EMBED_DIM, -1.0 - int(t[1:]), dtype=np.float32) for t in texts]


def _echo_vectors(request):
    texts = json.loads(request.content)["texts"]
    return httpx.Response(200, json={"vectors": [[float(t[1:])] * embeddings.EMBED_DIM for t in texts]})


def test_rerank_uses_cloud_scores(transport):  # AC-18
    transport.route(RERANK, 200, json={"scores": [0.1, 0.9, 0.5]})
    out = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
    assert [c.chunk_id for c in out] == ["b", "c"]
    assert transport.calls(RERANK)[0].headers["X-ARP-Model"] == client.CLOUD_RERANK_MODEL


def test_rerank_503_keeps_retrieval_order(transport, monkeypatch):  # AC-20
    transport.route(RERANK, 503)
    monkeypatch.setattr(rerank, "_get_model", lambda: pytest.fail("local reranker built"))
    out = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
    assert [c.chunk_id for c in out] == ["a", "b"]
    assert len(transport.calls(RERANK)) == 2


def test_token_refreshed_after_expiry(transport, monkeypatch):  # AC-17
    clock = [datetime(2026, 10, 17, 12, 0, 0)]

    class FakeCreds:
        issued = 0

        def __init__(self):
            self.token, self.expiry = None, None

        @property
        def valid(self):
            return self.token is not None and clock[0] < self.expiry

        def refresh(self, request):
            FakeCreds.issued += 1
            self.token, self.expiry = f"token-{FakeCreds.issued}", clock[0] + timedelta(seconds=3600)

    from google.oauth2 import service_account

    monkeypatch.setattr(client, "_id_token", lambda audience: client._token("id", audience))
    monkeypatch.setattr(client, "_creds", {})
    monkeypatch.setattr(
        service_account.IDTokenCredentials, "from_service_account_file", lambda *a, **k: FakeCreds()
    )
    transport.route(RERANK, 200, json={"scores": [0.2, 0.1]})
    assert client.rerank_scores("q", ["a", "b"]) == [0.2, 0.1]
    clock[0] += timedelta(seconds=3601)
    assert client.rerank_scores("q", ["a", "b"]) == [0.2, 0.1]
    first, second = (r.headers["Authorization"] for r in transport.calls(RERANK))
    assert first != second


def test_rerank_off_sends_nothing(transport):  # AC-19
    document = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="AR",
        full_text="Revenue grew strongly.\n\nThe annual bonus was paid in cash.",
    )
    field = FieldDefinition(
        name="bonus", description="d", data_type=FieldDataType.STRING, extraction_instructions="look",
        seed_keywords=["annual bonus"],
    )
    assert field_evidence(field, [document], Settings(hybrid_retrieval_enabled=False))
    assert transport.calls(RERANK) == []


def test_embed_batches_and_order(transport):  # AC-21
    transport.route(EMBED, _echo_vectors)
    out = embeddings.embed_texts([f"t{i}" for i in range(600)])
    assert [len(json.loads(r.content)["texts"]) for r in transport.calls(EMBED)] == [256, 256, 88]
    assert out.shape == (600, embeddings.EMBED_DIM) and out.dtype == np.float32
    assert all((out[i] == float(i)).all() for i in range(600))
    assert transport.calls(EMBED)[0].headers["X-ARP-Model"] == embeddings.EMBED_MODEL_NAME


def test_embed_batch_failure_recomputes_all_locally(transport, monkeypatch):  # AC-22
    def second_batch_fails(request):
        texts = json.loads(request.content)["texts"]
        return httpx.Response(503) if texts[0] == "t256" else _echo_vectors(request)

    transport.route(EMBED, second_batch_fails)
    monkeypatch.setattr(embeddings, "_get_model", lambda: _FakeLocalEmbedder())
    out = embeddings.embed_texts([f"t{i}" for i in range(600)])
    assert out.shape == (600, embeddings.EMBED_DIM)
    assert all((out[i] == -1.0 - i).all() for i in range(600))


def test_embed_409_falls_back(transport, monkeypatch):  # AC-46
    transport.route(EMBED, 409, json={"detail": "model mismatch"})
    monkeypatch.setattr(embeddings, "_get_model", lambda: _FakeLocalEmbedder())
    out = embeddings.embed_texts(["t0", "t1", "t2"])
    assert (out[2] == -3.0).all()
    assert len(transport.calls(EMBED)) == 1


def test_emerging_themes_embeds_in_cloud(transport, monkeypatch):  # AC-23
    from arp.emerging_themes import clustering

    transport.route(EMBED, lambda request: httpx.Response(
        200, json={"vectors": [[0.0] * embeddings.EMBED_DIM for _ in json.loads(request.content)["texts"]]}
    ))
    monkeypatch.setattr(clustering, "_tag_text", lambda tag: "t0")
    monkeypatch.setattr(clustering, "_run_once", lambda emb, size, seed: np.full(len(emb), -1))
    assert clustering.cluster_tags([object()] * 3, {}, {}, "2026-09") == []
    assert len(transport.calls(EMBED)) >= 1


def test_signal_lab_embedder_stays_local(transport, monkeypatch):  # AC-48
    from arp.signal_lab.methods.embedding import default_embedder

    class FakeTextEmbedding:
        def __init__(self, model_name):
            pass

        def embed(self, texts):
            return [np.ones(4) for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding))
    assert default_embedder().embed(["a", "b"]).shape == (2, 4)
    assert transport.calls(EMBED) == []


def test_models_unset_makes_no_requests(transport, monkeypatch):  # AC-1
    empty = Settings(compute_parse_url="", compute_models_url="", compute_bucket="", compute_credentials_file="")
    monkeypatch.setattr(client, "get_settings", lambda: empty)
    monkeypatch.setattr(rerank, "_score", lambda q, texts: [0.1, 0.9])
    monkeypatch.setattr(embeddings, "_get_model", lambda: _FakeLocalEmbedder())
    assert [c.chunk_id for c in rerank.rerank("q", [chunk("a"), chunk("b")], top_n=1)] == ["b"]
    assert embeddings.embed_texts(["t0"]).shape == (1, embeddings.EMBED_DIM)
    assert transport.requests == []


@pytest.mark.parametrize("body", [{"detail": "x"}, {"scores": [0.5]}, {"scores": ["high", "low", "mid"]}])
def test_malformed_rerank_reply_keeps_retrieval_order(transport, body):  # final review I6
    transport.route(RERANK, 200, json=body)
    out = rerank.rerank("q", [chunk("a"), chunk("b"), chunk("c")], top_n=2)
    assert [c.chunk_id for c in out] == ["a", "b"]


@pytest.mark.parametrize("vectors", [[[0.0] * 384], [[0.0] * 768] * 3, "nope"])
def test_malformed_embed_reply_falls_back(transport, monkeypatch, vectors):  # final review I6
    transport.route(EMBED, 200, json={"vectors": vectors})
    monkeypatch.setattr(embeddings, "_get_model", lambda: _FakeLocalEmbedder())
    out = embeddings.embed_texts(["t0", "t1", "t2"])
    assert out.shape == (3, embeddings.EMBED_DIM) and (out[2] == -3.0).all()


def test_models_calls_capped_at_service_capacity(transport):  # final review I5
    import threading
    import time

    state = {"in_flight": 0, "max": 0}
    lock, full = threading.Lock(), threading.Event()

    def handler(request):
        with lock:
            state["in_flight"] += 1
            state["max"] = max(state["max"], state["in_flight"])
            if state["in_flight"] >= client.MODELS_SLOTS:
                full.set()
        full.wait(2)
        time.sleep(0.05)
        with lock:
            state["in_flight"] -= 1
        return httpx.Response(200, json={"scores": [0.1]})

    transport.route(RERANK, handler)
    threads = [threading.Thread(target=client.rerank_scores, args=("q", ["a"])) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert state["max"] == client.MODELS_SLOTS == 8
