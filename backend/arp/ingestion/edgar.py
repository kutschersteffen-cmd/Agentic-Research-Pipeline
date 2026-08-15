from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import httpx

from arp.ingestion.base import DocumentSource
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.storage.document_store import DocumentContentStore, derive_doc_id
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

logger = logging.getLogger(__name__)

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"

_FORM_TO_DOCTYPE = {
    "10-K": DocType.ANNUAL_REPORT_10K,
    "DEF 14A": DocType.PROXY_DEF14A,
}

# Bump whenever _extract_html_text_from_string's logic changes.
_EDGAR_PARSER_LOGIC_VERSION = 1


@functools.lru_cache(maxsize=1)
def _edgar_parser_version() -> str:
    parts = [f"logic={_EDGAR_PARSER_LOGIC_VERSION}"]
    try:
        parts.append(f"trafilatura={_pkg_version('trafilatura')}")
    except PackageNotFoundError:
        parts.append("trafilatura=unknown")
    return "|".join(parts)


class EdgarDocumentSource(DocumentSource):
    """Fetches US filings (10-K, DEF 14A) from SEC EDGAR's free, no-key APIs.

    SEC requires a descriptive User-Agent identifying the requester and
    asks for a modest request rate; both are respected here. EDGAR has no
    sustainability-report or earnings-transcript endpoint, so those doc
    types come from LocalFileDocumentSource (manual upload or the
    discovery crawler) instead.
    """

    name = "edgar"

    def __init__(
        self,
        user_agent: str,
        cache_dir: Path,
        request_delay_seconds: float = 0.15,
        content_store: DocumentContentStore | None = None,
        submissions_ttl_hours: float = 24.0,
    ) -> None:
        self._headers = {"User-Agent": user_agent}
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._delay = request_delay_seconds
        self._ticker_map: dict[str, str] | None = None
        self._lock = asyncio.Lock()
        self._content_store = content_store
        self._submissions_ttl_hours = submissions_ttl_hours

    async def fetch(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        wanted_forms = [f for f, dt in _FORM_TO_DOCTYPE.items() if not doc_types or dt in doc_types]
        if not wanted_forms:
            return []
        if self._content_store is not None:
            try:
                safe_id(company.company_id, label="company_id")
            except UnsafeIdentifierError:
                # Mirrors LocalFileDocumentSource.fetch: fail this one
                # company closed rather than let a malformed company_id
                # reach register_document, and don't abort the batch.
                logger.warning("Rejected unsafe company_id in EDGAR fetch: %r", company.company_id)
                return []
        cik = company.cik or await self._resolve_cik(company.ticker)
        if not cik:
            logger.info("EDGAR: could not resolve CIK for %s, skipping", company.company_id)
            return []

        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            submissions = await self._get_submissions(client, cik.zfill(10))
            if not submissions:
                return []
            recent = submissions.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            docs: list[SourceDocument] = []
            for form in wanted_forms:
                idx = next((i for i, f in enumerate(forms) if f == form), None)
                if idx is None:
                    continue
                accession = recent["accessionNumber"][idx].replace("-", "")
                primary_doc = recent["primaryDocument"][idx]
                filing_date = recent.get("filingDate", [None] * len(forms))[idx]
                url = _ARCHIVES_BASE.format(cik_int=int(cik), accession_nodash=accession, primary_doc=primary_doc)
                text, content_key = await self._get_filing_text(client, url, accession, primary_doc)
                if not text or not text.strip():
                    continue

                doc_type = _FORM_TO_DOCTYPE[form]
                title = f"{company.name} {form} ({filing_date})"
                kwargs: dict = dict(
                    company_id=company.company_id,
                    doc_type=doc_type,
                    title=title,
                    source_url=url,
                    fiscal_period=filing_date,
                    full_text=text,
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                if self._content_store is not None and content_key is not None:
                    doc_id = derive_doc_id(company.company_id, doc_type.value, content_key)
                    kwargs["doc_id"] = self._content_store.register_document(
                        doc_id=doc_id,
                        company_id=company.company_id,
                        doc_type=doc_type.value,
                        content_key=content_key,
                        title=title,
                        local_path=None,
                        source_url=url,
                    )
                docs.append(SourceDocument(**kwargs))
            return docs

    async def _get_submissions(self, client: httpx.AsyncClient, cik10: str) -> dict | None:
        """Filings change over time, so this is TTL-bounded (unlike the
        accession-keyed filing-document cache below, which never
        expires) -- a plain JSON file next to the ticker map, not the
        content store, since submissions payloads aren't parsed document
        text and don't belong in the parsed_content schema."""
        path = self._cache_dir / f"submissions_{cik10}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text())
                if time.time() - payload["_fetched_at"] < self._submissions_ttl_hours * 3600:
                    return payload["data"]
            except (json.JSONDecodeError, KeyError, OSError):
                pass  # corrupt/stale cache entry -- treat as a miss

        data = await self._get_json(client, _SUBMISSIONS_URL.format(cik10=cik10))
        if data is not None:
            try:
                path.write_text(json.dumps({"_fetched_at": time.time(), "data": data}))
            except OSError:
                logger.warning("Could not write EDGAR submissions cache for CIK %s", cik10)
        return data

    async def _get_filing_text(
        self, client: httpx.AsyncClient, url: str, accession: str, primary_doc: str
    ) -> tuple[str | None, str | None]:
        """Filing documents are immutable once filed (an accession number
        is never reused), so this cache -- unlike submissions -- has no
        TTL and is the strongest cache key in the system. Reuses
        DocumentContentStore's parsed_content table (key_kind=
        "edgar_accession") rather than a separate cache, so `arp
        documents cache-stats`/`cache-prune` cover EDGAR content too.
        Returns (text, content_key); content_key is None when no
        content_store is configured, matching LocalFileDocumentSource's
        doc_id=None-on-no-store convention.
        """
        if self._content_store is None:
            return await self._get_and_extract_text(client, url), None

        content_key = hashlib.sha256(f"edgar:{accession}/{primary_doc}".encode("utf-8")).hexdigest()
        cached = self._content_store.lookup(content_key, _edgar_parser_version())
        if cached is not None:
            return cached.full_text, content_key

        text = await self._get_and_extract_text(client, url)
        if text and text.strip():
            self._content_store.store(
                content_key,
                key_kind="edgar_accession",
                parser_version=_edgar_parser_version(),
                source_suffix=Path(primary_doc).suffix.lower(),
                byte_size=len(text.encode("utf-8")),
                text=text,
                page_breaks=[],
            )
        return text, content_key

    async def _resolve_cik(self, ticker: str | None) -> str | None:
        if not ticker:
            return None
        async with self._lock:
            if self._ticker_map is None:
                self._ticker_map = await self._load_ticker_map()
        return self._ticker_map.get(ticker.upper())

    async def _load_ticker_map(self) -> dict[str, str]:
        cache_path = self._cache_dir / "sec_company_tickers.json"
        if cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text())
                return {row["ticker"].upper(): str(row["cik_str"]) for row in raw.values()}
            except (json.JSONDecodeError, KeyError, OSError):
                pass
        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            resp = await client.get(_TICKER_MAP_URL)
            resp.raise_for_status()
            raw = resp.json()
        cache_path.write_text(json.dumps(raw))
        return {row["ticker"].upper(): str(row["cik_str"]) for row in raw.values()}

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict | None:
        await asyncio.sleep(self._delay)
        resp = await client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def _get_and_extract_text(self, client: httpx.AsyncClient, url: str) -> str | None:
        await asyncio.sleep(self._delay)
        resp = await client.get(url)
        if resp.status_code != 200:
            return None
        if url.lower().endswith((".htm", ".html")):
            return _extract_html_text_from_string(resp.text)
        return resp.text


def _extract_html_text_from_string(raw_html: str) -> str:
    import trafilatura

    extracted = trafilatura.extract(raw_html, favor_recall=True)
    if extracted:
        return extracted
    from bs4 import BeautifulSoup

    return BeautifulSoup(raw_html, "lxml").get_text("\n")
