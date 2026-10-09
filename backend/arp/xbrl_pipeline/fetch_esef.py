"""ESEF (filings.xbrl.org) fetch: the latest filing's xBRL-JSON facts plus its report package."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from urllib.parse import urljoin

import httpx

from arp.ingestion.esef import MAX_PACKAGE_BYTES, download_capped, list_esef_filings
from arp.net_safety import ssrf_guard_request_hook
from arp.schemas.common import CompanyRef
from arp.xbrl_pipeline.esef_json import catalog_from_rows, flatten_xbrl_json
from arp.xbrl_pipeline.fetch import FETCH_DELAY_SECONDS, with_retry
from arp.xbrl_pipeline.models import CompanyStatus, ReportMeta
from arp.xbrl_pipeline.required import resolve_required_esef
from arp.xbrl_pipeline.store import XbrlStore

logger = logging.getLogger(__name__)
_LEI = re.compile(r"[A-Z0-9]{20}")


@dataclass(frozen=True)
class EsefFiling:
    attributes: dict
    facts_json: bytes
    package: bytes
    package_url: str


class EsefSource(Protocol):
    async def latest_filing(self, lei: str) -> EsefFiling | None: ...


def normalise_lei(value: str | None) -> str | None:
    lei = (value or "").strip().upper()
    return lei if _LEI.fullmatch(lei) else None


def pick_latest(filings: list[dict], *, this_year: int) -> dict | None:
    """Latest by period_end among records with both downloads; implausible years (the index has some) are ignored."""
    ok = [f for f in filings if f.get("json_url") and f.get("package_url")
          and 2015 <= int((f.get("period_end") or "0")[:4] or 0) <= this_year + 1]
    return max(ok, key=lambda f: f["period_end"], default=None)


class IndexEsefSource:
    def __init__(self, index_url: str, *, client: httpx.AsyncClient | None = None,
                 max_bytes: int = MAX_PACKAGE_BYTES) -> None:
        self._index_url, self._client, self._max_bytes = index_url.rstrip("/"), client, max_bytes

    async def latest_filing(self, lei: str) -> EsefFiling | None:
        if self._client is not None:
            return await self._latest(self._client, lei)
        async with httpx.AsyncClient(
            timeout=60.0, follow_redirects=True, event_hooks={"request": [ssrf_guard_request_hook]}
        ) as client:
            return await self._latest(client, lei)

    async def _latest(self, client: httpx.AsyncClient, lei: str) -> EsefFiling | None:
        latest = pick_latest(await list_esef_filings(client, self._index_url, lei), this_year=date.today().year)
        if latest is None:
            return None
        base = self._index_url + "/"
        json_url, package_url = urljoin(base, latest["json_url"]), urljoin(base, latest["package_url"])
        facts = await download_capped(client, json_url, self._max_bytes)
        package = await download_capped(client, package_url, self._max_bytes)
        return EsefFiling(latest, facts, package, package_url)


def _store_report(lei: str, filing: EsefFiling, store: XbrlStore) -> str:
    if not filing.package:
        return "none"
    a = filing.attributes
    known = store.report_meta(lei)
    if known and known.accession == a["fxo_id"]:
        return "unchanged"
    sha = hashlib.sha256(filing.package).hexdigest()
    store.save_report(lei, filing.package, ReportMeta(
        accession=a["fxo_id"], form="ESEF", filing_date=(a.get("date_added") or "")[:10] or None,
        source_url=filing.package_url, primary_document=(a.get("report_url") or "").rpartition("/")[2],
        filename=f"package-{sha[:16]}.zip", sha256=sha, size=len(filing.package), inline_xbrl=True))
    return "stored"


async def fetch_company_esef(
    company: CompanyRef, *, source: EsefSource, store: XbrlStore, tags: frozenset[str] | None, sleep=asyncio.sleep
) -> CompanyStatus:
    def status(st: str, lei: str | None = None, sha: str | None = None, n: int = 0, report: str = "none") -> CompanyStatus:
        return CompanyStatus(company_id=company.company_id, cik=lei, status=st, source_sha=sha, fact_count=n,
                             report=report, market="esef")

    lei = normalise_lei(company.lei)
    if lei is None:
        return status("no_lei")
    filing = await with_retry(lambda: source.latest_filing(lei), sleep=sleep)
    await sleep(FETCH_DELAY_SECONDS)
    if filing is None:
        return status("not_found", lei)
    sha = store.save_original(lei, filing.facts_json, prefix="xbrl-json")
    tag_list = sorted(tags) if tags is not None else None
    meta = store.meta(lei)
    if meta and meta["source_sha"] == sha and meta["tags"] == tag_list:
        store.add_company_id(lei, company.company_id)
        result, count = "unchanged", meta["fact_count"]
    else:
        rows, skipped = flatten_xbrl_json(json.loads(filing.facts_json), company_id=company.company_id, lei=lei,
                                          source_sha=sha, filing=filing.attributes)
        count = store.write_facts(lei, [r for r in rows if tags is None or r.tag_id in tags])
        store.write_catalog(lei, catalog_from_rows(rows))
        store.write_required(lei, resolve_required_esef(rows, company_id=company.company_id, lei=lei))
        store.set_meta(lei, source_sha=sha, tags=tag_list, company_id=company.company_id, company_name=company.name,
                       fact_count=count, market="esef", original_file=f"xbrl-json-{sha[:16]}.json",
                       skipped_dimensional=skipped)
        result = "ok"
    try:
        report = _store_report(lei, filing, store)
    except Exception as exc:  # noqa: BLE001 -- a report problem never changes the company's status
        logger.warning("ESEF package for %s not stored: %s", lei, exc, exc_info=True)
        report = "error"
    return status(result, lei, sha, count, report)
