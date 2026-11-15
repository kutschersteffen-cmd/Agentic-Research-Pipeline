from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user
from arp.api.deps import get_llm_client, get_portfolio_store, get_superset_client, settings_dep
from arp.bi import service
from arp.bi.service import BIError, DashboardNotFound, DesignResult, NotAnARPDashboard
from arp.bi.superset_client import SupersetClient, SupersetError
from arp.config import Settings, get_settings
from arp.llm.base import LLMClient
from arp.portfolio import qa_audit
from arp.storage.portfolio_store import PortfolioStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bi", tags=["bi"])

_Text = Field(min_length=1, max_length=2000)


class DesignRequest(BaseModel, str_strip_whitespace=True):
    brief: str = _Text


class AskRequest(BaseModel, str_strip_whitespace=True):
    question: str = _Text


class EmbedRequest(BaseModel):
    dashboard_id: str = Field(pattern=r"^\d+$")  # numeric Superset dashboard id
    company_id: str | None = None  # limit the company datasets to this one (must exist in the store)


class EmbedToken(BaseModel):
    token: str
    embedded_id: str  # the UUID the embed SDK mounts, not the numeric dashboard id


class DashboardItem(BaseModel):
    id: int
    slug: str
    title: str
    published: bool


def _bad_gateway(e: Exception, settings: Settings | None = None) -> HTTPException:
    cause = e.__cause__ or e  # BIError wraps the SupersetError whose body operators need
    logger.warning("superset error: %s body=%r", e, getattr(cause, "body", None))
    # Fixed texts only: a Superset response body never reaches the client (it may hold hosts, DSNs or secrets).
    status = cause.status_code if isinstance(cause, SupersetError) else None
    if isinstance(e, httpx.TransportError) or isinstance(cause, httpx.TransportError):  # a raw httpx error's cause is httpcore's
        url = (settings or get_settings()).superset_url.rstrip("/")
        detail = f"Superset is not reachable at {url}. It is not set up here or not running."
    elif status in (401, 403):
        detail = f"Superset login failed (HTTP {status}): check ARP_SUPERSET_USER and ARP_SUPERSET_PASSWORD."
    elif status == 404:
        detail = "Superset has no such dataset or dashboard (HTTP 404): run `arp bi bootstrap`."
    elif isinstance(e, BIError):  # ARP's own short message
        detail = str(e)
    elif status is not None:
        detail = f"Superset request failed (HTTP {status})."
    else:
        detail = "Superset request failed."
    return HTTPException(502, detail)


@router.post("/design", response_model=DesignResult)
async def design(
    req: DesignRequest,
    llm: LLMClient = Depends(get_llm_client),
    client: SupersetClient = Depends(get_superset_client),
    settings: Settings = Depends(settings_dep),
) -> DesignResult:
    """A rejected plan is a normal 200: the UI shows `rejected`."""
    try:
        return await service.design_dashboard(req.brief, llm, client)
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _bad_gateway(e, settings) from e


@router.post("/ask", response_model=DesignResult)
async def ask(
    req: AskRequest,
    llm: LLMClient = Depends(get_llm_client),
    client: SupersetClient = Depends(get_superset_client),
    settings: Settings = Depends(settings_dep),
    principal: Principal = Depends(current_user),
) -> DesignResult:
    result, error = None, None
    try:
        result = await service.ask_chart(req.question, llm, client)
        return result
    except (BIError, SupersetError, httpx.HTTPError) as e:
        error = f"{type(e).__name__}: {e}"
        raise _bad_gateway(e, settings) from e
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        text = (result.url or result.clarification_needed or "; ".join(result.rejected)) if result else None
        qa_audit.record_answer(
            settings, endpoint="bi.ask", principal=principal, question=req.question,
            answer_text=text, vintage={"slug": result.slug, "dashboard_id": result.dashboard_id} if result else {}, error=error,
        )


@router.post("/embed-token", response_model=EmbedToken)
async def embed_token(
    req: EmbedRequest,
    client: SupersetClient = Depends(get_superset_client),
    store: PortfolioStore = Depends(get_portfolio_store),
    settings: Settings = Depends(settings_dep),
) -> EmbedToken:
    # The id becomes an SQL clause in the guest token: only ids in the store get that far.
    if req.company_id is not None and store.get_company(req.company_id) is None:
        raise HTTPException(404, "Unknown company.")
    try:
        embedded_id, token = await asyncio.to_thread(service.embed_token, client, req.dashboard_id, req.company_id)
        return EmbedToken(token=token, embedded_id=embedded_id)
    except DashboardNotFound as e:
        raise HTTPException(404, str(e)) from e
    except NotAnARPDashboard as e:
        raise HTTPException(403, str(e)) from e
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _bad_gateway(e, settings) from e


@router.get("/dashboards", response_model=list[DashboardItem])
async def dashboards(
    client: SupersetClient = Depends(get_superset_client), settings: Settings = Depends(settings_dep)
) -> list[DashboardItem]:
    try:
        items = await asyncio.to_thread(client.list_dashboards)
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _bad_gateway(e, settings) from e
    return sorted((DashboardItem(**i) for i in items), key=lambda d: (d.title.lower(), d.slug))
