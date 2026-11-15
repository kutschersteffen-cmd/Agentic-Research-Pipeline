"""`GET /api/stewardship/cockpit` (spec `stewardship-cockpit`): read-only, computed on every request."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException

from arp.api.deps import get_run_store, settings_dep
from arp.config import Settings
from arp.db.session import require_dsn
from arp.schemas.cockpit import CockpitResponse
from arp.stewardship import cockpit, voting_feed
from arp.stewardship.tiers import TierStore
from arp.storage.portfolio_store import portfolio_directories
from arp.storage.portfolio_store_factory import build_portfolio_store
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/stewardship", tags=["stewardship"])


@router.get("/cockpit", response_model=CockpitResponse)
def get_cockpit(
    portfolio_id: str | None = None,
    as_of: date | None = None,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
) -> dict:
    as_of = as_of or datetime.now(UTC).date()
    store = build_portfolio_store(settings)
    portfolios = sorted(store.list_portfolios(), key=lambda p: (p.name, p.portfolio_id))
    held = None
    if portfolio_id is None:
        scope = {"portfolio_id": None, "label": f"All portfolios ({len(portfolios)})"}
    else:
        portfolio = next((p for p in portfolios if p.portfolio_id == portfolio_id), None)
        if portfolio is None:
            raise HTTPException(404, f"Unknown portfolio {portfolio_id}")
        scope = {"portfolio_id": portfolio_id, "label": portfolio.name}
        securities, _ = portfolio_directories(store)
        held = {
            sec.company_id
            for h in store.load_holdings_as_of(as_of.isoformat(), [portfolio_id])
            if (sec := securities.get(h.security_id)) and sec.company_id
        }
    body = cockpit.build(require_dsn(settings), as_of, voting_feed.items(run_store), TierStore(settings.stewardship_streams_dir).latest(), held)
    return {**body, "scope": scope, "portfolios": [{"portfolio_id": p.portfolio_id, "name": p.name} for p in portfolios]}
