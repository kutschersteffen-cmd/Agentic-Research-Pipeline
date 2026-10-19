"""Fetches the registered sources through the SSRF guard and stores them in `barrier_source_documents`."""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime

import httpx
from pypdf import PdfReader

from arp import net_safety
from arp.config import get_settings
from arp.ingestion.html_text import extract_html_text
from arp.ingestion.indexing_config import IndexingConfig
from arp.schemas.transition_barrier import PrimarySource
from arp.storage.document_blob_store import blob_store_for, upload_or_fail
from arp.transition_barrier import store
from arp.transition_barrier.facts import pdf_pages

logger = logging.getLogger(__name__)

MAX_BYTES = 50 * 1024 * 1024
PDF, HTML = "application/pdf", "text/html"
assert_safe = net_safety.assert_safe_fetch_target  # a module attribute so tests can swap in a resolver-free check


class FetchSkipped(Exception):
    """A source that is not stored; the message is the reason shown in the result note."""


@dataclass
class Fetched:
    content: bytes
    content_type: str
    last_modified: date | None


def build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, event_hooks={"request": [net_safety.ssrf_guard_request_hook]}
    )


def parse(fetched: Fetched) -> tuple[list[str], bool]:
    """(page texts, html): one text per PDF page, or a single text for an HTML page."""
    if fetched.content_type == HTML:
        return [extract_html_text(fetched.content.decode("utf-8", errors="replace"))], True
    return pdf_pages(fetched.content), False


def doc_as_of(fetched: Fetched, today: date) -> date:
    """`Last-Modified`, else the PDF's `/CreationDate`, else the fetch date (R4)."""
    if fetched.last_modified:
        return fetched.last_modified
    if fetched.content_type == PDF:
        try:
            created = PdfReader(io.BytesIO(fetched.content)).metadata.creation_date
        except Exception:  # a missing or malformed date is no date
            created = None
        if created:
            return created.date()
    return today


def _last_modified(value: str | None) -> date | None:
    try:
        return parsedate_to_datetime(value).date() if value else None
    except (TypeError, ValueError):
        return None


async def fetch(url: str, *, client: httpx.AsyncClient) -> Fetched:
    try:
        assert_safe(url)
        async with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise FetchSkipped(f"HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in (PDF, HTML):
                raise FetchSkipped(f"unsupported type {content_type or 'unknown'}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FetchSkipped("over 50 MB")
            last_modified = _last_modified(response.headers.get("last-modified"))
    except net_safety.UnsafeURLError as exc:
        raise FetchSkipped(f"refused: {exc}") from exc
    except httpx.HTTPError as exc:
        raise FetchSkipped(str(exc) or type(exc).__name__) from exc
    fetched = Fetched(bytes(body), content_type, last_modified)
    try:
        texts, _ = parse(fetched)
    except Exception as exc:  # an unreadable PDF
        raise FetchSkipped("unreadable PDF") from exc
    if not any(t.strip() for t in texts):
        raise FetchSkipped("no text layer")
    return fetched


async def fetch_sources(sources: list[PrimarySource], today: date) -> list[str]:
    """Fetches and stores each fetchable source; returns a `Not fetched: ...` note for each one skipped."""
    notes: list[str] = []
    blobs = None
    async with build_client() as client:
        for source in sources:
            if not source.url or source.manual or not source.key or not source.tier:
                continue
            try:
                fetched = await fetch(source.url, client=client)
            except FetchSkipped as exc:
                notes.append(f"Not fetched: {source.source_name} ({exc})")
                continue
            blobs = blobs or blob_store_for(IndexingConfig.from_settings(get_settings()))
            content_key = hashlib.sha256(fetched.content).hexdigest()
            upload_or_fail(blobs, content_key, fetched.content)
            page_texts, html = parse(fetched)
            store.save_source_document(
                source_key=source.key, url=source.url, title=source.source_name, publisher=source.publisher,
                tier=source.tier.value, as_of=doc_as_of(fetched, today), content_key=content_key,
                content_type=fetched.content_type, page_texts=page_texts, html=html,
            )
    return notes
