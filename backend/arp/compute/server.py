"""The Cloud Run GPU service behind arp/compute/client.py, deployed twice from
one image (backend/Dockerfile.compute): arp-parse serves /parse, arp-models
/rerank and /embed. It runs the same functions the backend runs locally, on a
GPU. There is no auth in here: Cloud Run admits only callers holding
run.invoker. Endpoints are plain `def` so they run in the threadpool and
/healthz still answers during a long parse."""

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
from arp.retrieval.embeddings import EMBED_MODEL_NAME
from arp.schemas.common import TableSpan

MAX_EMBED_TEXTS = 1024

app = FastAPI(title="ARP compute")
app.add_middleware(GZipMiddleware, minimum_size=1000)

_models: dict[str, object] = {}
_models_lock = threading.Lock()


def _gcs_root() -> Path:
    return Path(os.environ.get("ARP_COMPUTE_GCS_ROOT", "/gcs"))


def _cuda_available() -> bool:
    import torch

    return torch.cuda.is_available()


def _load_reranker():
    import torch  # noqa: F401 -- loads the CUDA/cuDNN libraries onnxruntime-gpu needs
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(CLOUD_RERANK_MODEL, cuda=True)


def _load_embedder():
    import torch  # noqa: F401 -- loads the CUDA/cuDNN libraries onnxruntime-gpu needs
    from fastembed import TextEmbedding

    return TextEmbedding(EMBED_MODEL_NAME, cuda=True)


def _require_cuda(model):
    session = getattr(getattr(model, "model", None), "model", None)  # fastembed's onnxruntime session
    providers = session.get_providers() if session is not None else []
    if "CUDAExecutionProvider" not in providers:  # onnxruntime falls back to CPU with only a warning
        raise HTTPException(503, f"model not on the GPU: providers={providers}")
    return model


def _model(name: str, load):
    with _models_lock:  # a burst on a cold instance must not load several copies onto one GPU
        if name not in _models:
            _models[name] = _require_cuda(load())
        return _models[name]


def _reranker():
    return _model("rerank", _load_reranker)


def _embedder():
    return _model("embed", _load_embedder)


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
    _check_model(x_arp_model, CLOUD_RERANK_MODEL)
    return {"scores": [float(s) for s in _reranker().rerank(request.query, request.texts)]}


@app.post("/embed")
def embed(request: EmbedRequest, x_arp_model: str | None = Header(default=None)) -> dict:
    _check_model(x_arp_model, EMBED_MODEL_NAME)
    return {"vectors": np.asarray(list(_embedder().embed(request.texts)), dtype=np.float32).tolist()}


@app.get("/healthz")
def healthz() -> dict:
    return {"parser_version": parser_version(), "cuda": _cuda_available()}
