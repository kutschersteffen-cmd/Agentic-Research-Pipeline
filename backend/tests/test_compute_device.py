"""ARP_COMPUTE_DEVICE in the compute service (spec portable-docker-images, slice 2). No model is loaded:
every loader is a stand-in that records the device it was asked for."""

import pytest
import torch
from fastapi.testclient import TestClient

from arp.compute import server
from arp.compute.client import CLOUD_RERANK_MODEL
from arp.ingestion.local_files import parser_version
from arp.models import local
from arp.models.registry import entry, model_header
from arp.retrieval.embeddings import EMBED_MODEL_NAME

NO_GPU = "ARP_COMPUTE_DEVICE=cuda but no GPU is visible"


@pytest.fixture
def gpu(monkeypatch):
    """Sets whether torch sees a GPU; ARP_COMPUTE_DEVICE starts unset and nothing is loaded yet."""
    monkeypatch.delenv("ARP_COMPUTE_DEVICE", raising=False)
    monkeypatch.setattr(server, "_models", {})
    monkeypatch.setattr(local, "_pipes", {})
    monkeypatch.setenv("DOCLING_DEVICE", "auto")  # the parse endpoint sets it; restored after the test

    def visible(available: bool):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: available)
        return TestClient(server.app)

    return visible


def test_healthz_cpu_by_default(gpu):  # AC-1
    body = gpu(False).get("/healthz").json()
    assert body["device"] == "cpu" and body["cuda"] is False and body["parser_version"]


def test_healthz_cpu_forced_with_gpu(gpu, monkeypatch):  # AC-4
    c = gpu(True)
    monkeypatch.setenv("ARP_COMPUTE_DEVICE", "cpu")
    body = c.get("/healthz").json()
    assert (body["device"], body["cuda"]) == ("cpu", True)


def test_device_read_per_request(gpu, monkeypatch):
    c = gpu(True)
    assert c.get("/healthz").json()["device"] == "cuda"  # auto with a GPU
    monkeypatch.setenv("ARP_COMPUTE_DEVICE", "cpu")
    assert c.get("/healthz").json()["device"] == "cpu"
    monkeypatch.setenv("ARP_COMPUTE_DEVICE", "gpu-please")  # unknown value = auto
    assert c.get("/healthz").json()["device"] == "cuda"


@pytest.mark.parametrize("path,body,headers", [
    ("/embed", {"texts": ["hello"]}, {}),  # AC-2: no X-ARP-Model, still 503 rather than 409
    ("/rerank", {"query": "q", "texts": ["a"]}, {"X-ARP-Model": CLOUD_RERANK_MODEL}),  # AC-3
    ("/parse", {"object": f"parse/{'0' * 64}.pdf"}, {"X-ARP-Parser-Version": parser_version()}),  # AC-30: no 404
    ("/classify", {"texts": ["a"], "labels": ["x"], "hypothesis": "{}"}, {"X-ARP-Model": "wrong"}),
    ("/spans", {"texts": ["a"], "labels": ["x"]}, {"X-ARP-Model": "wrong"}),
    ("/tag", {"key": "nope", "texts": ["a"]}, {}),
])
def test_cuda_required_without_gpu_is_503_first(gpu, monkeypatch, path, body, headers):  # AC-2, AC-3, AC-30
    c = gpu(False)
    monkeypatch.setenv("ARP_COMPUTE_DEVICE", "cuda")
    monkeypatch.setattr(server, "_load_embedder", lambda *a: pytest.fail("model loaded"))
    monkeypatch.setattr(server, "_load_reranker", lambda *a: pytest.fail("model loaded"))
    r = c.post(path, json=body, headers=headers)
    assert r.status_code == 503 and r.json() == {"detail": NO_GPU}


class _Embedder:
    def embed(self, texts):
        return [[0.25] * 384 for _ in texts]


def test_embed_on_cpu(gpu, monkeypatch):  # AC-7
    asked = []
    monkeypatch.setattr(server, "_load_embedder", lambda key, device: asked.append(device) or _Embedder())
    r = gpu(False).post("/embed", json={"texts": ["hello"]}, headers={"X-ARP-Model": EMBED_MODEL_NAME})
    assert r.status_code == 200
    vectors = r.json()["vectors"]
    assert len(vectors) == 1 and len(vectors[0]) == 384 and all(isinstance(v, float) for v in vectors[0])
    assert asked == ["cpu"]


class _Reranker:
    def rerank(self, query, texts):
        return [1.0 for _ in texts]


class _Gliner:
    def predict_entities(self, text, labels, threshold):
        return [{"label": labels[0], "text": text, "start": 0, "end": len(text), "score": 0.9}]


def _pipe(task):
    if task == "zero-shot-classification":
        return lambda texts, candidate_labels, **kw: [{"labels": candidate_labels, "scores": [0.5]} for _ in texts]
    return lambda texts, **kw: [{"label": "yes", "score": 0.7} for _ in texts]


class _Net:
    def __init__(self):
        self.device = None

    def to(self, device):
        self.device = device
        return self

    def eval(self):
        return self

    def __call__(self, **batch):
        return type("Out", (), {"last_hidden_state": torch.ones(batch["input_ids"].shape[0], 2, 4)})()


class _Batch(dict):
    def __init__(self, moved, **kw):
        super().__init__(**kw)
        self._moved = moved

    def to(self, device):
        self._moved.append(device)
        return self


def test_every_model_endpoint_loads_on_cpu(gpu, monkeypatch):  # AC-9
    asked = {}
    monkeypatch.setattr(server, "_load_reranker", lambda key, device: asked.setdefault("rerank", device) and _Reranker())
    monkeypatch.setattr(local, "_gliner", lambda e, device: asked.setdefault("spans", device) and _Gliner())
    monkeypatch.setattr(local, "_pipeline", lambda task, e, **kw: asked.setdefault(e.key, kw.get("device")) and _pipe(task))
    c = gpu(False)

    r = c.post("/rerank", json={"query": "q", "texts": ["a", "b"]}, headers={"X-ARP-Model": CLOUD_RERANK_MODEL})
    assert r.status_code == 200 and r.json() == {"scores": [1.0, 1.0]}
    r = c.post("/spans", json={"texts": ["a"], "labels": ["x"]}, headers={"X-ARP-Model": model_header(entry("gliner"))})
    assert r.status_code == 200 and r.json()["spans"][0][0]["label"] == "x"
    r = c.post("/tag", json={"key": "climate_detector", "texts": ["a"]},
               headers={"X-ARP-Model": model_header(entry("climate_detector"))})
    assert r.status_code == 200 and r.json() == {"results": [{"label": "yes", "score": 0.7}]}
    r = c.post("/classify", json={"texts": ["a"], "labels": ["x"], "hypothesis": "{}"},
               headers={"X-ARP-Model": model_header(entry("nli"))})
    assert r.status_code == 200 and r.json() == {"scores": [{"x": 0.5}]}
    assert asked == {"rerank": "cpu", "spans": "cpu", "climate_detector": "cpu", "nli": "cpu"}


@pytest.mark.parametrize("gpu_visible,mode,device,dtype", [
    (False, None, "cpu", torch.float32),  # AC-9: CPU, float32
    (True, None, "cuda", torch.float16),
    (True, "cpu", "cpu", torch.float32),
])
def test_bge_m3_dtype_follows_device(gpu, monkeypatch, gpu_visible, mode, device, dtype):  # AC-9
    import transformers

    e, loaded, moved, net = entry("embed_bge_m3"), {}, [], _Net()

    def model(hf_id, revision, torch_dtype):
        loaded["model"] = (hf_id, revision, torch_dtype)
        return net

    def tokenizer(hf_id, revision):
        loaded["tokenizer"] = (hf_id, revision)
        return lambda texts, **kw: _Batch(moved, input_ids=torch.ones(len(texts), 2))

    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", model)
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", tokenizer)
    c = gpu(gpu_visible)
    if mode:
        monkeypatch.setenv("ARP_COMPUTE_DEVICE", mode)
    r = c.post("/embed", json={"texts": ["a"]}, headers={"X-ARP-Model": model_header(e)})
    assert r.status_code == 200 and len(r.json()["vectors"][0]) == 4  # no onnxruntime check on a torch model
    assert loaded == {"model": (e.hf_id, e.revision, dtype), "tokenizer": (e.hf_id, e.revision)}
    assert net.device == device and moved == [device]


class _OnnxSession:
    def get_providers(self):
        return ["CPUExecutionProvider"]


class _CpuFallbackReranker(_Reranker):
    model = type("Inner", (), {"model": _OnnxSession()})()


def test_cuda_reranker_on_cpu_providers_is_503(gpu, monkeypatch):
    c = gpu(True)
    monkeypatch.setenv("ARP_COMPUTE_DEVICE", "cuda")
    monkeypatch.setattr(server, "_load_reranker", lambda key, device: _CpuFallbackReranker())
    r = c.post("/rerank", json={"query": "q", "texts": ["a"]}, headers={"X-ARP-Model": CLOUD_RERANK_MODEL})
    assert r.status_code == 503 and "CPUExecutionProvider" in r.json()["detail"]


def test_one_model_per_key_on_its_device(gpu, monkeypatch):
    loads = []
    monkeypatch.setattr(server, "_load_reranker", lambda key, device: loads.append((key, device)) or _Reranker())
    monkeypatch.setattr(server, "_load_embedder", lambda key, device: loads.append((key, device)) or _Embedder())
    c = gpu(False)
    colbert, e5 = model_header(entry("rerank_colbert")), model_header(entry("embed_e5_large"))
    for header in (CLOUD_RERANK_MODEL, CLOUD_RERANK_MODEL, colbert):
        assert c.post("/rerank", json={"query": "q", "texts": ["a"]}, headers={"X-ARP-Model": header}).status_code == 200
    for header in (EMBED_MODEL_NAME, e5, e5):
        assert c.post("/embed", json={"texts": ["a"]}, headers={"X-ARP-Model": header}).status_code == 200
    assert loads == [("rerank", "cpu"), ("rerank_colbert", "cpu"), ("embed", "cpu"), ("embed_e5_large", "cpu")]

