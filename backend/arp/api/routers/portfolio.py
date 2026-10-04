from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import get_llm_client, get_portfolio_store, settings_dep
from arp.api.routers.universe import save_universe
from arp.config import Settings
from arp.llm.base import LLMClient
from arp.portfolio import aggregation, analytics, datapoint_mapping, governance, qa_agent
from arp.portfolio.mock_data import generate_demo_dataset
from arp.portfolio.monitoring import evaluator as monitoring_evaluator
from arp.portfolio.news.classifier import classify_article
from arp.schemas.common import CompanyRef
from arp.schemas.governance import (
    GovernanceDecision,
    GovernanceDecisionType,
    GovernanceItemType,
    PolicyChange,
    PolicySettingName,
    RiskCategoryOwner,
)
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, PivotResult, PivotSpec, Portfolio, PortfolioGroup, TrendPoint
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
    policy = governance.get_current_policy(store, settings)
    summary = await generate_demo_dataset(
        store, policy["portfolio_confidence_review_threshold"], policy["climate_validation_tolerance_pct"]
    )
    return summary.__dict__


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


@router.get("/securities-needing-review")
def securities_needing_review(store: PortfolioStore = Depends(get_portfolio_store)) -> list[dict]:
    """Entity-resolution matches below the confidence threshold -- the
    review-queue counterpart to `POST /demo/seed`'s deliberately
    unresolved demo instrument (see `entity_resolution.py`)."""
    return [r.model_dump() for r in store.list_resolutions_needing_review()]


@router.get("/climate-conflicts")
def climate_conflicts(store: PortfolioStore = Depends(get_portfolio_store)) -> list[dict]:
    """Data points whose internal-API value disagreed with an independent
    extraction beyond tolerance -- the governance surface for climate-data
    disagreements, alongside `securities-needing-review`'s entity-resolution
    ones (see `climate/validation.py::cross_check_and_store`)."""
    return [obs.model_dump() for obs in datapoint_mapping.list_conflicting_observations(store)]


class AnalyticRequest(BaseModel):
    name: str = "ad hoc query"
    portfolio_filter: list[str] = Field(default_factory=list)
    security_filter: dict[str, str] = Field(default_factory=dict)
    group_by: str
    metric: str
    data_point_field_id: str | None = None
    as_of: str | None = None
    date_range: tuple[str, str] | None = None
    save: bool = False


@router.post("/aggregate")
def run_aggregation(
    req: AnalyticRequest, store: PortfolioStore = Depends(get_portfolio_store)
) -> AggregationResult | list[TrendPoint]:
    """Executes an ad hoc (or Analytics-Builder-drafted) query against the
    deterministic aggregation engine -- the same executor `qa_agent.py`
    uses for natural-language questions, so a saved analytic and a typed
    query always compute a number the same way.
    """
    spec = AnalyticSpec(
        name=req.name,
        portfolio_filter=req.portfolio_filter,
        security_filter=req.security_filter,
        group_by=req.group_by,
        metric=req.metric,
        data_point_field_id=req.data_point_field_id,
        as_of=req.as_of,
        date_range=req.date_range,
    )
    securities, companies = portfolio_directories(store)
    try:
        result = analytics.execute(spec, store, securities, companies)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if req.save:
        analytics.save_analytic(store, spec)
    return result


class PivotRequest(BaseModel):
    name: str = "ad hoc pivot"
    portfolio_filter: list[str] = Field(default_factory=list)
    security_filter: dict[str, str] = Field(default_factory=dict)
    row_dim: str
    col_dim: str
    metric: str
    data_point_field_id: str | None = None
    as_of: str | None = None


@router.post("/pivot", response_model=PivotResult)
def run_pivot(req: PivotRequest, store: PortfolioStore = Depends(get_portfolio_store)) -> PivotResult:
    """A two-dimension permutation of /aggregate -- e.g. sector x asset
    class, or issuer x portfolio to see one exposure figure broken out
    across every portfolio at once in a single query."""
    spec = PivotSpec(
        name=req.name,
        portfolio_filter=req.portfolio_filter,
        security_filter=req.security_filter,
        row_dim=req.row_dim,
        col_dim=req.col_dim,
        metric=req.metric,
        data_point_field_id=req.data_point_field_id,
        as_of=req.as_of,
    )
    securities, companies = portfolio_directories(store)
    try:
        return analytics.execute_pivot(spec, store, securities, companies)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/analytics", response_model=list[AnalyticSpec])
def list_saved_analytics(store: PortfolioStore = Depends(get_portfolio_store)) -> list[AnalyticSpec]:
    return analytics.list_analytics(store)


@router.get("/analytics/{analytic_id}/run")
def run_saved_analytic(
    analytic_id: str, store: PortfolioStore = Depends(get_portfolio_store)
) -> AggregationResult | list[TrendPoint]:
    spec = analytics.get_analytic(store, analytic_id)
    if spec is None:
        raise HTTPException(404, f"Unknown analytic_id: {analytic_id}")
    securities, companies = portfolio_directories(store)
    return analytics.execute(spec, store, securities, companies)


class AskRequest(BaseModel):
    question: str


@router.post("/ask", response_model=qa_agent.QAAnswer)
async def ask(
    req: AskRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    llm: LLMClient = Depends(get_llm_client),
) -> qa_agent.QAAnswer:
    """Answers a plain-language portfolio question. The LLM only drafts the
    query (see qa_agent.py); the returned `result`/`spec` always show the
    real, deterministically computed figures behind `answer_text`."""
    securities, companies = portfolio_directories(store)
    answer, _usage = await qa_agent.answer_question(req.question, llm, store, securities, companies)
    return answer


@router.get("/news")
def list_news(company_id: str | None = None, store: PortfolioStore = Depends(get_portfolio_store)) -> list[dict]:
    return [n.model_dump() for n in store.list_news(company_id)]


@router.post("/news/classify")
async def classify_news(
    store: PortfolioStore = Depends(get_portfolio_store), llm: LLMClient = Depends(get_llm_client)
) -> dict:
    """Runs the LLM risk classifier (news/classifier.py) over every
    ingested, not-yet-classified news item and persists any resulting,
    grounded risk flags. A deliberate, inspectable batch pass rather than
    something that happens silently on ingestion -- `POST /demo/seed`
    seeds news items but never classifies them itself.
    """
    items = store.list_news()
    already_classified = {f.news_id for f in store.list_flags()}
    pending = [i for i in items if i.news_id not in already_classified]
    flags_created = 0
    for item in pending:
        flag, _usage = await classify_article(item, llm)
        if flag is not None:
            store.append_flag(flag)
            flags_created += 1
    return {"classified": len(pending), "flags_created": flags_created}


@router.get("/news/flags")
def list_flags(company_id: str | None = None, store: PortfolioStore = Depends(get_portfolio_store)) -> list[dict]:
    return [f.model_dump() for f in store.list_flags(company_id)]


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


@router.get("/governance/pending-reviews")
def governance_pending_reviews(store: PortfolioStore = Depends(get_portfolio_store)) -> dict:
    pending = governance.list_pending_reviews(store)
    return {
        "entity_resolution": [r.model_dump() for r in pending["entity_resolution"]],
        "climate_conflict": [o.model_dump() for o in pending["climate_conflict"]],
    }


class GovernanceDecisionRequest(BaseModel):
    item_type: GovernanceItemType
    item_key: str
    decision: GovernanceDecisionType
    reason: str = ""
    override_value: float | str | bool | None = None


@router.post("/governance/decisions", response_model=GovernanceDecision)
def record_governance_decision(
    req: GovernanceDecisionRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    principal: Principal = Depends(current_user),
) -> GovernanceDecision:
    try:
        return governance.record_decision(
            store, req.item_type, req.item_key, req.decision, principal.name, req.reason, req.override_value
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/governance/decisions")
def list_governance_decisions(item_type: GovernanceItemType | None = None, store: PortfolioStore = Depends(get_portfolio_store)) -> list[dict]:
    decisions = [row["decision"] for row in store.list_governance_events() if row["event_type"] == "decision_recorded"]
    return [d for d in decisions if item_type is None or d["item_type"] == item_type]


@router.get("/governance/policy")
def get_governance_policy(store: PortfolioStore = Depends(get_portfolio_store), settings: Settings = Depends(settings_dep)) -> dict:
    return {"values": governance.get_current_policy(store, settings), "history": governance.policy_history(store)}


class PolicyChangeRequest(BaseModel):
    setting_name: PolicySettingName
    new_value: float
    reason: str = ""


@router.put("/governance/policy", response_model=PolicyChange)
def update_governance_policy(
    req: PolicyChangeRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    settings: Settings = Depends(settings_dep),
    principal: Principal = Depends(current_user),
) -> PolicyChange:
    try:
        return governance.set_policy(store, settings, req.setting_name, req.new_value, principal.name, req.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/governance/owners", response_model=list[RiskCategoryOwner])
def list_governance_owners(store: PortfolioStore = Depends(get_portfolio_store)) -> list[RiskCategoryOwner]:
    return list(governance.list_owners(store).values())


class OwnerAssignRequest(BaseModel):
    owner: str


@router.put("/governance/owners/{category}", response_model=RiskCategoryOwner)
def assign_governance_owner(
    category: str,
    req: OwnerAssignRequest,
    store: PortfolioStore = Depends(get_portfolio_store),
    principal: Principal = Depends(current_user),
) -> RiskCategoryOwner:
    try:
        return governance.set_owner(store, category, req.owner, principal.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
