"""BI designer orchestration: brief -> plan -> Superset charts + draft dashboard.

Nothing is written to Superset unless the planner returns a valid plan.
Creation is compensating: when a step fails, everything this call created is
deleted again. Dashboards stay drafts; making one public is a human step in
Superset (the client cannot do it)."""

from __future__ import annotations

import asyncio
import contextlib

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


def _build_dashboard(client: SupersetClient, plan: ChartPlan, ids: dict[str, int]) -> DesignResult:
    slug = f"arp-{plan_hash(plan)}"
    try:
        existing = client.find_dashboard(slug)
        if existing is not None:
            charts = client.dashboard_charts(existing)
            if len(charts) == len(plan.charts):  # same plan as before: reuse, create nothing
                return _result(existing, slug, plan)
            # Half-built or emptied since: replace it rather than return it as done.
            client.delete_dashboard(existing)
            _cleanup(client, list(charts))
    except _ERRORS as e:
        raise BIError(f"Superset: {e}") from e
    created: list[int] = []
    try:
        _create_charts(client, plan, ids, created)
        try:
            dash = client.create_dashboard(plan.title, slug, compile_dashboard(created, [c.title for c in plan.charts]), created)
        except _ERRORS as e:
            raise BIError(f"Creating dashboard {plan.title!r} failed: {e}") from e
    except Exception:  # any failure, compiler bugs included: remove what this call made
        _cleanup(client, created)
        raise
    return _result(dash, slug, plan)


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


def embed_token(client: SupersetClient, dashboard_id: str, rls: list[dict] | None = None) -> str:
    """Guest token for embedding the dashboard. Guest tokens name the
    dashboard's embedded UUID, not its id, so embedding is enabled first
    (idempotent). `rls` is the row-level-security hook; empty in v1."""
    try:
        return client.guest_token(client.ensure_embedded(int(dashboard_id)), rls or [])
    except _ERRORS as e:
        raise BIError(f"Superset: {e}") from e
