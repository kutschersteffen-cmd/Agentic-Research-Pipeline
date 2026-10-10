from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar

import httpx

from arp.config import Settings
from arp.ingestion.edgar import AnnualOriginal, EdgarDocumentSource
from arp.ingestion.xbrl import XbrlFactSource
from arp.orchestration.batch_runner import read_done_keys, run_batch
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import hold_run
from arp.schemas.common import CompanyRef
from arp.storage.atomic_io import atomic_write_text
from arp.storage.run_store import RunStore
from arp.storage.safe_path import safe_id
from arp.xbrl_pipeline.flatten import build_catalog, flatten_company_facts
from arp.xbrl_pipeline.models import CompanyStatus, Market, ReportMeta  # noqa: F401 -- Market stays importable from here
from arp.xbrl_pipeline.required import resolve_required
from arp.xbrl_pipeline.store import XbrlStore

if TYPE_CHECKING:
    from arp.universe_workbench.mapping import MasterIndex
    from arp.universe_workbench.routing import Route
    from arp.xbrl_pipeline.fetch_esef import EsefSource

RunMarket = Literal["auto", "sec", "esef"]
T = TypeVar("T")
logger = logging.getLogger(__name__)

FETCH_DELAY_SECONDS = 0.15
_INLINE_MARKER = b"http://www.xbrl.org/2013/inlineXBRL"


class SecSource(Protocol):
    async def resolve_cik(self, cik: str | None, ticker: str | None) -> str | None: ...
    async def fetch_company_facts_raw(self, cik: str) -> tuple[dict | None, bytes | None]: ...
    async def fetch_latest_annual_original(self, cik: str) -> AnnualOriginal | None: ...


class _SecSource:
    def __init__(self, edgar: EdgarDocumentSource, facts: XbrlFactSource) -> None:
        self._edgar, self._facts = edgar, facts

    async def resolve_cik(self, cik: str | None, ticker: str | None) -> str | None:
        return await self._facts.resolve_cik(cik, ticker)

    async def fetch_company_facts_raw(self, cik: str) -> tuple[dict | None, bytes | None]:
        return await self._facts.fetch_company_facts_raw(cik)

    async def fetch_latest_annual_original(self, cik: str) -> AnnualOriginal | None:
        return await self._edgar.fetch_latest_annual_original(cik)


def build_source(settings: Settings, *, refresh: bool = False) -> SecSource:
    # No content or indexing stores: this pipeline never registers documents in shared stores.
    edgar = EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir)
    facts = XbrlFactSource(edgar, settings.cache_dir, ttl_hours=0 if refresh else settings.xbrl_facts_ttl_hours)
    return _SecSource(edgar, facts)


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, httpx.TransportError)


async def with_retry(
    call: Callable[[], Awaitable[T]], *, attempts: int = 3, base_delay: float = 1.0, sleep=asyncio.sleep
) -> T:
    for attempt in range(attempts):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 -- re-raised unless retryable
            if not _retryable(exc) or attempt == attempts - 1:
                raise
            await sleep(base_delay * 2**attempt)
    raise AssertionError("unreachable")


async def _fetch_report(cik10: str, cik: str, *, source: SecSource, store: XbrlStore, sleep) -> str:
    try:
        annual = await with_retry(lambda: source.fetch_latest_annual_original(cik), sleep=sleep)
        await sleep(FETCH_DELAY_SECONDS)
        if annual is None:
            return "none"
        known = store.report_meta(cik10)
        if known and known.accession == annual.accession:
            return "unchanged"
        safe_id(annual.accession, label="accession")
        store.save_report(cik10, annual.content, ReportMeta(
            accession=annual.accession, form=annual.form, filing_date=annual.filing_date,
            source_url=annual.source_url, primary_document=annual.primary_document,
            filename=f"annual-{annual.accession}.htm", sha256=hashlib.sha256(annual.content).hexdigest(), size=len(annual.content),
            inline_xbrl=_INLINE_MARKER in annual.content,
        ))
        return "stored"
    except Exception as exc:  # noqa: BLE001 -- a report problem never changes the company's status
        logger.warning("annual report for %s not stored: %s", cik10, exc, exc_info=True)
        return "error"


def _status(company_id: str, st: str, key: str | None = None, sha: str | None = None, n: int = 0,
            report: str = "none", market: str = "sec") -> CompanyStatus:
    return CompanyStatus(company_id=company_id, cik=key, status=st, source_sha=sha, fact_count=n,
                         report=report, market=market)


async def fetch_company(
    company: CompanyRef, *, source: SecSource, store: XbrlStore, tags: frozenset[str] | None, sleep=asyncio.sleep
) -> CompanyStatus:
    cik = await source.resolve_cik(company.cik, company.ticker)
    if not cik or not cik.isdigit():
        if cik:
            logger.warning("%s: resolved CIK %r is not numeric, treating as no_cik", company.company_id, cik)
        return _status(company.company_id, "no_cik")
    cik10 = cik.zfill(10)
    data, raw = await with_retry(lambda: source.fetch_company_facts_raw(cik), sleep=sleep)
    await sleep(FETCH_DELAY_SECONDS)
    if data is None:
        return _status(company.company_id, "not_found", cik10)
    sha = store.save_original(cik10, raw if raw is not None else json.dumps(data, sort_keys=True).encode())
    tag_list = sorted(tags) if tags is not None else None
    meta = store.meta(cik10)
    if meta and meta["source_sha"] == sha and meta["tags"] == tag_list:
        store.add_company_id(cik10, company.company_id)
        result, count = "unchanged", meta["fact_count"]
    else:
        count = store.write_facts(cik10, flatten_company_facts(
            data, company_id=company.company_id, cik=cik10, source_sha=sha, concepts=tags))
        store.write_catalog(cik10, build_catalog(data))
        store.write_required(cik10, resolve_required(data, company_id=company.company_id, cik=cik10))
        store.set_meta(cik10, source_sha=sha, tags=tag_list, company_id=company.company_id,
                       company_name=company.name, fact_count=count)
        result = "ok"
    report = await _fetch_report(cik10, cik, source=source, store=store, sleep=sleep)
    return _status(company.company_id, result, cik10, sha, count, report)


def _write_routing(run_store: RunStore, run_id: str, routes: list[Route]) -> None:
    entries = [{"company_id": r.company.company_id, "market": r.market, "status": r.status, "basis": r.basis,
                "detail": r.detail, "company": r.company.model_dump(mode="json")} for r in routes]
    atomic_write_text(run_store.run_dir(run_id) / "routing.json", json.dumps(entries, indent=2), prefix=".routing_")


def load_routing(run_store: RunStore, run_id: str) -> dict[str, dict]:
    """company id -> routing entry of an auto run; created from the stored companies when the file is missing."""
    path = run_store.run_dir(run_id) / "routing.json"
    if not path.exists():
        from arp.universe_workbench.routing import route_universe

        _write_routing(run_store, run_id, route_universe(run_store.load_companies(run_id) or []))
    return {e["company_id"]: e for e in json.loads(path.read_text(encoding="utf-8"))}


def create_xbrl_run(
    companies: list[CompanyRef], tags: list[str] | None, refresh: bool, run_store: RunStore,
    market: RunMarket = "sec", index: MasterIndex | None = None,
) -> str:
    params = {"tags": tags, "refresh": refresh, "market": market}
    routes = None
    if market == "auto":
        from arp.universe_workbench.routing import route_universe

        routes = route_universe(companies, index)
        companies = [r.company for r in routes]
    run_id = JobManager(run_store).create_run("xbrl_fetch", params, len(companies), companies=companies).run_id
    if routes is not None:
        _write_routing(run_store, run_id, routes)
    return run_id


def _sync_counts(run_store: RunStore, run_id: str) -> None:
    """Counts rebuilt from the files, so a resume never double counts: a company with a
    result row is completed, one whose errors have no result row is failed."""
    done = read_done_keys(run_store.results_path(run_id))
    failed = {r.get("key") for r in run_store.read_jsonl(run_store.errors_path(run_id))} - done - {None}
    with run_store.lock(run_id):
        manifest = run_store.load_manifest(run_id)
        manifest.completed_count, manifest.failed_count = len(done), len(failed)
        run_store.save_manifest(manifest)


def _auto_fetch(routing: dict[str, dict], settings: Settings, refresh: bool, sec, esef):
    """Fetch one company by its stored route and stored (enriched) company; each source is built only
    when a company first needs it."""
    from arp.xbrl_pipeline.fetch_esef import IndexEsefSource, fetch_company_esef

    sources = {"sec": sec, "esef": esef}
    builders = {"sec": lambda: build_source(settings, refresh=refresh), "esef": lambda: IndexEsefSource(settings.esef_index_url)}

    async def fetch_one(company: CompanyRef, *, store: XbrlStore, tags: frozenset[str] | None) -> CompanyStatus:
        entry = routing.get(company.company_id) or {"status": "unrouted", "detail": "not in stored routing"}
        if entry["status"] != "routed":
            return CompanyStatus(company_id=company.company_id, cik=None, status=entry["status"], source_sha=None,
                                 fact_count=0, report="none", market=None, note=entry["detail"])
        m, company = entry["market"], CompanyRef.model_validate(entry["company"])
        sources[m] = sources[m] or builders[m]()
        return await (fetch_company if m == "sec" else fetch_company_esef)(company, source=sources[m], store=store, tags=tags)

    return fetch_one


async def execute_xbrl_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    settings: Settings,
    run_store: RunStore,
    tags: list[str] | None,
    refresh: bool,
    market: RunMarket = "sec",
    source: SecSource | EsefSource | None = None,
    esef_source: EsefSource | None = None,
) -> str:
    job_manager = JobManager(run_store)
    if market == "auto":
        fetch_one = _auto_fetch(load_routing(run_store, run_id), settings, refresh, source, esef_source)
    elif market == "esef":  # refresh does not apply: the JSON is always re-downloaded and hashed
        from arp.xbrl_pipeline.fetch_esef import IndexEsefSource, fetch_company_esef

        source = source or IndexEsefSource(settings.esef_index_url)
        fetch_one = fetch_company_esef
    else:
        source = source or build_source(settings, refresh=refresh)
        fetch_one = fetch_company
    store = XbrlStore(settings.xbrl_dir)
    tag_set = frozenset(tags) if tags is not None else None

    with hold_run(run_store, run_id):
        job_manager.mark_running(run_id)
        _sync_counts(run_store, run_id)
        await run_batch(
            companies,
            item_key=lambda c: c.company_id,
            worker=(lambda c: fetch_one(c, store=store, tags=tag_set)) if market == "auto"
            else (lambda c: fetch_one(c, source=source, store=store, tags=tag_set)),
            results_path=run_store.results_path(run_id),
            errors_path=run_store.errors_path(run_id),
            concurrency=1,  # SEC rate limit: one company at a time, paced by FETCH_DELAY_SECONDS
            result_to_json=lambda r: r.model_dump(mode="json"),
            on_success=lambda c, r: job_manager.record_progress(run_id, completed_delta=1),
            on_error=lambda c, exc: job_manager.record_progress(run_id, failed_delta=1),
        )
        _sync_counts(run_store, run_id)
        job_manager.finish_run(run_id)
    return run_id
