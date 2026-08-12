from __future__ import annotations

import json

from fastapi import APIRouter, Depends, UploadFile

from arp.api.deps import settings_dep
from arp.config import Settings
from arp.research.taxonomy_sources.etf_holdings import load_universe_from_holdings
from arp.universe import load_company_universe

router = APIRouter(prefix="/api/universe", tags=["universe"])


@router.post("/upload")
async def upload_universe(file: UploadFile, settings: Settings = Depends(settings_dep)) -> dict:
    """Uploads a company universe CSV/JSON (company_id, name, ticker,
    website, cik, country, sector) and returns its server-side path plus a
    parse summary, so subsequent run-creation calls can reference a large
    universe (up to 4000+ companies) by path instead of inlining it in
    every request body.
    """
    dest_dir = settings.runs_dir / "_universes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    contents = await file.read()
    dest_path.write_bytes(contents)
    companies = load_company_universe(dest_path)
    return {"path": str(dest_path), "company_count": len(companies), "sample": [c.model_dump() for c in companies[:5]]}


@router.post("/raw-upload")
async def raw_upload(file: UploadFile, settings: Settings = Depends(settings_dep)) -> dict:
    """Saves an arbitrary file (a fund/index holdings export, in whatever
    format the provider gives it) and returns its server-side path,
    without attempting to parse it as anything -- the path can then be
    passed as `holdings_path` to a taxonomy creation request
    (derivation_method=etf_index_holdings) or to POST /api/etf-overlap.
    """
    dest_dir = settings.runs_dir / "_universes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"_raw_{file.filename}"
    dest_path.write_bytes(await file.read())
    return {"path": str(dest_path)}


@router.post("/from-holdings")
async def universe_from_holdings(file: UploadFile, settings: Settings = Depends(settings_dep)) -> dict:
    """Builds a company universe from a fund/index holdings export --
    the Universe Builder's path for constructing a universe from a
    sector or index fund's constituents (found via the same fund-discovery
    search the ETF-holdings taxonomy method uses) instead of a hand-
    written list. Reuses the holdings CSV parser's ticker/name/sector
    column-variant handling, then persists the normalized result as a
    proper universe file so it's immediately usable as `universe_path`
    anywhere else in the app.
    """
    dest_dir = settings.runs_dir / "_universes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    raw_path = dest_dir / f"_raw_holdings_{file.filename}"
    raw_path.write_bytes(await file.read())

    companies = load_universe_from_holdings(raw_path)
    saved_path = dest_dir / f"{raw_path.stem}_universe.json"
    saved_path.write_text(json.dumps([c.model_dump(mode="json") for c in companies], indent=2))

    return {
        "path": str(saved_path),
        "company_count": len(companies),
        "sample": [c.model_dump() for c in companies[:5]],
    }
