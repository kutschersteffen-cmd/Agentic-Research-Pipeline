from __future__ import annotations

import asyncio
import math
import re

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from arp.api import deps
from arp.api.deps import get_portfolio_store, get_project_store, get_superset_client
from arp.api.routers.bi import _bad_gateway
from arp.bi.plan import ChartPlan
from arp.bi.service import BIError, _datasets
from arp.bi.superset_client import SupersetError
from arp.bi.validator import validate_plan
from arp.projects import store as store_mod
from arp.projects.dashboards import plan_to_template, provision_project_dashboard
from arp.projects.service import OpenedDashboard, OpenError, OpenResult, dashboard_state, open_project
from arp.projects.store import Project, ProjectError, ProjectNotFound, ProjectStore

router = APIRouter(prefix="/api/projects", tags=["projects"])

_ERRORS = (BIError, SupersetError, httpx.HTTPError)


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    data_files: int
    dashboards: int


class CreateRequest(BaseModel, str_strip_whitespace=True):
    id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class SaveDashboardRequest(BaseModel, str_strip_whitespace=True):
    title: str = Field(min_length=1, max_length=200)
    plan: ChartPlan


def _require_postgres() -> None:
    # Listed first in a handler's dependencies so nothing runs before this check.
    if deps.get_settings().portfolio_backend != "postgres":
        raise HTTPException(503, "Projects need Postgres: set ARP_PORTFOLIO_BACKEND=postgres.")


def _summary(p: Project) -> ProjectSummary:
    return ProjectSummary(
        id=p.id, name=p.name, description=p.description, created_at=p.created_at,
        data_files=sum(len(s.files) for s in p.data), dashboards=len(p.dashboards),
    )  # fmt: skip


def _get(store: ProjectStore, id: str) -> Project:
    try:
        return store.get(id)
    except ProjectNotFound as e:
        raise HTTPException(404, str(e)) from e


@router.get("", response_model=list[ProjectSummary])
def list_projects(store: ProjectStore = Depends(get_project_store)) -> list[ProjectSummary]:
    return [_summary(p) for p in store.list()]


@router.post("", response_model=Project, status_code=201)
def create_project(req: CreateRequest, store: ProjectStore = Depends(get_project_store)) -> Project:
    pid = req.id or re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-")[:63].strip("-")
    try:
        return store.create(pid, req.name, req.description)
    except ProjectError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/{id}", response_model=Project)
def get_project(id: str, store: ProjectStore = Depends(get_project_store)) -> Project:
    return _get(store, id)


@router.post("/{id}/data", response_model=Project)
async def upload_data(
    id: str,
    file: UploadFile = File(...),
    notional_eur: str = Form(...),
    store: ProjectStore = Depends(get_project_store),
) -> Project:
    try:
        notional = float(notional_eur)
    except ValueError:
        notional = math.nan
    if not math.isfinite(notional) or notional <= 0:
        raise HTTPException(422, "notional_eur must be a finite number greater than 0")
    limit = store_mod.MAX_UPLOAD_BYTES
    content = await file.read(limit + 1)  # never buffers more than limit + 1 bytes
    if len(content) > limit:
        raise HTTPException(422, f"Upload exceeds {limit // (1024 * 1024)} MB limit")
    _get(store, id)
    try:
        return await asyncio.to_thread(
            store.add_data_file, id, file.filename or "", content, {"notional_eur": notional}
        )
    except ProjectNotFound as e:
        raise HTTPException(404, str(e)) from e
    except ProjectError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/{id}/open", response_model=OpenResult, dependencies=[Depends(_require_postgres)])
async def open_(
    id: str,
    store: ProjectStore = Depends(get_project_store),
    portfolio_store=Depends(get_portfolio_store),
    client=Depends(get_superset_client),
) -> OpenResult:
    try:
        return await asyncio.to_thread(open_project, store, portfolio_store, client, id)
    except ProjectNotFound as e:
        raise HTTPException(404, str(e)) from e
    except ProjectError as e:
        raise HTTPException(422, str(e)) from e
    except OpenError as e:
        raise HTTPException(502, f"Opening the project failed at {e.step}: {e}") from e
    except _ERRORS as e:
        raise _bad_gateway(e) from e


def _save_dashboard(store: ProjectStore, client, id: str, req: SaveDashboardRequest) -> OpenedDashboard:
    _, metas = _datasets(client)
    problems = validate_plan(req.plan, metas, max_charts=6)
    if problems:
        raise HTTPException(422, problems)
    template = plan_to_template(id, req.title, req.plan)
    store.save_dashboard(id, template.slug, req.title, "template", template.model_dump_json().encode())
    status = provision_project_dashboard(client, id, template)
    dash_id, published = dashboard_state(client, template.slug, f"dashboard:{template.slug}")
    return OpenedDashboard(id=dash_id, slug=template.slug, title=req.title, published=published, status=status)


@router.post("/{id}/dashboards", response_model=OpenedDashboard, dependencies=[Depends(_require_postgres)])
async def save_dashboard(
    id: str,
    req: SaveDashboardRequest,
    store: ProjectStore = Depends(get_project_store),
    client=Depends(get_superset_client),
) -> OpenedDashboard:
    _get(store, id)
    try:
        return await asyncio.to_thread(_save_dashboard, store, client, id, req)
    except ProjectNotFound as e:
        raise HTTPException(404, str(e)) from e
    except ProjectError as e:
        raise HTTPException(422, str(e)) from e
    except OpenError as e:
        raise HTTPException(502, f"Saving the dashboard failed: {e}") from e
    except _ERRORS as e:
        raise _bad_gateway(e) from e
