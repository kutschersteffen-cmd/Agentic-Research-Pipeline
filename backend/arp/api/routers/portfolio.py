from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import get_llm_client, get_portfolio_store, settings_dep
from arp.api.routers.universe import save_universe
from arp.config import Settings
from arp.holdings.file_source import file_ref
from arp.holdings.intake import IntakeError
from arp.llm.base import LLMClient
from arp.portfolio import aggregation, qa_agent, qa_audit
from arp.portfolio.climate import esg_intake
from arp.portfolio.mock_data import generate_demo_dataset
from arp.portfolio.monitoring import evaluator as monitoring_evaluator
from arp.portfolio.monthly_run import MonthlyRunResult, load_status, run_month
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import (
    Portfolio,
    PortfolioGroup,
)
from arp.schemas.portfolio_monitoring import Alert, AlertRule, AlertStatus, AlertTransition
from arp.storage.portfolio_store import PortfolioStore, portfolio_directories

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.post("/demo/seed")
async def seed_demo_dataset(
    store: PortfolioStore = Depends(get_portfolio_store), settings: Settings = Depends(settings_dep)
) -> dict:
    """Seeds the built-in illustrative multi-portfolio demo dataset -- see
    `arp.portfolio.mock_data` for exactly what it contains. Safe to call
    repeatedly: seeding is deterministic and snapshot-overwriting per
    date, so re-seeding always reproduces the same dataset.
    """
    summary = await generate_demo_dataset(store)
    return summary.__dict__


@router.post("/esg/upload")
async def upload_esg(
    file: UploadFile = File(...),
    provider: str = Form("default"),
    month: str = Form(...),
    _: Principal = Depends(current_user),
    settings: Settings = Depends(settings_dep),
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")

    def intake():
        return esg_intake.ingest_esg_bytes(
            store, data, file.filename or "", provider=provider, month=month, source_ref=file_ref(data))

    try:
        return asdict(await run_in_threadpool(intake))
    except IntakeError as e:
        raise HTTPException(e.status, {"message": e.message, "errors": [asdict(x) for x in e.errors]}) from None
    except ValueError as e:  # unreadable file, unknown provider, bad month
        raise HTTPException(422, {"message": str(e), "errors": []}) from None


@router.get("/esg/template")
def esg_template(fmt: Literal["csv", "xlsx"] = Query("csv", alias="format")) -> Response:
    media = "text/csv" if fmt == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(esg_intake.template(fmt), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="esg-template.{fmt}"'})


@router.get("/portfolios", response_model=list[Portfolio])
def list_portfolios(store: PortfolioStore = Depends(get_portfolio_store)) -> list[Portfolio]:
    return store.list_portfolios()


class GroupRequest(BaseModel):
    group_id: str | None = Field(default=None, description="Existing id: saves a new version.")
    name: str
    kind: Literal["portfolios", "companies", "securities"]
    members: list[str]


@router.post("/groups", response_model=PortfolioGroup)
def save_group(
    req: GroupRequest, store: PortfolioStore = Depends(get_portfolio_store), principal: Principal = Depends(require_role("analyst"))
) -> PortfolioGroup:
    group = PortfolioGroup(
        **req.model_dump(exclude_none=True), created_by=principal.name  # never the user_id
    )
    store.save_group(group)
    return group


@router.get("/groups", response_model=list[PortfolioGroup])
def list_groups(store: PortfolioStore = Depends(get_portfolio_store), _: Principal = Depends(current_user)) -> list[PortfolioGroup]:
    return store.list_groups()


@router.get("/groups/{group_id}", response_model=PortfolioGroup)
def get_group(group_id: str, store: PortfolioStore = Depends(get_portfolio_store), _: Principal = Depends(current_user)) -> PortfolioGroup:
    group = store.get_group(group_id)
    if group is None:
        raise HTTPException(404, f"Unknown group_id: {group_id}")
    return group


@router.get("/companies", response_model=list[CompanyRef])
def list_companies(store: PortfolioStore = Depends(get_portfolio_store)) -> list[CompanyRef]:
    return store.list_companies()


class HoldingsUniverseRequest(BaseModel):
    portfolio_ids: list[str] = Field(default_factory=list, description="Empty: every portfolio.")
    as_of: str | None = Field(default=None, description="Defaults to the latest snapshot date.")


@router.post("/universe")
def holdings_universe(
    req: HoldingsUniverseRequest,
    settings: Settings = Depends(settings_dep),
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """The companies held in the selected portfolios, saved as a universe file,
    so Transition Plan, Extraction or Discovery can run on them without an
    upload. Holdings that don't resolve to a company are counted, not guessed."""
    dates = store.all_snapshot_dates()
    as_of = req.as_of or (dates[-1] if dates else None)
    holdings = store.load_holdings_as_of(as_of, req.portfolio_ids or None) if as_of else []
    if not holdings:
        raise HTTPException(404, "No holdings for that selection and date.")
    securities, companies = portfolio_directories(store)
    result = aggregation.aggregate(
        holdings, securities, companies, group_by="company_id", metric="market_value_sum",
        as_of=as_of, portfolio_filter=req.portfolio_ids or None,
    )
    held = [companies[r.group_value] for r in result.rows if r.group_value in companies]
    unresolved = sum(1 for r in result.rows if r.group_value not in companies)
    name = "holdings_" + ("_".join(req.portfolio_ids) if req.portfolio_ids else "all") + f"_{as_of}"
    return {**save_universe(settings, held, name[:80]), "as_of": as_of, "unresolved": unresolved}


class AskRequest(BaseModel):
    question: str


@router.post("/ask", response_model=qa_agent.QAAnswer)
async def ask(
    req: AskRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    llm: LLMClient = Depends(get_llm_client),
    settings: Settings = Depends(settings_dep),
    principal: Principal = Depends(current_user),
) -> qa_agent.QAAnswer:
    """Answers a plain-language portfolio question. The LLM only drafts the
    query (see qa_agent.py); the returned `result`/`spec` always show the
    real, deterministically computed figures behind `answer_text`. Every
    call -- answered, unresolvable or failed -- leaves an audit row."""
    answer, error = None, None
    try:
        securities, companies = portfolio_directories(store)
        answer, _usage = await qa_agent.answer_question(req.question, llm, store, securities, companies)
        return answer
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        qa_audit.record_answer(
            settings, endpoint="portfolio.ask", principal=principal, question=req.question,
            answer_text=answer.answer_text if answer else None, vintage=answer.vintage if answer else {}, error=error,
            resolvable=answer.resolvable if answer else None,
        )


@router.get("/qa-audit")
def qa_audit_log(
    limit: int = Query(200, ge=1, le=1000), settings: Settings = Depends(settings_dep), _: Principal = Depends(require_role("approver"))
) -> list[dict]:
    return qa_audit.list_audit(settings, limit=limit)


@router.get("/monitoring/rules", response_model=list[AlertRule])
def list_monitoring_rules(store: PortfolioStore = Depends(get_portfolio_store)) -> list[AlertRule]:
    return store.list_rules()


@router.post("/monitoring/rules", response_model=AlertRule)
def create_monitoring_rule(rule: AlertRule, store: PortfolioStore = Depends(get_portfolio_store)) -> AlertRule:
    store.save_rule(rule)
    return rule


@router.get("/monitoring/alerts", response_model=list[Alert])
def list_monitoring_alerts(status: AlertStatus | None = None, store: PortfolioStore = Depends(get_portfolio_store)) -> list[Alert]:
    return monitoring_evaluator.list_alerts(store, status=status)


class AlertTransitionRequest(BaseModel):
    status: AlertStatus
    reason: str = ""
    owner: str | None = None


@router.post("/monitoring/alerts/{scope_id}/{alert_id}/transition", response_model=Alert)
def transition_monitoring_alert(
    scope_id: str,
    alert_id: str,
    req: AlertTransitionRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    principal: Principal = Depends(current_user),
) -> Alert:
    """A human-decided status change -- `decided_by` required, mirrors the
    engagement router's escalate-issue route exactly (see
    engagement_store.py::set_escalation_stage)."""
    try:
        return monitoring_evaluator.transition_alert(
            store, scope_id, alert_id, AlertTransition(status=req.status, decided_by=principal.name, reason=req.reason, owner=req.owner)
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/monitoring/evaluate-now")
def evaluate_monitoring_now(store: PortfolioStore = Depends(get_portfolio_store), settings: Settings = Depends(settings_dep)) -> dict:
    """Manual trigger for demo/testing -- runs the exact same entrypoints
    the scheduler uses (see monitoring/scheduler.py), same discipline as
    discovery's manual-vs-scheduled split."""
    threshold_alerts = monitoring_evaluator.evaluate_threshold_rules(store)
    news_alerts = monitoring_evaluator.evaluate_news_triggers(store, min_severity=settings.portfolio_monitoring_news_min_severity)
    return {"threshold_alerts_raised": len(threshold_alerts), "news_alerts_raised": len(news_alerts)}


class MonthlyRunRequest(BaseModel):
    month: str
    portfolio_ids: list[str] | None = None
    esg_provider: str = "default"


@router.get("/monthly-run/status")
def get_monthly_run_status(
    month: str, portfolio_ids: list[str] | None = Query(None), esg_provider: str = "default",
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    """Read-only: the month's load statuses and what would block its run."""
    ids = portfolio_ids if portfolio_ids is not None else [p.portfolio_id for p in store.list_portfolios()]
    try:
        return load_status(store, month, ids, esg_provider)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/monthly-run", response_model=MonthlyRunResult)
def post_monthly_run(
    body: MonthlyRunRequest, store: PortfolioStore = Depends(get_portfolio_store), settings: Settings = Depends(settings_dep)
) -> MonthlyRunResult:
    ids = body.portfolio_ids if body.portfolio_ids is not None else [p.portfolio_id for p in store.list_portfolios()]
    try:
        return run_month(store, settings, body.month, portfolio_ids=ids, esg_provider=body.esg_provider)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
