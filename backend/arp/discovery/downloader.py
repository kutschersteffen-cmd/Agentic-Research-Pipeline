from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from arp.discovery.crawler import CandidateDocumentLink
from arp.net_safety import UnsafeURLError, ssrf_guard_request_hook
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import CaptureRecord, DiscoveredDocument
from arp.storage.document_blob_store import CaptureStoreError, upload_or_fail
from arp.storage.jsonl_io import append_jsonl, read_jsonl
from arp.storage.locks import KeyedLock
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

logger = logging.getLogger(__name__)

CAPTURE_LOG = "_captures.jsonl"
_capture_locks = KeyedLock(lock_path=lambda log: Path(log + ".lock"))


def append_capture(documents_dir: Path, record: CaptureRecord) -> None:
    log = documents_dir / CAPTURE_LOG
    with _capture_locks.acquire(str(log)):
        append_jsonl(log, record.model_dump())


def latest_capture(documents_dir: Path, content_key: str) -> CaptureRecord | None:
    # ponytail: linear scan of the capture log, index by content_key if it grows past ~100k rows
    log = documents_dir / CAPTURE_LOG
    if not log.exists():
        return None
    rows = [r for r in read_jsonl(log) if r.get("content_key") == content_key]
    return CaptureRecord(**rows[-1]) if rows else None

_EXT_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/plain": ".txt",
}


def _slugify(text: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-")
    return slug[:max_len] or "document"


async def download_documents(
    company: CompanyRef,
    candidates: list[CandidateDocumentLink],
    documents_dir: Path,
    user_agent: str,
    timeout_seconds: float = 30.0,
    *,
    store,
    trigger: str = "discovery",
    rights_tag: str = "public_disclosure",
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DiscoveredDocument]:
    """Downloads each candidate link into
    `documents_dir/<company_id>/<doc_type>/<slug>` and returns the resulting
    DiscoveredDocument records (content hash included), so callers can diff
    against previously known state. The bytes go to `store` and are read
    back and hash-checked first; a document whose copy cannot be verified is
    logged as uncollected, gets no working copy and is skipped.
    """
    discovered: list[DiscoveredDocument] = []
    try:
        safe_company_id = safe_id(company.company_id, label="company_id")
    except UnsafeIdentifierError:
        logger.warning("Rejected unsafe company_id in document download: %r", company.company_id)
        return discovered
    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout_seconds,
        follow_redirects=True,
        event_hooks={"request": [ssrf_guard_request_hook]},
        transport=transport,
    ) as client:
        for candidate in candidates:
            try:
                resp = await client.get(candidate.url)
                resp.raise_for_status()
            except (httpx.HTTPError, UnsafeURLError) as exc:
                logger.info("Failed to download %s: %s", candidate.url, exc)
                continue

            content = resp.content
            content_key = hashlib.sha256(content).hexdigest()
            record = CaptureRecord(
                trigger=trigger,
                url_chain=[str(r.url) for r in resp.history] + [str(resp.url)],
                status=resp.status_code,
                headers={k: v for k, v in resp.headers.items() if k.lower() != "set-cookie"},
                content_key=content_key,
                storage_uri=None,
                rights_tag=rights_tag,
            )
            try:
                record.storage_uri = upload_or_fail(store, content_key, content)
            except CaptureStoreError as exc:
                logger.warning("Capture store failed for %s: %s", candidate.url, exc)
                record.error = str(exc)
                append_capture(documents_dir, record)
                continue
            record.collected = True
            append_capture(documents_dir, record)

            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            ext = _EXT_BY_CONTENT_TYPE.get(content_type)
            if ext is None:
                url_ext = Path(urlparse(candidate.url).path).suffix.lower()
                ext = url_ext if url_ext in (".pdf", ".html", ".htm", ".txt") else ".html"

            dest_dir = documents_dir / safe_company_id / candidate.doc_type.value
            dest_dir.mkdir(parents=True, exist_ok=True)
            filename = _slugify(candidate.link_text or Path(urlparse(candidate.url).path).stem) + ext
            dest_path = dest_dir / filename
            dest_path.write_bytes(content)

            discovered.append(
                DiscoveredDocument(
                    company_id=company.company_id,
                    doc_type=candidate.doc_type,
                    url=candidate.url,
                    local_path=str(dest_path),
                    sha256=content_key,
                    http_last_modified=resp.headers.get("last-modified"),
                    http_etag=resp.headers.get("etag"),
                    capture_id=record.capture_id,
                )
            )
    return discovered
