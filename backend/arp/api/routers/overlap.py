from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import settings_dep
from arp.api.saved_universe import saved_universe_file
from arp.config import Settings
from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights
from arp.research.taxonomy_sources.overlap import compute_holdings_overlap
from arp.schemas.taxonomy_sources import HoldingsOverlapResult

router = APIRouter(prefix="/api/etf-overlap", tags=["overlap"])


class OverlapRequest(BaseModel):
    funds: dict[str, str] = Field(description="fund display name -> server-side holdings CSV path (see POST /api/universe/raw-upload).")


@router.post("", response_model=HoldingsOverlapResult)
def compute_overlap(req: OverlapRequest, settings: Settings = Depends(settings_dep)) -> HoldingsOverlapResult:
    if len(req.funds) < 2:
        raise HTTPException(400, "Provide at least two funds to compare.")
    paths = {name: saved_universe_file(path_str, settings) for name, path_str in req.funds.items()}
    if None in paths.values():
        raise HTTPException(400, "Holdings file must be an uploaded file.")
    fund_holdings = {name: load_holdings_with_weights(path) for name, path in paths.items()}
    return compute_holdings_overlap(fund_holdings)
