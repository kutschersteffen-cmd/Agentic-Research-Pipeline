from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_document_content_store, get_identifier_map, get_run_store, settings_dep
from arp.config import Settings
from arp.schemas.common import CompanyRef
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe
from arp.universe_workbench.availability import availability
from arp.universe_workbench.mapping import MasterIndex, map_company
from arp.universe_workbench.routing import route_company
from arp.xbrl_pipeline.store import XbrlStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/universe", tags=["universe"])

MAX_COMPANIES = 10_000


class WorkbenchRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    availability: bool = True  # false skips the store scans (routing preview)


def _xbrl_store(settings: Settings = Depends(settings_dep)) -> XbrlStore:
    return XbrlStore(settings.xbrl_dir)


@router.post("/workbench")
def workbench(
    req: WorkbenchRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    xbrl_store: XbrlStore = Depends(_xbrl_store),
    idmap: IdentifierMapStore = Depends(get_identifier_map),
    content_store: DocumentContentStore = Depends(get_document_content_store),
) -> dict:
    companies = req.companies
    if not companies and req.universe_path:
        try:
            path = Path(req.universe_path).resolve()
        except (OSError, ValueError) as exc:  # ValueError: NUL byte in the path
            raise HTTPException(400, "Universe file must be a saved universe.") from exc
        if not path.is_relative_to((settings.runs_dir / "_universes").resolve()):
            raise HTTPException(400, "Universe file must be a saved universe.")
        try:
            companies = load_company_universe(path)
        except Exception as exc:
            logger.warning("universe file unreadable: %s", exc)
            raise HTTPException(400, "Could not read the universe file.") from exc
        if not companies:
            raise HTTPException(400, "Universe file is empty.")
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")
    if len(companies) > MAX_COMPANIES:
        raise HTTPException(400, f"At most {MAX_COMPANIES} companies per request.")

    index = MasterIndex.build(idmap)
    avail = availability(
        companies, run_store=run_store, content_store=content_store,
        xbrl_store=xbrl_store, documents_dir=settings.documents_dir,
    ) if req.availability else {}
    routes = {"sec": 0, "esef": 0, "no_source": 0, "unrouted": 0}
    mapping = {"mapped": 0, "ambiguous": 0, "unmapped": 0, "no_identifier": 0}
    rows = []
    for c in companies:
        m, r = map_company(c, index), route_company(c, index)
        routes[r.market if r.status == "routed" else r.status] += 1
        mapping[m.status] += 1
        rows.append({
            "company": r.company.model_dump(mode="json"),
            "mapping": asdict(m),
            "route": {"market": r.market, "status": r.status, "basis": r.basis, "detail": r.detail},
            "availability": avail[c.company_id].model_dump(mode="json") if avail else None,
        })
    return {"rows": rows, "counts": {"routes": routes, "mapping": mapping}}
