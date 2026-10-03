"""Idempotent project open: import data, then provision dashboards, under the project lock."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
from pydantic import BaseModel

from arp.bi.plan import DashboardTemplate
from arp.bi.service import BIError, DashboardNotFound, NotAnARPDashboard
from arp.bi.superset_client import SupersetError
from arp.bi.views import PLACEHOLDER_SECRETS
from arp.config import get_settings
from arp.portfolio.constituent_import import import_constituent_files
from arp.projects.dashboards import provision_project_dashboard
from arp.projects.store import MAX_UPLOAD_BYTES, ProjectError, ProjectStore, StoredDashboard


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
        try:
            paths: list[Path] = [store.file_path(project_id, "data", f) for f in src.files]
            summary = import_constituent_files(
                portfolio_store, paths, src.params["notional_eur"], project_id=project_id
            )
        except Exception as e:  # openpyxl raises BadZipFile, StopIteration, TypeError, ... on bad files
            raise OpenError("data", f"{src.kind}: {e}") from e
        out.append({"kind": src.kind, **summary})
    return out


def dashboard_state(client, slug: str, step: str) -> tuple[int | None, bool]:
    """(Superset id, published) of the dashboard under `slug`; (None, False) if absent."""
    dash_id = client.find_dashboard(slug)
    if dash_id is None:
        return None, False
    meta = client.get_dashboard(dash_id)
    if "published" not in meta:
        raise OpenError(step, "Superset did not report published state")
    return dash_id, bool(meta["published"])


def _open_dashboard(store: ProjectStore, client, project_id: str, d) -> OpenedDashboard:
    step = f"dashboard:{d.slug}"
    if d.source == "superset-export":
        return _open_export(store, client, project_id, d, step)
    try:
        template = DashboardTemplate.model_validate_json(
            store.file_path(project_id, "dashboards", d.file).read_text(encoding="utf-8")
        )
        if template.slug != d.slug:
            raise OpenError(step, f"Stored template slug {template.slug!r} does not match {d.slug!r}")
        status = provision_project_dashboard(client, project_id, template)
        dash_id, published = dashboard_state(client, d.slug, step)
    except SupersetError as e:  # never echo e.body
        raise OpenError(step, f"Superset returned HTTP {e.status_code}") from None
    except httpx.HTTPError:
        raise OpenError(step, "Superset is unreachable") from None
    except (BIError, ProjectError, OSError, ValueError) as e:
        raise OpenError(step, str(e)) from e
    return OpenedDashboard(id=dash_id, slug=d.slug, title=d.title, published=published, status=status)


def _open_export(store: ProjectStore, client, project_id: str, d, step: str) -> OpenedDashboard:
    """Import a stored bundle only when the slug is absent: import overwrites layout, so never over a live one."""
    try:
        dash_id, published = dashboard_state(client, d.slug, step)
        if dash_id is not None:
            return OpenedDashboard(id=dash_id, slug=d.slug, title=d.title, published=published, status="unchanged")
        password = get_settings().bi_reader_password
        if not password or password in PLACEHOLDER_SECRETS:
            raise OpenError(step, "ARP_BI_READER_PASSWORD is unset or a placeholder; cannot import the stored dashboard")
        path = store.file_path(project_id, "dashboards", d.file)
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise OpenError(step, "Stored bundle is too large to import")
        bundle = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(bundle)) as z:
            parts = [n.split("/") for n in z.namelist()]
            keys = ["/".join(q[1:]) for q in parts if len(q) == 3 and q[1] == "databases" and q[2].endswith(".yaml")]
        if len(keys) != 1:  # ponytail: multi-database bundles unsupported, one reader password only
            raise OpenError(step, f"Stored bundle must contain exactly one databases/*.yaml entry, found {len(keys)}")
        client.import_dashboard(bundle, {keys[0]: password})
        dash_id, published = dashboard_state(client, d.slug, step)
        if dash_id is not None and published:  # only a dashboard this import just created
            client.unpublish_dashboard(dash_id)
            dash_id, published = dashboard_state(client, d.slug, step)
            if published:
                raise OpenError(step, "could not unpublish the imported dashboard")
    except SupersetError as e:  # never echo e.body
        raise OpenError(step, f"Superset returned HTTP {e.status_code}") from None
    except httpx.HTTPError:
        raise OpenError(step, "Superset is unreachable") from None
    except zipfile.BadZipFile:
        raise OpenError(step, "Stored bundle is not a valid zip") from None
    except (BIError, ProjectError, OSError, ValueError) as e:
        raise OpenError(step, str(e)) from e
    if dash_id is None:
        raise OpenError(step, "Import finished but the dashboard slug was not found")
    return OpenedDashboard(id=dash_id, slug=d.slug, title=d.title, published=published, status="created")


def export_dashboard_to_project(store: ProjectStore, client, project_id: str, dashboard_id: int) -> StoredDashboard:
    """Store a hand-built Superset dashboard as an export bundle under the project.

    Only `arp-` slugs are accepted; the dashboard keeps its own slug. Data scoping caveat:
    a hand-built dashboard is NOT scoped to the project -- its charts are the user's own,
    so it may show other projects' rows unless they filtered by project_id themselves."""
    try:
        meta = client.get_dashboard(dashboard_id)
    except SupersetError as e:
        if e.status_code == 404:
            raise DashboardNotFound(f"Dashboard {dashboard_id} not found.") from e
        raise
    slug = meta.get("slug") or ""
    if not slug.startswith("arp-"):
        raise NotAnARPDashboard(f"Dashboard {dashboard_id} has no arp- slug; only arp- dashboards can be stored.")
    store.get(project_id)
    bundle = client.export_dashboard(dashboard_id)
    project = store.save_dashboard(
        project_id, slug, meta.get("dashboard_title") or slug, "superset-export", bundle
    )
    return next(d for d in project.dashboards if d.slug == slug)


def open_project(store: ProjectStore, portfolio_store, client, project_id: str) -> OpenResult:
    with store.lock(project_id):
        data = _import_data(store, portfolio_store, project_id)
        dashboards = [_open_dashboard(store, client, project_id, d) for d in store.get(project_id).dashboards]
        return OpenResult(data=data, dashboards=dashboards)
