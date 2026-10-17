import threading

import pytest
from fastapi.testclient import TestClient

from arp.compute import server
from arp.compute.client import CLOUD_RERANK_MODEL
from arp.retrieval.embeddings import EMBED_MODEL_NAME

OBJ = f"parse/{'a' * 64}.pdf"
V1 = {"X-ARP-Parser-Version": "v1"}


class _FakeReranker:
    def rerank(self, query, texts, batch_size=64):
        return [float(len(t)) for t in texts]


class _FakeEmbedder:
    def embed(self, texts, batch_size=256):
        return [[float(i)] * 3 for i, _ in enumerate(texts)]


@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_COMPUTE_GCS_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "parser_version", lambda: "v1")
    monkeypatch.setattr(server, "parse_file_to_text_with_pages", lambda path: ("T", [0], []))
    monkeypatch.setattr(server, "_reranker", lambda: _FakeReranker())
    monkeypatch.setattr(server, "_embedder", lambda: _FakeEmbedder())
    (tmp_path / "parse").mkdir()
    return TestClient(server.app)


def _put_object(tmp_path):
    (tmp_path / OBJ).write_bytes(b"%PDF-1.4")


@pytest.mark.parametrize("obj", ["../etc/passwd", "parse/abc.pdf", f"parse/{'a' * 64}.docx"])
def test_parse_rejects_bad_object(c, obj):  # AC-24
    assert c.post("/parse", json={"object": obj}, headers=V1).status_code == 422


@pytest.mark.parametrize("headers,client_v", [({"X-ARP-Parser-Version": "v0"}, "v0"), ({}, "missing")])
def test_parse_version_mismatch(c, tmp_path, headers, client_v):  # AC-25
    _put_object(tmp_path)
    r = c.post("/parse", json={"object": OBJ}, headers=headers)
    assert r.status_code == 409
    assert "service=v1" in r.json()["detail"] and f"client={client_v}" in r.json()["detail"]


def test_parse_ok(c, tmp_path):  # AC-26
    _put_object(tmp_path)
    r = c.post("/parse", json={"object": OBJ}, headers=V1)
    assert r.status_code == 200
    assert set(r.json()) == {"text", "page_breaks", "table_spans"}
    assert r.json()["text"] == "T"


def test_parse_missing_file_is_404(c):  # AC-41
    r = c.post("/parse", json={"object": OBJ}, headers=V1)
    assert r.status_code == 404 and r.json()["detail"] == f"object not found: {OBJ}"


def test_parse_error_is_422(c, tmp_path, monkeypatch):
    _put_object(tmp_path)

    def boom(path):
        raise ValueError("bad")

    monkeypatch.setattr(server, "parse_file_to_text_with_pages", boom)
    r = c.post("/parse", json={"object": OBJ}, headers=V1)
    assert r.status_code == 422 and r.json()["detail"] == "parse failed: ValueError: bad"


def test_model_header_mismatch_is_409(c):  # AC-45
    other = {"X-ARP-Model": "other"}
    assert c.post("/embed", json={"texts": ["a"]}, headers=other).status_code == 409
    assert c.post("/rerank", json={"query": "q", "texts": ["a"]}, headers=other).status_code == 409


def test_rerank_and_embed_shapes(c):
    r = c.post("/rerank", json={"query": "q", "texts": ["a", "bbb"]}, headers={"X-ARP-Model": CLOUD_RERANK_MODEL})
    assert r.json() == {"scores": [1.0, 3.0]}
    model = {"X-ARP-Model": EMBED_MODEL_NAME}
    assert c.post("/embed", json={"texts": ["a", "b"]}, headers=model).json() == {"vectors": [[0.0] * 3, [1.0] * 3]}
    assert c.post("/embed", json={"texts": ["x"] * 1025}, headers=model).status_code == 422


def test_model_built_once_under_burst(monkeypatch):  # Review 4
    built = []

    class SlowModel:
        def __init__(self, *args, **kwargs):
            built.append(1)
            threading.Event().wait(0.1)
            self.model = type("Inner", (), {"model": _Session(["CUDAExecutionProvider", "CPUExecutionProvider"])})()

    monkeypatch.setattr(server, "_load_embedder", SlowModel)
    monkeypatch.setattr(server, "_models", {})
    threads = [threading.Thread(target=server._embedder) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert built == [1]


def test_healthz_answers_during_parse(c, tmp_path, monkeypatch):  # Review 5
    _put_object(tmp_path)
    started, release = threading.Event(), threading.Event()

    def slow_parse(path):
        started.set()
        release.wait(5)
        return ("T", [0], [])

    monkeypatch.setattr(server, "parse_file_to_text_with_pages", slow_parse)
    monkeypatch.setattr(server, "_cuda_available", lambda: False)
    worker = threading.Thread(target=lambda: c.post("/parse", json={"object": OBJ}, headers=V1))
    worker.start()
    assert started.wait(5)
    assert c.get("/healthz").json() == {"parser_version": "v1", "cuda": False}
    release.set()
    worker.join(5)


class _Session:
    def __init__(self, providers):
        self._providers = providers

    def get_providers(self):
        return self._providers


class _CpuEmbedder:
    def __init__(self):
        self.model = type("Inner", (), {"model": _Session(["CPUExecutionProvider"])})()


def test_model_on_cpu_is_503(monkeypatch):  # final review I4
    monkeypatch.setattr(server, "_load_embedder", _CpuEmbedder)
    monkeypatch.setattr(server, "_models", {})
    r = TestClient(server.app).post("/embed", json={"texts": ["a"]}, headers={"X-ARP-Model": EMBED_MODEL_NAME})
    assert r.status_code == 503 and "CPUExecutionProvider" in r.json()["detail"]
