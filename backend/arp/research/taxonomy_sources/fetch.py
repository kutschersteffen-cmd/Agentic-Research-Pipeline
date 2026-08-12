from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_MAX_CHARS = 60_000  # keep a single source's contribution to the prompt bounded
_MAX_ORIGINAL_BYTES = 25 * 1024 * 1024  # don't cache/serve anything absurdly large

_EXT_BY_CONTENT_TYPE = {"application/pdf": ".pdf", "text/html": ".html"}


async def fetch_source_text(url: str, user_agent: str, timeout: float = 20.0) -> str | None:
    """Best-effort fetch + text extraction for a user-selected authority
    source URL. Returns None on any failure rather than raising, so one
    unreachable source doesn't abort a multi-source derivation.
    """
    headers = {"User-Agent": user_agent}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.info("Failed to fetch authority source %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        return None

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    text: str | None
    if content_type == "application/pdf" or url.lower().endswith(".pdf"):
        text = _extract_pdf_text(resp.content)
    else:
        text = _extract_html_text(resp.text)
    if not text:
        return None
    return text[:_MAX_CHARS]


def _cache_paths(cache_dir: Path, url: str) -> tuple[Path, Path]:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.bin", cache_dir / f"{key}.json"


async def fetch_source_original(url: str, user_agent: str, cache_dir: Path, timeout: float = 30.0) -> tuple[bytes, str] | None:
    """Fetches (or returns from disk cache) the original bytes of a
    user-selected source, for in-app inspection -- a PDF or HTML page
    rendered as-is, not the extracted plain text `fetch_source_text`
    produces for prompting. Cached by URL hash so repeatedly opening the
    inspector for the same source doesn't refetch it.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    content_path, meta_path = _cache_paths(cache_dir, url)
    if content_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            return content_path.read_bytes(), meta["content_type"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # fall through and refetch a corrupted cache entry

    headers = {"User-Agent": user_agent}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.info("Failed to fetch original document %s: %s", url, exc)
        return None
    if resp.status_code != 200 or len(resp.content) > _MAX_ORIGINAL_BYTES:
        return None

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _EXT_BY_CONTENT_TYPE:
        content_type = "application/pdf" if url.lower().endswith(".pdf") else "text/html"

    content_path.write_bytes(resp.content)
    meta_path.write_text(json.dumps({"content_type": content_type, "url": url}))
    return resp.content, content_type


def _extract_html_text(raw_html: str) -> str | None:
    import trafilatura

    extracted = trafilatura.extract(raw_html, favor_recall=True)
    if extracted:
        return extracted
    from bs4 import BeautifulSoup

    return BeautifulSoup(raw_html, "lxml").get_text("\n")


def _extract_pdf_text(content: bytes) -> str | None:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 - malformed PDF shouldn't abort the derivation
        logger.info("Failed to parse PDF: %s", exc)
        return None
