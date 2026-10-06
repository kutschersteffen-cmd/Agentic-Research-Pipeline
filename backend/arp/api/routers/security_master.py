"""Data Hub: the security master (the golden source mapping securities to internal issuer ids, exact match only) and
the overview of every input feed, the open issues and Smart Search over them."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from arp import catalog, smart_search
from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import (
    get_decision_store,
    get_index_store,
    get_llm_client,
    get_portfolio_store,
    get_reporting_store,
    get_run_store,
    get_taxonomy_store,
    settings_dep,
)
from arp.config import Settings
from arp.holdings import security_master
from arp.holdings.intake import IntakeError, previous_month_end
from arp.llm.base import LLMClient
from arp.portfolio import feeds, issues, qa_audit
from arp.portfolio.climate.esg_api_source import pull_esg
from arp.portfolio.news.api_source import pull_news
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/security-master", tags=["security-master"])
feeds_router = APIRouter(prefix="/api/feeds", tags=["feeds"])
issues_router = APIRouter(prefix="/api/issues", tags=["issues"])
search_router = APIRouter(prefix="/api/smart-search", tags=["smart-search"])


def _idmap(settings: Settings = Depends(settings_dep)) -> IdentifierMapStore:
    return IdentifierMapStore(settings.identifier_map_path)


@router.get("")
def get_status(store=Depends(get_portfolio_store), idmap: IdentifierMapStore = Depends(_idmap)) -> dict:
    return security_master.status(store, idmap)


@feeds_router.get("")
def get_feeds(store=Depends(get_portfolio_store), idmap: IdentifierMapStore = Depends(_idmap)) -> dict:
    """Every input feed with its last load and whether it is behind (Data Hub · Feeds)."""
    return {"feeds": feeds.overview(store, idmap, date.today())}


@feeds_router.post("/news/pull")
def post_news_pull(
    since: str | None = None, settings: Settings = Depends(settings_dep), store=Depends(get_portfolio_store),
    idmap: IdentifierMapStore = Depends(_idmap),
) -> dict:
    """Pulls new stories from Refinitiv News; each is tied to an issuer through the security master's PermIDs only."""
    if not settings.news_api_client_id or not settings.news_api_client_secret:
        raise HTTPException(503, "news API is not configured (ARP_NEWS_API_CLIENT_ID, ARP_NEWS_API_CLIENT_SECRET)")
    try:
        return pull_news(store, settings, idmap, since=since)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"news pull failed: {type(e).__name__}") from None
    except ValueError as e:  # an unexpected response shape
        raise HTTPException(502, str(e)) from None


@feeds_router.post("/esg/pull")
def post_esg_pull(
    month: str | None = None, provider: str = "default", settings: Settings = Depends(settings_dep),
    store=Depends(get_portfolio_store),
) -> dict:
    """Pulls a month's ESG file (default: last month) through the same intake as an upload."""
    if not settings.esg_api_base_url or not settings.esg_api_token:
        raise HTTPException(503, "ESG API is not configured (ARP_ESG_API_URL, ARP_ESG_API_TOKEN)")
    try:
        result = pull_esg(store, settings, month or previous_month_end(date.today())[:7], provider)
    except IntakeError as e:
        raise HTTPException(e.status, {"message": e.message, "errors": [asdict(x) for x in e.errors[:200]]}) from None
    except httpx.HTTPError as e:
        raise HTTPException(502, f"ESG pull failed: {type(e).__name__}") from None
    except ValueError as e:
        raise HTTPException(422, {"message": str(e), "errors": []}) from None
    return asdict(result)


@router.get("/unmatched")
def get_unmatched(store=Depends(get_portfolio_store), idmap: IdentifierMapStore = Depends(_idmap)) -> dict:
    return {"rows": security_master.unmatched(store, idmap)}


@router.get("/template")
def download_template() -> Response:
    return Response(",".join(security_master.COLUMNS) + "\n", media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="security-master-template.csv"'})


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    user: Principal = Depends(require_role("approver")),  # replaces the golden source for the whole tool
    settings: Settings = Depends(settings_dep),
    store=Depends(get_portfolio_store),
    idmap: IdentifierMapStore = Depends(_idmap),
) -> dict:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")
    try:
        # ponytail: no lock -- two simultaneous loads each replace the map whole, last one wins; add a KeyedLock if that happens.
        return await run_in_threadpool(security_master.load, store, idmap, data, file.filename or "")
    except security_master.MasterRejected as e:
        raise HTTPException(422, {"message": str(e), "errors": [asdict(x) for x in e.errors[:200]]}) from None
    except ValueError as e:  # unreadable or unsupported file
        raise HTTPException(422, {"message": str(e), "errors": []}) from None


@issues_router.get("")
def get_issues(
    store=Depends(get_portfolio_store), idmap: IdentifierMapStore = Depends(_idmap), run_store: RunStore = Depends(get_run_store),
) -> dict:
    """Every open data problem: feeds behind or failed, unmatched securities, undecided failing checks (Data Hub · Issues)."""
    return {"issues": issues.open_issues(store, idmap, run_store, date.today())}


class SmartSearchRequest(BaseModel):
    question: str


@search_router.post("", response_model=smart_search.SearchAnswer)
async def post_smart_search(
    req: SmartSearchRequest, settings: Settings = Depends(settings_dep), store=Depends(get_portfolio_store),
    idmap: IdentifierMapStore = Depends(_idmap), run_store: RunStore = Depends(get_run_store), decisions=Depends(get_decision_store),
    taxonomy=Depends(get_taxonomy_store), index=Depends(get_index_store), reports=Depends(get_reporting_store),
    llm: LLMClient = Depends(get_llm_client), principal: Principal = Depends(current_user),
) -> smart_search.SearchAnswer:
    """A plain-language question becomes a filter over issues, outputs or feeds (the model's only job); code applies it.
    Every call leaves an audit row, like Ask the Portfolio."""
    answer, error = None, None
    try:
        today = date.today()
        lists = await run_in_threadpool(lambda: {
            "issues": issues.open_issues(store, idmap, run_store, today),
            "outputs": catalog.catalog(runs_dir=settings.runs_dir, run_store=run_store, decisions=decisions, taxonomy=taxonomy,
                                       index=index, reports=reports),
            "feeds": feeds.overview(store, idmap, today),
        })
        answer, _usage = await smart_search.smart_search(req.question, llm, **lists)
        return answer
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        qa_audit.record_answer(settings, endpoint="datahub.smart_search", principal=principal, question=req.question,
                               answer_text=answer.answer_text if answer else None, vintage={}, error=error,
                               resolvable=answer.resolvable if answer else None)
