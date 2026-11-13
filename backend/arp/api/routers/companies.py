from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from arp.api.deps import get_portfolio_store, settings_dep
from arp.config import Settings
from arp.db import company_view as view
from arp.db.companies import normalise_identifier
from arp.db.models import CompanyIdentifier, FieldKind
from arp.db.session import transaction
from arp.portfolio.climate.esg_intake import FIELD_IDS as CLIMATE_FIELD_IDS
from arp.schemas.portfolio import DataPointObservation
from arp.showcase.schema import FIELD_IDS as SIMULATED_FIELD_IDS

router = APIRouter(prefix="/api", tags=["companies"])


def _resolve(s, ref: str):
    cid = view.resolve_ref(s, ref)
    if cid is None:
        raise HTTPException(404, "Company not found")
    return cid


@router.get("/companies")
def search_companies(q: str = Query("", max_length=200), limit: int = Query(20, ge=1, le=100)) -> list[view.CompanySearchHit]:
    with transaction() as s:
        return view.search(s, q, limit)


@router.get("/companies/{ref}")
def get_company(ref: str, store=Depends(get_portfolio_store), settings: Settings = Depends(settings_dep)) -> view.CompanySummary:
    with transaction() as s:
        return view.summary(s, _resolve(s, ref), today=date.today(), store=store, documents_dir=settings.documents_dir)


@router.get("/companies/{ref}/simulated-esg")
def get_simulated_esg(ref: str, store=Depends(get_portfolio_store)) -> list[DataPointObservation]:
    """The company's latest SIMULATED value per climate and `simulated_esg` field (`arp showcase load`), in schema
    order; empty when it has none. Only source `simulated`: every value here is invented and must be shown so."""
    with transaction() as s:
        cid = _resolve(s, ref)
        universe = set(s.scalars(select(CompanyIdentifier.value).where(
            CompanyIdentifier.company_id == cid, CompanyIdentifier.scheme == "UNIVERSE", CompanyIdentifier.valid_to.is_(None))))
    if not universe:
        return []
    # UNIVERSE aliases are stored upper-cased; the portfolio store keeps the id as written
    # shortcut: reads every portfolio-store company per call; index by normalised id if the store grows past ~10k
    company_id = next((c.company_id for c in store.list_companies() if normalise_identifier("UNIVERSE", c.company_id) in universe), None)
    out = []
    for field_id in [*CLIMATE_FIELD_IDS, *SIMULATED_FIELD_IDS] if company_id else []:
        simulated = [o for o in store.load_observations(company_id, field_id) if o.source == "simulated"]
        if simulated:
            out.append(sorted(simulated, key=lambda o: o.observed_at)[-1])  # a tie: the later row is the correction, as resolve_field_value
    return out


@router.get("/companies/{ref}/facts")
def get_company_facts(
    ref: str, as_of: datetime | None = None, kind: FieldKind | None = None, field_id: str | None = None,
    period_end: date | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
) -> list[view.CompanyFactRow]:
    if as_of is not None and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    with transaction() as s:
        return view.facts(s, _resolve(s, ref), as_of=as_of, kind=kind, field_id=field_id, period_end=period_end,
                          limit=limit, offset=offset)


@router.get("/facts/{fact_id}/trail")
def get_fact_trail(fact_id: int) -> view.FactTrail:
    with transaction() as s:
        try:
            return view.trail(s, fact_id)
        except LookupError:
            raise HTTPException(404, "Fact not found") from None
