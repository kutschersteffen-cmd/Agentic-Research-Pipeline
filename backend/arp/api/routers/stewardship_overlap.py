"""Fund overlap (spec `stewardship-workbench-overlap`): fund pairs, the fund x company grid and the companies picked
in more than one scope. Read only; reads need `viewer` (the router-level `authorize`). Neither route builds the
worklist or the house universe: both read the latest holdings once (`fund_holdings`) and the selection log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from arp.api.deps import get_stream_store, settings_dep
from arp.api.routers.stewardship_worklist import _cycle
from arp.config import Settings
from arp.schemas.overlap import FundOverlap, OverlapMatrix
from arp.stewardship import overlap, worklist
from arp.stewardship.process import StreamStore
from arp.stewardship.universe import HouseUniverseSetting
from arp.storage.portfolio_store import portfolio_directories
from arp.storage.portfolio_store_factory import build_portfolio_store

router = APIRouter(prefix="/api/stewardship/overlap", tags=["stewardship"])


def _read(settings: Settings) -> tuple[str, object, dict, str | None]:
    """(universe source, portfolio store, `fund_holdings()` or {} with the sample universe, latest snapshot date)."""
    source = HouseUniverseSetting(settings.stewardship_streams_dir).get()["source"]
    store = build_portfolio_store(settings)
    if source != "portfolio":
        return source, store, {}, None
    dates = store.all_snapshot_dates()
    return source, store, worklist.fund_holdings(store), dates[-1] if dates else None


@router.get("", response_model=FundOverlap)
def get_overlap(
    cycle: str | None = None, settings: Settings = Depends(settings_dep), streams: StreamStore = Depends(get_stream_store)
) -> dict:
    """Every house fund, every fund pair's shared companies and shared weight, and the companies picked in two or
    more scopes in `cycle` (default: the current one)."""
    cycle = _cycle(cycle)
    _, store, funds, as_of = _read(settings)
    selections = worklist.SelectionLog(streams.root).all_rows(cycle)
    return {"as_of": as_of, "cycle": cycle, **overlap.overview(funds, selections, worklist.scope_labels(store))}


@router.get("/matrix", response_model=OverlapMatrix)
def get_overlap_matrix(
    basis: str = "top",
    n: int = 100,
    scope: str | None = None,
    cycle: str | None = None,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
) -> dict:
    """A fund x company grid of weights: the `n` companies with the largest house weight (`basis=top`), or every
    company picked in `scope` in `cycle` (`basis=selection`)."""
    cycle = _cycle(cycle)
    if basis not in ("top", "selection"):
        raise HTTPException(422, f"Unknown basis {basis}")
    if basis == "top" and not 1 <= n <= 200:
        raise HTTPException(422, "n must be 1 to 200")
    if basis == "selection" and not scope:
        raise HTTPException(422, "basis selection needs a scope")
    source, store, funds, as_of = _read(settings)
    picked = None
    if basis == "selection":
        try:
            worklist.resolve_scope(scope, {"source": source}, store)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        picked = {r["issuer_id"]: r["company"] for r in worklist.SelectionLog(streams.root).rows(cycle, scope)}
    names = {cid: c.name for cid, c in portfolio_directories(store)[1].items()}
    grid = overlap.matrix(funds, names, n if basis == "top" else None, picked)
    return {"as_of": as_of, "basis": basis, "scope": scope if basis == "selection" else None, "cycle": cycle, **grid}
