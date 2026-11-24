"""The compute service behind arp/compute/client.py (image: backend/Dockerfile.compute): /parse,
/rerank and /embed (every registry rerank and embed model, each loaded on first use), /classify,
/spans and /tag. It runs the same functions the backend runs locally, on the device
ARP_COMPUTE_DEVICE picks (see _device). There is no auth in here: keep it on a private network.
Endpoints are plain `def` so they run in the threadpool and /healthz still answers during a long
parse."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from arp.compute.client import CLOUD_RERANK_MODEL
from arp.ingestion.local_files import parse_file_to_text_with_pages, parser_version
from arp.models import local
from arp.models.registry import entries, entry, model_header
from arp.retrieval.embeddings import EMBED_MODEL_NAME
from arp.schemas.common import TableSpan

MAX_EMBED_TEXTS = 1024
NO_GPU = "ARP_COMPUTE_DEVICE=cuda but no GPU is visible"

app = FastAPI(title="ARP compute")
app.add_middleware(GZipMiddleware, minimum_size=1000)

_models: dict[str, object] = {}
_models_lock = threading.Lock()


def _gcs_root() -> Path:
    return Path(os.environ.get("ARP_COMPUTE_GCS_ROOT", "/gcs"))


def _cuda_available() -> bool:
    import torch

    return torch.cuda.is_available()


def _device() -> str:
    """Where models load, read on every request: ARP_COMPUTE_DEVICE `cpu` or `cuda`; `auto` (the default,
    also for any other value) is `cuda` when torch sees a GPU, else `cpu`."""
    mode = os.environ.get("ARP_COMPUTE_DEVICE", "auto")
    if mode in ("cpu", "cuda"):
        return mode
    return "cuda" if _cuda_available() else "cpu"


def _model_device() -> str:
    """The device for a model endpoint; its first check, before any header check or model load:
    503 when ARP_COMPUTE_DEVICE=cuda and no GPU is visible."""
    device = _device()
    if device == "cuda" and not _cuda_available():
        raise HTTPException(503, NO_GPU)
    return device


# What clients send in X-ARP-Model for the two original models; every other one is named hf_id@revision.
_LEGACY_NAMES = {"embed": EMBED_MODEL_NAME, "rerank": CLOUD_RERANK_MODEL}


class _MaxSim:
    """A ColBERT reranker: a text scores the sum, over the query's token vectors, of each one's best dot
    product with the text's token vectors."""

    def __init__(self, late) -> None:
        self._late = late
        self.model = late.model  # so _require_cuda finds the onnxruntime session

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        q = np.asarray(next(iter(self._late.query_embed(query))))
        return [float((q @ np.asarray(d).T).max(axis=1).sum()) for d in self._late.embed(texts)]


class _ClsEmbedder:
    """bge-m3 dense vectors (transformers): the CLS token's last hidden state, L2-normalised, as its model card does."""

    def __init__(self, e, device: str) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._device = device
        self._tokenizer = AutoTokenizer.from_pretrained(e.hf_id, revision=e.revision)
        dtype = torch.float16 if device == "cuda" else torch.float32  # CPUs have no fast float16
        self._net = AutoModel.from_pretrained(e.hf_id, revision=e.revision, torch_dtype=dtype).to(device).eval()

    def embed(self, texts: list[str], batch_size: int = 16):
        for start in range(0, len(texts), batch_size):
            batch = self._tokenizer(texts[start : start + batch_size], padding=True, truncation=True,
                                    max_length=8192, return_tensors="pt").to(self._device)  # 8,192 tokens covers any chunk
            with self._torch.no_grad():
                cls = self._net(**batch).last_hidden_state[:, 0]
            yield from self._torch.nn.functional.normalize(cls.float(), dim=-1).cpu().numpy()


def _load_reranker(key: str = "rerank", device: str = "cpu"):
    import torch  # noqa: F401 -- loads the CUDA/cuDNN libraries onnxruntime-gpu needs

    if key == "rerank":
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        return TextCrossEncoder(CLOUD_RERANK_MODEL, cuda=device == "cuda")
    from fastembed import LateInteractionTextEmbedding

    return _MaxSim(LateInteractionTextEmbedding(entry(key).hf_id, cuda=device == "cuda"))


def _load_embedder(key: str = "embed", device: str = "cpu"):
    if key == "embed_bge_m3":
        return _ClsEmbedder(entry(key), device)
    import torch  # noqa: F401 -- loads the CUDA/cuDNN libraries onnxruntime-gpu needs
    from fastembed import TextEmbedding

    return TextEmbedding(EMBED_MODEL_NAME if key == "embed" else entry(key).hf_id, cuda=device == "cuda")


def _require_cuda(model):
    session = getattr(getattr(model, "model", None), "model", None)  # fastembed's onnxruntime session
    providers = session.get_providers() if session is not None else []
    if "CUDAExecutionProvider" not in providers:  # onnxruntime falls back to CPU with only a warning
        raise HTTPException(503, f"model not on the GPU: providers={providers}")
    return model


def _model(name: str, load, check):
    with _models_lock:  # a burst on a cold instance must not load several copies onto one GPU
        if name not in _models:
            _models[name] = check(load())
        return _models[name]


def _check(device: str, onnx: bool = True):
    """On CUDA, an onnxruntime model must really be on the GPU; on CPU there is nothing to check."""
    return _require_cuda if device == "cuda" and onnx else (lambda m: m)


# One loaded model per registry key, on the device of the request that loaded it.
def _reranker(key: str = "rerank"):
    device = _device()
    return _model(key, lambda: _load_reranker(key, device), _check(device))


def _embedder(key: str = "embed"):
    device = _device()
    return _model(key, lambda: _load_embedder(key, device), _check(device, onnx=key != "embed_bge_m3"))


def _served(received: str | None, capability: str) -> str:
    """The registry key of the `capability` model `received` names; 409 for any other name."""
    for e in entries(capability):
        if received in (model_header(e), _LEGACY_NAMES.get(e.key)):
            return e.key
    raise HTTPException(409, f"model not served by /{capability}: client={received or 'missing'}")


def _check_model(received: str | None, expected: str) -> None:
    if received != expected:
        raise HTTPException(409, f"model mismatch: service={expected} client={received or 'missing'}")


class ParseRequest(BaseModel):
    object: str = Field(pattern=r"^parse/[0-9a-f]{64}\.pdf$")


class ParseResponse(BaseModel):
    text: str
    page_breaks: list[int]
    table_spans: list[TableSpan]


class RerankRequest(BaseModel):
    query: str
    texts: list[str]


class EmbedRequest(BaseModel):
    texts: list[str] = Field(max_length=MAX_EMBED_TEXTS)


@app.post("/parse", response_model=ParseResponse)
def parse(request: ParseRequest, x_arp_parser_version: str | None = Header(default=None)) -> ParseResponse:
    # docling's accelerator reads DOCLING_DEVICE when the (cached) converter is built on the first parse
    os.environ["DOCLING_DEVICE"] = _model_device()
    service = parser_version()
    if x_arp_parser_version != service:  # a parse stored under another version would mix the cache
        raise HTTPException(409, f"parser_version mismatch: service={service} client={x_arp_parser_version or 'missing'}")
    path = _gcs_root() / request.object
    if not path.is_file():
        raise HTTPException(404, f"object not found: {request.object}")
    try:
        text, page_breaks, table_spans = parse_file_to_text_with_pages(path)
    except Exception as exc:  # noqa: BLE001 - one broken file, reported as such rather than as an outage
        raise HTTPException(422, f"parse failed: {type(exc).__name__}: {exc}") from exc
    return ParseResponse(text=text, page_breaks=page_breaks, table_spans=table_spans)


@app.post("/rerank")
def rerank(request: RerankRequest, x_arp_model: str | None = Header(default=None)) -> dict:
    _model_device()
    key = _served(x_arp_model, "rerank")
    model = _reranker() if key == "rerank" else _reranker(key)
    return {"scores": [float(s) for s in model.rerank(request.query, request.texts)]}


@app.post("/embed")
def embed(request: EmbedRequest, x_arp_model: str | None = Header(default=None)) -> dict:
    _model_device()
    key = _served(x_arp_model, "embed")
    model = _embedder() if key == "embed" else _embedder(key)
    return {"vectors": np.asarray(list(model.embed(request.texts)), dtype=np.float32).tolist()}


class ClassifyRequest(BaseModel):
    texts: list[str] = Field(max_length=MAX_EMBED_TEXTS)
    labels: list[str]
    hypothesis: str


class SpansRequest(BaseModel):
    texts: list[str] = Field(max_length=MAX_EMBED_TEXTS)
    labels: list[str]
    threshold: float = 0.5


class TagRequest(BaseModel):
    key: str
    texts: list[str] = Field(max_length=MAX_EMBED_TEXTS)


@app.post("/classify")
def classify(request: ClassifyRequest, x_arp_model: str | None = Header(default=None)) -> dict:
    device = _model_device()
    e = entry("nli")
    _check_model(x_arp_model, model_header(e))
    return {"scores": local.nli_scores(e, request.texts, request.labels, request.hypothesis, device=device)}


@app.post("/spans")
def spans(request: SpansRequest, x_arp_model: str | None = Header(default=None)) -> dict:
    device = _model_device()
    e = entry("gliner")
    _check_model(x_arp_model, model_header(e))
    return {"spans": local.span_scores(e, request.texts, request.labels, request.threshold, device=device)}


@app.post("/tag")
def tag(request: TagRequest, x_arp_model: str | None = Header(default=None)) -> dict:
    device = _model_device()
    try:
        e = entry(request.key)
    except KeyError as exc:
        raise HTTPException(404, f"unknown model key: {request.key}") from exc
    if e.capability != "tag":
        raise HTTPException(404, f"not a tag model: {request.key}")
    _check_model(x_arp_model, model_header(e))
    return {"results": local.tag_scores(e, request.texts, device=device)}


@app.get("/healthz")
def healthz() -> dict:
    return {"parser_version": parser_version(), "cuda": _cuda_available(), "device": _device()}
