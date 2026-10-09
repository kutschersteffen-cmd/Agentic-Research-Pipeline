from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from arp.api.deps import settings_dep
from arp.config import Settings
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import RunBusy, run_lease
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError
from arp.universe import load_company_universe
from arp.xbrl_pipeline.fetch import create_xbrl_run, execute_xbrl_run
from arp.xbrl_pipeline.models import RequiredRow
from arp.xbrl_pipeline.registry import TaxonomyRegistry, http_fetch, update_taxonomies
from arp.xbrl_pipeline.selection import cut_selection, list_selections, parse_tag_ids, read_selection_facts
from arp.xbrl_pipeline.store import XbrlStore
from arp.xbrl_pipeline.verify import CircularRunError, UnsupportedRunError, verify_run
from arp.xbrl_pipeline.views import download_path, list_company_files, pivot_facts, query_facts

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()

router = APIRouter(prefix="/api/xbrl", tags=["xbrl"])

Offset = Query(0, ge=0)
Limit = Query(100, ge=1, le=500)


def _run_store(settings: Settings = Depends(settings_dep)) -> RunStore:
    return RunStore(settings.runs_dir)


def _store(settings: Settings = Depends(settings_dep)) -> XbrlStore:
    return XbrlStore(settings.xbrl_dir)


def _manifest(run_store: RunStore, run_id: str):
    try:
        manifest = run_store.load_manifest(run_id)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest


def _on_done(task: asyncio.Task, run_id: str, run_store: RunStore) -> None:
    _tasks.discard(task)
    if task.cancelled() or task.exception() is None:
        return
    logger.error("XBRL run %s failed", run_id, exc_info=task.exception())
    try:  # a failure before the batch finished (e.g. build_source) would leave the run "running" forever
        JobManager(run_store).finish_run(run_id, error=f"{type(task.exception()).__name__}: {task.exception()}")
    except Exception:
        logger.exception("could not mark XBRL run %s failed", run_id)


def _launch(run_id: str, companies: list[CompanyRef], tags: list[str] | None, refresh: bool,
            settings: Settings, run_store: RunStore) -> None:
    task = asyncio.create_task(execute_xbrl_run(
        run_id, companies, settings=settings, run_store=run_store, tags=tags, refresh=refresh), name=run_id)
    _tasks.add(task)  # strong ref: a running task must not be garbage-collected
    task.add_done_callback(lambda t: _on_done(t, run_id, run_store))


class XbrlRunRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    tags: list[str] | None = None
    refresh: bool = False


@router.post("/runs")
async def start_run(
    req: XbrlRunRequest, settings: Settings = Depends(settings_dep), run_store: RunStore = Depends(_run_store)
) -> dict:
    companies = req.companies
    if not companies and req.universe_path:
        try:
            companies = load_company_universe(req.universe_path)
        except Exception as exc:  # whatever the file parsers raise: never echo the path or content
            logger.warning("universe file unreadable: %s", exc)
            raise HTTPException(400, "Could not read the universe file.") from exc
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")
    if req.tags is not None:
        try:
            parse_tag_ids(req.tags)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    run_id = create_xbrl_run(companies, req.tags, req.refresh, run_store)
    _launch(run_id, companies, req.tags, req.refresh, settings, run_store)
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_run(run_id: str, run_store: RunStore = Depends(_run_store)) -> dict:
    return _manifest(run_store, run_id).model_dump(mode="json")


@router.get("/runs/{run_id}/results")
def get_run_results(
    run_id: str, offset: int = Offset, limit: int = Limit, run_store: RunStore = Depends(_run_store)
) -> dict:
    _manifest(run_store, run_id)
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.post("/runs/{run_id}/retry")
async def retry_run(
    run_id: str, settings: Settings = Depends(settings_dep), run_store: RunStore = Depends(_run_store)
) -> dict:
    manifest = _manifest(run_store, run_id)
    companies = run_store.load_companies(run_id)
    if not companies:
        raise HTTPException(400, "This run stored no companies and cannot be retried.")
    # The lease is the truth (the OS frees it if a worker dies); a manifest stuck on "running" must not block retry.
    if any(t.get_name() == run_id for t in _tasks):
        raise HTTPException(409, "This run is currently executing.")
    try:
        with run_lease(run_store, run_id):
            pass
    except RunBusy as exc:
        raise HTTPException(409, "This run is currently executing.") from exc
    JobManager(run_store).mark_running(run_id)  # visible to the client before the task takes the lease
    _launch(run_id, companies, manifest.params.get("tags"), bool(manifest.params.get("refresh")),
            settings, run_store)
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/tags")
def search_tags(
    q: str = "", taxonomy: str | None = None, seen_only: bool = False, extension_only: bool = False,
    offset: int = Offset, limit: int = Query(50, ge=1, le=500), store: XbrlStore = Depends(_store),
) -> dict:
    items, total = TaxonomyRegistry(store).search(
        q, taxonomy=taxonomy, seen_only=seen_only, extension_only=extension_only, offset=offset, limit=limit)
    return {"items": items, "total": total}


@router.post("/taxonomy/update")
async def update_taxonomy(settings: Settings = Depends(settings_dep), store: XbrlStore = Depends(_store)) -> dict:
    try:
        return await update_taxonomies(store, fetch=partial(http_fetch, user_agent=settings.edgar_user_agent))
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Taxonomy update failed: {exc}") from exc


class SelectionRequest(BaseModel):
    tags: list[str]


@router.put("/selections/{name}")
def put_selection(name: str, req: SelectionRequest, store: XbrlStore = Depends(_store)) -> dict:
    try:
        count = cut_selection(store, name, parse_tag_ids(req.tags))
    except (UnsafeIdentifierError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"name": name, "tags": sorted(set(req.tags)), "row_count": count}


@router.get("/selections")
def get_selections(store: XbrlStore = Depends(_store)) -> list[dict]:
    return list_selections(store)


@router.get("/selections/{name}/facts")
def get_selection_facts(
    name: str, offset: int = Offset, limit: int = Limit, store: XbrlStore = Depends(_store)
) -> dict:
    try:
        rows, total = read_selection_facts(store, name, offset=offset, limit=limit)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc
    if name not in {s["name"] for s in list_selections(store)}:
        raise HTTPException(404, "Selection not found")
    return {"items": rows, "total": total}


@router.get("/companies")
def get_companies(offset: int = Offset, limit: int = Query(50, ge=1, le=500), store: XbrlStore = Depends(_store)) -> dict:
    items, total = list_company_files(store, offset=offset, limit=limit)
    return {"items": items, "total": total}


@router.get("/companies/{cik}/files/{kind}")
def download_file(cik: str, kind: str, store: XbrlStore = Depends(_store)) -> FileResponse:
    try:
        path = download_path(store, cik, kind)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "File not found") from exc
    # A 10-K is third-party HTML: never render it inline in our origin.
    return FileResponse(path, filename=path.name, content_disposition_type="attachment", headers={
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.get("/companies/{cik}/facts")
def get_facts(
    cik: str, q: str = "", taxonomy: str | None = None, form: str | None = None, period_year: int | None = None,
    annual_only: bool = False, sort: str = "period_end", order: Literal["asc", "desc"] = "desc",
    offset: int = Offset, limit: int = Limit, store: XbrlStore = Depends(_store),
) -> dict:
    try:
        items, total = query_facts(store, cik, q=q, taxonomy=taxonomy, form=form, period_year=period_year,
                                   annual_only=annual_only, sort=sort, order=order, offset=offset, limit=limit)
    except (UnsafeIdentifierError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"items": items, "total": total}


@router.get("/companies/{cik}/pivot")
def get_pivot(
    cik: str, q: str = "", taxonomy: str | None = None, offset: int = Offset, limit: int = Limit,
    store: XbrlStore = Depends(_store),
):
    try:
        return pivot_facts(store, cik, q=q, taxonomy=taxonomy, offset=offset, limit=limit)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/required")
def get_required(
    run_id: str, run_store: RunStore = Depends(_run_store), store: XbrlStore = Depends(_store)
) -> list[RequiredRow]:
    _manifest(run_store, run_id)
    ids = {c.company_id for c in run_store.load_companies(run_id) or []}
    # A CIK keeps the rows of its first fetch; any company_id that fetched it may ask for them.
    return [r for cik in store.ciks() if ids & set(store.company_ids(cik)) for r in store.read_required(cik)]


class VerifyRequest(BaseModel):
    run_id: str
    mapping: dict[str, str]
    tolerance: float = Field(0.005, ge=0, le=1)


@router.post("/verify")
def verify(req: VerifyRequest, run_store: RunStore = Depends(_run_store), store: XbrlStore = Depends(_store)):
    _manifest(run_store, req.run_id)
    try:
        return verify_run(req.run_id, run_store=run_store, store=store, mapping=req.mapping,
                          tolerance=req.tolerance)
    except CircularRunError as exc:
        raise HTTPException(409, str(exc)) from exc
    except UnsupportedRunError as exc:
        raise HTTPException(400, str(exc)) from exc
