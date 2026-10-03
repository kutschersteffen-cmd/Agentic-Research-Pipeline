"""Idempotent project open: import data, then provision dashboards, under the project lock."""

from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import BaseModel

from arp.bi.plan import DashboardTemplate
from arp.bi.service import BIError
from arp.bi.superset_client import SupersetError
from arp.portfolio.constituent_import import import_constituent_files
from arp.projects.dashboards import provision_project_dashboard
from arp.projects.store import ProjectError, ProjectStore


class OpenError(Exception):
    """A step failed; `step` is "data" or "dashboard:<slug>". Earlier work stays."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


class OpenedDashboard(BaseModel):
    id: int | None
    slug: str
    title: str
    published: bool
    status: str  # created | rebuilt | unchanged | skipped


class OpenResult(BaseModel):
    data: list[dict]
    dashboards: list[OpenedDashboard]


def _import_data(store: ProjectStore, portfolio_store, project_id: str) -> list[dict]:
    out = []
    for src in store.get(project_id).data:
        if src.kind != "dws-constituents":
            continue
        if "notional_eur" not in src.params:
            raise OpenError("data", "Missing notional_eur parameter for the constituent files")
        paths: list[Path] = [store.file_path(project_id, "data", f) for f in src.files]
        try:
            summary = import_constituent_files(
                portfolio_store, paths, src.params["notional_eur"], project_id=project_id
            )
        except (ValueError, OSError) as e:
            raise OpenError("data", str(e)) from e
        out.append({"kind": src.kind, **summary})
    return out


def _open_dashboard(store: ProjectStore, client, project_id: str, d) -> OpenedDashboard:
    if d.source == "superset-export":
        # Import is wired in Task 8; until then the bundle is not applied.
        return OpenedDashboard(id=None, slug=d.slug, title=d.title, published=False, status="skipped")
    step = f"dashboard:{d.slug}"
    try:
        template = DashboardTemplate.model_validate_json(
            store.file_path(project_id, "dashboards", d.file).read_text(encoding="utf-8")
        )
        status = provision_project_dashboard(client, project_id, template)
        dash_id = client.find_dashboard(d.slug)
        published = bool(client.get_dashboard(dash_id)["published"]) if dash_id is not None else False
    except SupersetError as e:  # never echo e.body
        raise OpenError(step, f"Superset returned HTTP {e.status_code}") from None
    except httpx.HTTPError:
        raise OpenError(step, "Superset is unreachable") from None
    except (BIError, ProjectError, OSError, ValueError) as e:
        raise OpenError(step, str(e)) from e
    return OpenedDashboard(id=dash_id, slug=d.slug, title=d.title, published=published, status=status)


def open_project(store: ProjectStore, portfolio_store, client, project_id: str) -> OpenResult:
    with store.lock(project_id):
        data = _import_data(store, portfolio_store, project_id)
        dashboards = [_open_dashboard(store, client, project_id, d) for d in store.get(project_id).dashboards]
        return OpenResult(data=data, dashboards=dashboards)
