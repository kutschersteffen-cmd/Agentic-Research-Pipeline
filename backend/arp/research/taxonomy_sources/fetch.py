from __future__ import annotations

import io
import logging

import httpx

logger = logging.getLogger(__name__)

_MAX_CHARS = 60_000  # keep a single source's contribution to the prompt bounded


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
