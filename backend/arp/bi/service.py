"""BI designer orchestration: brief -> plan -> Superset charts + draft dashboard.

Nothing is written to Superset unless the planner returns a valid plan.
Creation is compensating: when a step fails, everything this call created is
deleted again. Dashboards stay drafts; making one public is a human step in
Superset (the client cannot do it)."""

from __future__ import annotations

import asyncio
import contextlib
import threading

import httpx
from pydantic import BaseModel

from arp.bi.catalog import BI_DATABASE, VIEW_DATASETS
from arp.bi.compiler import compile_chart, compile_dashboard, plan_hash
from arp.bi.plan import ChartPlan, DatasetMeta
from arp.bi.planner import plan_from_brief
from arp.bi.superset_client import SupersetClient, SupersetError
from arp.config import get_settings
from arp.llm.base import LLMClient

SCRATCH_SLUG = "arp-scratch"
_ERRORS = (SupersetError, httpx.HTTPError)


class BIError(Exception):
    """Superset rejected or failed a step; whatever this call created was removed."""


class DashboardNotFound(BIError):
    """No Superset dashboard has that id."""


class NotAnARPDashboard(BIError):
    """The dashboard was not made by ARP (slug not `arp-...`), so ARP will not embed it."""


class DesignResult(BaseModel):
    dashboard_id: int | None = None
    slug: str | None = None
    url: str | None = None
    plan: ChartPlan | None = None
    rejected: list[str] = []
    # ponytail: plan_from_brief returns (None, reasons) for both a refusal and a failed
    # repair round, so every reason lands in `rejected`; this stays None until it says which.
    clarification_needed: str | None = None


def _datasets(client: SupersetClient) -> tuple[dict[str, int], dict[str, DatasetMeta]]:
    """Catalog name -> Superset dataset id and its live columns/metrics.
    Looks them up only: creating them is `arp bi bootstrap`'s job."""
    try:
        db = client.find_database(BI_DATABASE)
        if db is None:
            raise BIError(f"Superset has no database {BI_DATABASE!r} -- run `arp bi bootstrap`.")
        ids = {}
        for name, d in VIEW_DATASETS.items():
            ids[name] = client.find_dataset(db, "bi", d.table)
            if ids[name] is None:
                raise BIError(f"Superset has no dataset bi.{d.table} -- run `arp bi bootstrap`.")
        return ids, {name: client.dataset_meta(i) for name, i in ids.items()}
    except _ERRORS as e:
        raise BIError(f"Superset: {e}") from e


def _result(dashboard_id: int, slug: str, plan: ChartPlan) -> DesignResult:
    url = f"{get_settings().superset_url.rstrip('/')}/superset/dashboard/{slug}/"
    return DesignResult(dashboard_id=dashboard_id, slug=slug, url=url, plan=plan)


def _create_charts(client: SupersetClient, plan: ChartPlan, ids: dict[str, int], created: list[int]) -> None:
    """Appends each new chart id to `created` as it goes, so the caller can clean up."""
    for spec in plan.charts:
        try:
            created.append(
                client.create_chart(spec.title, ids[spec.dataset], spec.viz_type, compile_chart(spec, ids[spec.dataset]))
            )
        except _ERRORS as e:
            raise BIError(f"Creating chart {spec.title!r} failed: {e}") from e


def _cleanup(client: SupersetClient, chart_ids: list[int]) -> None:
    # Best effort: the original error is what the caller needs to see. A
    # dashboard is never deleted here; create_dashboard removes its own half-made one.
    for cid in chart_ids:
        with contextlib.suppress(*_ERRORS):
            client.delete_chart(cid)


def _ensure_dashboard(
    client: SupersetClient, slug: str, plan: ChartPlan, ids: dict[str, int], json_metadata: dict | None = None
) -> tuple[int, str]:
    """(dashboard id, "created" | "rebuilt" | "unchanged") for `slug` holding the plan's charts."""
    status = "created"
    try:
        existing = client.find_dashboard(slug)
        if existing is not None:
            charts = client.dashboard_charts(existing)
            # Same plan as before: reuse, create nothing. More charts means a person
            # extended it, which must survive a re-run.
            if len(charts) >= len(plan.charts):
                return existing, "unchanged"
            # Fewer: half-built or emptied since; replace it rather than return it as done.
            # Only the dashboard goes; its charts may sit on other dashboards too.
            client.delete_dashboard(existing)
            status = "rebuilt"
    except _ERRORS as e:
        raise BIError(f"Superset: {e}") from e
    created: list[int] = []
    try:
        _create_charts(client, plan, ids, created)
        try:
            position = compile_dashboard(created, [c.title for c in plan.charts])
            dash = client.create_dashboard(plan.title, slug, position, created, json_metadata)
        except _ERRORS as e:
            raise BIError(f"Creating dashboard {plan.title!r} failed: {e}") from e
    except Exception:  # any failure, compiler bugs included: remove what this call made
        _cleanup(client, created)
        raise
    return dash, status


def _build_dashboard(client: SupersetClient, plan: ChartPlan, ids: dict[str, int]) -> DesignResult:
    slug = f"arp-{plan_hash(plan)}"
    return _result(_ensure_dashboard(client, slug, plan, ids)[0], slug, plan)


def _add_to_scratch(client: SupersetClient, plan: ChartPlan, ids: dict[str, int]) -> DesignResult:
    title = plan.charts[0].title
    created: list[int] = []
    try:
        _create_charts(client, plan, ids, created)
        try:
            dash = client.find_dashboard(SCRATCH_SLUG)
            if dash is None:
                dash = client.create_dashboard("Scratch", SCRATCH_SLUG, compile_dashboard(created, [title]), created)
            else:
                charts = client.dashboard_charts(dash) | {created[0]: title}
                order = sorted(charts)  # chart ids grow, so this is question order
                client.update_dashboard(dash, compile_dashboard(order, [charts[c] for c in order]), created)
        except _ERRORS as e:
            raise BIError(f"Adding chart {title!r} to the scratch dashboard failed: {e}") from e
    except Exception:  # an existing scratch dashboard keeps its charts; only the new one goes
        _cleanup(client, created)
        raise
    return _result(dash, SCRATCH_SLUG, plan)


async def design_dashboard(brief: str, llm: LLMClient, client: SupersetClient) -> DesignResult:
    # The client is sync; its calls run in a thread to keep the event loop free.
    ids, metas = await asyncio.to_thread(_datasets, client)
    plan, reasons = await plan_from_brief(brief, metas, llm)
    if plan is None:
        return DesignResult(rejected=reasons)
    return await asyncio.to_thread(_build_dashboard, client, plan, ids)


async def ask_chart(question: str, llm: LLMClient, client: SupersetClient) -> DesignResult:
    """One question -> one chart, added to the shared scratch dashboard."""
    ids, metas = await asyncio.to_thread(_datasets, client)
    plan, reasons = await plan_from_brief(f"Answer with exactly one chart: {question}", metas, llm)
    if plan is None:
        return DesignResult(rejected=reasons)
    plan = plan.model_copy(update={"charts": plan.charts[:1]})  # a question gets one chart, the planner's first
    return await asyncio.to_thread(_add_to_scratch, client, plan, ids)


# Superset's embedded upsert races: concurrent first-time POSTs each mint a UUID and
# only the last one survives, so the other caller's iframe 404s (React StrictMode's
# double effect hit this on every fresh draft).
# ponytail: one process-wide lock; a multi-worker deploy needs a DB/advisory lock.
_EMBED_LOCK = threading.Lock()


def embed_token(client: SupersetClient, dashboard_id: str, rls: list[dict] | None = None) -> tuple[str, str]:
    """(embedded UUID, guest token) for embedding the dashboard. Guest tokens
    and the embed SDK name the embedded UUID, not the id, so embedding is
    enabled first (idempotent). `rls` is the row-level-security hook; empty in v1.
    Only ARP's own dashboards (slug `arp-...`, scratch included) are embedded."""
    try:
        try:
            slug = client.get_dashboard(int(dashboard_id)).get("slug") or ""
        except SupersetError as e:
            if e.status_code == 404:
                raise DashboardNotFound(f"Dashboard {dashboard_id} not found.") from e
            raise
        if not slug.startswith("arp-"):
            raise NotAnARPDashboard(f"Dashboard {dashboard_id} was not made by ARP; only arp- dashboards can be embedded.")
        with _EMBED_LOCK:
            embedded_id = client.ensure_embedded(int(dashboard_id))
        return embedded_id, client.guest_token(embedded_id, rls or [])
    except _ERRORS as e:
        raise BIError(f"Superset: {e}") from e
