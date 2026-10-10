from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException

from arp.api.deps import get_portfolio_store
from arp.db import company_view as view
from arp.db.models import FieldKind
from arp.db.session import transaction

router = APIRouter(prefix="/api", tags=["companies"])


def _resolve(s, ref: str):
    cid = view.resolve_ref(s, ref)
    if cid is None:
        raise HTTPException(404, "Company not found")
    return cid


@router.get("/companies")
def search_companies(q: str = "", limit: int = 20) -> list[view.CompanySearchHit]:
    with transaction() as s:
        return view.search(s, q, limit)


@router.get("/companies/{ref}")
def get_company(ref: str, store=Depends(get_portfolio_store)) -> view.CompanySummary:
    with transaction() as s:
        return view.summary(s, _resolve(s, ref), today=date.today(), store=store)


@router.get("/companies/{ref}/facts")
def get_company_facts(
    ref: str, as_of: datetime | None = None, kind: FieldKind | None = None, field_id: str | None = None,
    period_end: date | None = None, limit: int = 100, offset: int = 0,
) -> list[view.CompanyFactRow]:
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
