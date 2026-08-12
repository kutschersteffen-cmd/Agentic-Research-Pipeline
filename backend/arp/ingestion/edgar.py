from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

import httpx

from arp.ingestion.base import DocumentSource
from arp.schemas.common import CompanyRef, DocType, SourceDocument

logger = logging.getLogger(__name__)

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"

_FORM_TO_DOCTYPE = {
    "10-K": DocType.ANNUAL_REPORT_10K,
    "DEF 14A": DocType.PROXY_DEF14A,
}


class EdgarDocumentSource(DocumentSource):
    """Fetches US filings (10-K, DEF 14A) from SEC EDGAR's free, no-key APIs.

    SEC requires a descriptive User-Agent identifying the requester and
    asks for a modest request rate; both are respected here. EDGAR has no
    sustainability-report or earnings-transcript endpoint, so those doc
    types come from LocalFileDocumentSource (manual upload or the
    discovery crawler) instead.
    """

    name = "edgar"

    def __init__(self, user_agent: str, cache_dir: Path, request_delay_seconds: float = 0.15) -> None:
        self._headers = {"User-Agent": user_agent}
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._delay = request_delay_seconds
        self._ticker_map: dict[str, str] | None = None
        self._lock = asyncio.Lock()

    async def fetch(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        wanted_forms = [f for f, dt in _FORM_TO_DOCTYPE.items() if not doc_types or dt in doc_types]
        if not wanted_forms:
            return []
        cik = company.cik or await self._resolve_cik(company.ticker)
        if not cik:
            logger.info("EDGAR: could not resolve CIK for %s, skipping", company.company_id)
            return []

        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            submissions = await self._get_json(client, _SUBMISSIONS_URL.format(cik10=cik.zfill(10)))
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
                text = await self._get_and_extract_text(client, url)
                if not text or not text.strip():
                    continue
                docs.append(
                    SourceDocument(
                        company_id=company.company_id,
                        doc_type=_FORM_TO_DOCTYPE[form],
                        title=f"{company.name} {form} ({filing_date})",
                        source_url=url,
                        fiscal_period=filing_date,
                        full_text=text,
                        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )
            return docs

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
