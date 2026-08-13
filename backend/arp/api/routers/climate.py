from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from arp.api.deps import get_portfolio_store
from arp.portfolio import analytics
from arp.portfolio.climate import metrics as climate_metrics
from arp.portfolio.climate.schemas import build_climate_schema
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.portfolio import AggregationResult, PivotResult, PivotSpec, SecurityRef, TrendPoint
from arp.storage.portfolio_store import PortfolioStore

router = APIRouter(prefix="/api/climate", tags=["climate"])


def _directories(store: PortfolioStore) -> tuple[dict[str, SecurityRef], dict[str, CompanyRef]]:
    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}
    return securities, companies


def _resolve_as_of(store: PortfolioStore, as_of: str | None) -> str:
    if as_of:
        return as_of
    dates = store.all_snapshot_dates()
    if not dates:
        raise HTTPException(404, "No holdings snapshots available -- seed the demo dataset or ingest holdings first.")
    return dates[-1]


@router.get("/schema", response_model=DataPointSchema)
def climate_schema() -> DataPointSchema:
    return build_climate_schema()


@router.get("/waci", response_model=AggregationResult)
def waci(
    as_of: str | None = None,
    group_by: str = "portfolio_id",
    portfolio_id: list[str] | None = Query(default=None),
    store: PortfolioStore = Depends(get_portfolio_store),
) -> AggregationResult:
    securities, companies = _directories(store)
    resolved_as_of = _resolve_as_of(store, as_of)
    holdings = store.load_holdings_as_of(resolved_as_of, portfolio_id)
    return climate_metrics.compute_waci(
        store, holdings, securities, companies, as_of=resolved_as_of, group_by=group_by, portfolio_filter=portfolio_id
    )


@router.get("/waci/trend", response_model=list[TrendPoint])
def waci_trend(
    group_by: str = "portfolio_id",
    portfolio_id: list[str] | None = Query(default=None),
    store: PortfolioStore = Depends(get_portfolio_store),
) -> list[TrendPoint]:
    securities, companies = _directories(store)
    holdings_by_date = {d: store.load_holdings_as_of(d, portfolio_id) for d in store.all_snapshot_dates()}
    return climate_metrics.compute_waci_trend(store, holdings_by_date, securities, companies, group_by=group_by, portfolio_filter=portfolio_id)


@router.get("/financed-emissions")
def financed_emissions(
    as_of: str | None = None,
    portfolio_id: list[str] | None = Query(default=None),
    store: PortfolioStore = Depends(get_portfolio_store),
) -> dict:
    securities, _companies = _directories(store)
    resolved_as_of = _resolve_as_of(store, as_of)
    holdings = store.load_holdings_as_of(resolved_as_of, portfolio_id)
    return climate_metrics.compute_financed_emissions(
        store, holdings, securities, as_of=resolved_as_of, portfolio_filter=portfolio_id
    )


@router.get("/coverage/{field_id}")
def coverage(field_id: str, as_of: str | None = None, store: PortfolioStore = Depends(get_portfolio_store)) -> dict:
    securities, _companies = _directories(store)
    return climate_metrics.coverage_report(store, securities, field_id, as_of)


@router.get("/pivot/{field_id}", response_model=PivotResult)
def climate_pivot(
    field_id: str,
    row_dim: str = "sector",
    col_dim: str = "portfolio_id",
    as_of: str | None = None,
    portfolio_id: list[str] | None = Query(default=None),
    store: PortfolioStore = Depends(get_portfolio_store),
) -> PivotResult:
    """A climate field broken out across two dimensions at once, e.g.
    weighted-average carbon intensity by sector x portfolio -- reuses the
    same pivot executor as /api/portfolio/pivot, just pre-set to
    weighted_avg_datapoint against a climate field."""
    spec = PivotSpec(
        name=f"{field_id} pivot",
        portfolio_filter=portfolio_id or [],
        row_dim=row_dim,
        col_dim=col_dim,
        metric="weighted_avg_datapoint",
        data_point_field_id=field_id,
        as_of=as_of,
    )
    securities, companies = _directories(store)
    try:
        return analytics.execute_pivot(spec, store, securities, companies)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
