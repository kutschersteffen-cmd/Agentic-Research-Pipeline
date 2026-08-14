from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_llm_client, get_portfolio_store, settings_dep
from arp.config import Settings
from arp.llm.base import LLMClient
from arp.portfolio import analytics, qa_agent
from arp.portfolio.mock_data import generate_demo_dataset
from arp.portfolio.news.classifier import classify_article
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, PivotResult, PivotSpec, Portfolio, SecurityRef, TrendPoint
from arp.storage.portfolio_store import PortfolioStore

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _directories(store: PortfolioStore) -> tuple[dict[str, SecurityRef], dict[str, CompanyRef]]:
    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}
    return securities, companies


@router.post("/demo/seed")
async def seed_demo_dataset(
    store: PortfolioStore = Depends(get_portfolio_store), settings: Settings = Depends(settings_dep)
) -> dict:
    """Seeds the built-in illustrative multi-portfolio demo dataset -- see
    `arp.portfolio.mock_data` for exactly what it contains. Safe to call
    repeatedly: seeding is deterministic and snapshot-overwriting per
    date, so re-seeding always reproduces the same dataset.
    """
    summary = await generate_demo_dataset(
        store, settings.portfolio_confidence_review_threshold, settings.climate_validation_tolerance_pct
    )
    return summary.__dict__


@router.get("/portfolios", response_model=list[Portfolio])
def list_portfolios(store: PortfolioStore = Depends(get_portfolio_store)) -> list[Portfolio]:
    return store.list_portfolios()


@router.get("/companies", response_model=list[CompanyRef])
def list_companies(store: PortfolioStore = Depends(get_portfolio_store)) -> list[CompanyRef]:
    return store.list_companies()


@router.get("/securities-needing-review")
def securities_needing_review(store: PortfolioStore = Depends(get_portfolio_store)) -> list[dict]:
    """Entity-resolution matches below the confidence threshold -- the
    review-queue counterpart to `POST /demo/seed`'s deliberately
    unresolved demo instrument (see `entity_resolution.py`)."""
    return [r.model_dump() for r in store.list_resolutions_needing_review()]


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
    securities, companies = _directories(store)
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
    securities, companies = _directories(store)
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
    securities, companies = _directories(store)
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
    securities, companies = _directories(store)
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
