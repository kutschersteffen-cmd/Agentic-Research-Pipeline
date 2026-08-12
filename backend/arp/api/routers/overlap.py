from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights
from arp.research.taxonomy_sources.overlap import compute_holdings_overlap
from arp.schemas.taxonomy_sources import HoldingsOverlapResult

router = APIRouter(prefix="/api/etf-overlap", tags=["overlap"])


class OverlapRequest(BaseModel):
    funds: dict[str, str] = Field(description="fund display name -> server-side holdings CSV path (see POST /api/universe/raw-upload).")


@router.post("", response_model=HoldingsOverlapResult)
def compute_overlap(req: OverlapRequest) -> HoldingsOverlapResult:
    if len(req.funds) < 2:
        raise HTTPException(400, "Provide at least two funds to compare.")
    fund_holdings = {}
    for name, path_str in req.funds.items():
        path = Path(path_str)
        if not path.exists():
            raise HTTPException(404, f"Holdings file not found: {path_str}")
        fund_holdings[name] = load_holdings_with_weights(path)
    return compute_holdings_overlap(fund_holdings)
