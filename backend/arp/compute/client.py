"""Sends PDF parsing, reranking and embedding to the Cloud Run GPU services
(arp/compute/server.py) when backend/.env names them. Every public function
returns None when the caller should fall back to what it did before: a cloud
outage costs speed, never a run. After a failure a capability skips the cloud
for COOLDOWN_S, then tries again, so recovery needs no restart."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np

from arp.config import get_settings
from arp.schemas.common import TableSpan

logger = logging.getLogger(__name__)

COOLDOWN_S = 600.0
RETRY_DELAY_S = 5.0
CONNECT_TIMEOUT_S = 10.0
PARSE_TIMEOUT_S = 1800.0  # read timeout for an upload or a parse; a 500-page OCR parse takes minutes
MODELS_TIMEOUT_S = 180.0  # above an arp-models cold start
EMBED_BATCH = 256
PARSE_SLOTS = 2  # = arp-parse max instances, so extra callers queue here instead of getting 429
MODELS_SLOTS = 8  # = arp-models concurrency x max instances, for the same reason
CLOUD_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

_STORAGE = "https://storage.googleapis.com"
_TRANSIENT = {429, 502, 503, 504}

_http = httpx.Client()
_sleep = time.sleep
_now = time.monotonic
_cooldown_until: dict[str, float] = {}
last_error: dict[str, str] = {}
_warned: set[str] = set()
_parse_slots = threading.Semaphore(PARSE_SLOTS)
_models_slots = threading.Semaphore(MODELS_SLOTS)
_creds: dict[tuple[str, str], object] = {}
_creds_lock = threading.Lock()


def _timeout(read: float) -> httpx.Timeout:
    return httpx.Timeout(read, connect=CONNECT_TIMEOUT_S)


def _configured(capability: str) -> str | None:
    """The service URL when `capability` ("parse" or "models") has every setting it needs, else None."""
    settings = get_settings()
    url = settings.compute_parse_url if capability == "parse" else settings.compute_models_url
    if not url:
        last_error[capability] = f"ARP_COMPUTE_{capability.upper()}_URL not set"
        return None
    needs = {"ARP_COMPUTE_CREDENTIALS_FILE": settings.compute_credentials_file}
    if capability == "parse":
        needs["ARP_COMPUTE_BUCKET"] = settings.compute_bucket
    problem = next((f"{name} is empty" for name, value in needs.items() if not value), None)
    if problem is None and not Path(settings.compute_credentials_file).is_file():
        problem = f"key file {settings.compute_credentials_file} not found"
    if problem:
        last_error[capability] = problem
        if problem not in _warned:
            _warned.add(problem)
            logger.warning("Cloud %s is off: %s; computing locally.", capability, problem)
        return None
    return url.rstrip("/")


def parse_configured() -> bool:
    return _configured("parse") is not None


def models_configured() -> bool:
    return _configured("models") is not None


def _cooling(capability: str) -> bool:
    return _now() < _cooldown_until.get(capability, 0.0)


def _fail(capability: str, reason: str) -> None:
    _cooldown_until[capability] = _now() + COOLDOWN_S
    last_error[capability] = reason
    logger.warning("Cloud %s unavailable (%s); falling back for %d s.", capability, reason, COOLDOWN_S)


def _token(kind: str, key: str) -> str:
    """A cached google-auth credential's token, refreshed once it is no longer valid (they last 1 h)."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    key_file = get_settings().compute_credentials_file
    with _creds_lock:
        creds = _creds.get((kind, key))
        if creds is None:
            if kind == "id":
                creds = service_account.IDTokenCredentials.from_service_account_file(key_file, target_audience=key)
            else:
                creds = service_account.Credentials.from_service_account_file(key_file, scopes=[key])
            _creds[(kind, key)] = creds
        if not creds.valid:
            creds.refresh(Request())
        return creds.token


def _id_token(audience: str) -> str:
    return _token("id", audience)


def _storage_token() -> str:
    return _token("access", "https://www.googleapis.com/auth/devstorage.read_write")


def _auth(url: str) -> dict[str, str]:
    """An ID token whose audience is the Cloud Run service URL (scheme and host, no path)."""
    origin = httpx.URL(url)
    return {"Authorization": f"Bearer {_id_token(f'{origin.scheme}://{origin.netloc.decode()}')}"}


def _reason(response: httpx.Response) -> str:
    return f"{response.status_code} {response.text[:200]}"


def _post(
    capability: str, url: str, payload: dict, timeout: float, headers: dict[str, str] | None = None
) -> httpx.Response | None:
    """POST with an ID token for the service. A connect error or 429/502/503/504 is retried once.
    Returns a 2xx, 404 or 422 response; anything else sets the cooldown and returns None."""
    reason = ""
    for attempt in range(2):
        if attempt:
            _sleep(RETRY_DELAY_S)
        try:
            response = _http.post(
                url, json=payload, headers={**_auth(url), **(headers or {})}, timeout=_timeout(timeout)
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            continue
        except Exception as exc:  # noqa: BLE001 - auth, read timeout, anything: fall back, never raise into a run
            _fail(capability, f"{type(exc).__name__}: {exc}")
            return None
        if response.status_code in _TRANSIENT:
            reason = _reason(response)
            continue
        if response.is_success or response.status_code in (404, 422):
            return response
        _fail(capability, _reason(response))
        return None
    _fail(capability, reason)
    return None


def _upload(path: Path, bucket: str) -> str:
    """Puts the PDF at parse/<sha256>.pdf unless it is there already; returns the object name."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    name = f"parse/{digest.hexdigest()}.pdf"
    auth = {"Authorization": f"Bearer {_storage_token()}"}
    found = _http.get(
        f"{_STORAGE}/storage/v1/b/{bucket}/o/{quote(name, safe='')}", headers=auth, timeout=_timeout(PARSE_TIMEOUT_S)
    )
    if found.status_code == 200:
        return name
    if found.status_code != 404:
        raise RuntimeError(f"storage {_reason(found)}")
    with path.open("rb") as f:
        uploaded = _http.post(
            f"{_STORAGE}/upload/storage/v1/b/{bucket}/o",
            params={"uploadType": "media", "name": name, "ifGenerationMatch": "0"},
            content=f,
            headers={**auth, "Content-Type": "application/pdf", "Content-Length": str(path.stat().st_size)},
            timeout=_timeout(PARSE_TIMEOUT_S),
        )
    if uploaded.status_code not in (200, 412):  # 412: a concurrent upload of the same file won
        raise RuntimeError(f"storage upload {_reason(uploaded)}")
    return name


def parse_pdf(path: Path, parser_version: str) -> tuple[str, list[int], list[TableSpan]] | None:
    """The PDF parsed by arp-parse, as parse_file_to_text_with_pages returns it, or None to parse locally."""
    url = _configured("parse")
    if url is None:
        return None
    with _parse_slots:
        if _cooling("parse"):  # checked inside the slot so callers queued behind a hung service skip it
            return None
        try:
            name = _upload(path, get_settings().compute_bucket)
        except Exception as exc:  # noqa: BLE001 - a storage failure is a parse failure
            _fail("parse", f"{type(exc).__name__}: {exc}")
            return None
        headers = {"X-ARP-Parser-Version": parser_version}
        response = _post("parse", f"{url}/parse", {"object": name}, PARSE_TIMEOUT_S, headers)
        if response is not None and response.status_code == 404:  # the bucket mount can lag a fresh upload
            _sleep(RETRY_DELAY_S)
            response = _post("parse", f"{url}/parse", {"object": name}, PARSE_TIMEOUT_S, headers)
        if response is None:
            return None
        if response.status_code in (404, 422):  # one file, not an outage: no cooldown
            last_error["parse"] = _reason(response)
            return None
        try:
            body = response.json()
            return body["text"], body["page_breaks"], [TableSpan.model_validate(t) for t in body["table_spans"]]
        except Exception as exc:  # noqa: BLE001
            _fail("parse", f"bad response: {type(exc).__name__}: {exc}")
            return None


def _models_call(path: str, payload: dict, model: str, read):
    """POST to arp-models and return read(json body); any failure, or a reply read() rejects, is None."""
    url = _configured("models")
    if url is None:
        return None
    with _models_slots:
        if _cooling("models"):
            return None
        response = _post("models", f"{url}{path}", payload, MODELS_TIMEOUT_S, {"X-ARP-Model": model})
    if response is None:
        return None
    try:
        if not response.is_success:  # 404/422 are passed through for parse only
            raise ValueError(_reason(response))
        return read(response.json())
    except Exception as exc:  # noqa: BLE001 - a reply this backend can't use is a failure, never a raise
        _fail("models", f"{type(exc).__name__}: {exc}")
        return None


def _scores(body: dict, count: int) -> list[float]:
    scores = [float(s) for s in body["scores"]]
    if len(scores) != count:
        raise ValueError(f"{len(scores)} scores for {count} texts")
    return scores


def _vectors(body: dict, count: int) -> np.ndarray:
    from arp.retrieval.embeddings import EMBED_DIM

    vectors = np.asarray(body["vectors"], dtype=np.float32)
    if vectors.shape != (count, EMBED_DIM):
        raise ValueError(f"vectors of shape {vectors.shape}, expected {(count, EMBED_DIM)}")
    return vectors


def rerank_scores(query: str, texts: list[str]) -> list[float] | None:
    """Cross-encoder scores from arp-models, one per text, or None to keep the retrieval order."""
    payload = {"query": query, "texts": texts}
    return _models_call("/rerank", payload, CLOUD_RERANK_MODEL, lambda body: _scores(body, len(texts)))


def embed(texts: list[str]) -> np.ndarray | None:
    """EMBED_MODEL_NAME vectors from arp-models, or None to embed every text locally (never a mix)."""
    from arp.retrieval.embeddings import EMBED_MODEL_NAME

    parts: list[np.ndarray] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]
        vectors = _models_call(
            "/embed", {"texts": batch}, EMBED_MODEL_NAME, lambda body, n=len(batch): _vectors(body, n)
        )
        if vectors is None:
            return None
        parts.append(vectors)
    return np.concatenate(parts)


def healthz(url: str) -> dict | None:
    """A compute service's /healthz (parser_version, cuda), for `arp compute check`; None on any failure."""
    try:
        response = _http.get(f"{url.rstrip('/')}/healthz", headers=_auth(url), timeout=_timeout(MODELS_TIMEOUT_S))
        return response.json() if response.is_success else None
    except Exception:  # noqa: BLE001
        return None
