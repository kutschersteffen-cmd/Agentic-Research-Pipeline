from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_llm_client, get_superset_client
from arp.bi import service
from arp.bi.service import BIError, DashboardNotFound, DesignResult, NotAnARPDashboard
from arp.bi.superset_client import SupersetClient, SupersetError
from arp.llm.base import LLMClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bi", tags=["bi"])

_Text = Field(min_length=1, max_length=2000)


class DesignRequest(BaseModel, str_strip_whitespace=True):
    brief: str = _Text


class AskRequest(BaseModel, str_strip_whitespace=True):
    question: str = _Text


class EmbedRequest(BaseModel):
    dashboard_id: str = Field(pattern=r"^\d+$")  # numeric Superset dashboard id


class EmbedToken(BaseModel):
    token: str
    embedded_id: str  # the UUID the embed SDK mounts, not the numeric dashboard id


def _bad_gateway(e: Exception) -> HTTPException:
    cause = e.__cause__ or e  # BIError wraps the SupersetError whose body operators need
    logger.warning("superset error: %s body=%r", e, getattr(cause, "body", None))
    # BIError carries a short message of ours; a raw SupersetError/httpx error never
    # reaches the client verbatim (its body may hold secrets).
    return HTTPException(502, str(e) if isinstance(e, BIError) else "Superset request failed")


@router.post("/design", response_model=DesignResult)
async def design(
    req: DesignRequest,
    llm: LLMClient = Depends(get_llm_client),
    client: SupersetClient = Depends(get_superset_client),
) -> DesignResult:
    """A rejected plan is a normal 200: the UI shows `rejected`."""
    try:
        return await service.design_dashboard(req.brief, llm, client)
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _bad_gateway(e) from e


@router.post("/ask", response_model=DesignResult)
async def ask(
    req: AskRequest,
    llm: LLMClient = Depends(get_llm_client),
    client: SupersetClient = Depends(get_superset_client),
) -> DesignResult:
    try:
        return await service.ask_chart(req.question, llm, client)
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _bad_gateway(e) from e


@router.post("/embed-token", response_model=EmbedToken)
async def embed_token(req: EmbedRequest, client: SupersetClient = Depends(get_superset_client)) -> EmbedToken:
    try:
        embedded_id, token = await asyncio.to_thread(service.embed_token, client, req.dashboard_id)
        return EmbedToken(token=token, embedded_id=embedded_id)
    except DashboardNotFound as e:
        raise HTTPException(404, str(e)) from e
    except NotAnARPDashboard as e:
        raise HTTPException(403, str(e)) from e
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _bad_gateway(e) from e
