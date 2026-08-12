from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile

from arp.api.deps import settings_dep
from arp.config import Settings
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
