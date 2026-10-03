from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_llm_client, get_superset_client
from arp.bi import service
from arp.bi.service import BIError, DesignResult
from arp.bi.superset_client import SupersetClient, SupersetError
from arp.llm.base import LLMClient

# Not /api/portfolio/bi: that prefix belongs to the older GenBI router.
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


def _bad_gateway(e: Exception) -> HTTPException:
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
        return EmbedToken(token=await asyncio.to_thread(service.embed_token, client, req.dashboard_id))
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _bad_gateway(e) from e
