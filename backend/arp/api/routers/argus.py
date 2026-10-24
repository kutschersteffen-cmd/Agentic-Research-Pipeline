from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import get_document_content_store, get_identifier_map, get_run_store, settings_dep
from arp.api.routers.universe_workbench import MAX_COMPANIES
from arp.argus.companies import add_companies, parse_rows, register
from arp.argus.flows import ArgusFlow, FlowStore, get_flow_store
from arp.argus.rows import FlowRow, flow_rows
from arp.config import Settings
from arp.db.session import require_dsn, transaction
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.store import XbrlStore

router = APIRouter(prefix="/api/argus", tags=["argus"])


class ArgusFlowView(ArgusFlow):
    rows: list[FlowRow] = []


class FlowList(BaseModel):
    flows: list[ArgusFlow]


class FlowPatch(BaseModel):
    identity_run_id: str | None = None


class CompanyInput(BaseModel):
    name: str
    ticker: str | None = None
    isin: str | None = None
    lei: str | None = None
    cik: str | None = None


class AddCompanies(BaseModel):
    universe_path: str | None = None
    company: CompanyInput | None = None


class Viewer:
    """Turns a flow into its view: the flow plus step 1's rows, read fresh from the stores."""

    def __init__(
        self, settings: Settings = Depends(settings_dep), run_store: RunStore = Depends(get_run_store),
        content_store: DocumentContentStore = Depends(get_document_content_store),
        idmap: IdentifierMapStore = Depends(get_identifier_map), principal: Principal = Depends(current_user),
    ) -> None:
        self.settings, self.run_store, self.content_store, self.idmap, self.principal = settings, run_store, content_store, idmap, principal

    def __call__(self, flow: ArgusFlow | None) -> ArgusFlowView:
        if flow is None:
            raise HTTPException(404, "Extraction not found")
        with transaction(require_dsn(self.settings)) as session:
            rows = flow_rows(flow, session=session, run_store=self.run_store, content_store=self.content_store,
                             xbrl_store=XbrlStore(self.settings.xbrl_dir), idmap=self.idmap, principal=self.principal,
                             documents_dir=self.settings.documents_dir)
        return ArgusFlowView(**flow.model_dump(), rows=rows)


@router.post("/flows")
def create_flow(
    principal: Principal = Depends(require_role("analyst")), store: FlowStore = Depends(get_flow_store), view: Viewer = Depends(),
) -> ArgusFlowView:
    return view(store.create(principal))


@router.get("/flows", dependencies=[Depends(current_user)])
def list_flows(store: FlowStore = Depends(get_flow_store)) -> FlowList:
    return FlowList(flows=store.list())


@router.get("/flows/{flow_id}", dependencies=[Depends(current_user)])
def get_flow(flow_id: str, store: FlowStore = Depends(get_flow_store), view: Viewer = Depends()) -> ArgusFlowView:
    return view(store.get(flow_id))


@router.patch("/flows/{flow_id}", dependencies=[Depends(require_role("analyst"))])
def patch_flow(flow_id: str, req: FlowPatch, store: FlowStore = Depends(get_flow_store), view: Viewer = Depends()) -> ArgusFlowView:
    changes = req.model_dump(exclude_unset=True)
    return view(store.update(flow_id, lambda f: [setattr(f, k, v) for k, v in changes.items()]))


def _add(flow_id: str, rows: list[dict], store: FlowStore, settings: Settings, view: Viewer) -> ArgusFlowView:
    if store.get(flow_id) is None:
        raise HTTPException(404, "Extraction not found")
    if len(rows) > MAX_COMPANIES:
        raise HTTPException(400, f"At most {MAX_COMPANIES} companies per list.")
    with transaction(require_dsn(settings)) as session:
        companies = [c for c in (register(session, r) for r in rows) if c is not None]
    return view(store.update(flow_id, lambda f: add_companies(f, companies)))


@router.post("/flows/{flow_id}/companies/upload", dependencies=[Depends(require_role("analyst"))])
async def upload_companies(
    flow_id: str, file: UploadFile, store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep),
    view: Viewer = Depends(),
) -> ArgusFlowView:
    try:
        rows = parse_rows(file.filename or "", await file.read())
    except (ValueError, UnicodeDecodeError) as exc:  # JSONDecodeError is a ValueError
        raise HTTPException(400, f"Could not read the list: {exc}") from exc
    return _add(flow_id, rows, store, settings, view)


@router.post("/flows/{flow_id}/companies", dependencies=[Depends(require_role("analyst"))])
def add_flow_companies(
    flow_id: str, req: AddCompanies, store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep),
    view: Viewer = Depends(),
) -> ArgusFlowView:
    rows: list[dict] = []
    if req.company:
        rows.append(req.company.model_dump(exclude_none=True))
    if req.universe_path:
        try:
            path = Path(req.universe_path).resolve()
        except (OSError, ValueError) as exc:  # ValueError: NUL byte in the path
            raise HTTPException(400, "Universe file must be a saved universe.") from exc
        if not path.is_relative_to((settings.runs_dir / "_universes").resolve()) or not path.is_file():
            raise HTTPException(400, "Universe file must be a saved universe.")
        try:
            rows += parse_rows(path.name, path.read_bytes())
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(400, f"Could not read the universe file: {exc}") from exc
    if not rows:
        raise HTTPException(400, "Provide a company or a saved universe.")
    return _add(flow_id, rows, store, settings, view)
