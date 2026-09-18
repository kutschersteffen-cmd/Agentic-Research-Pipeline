from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_llm_client, get_portfolio_store
from arp.llm.base import LLMClient
from arp.portfolio.genbi import service
from arp.portfolio.genbi.schemas import DashboardSpec, GeneratedDashboard
from arp.storage.portfolio_store import PortfolioStore

router = APIRouter(prefix="/api/portfolio/bi", tags=["portfolio-bi"])


class GenerateRequest(BaseModel):
    brief: str
    narrate: bool = True
    save: bool = False


@router.post("/generate", response_model=GeneratedDashboard)
async def generate(
    req: GenerateRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    llm: LLMClient = Depends(get_llm_client),
) -> GeneratedDashboard:
    """Turns a plain-language brief into a whole dashboard: the LLM plans
    which queries to run and later writes the commentary, but every figure
    is computed by the deterministic aggregation engine and every figure in
    the commentary is checked back against those computed facts before it
    is returned (see `genbi/narrator.py`). An unplannable brief comes back
    with `clarification_needed` set and no invented panels.
    """
    dashboard, _usage = await service.generate_dashboard(req.brief, llm, store, narrate=req.narrate, save=req.save)
    return dashboard


@router.post("/execute", response_model=GeneratedDashboard)
def execute_spec(
    spec: DashboardSpec, as_of: str | None = None, store: PortfolioStore = Depends(get_portfolio_store)
) -> GeneratedDashboard:
    """Executes a dashboard spec as given -- including one the analyst
    edited after it was generated -- with no LLM in the loop. This is the
    path that makes a generated dashboard editable rather than take-it-or-
    leave-it: change a dimension, re-execute, same deterministic engine.
    """
    return service.run_dashboard(spec, store, as_of=as_of)


@router.get("/dashboards", response_model=list[DashboardSpec])
def list_dashboards(store: PortfolioStore = Depends(get_portfolio_store)) -> list[DashboardSpec]:
    return service.list_dashboards(store)


@router.post("/dashboards", response_model=DashboardSpec)
def save_dashboard(spec: DashboardSpec, store: PortfolioStore = Depends(get_portfolio_store)) -> DashboardSpec:
    service.save_dashboard(store, spec)
    return spec


@router.get("/dashboards/{dashboard_id}", response_model=DashboardSpec)
def get_dashboard(dashboard_id: str, store: PortfolioStore = Depends(get_portfolio_store)) -> DashboardSpec:
    spec = service.get_dashboard(store, dashboard_id)
    if spec is None:
        raise HTTPException(404, f"Unknown dashboard_id: {dashboard_id}")
    return spec


@router.get("/dashboards/{dashboard_id}/run", response_model=GeneratedDashboard)
def run_dashboard(
    dashboard_id: str, as_of: str | None = None, store: PortfolioStore = Depends(get_portfolio_store)
) -> GeneratedDashboard:
    """Re-runs a saved dashboard against current (or `as_of`) holdings --
    zero LLM calls, so a recurring report costs nothing and cannot drift
    between runs except through the underlying data."""
    spec = service.get_dashboard(store, dashboard_id)
    if spec is None:
        raise HTTPException(404, f"Unknown dashboard_id: {dashboard_id}")
    return service.run_dashboard(spec, store, as_of=as_of)
