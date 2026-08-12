from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from arp.discovery.crawler import CandidateDocumentLink
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import DiscoveredDocument

logger = logging.getLogger(__name__)

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
) -> list[DiscoveredDocument]:
    """Downloads each candidate link into
    `documents_dir/<company_id>/<doc_type>/<slug>` and returns the resulting
    DiscoveredDocument records (content hash included), so callers can diff
    against previously known state.
    """
    discovered: list[DiscoveredDocument] = []
    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(headers=headers, timeout=timeout_seconds, follow_redirects=True) as client:
        for candidate in candidates:
            try:
                resp = await client.get(candidate.url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.info("Failed to download %s: %s", candidate.url, exc)
                continue

            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            ext = _EXT_BY_CONTENT_TYPE.get(content_type)
            if ext is None:
                url_ext = Path(urlparse(candidate.url).path).suffix.lower()
                ext = url_ext if url_ext in (".pdf", ".html", ".htm", ".txt") else ".html"

            dest_dir = documents_dir / company.company_id / candidate.doc_type.value
            dest_dir.mkdir(parents=True, exist_ok=True)
            filename = _slugify(candidate.link_text or Path(urlparse(candidate.url).path).stem) + ext
            dest_path = dest_dir / filename
            dest_path.write_bytes(resp.content)

            discovered.append(
                DiscoveredDocument(
                    company_id=company.company_id,
                    doc_type=candidate.doc_type,
                    url=candidate.url,
                    local_path=str(dest_path),
                    sha256=hashlib.sha256(resp.content).hexdigest(),
                    http_last_modified=resp.headers.get("last-modified"),
                    http_etag=resp.headers.get("etag"),
                )
            )
    return discovered
