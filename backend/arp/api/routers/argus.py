from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import get_document_content_store, get_identifier_map, get_run_store, settings_dep
from arp.api.routers.universe_workbench import MAX_COMPANIES
from arp.argus.companies import add_companies, parse_rows, register
from arp.argus.documents import FlowFileView, discovered_files, file_views, file_year, save_upload
from arp.argus.flows import ArgusFlow, FlowFile, FlowStore, get_flow_store
from arp.argus.rows import FlowRow, flow_rows
from arp.config import Settings
from arp.db.session import require_dsn, transaction
from arp.discovery.doc_check import check_document
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import DocType, JobStatus
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError
from arp.xbrl_pipeline.store import XbrlStore

router = APIRouter(prefix="/api/argus", tags=["argus"])


class DiscoveryState(BaseModel):
    run_id: str
    status: str
    done: int
    total: int


class ArgusFlowView(ArgusFlow):
    rows: list[FlowRow] = []
    files: list[FlowFileView] = []
    discovery: DiscoveryState | None = None


class FindFiles(BaseModel):
    include_web: bool


class FlowList(BaseModel):
    flows: list[ArgusFlow]


class FlowPatch(BaseModel):
    identity_run_id: str | None = None
    step: int | None = Field(None, ge=1, le=5)
    reporting_year: int | None = Field(None, ge=1990, le=2100)
    doc_source: Literal["upload", "import", "filings", "web"] | None = None
    decisions: dict[str, Literal["kept", "removed"]] | None = None


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

    def files(self, flow: ArgusFlow) -> list[FlowFileView]:
        rows = self.run_store.read_results(flow.discovery_run_id) if flow.discovery_run_id else []
        return file_views(flow, discovered_files(rows, self.settings.documents_dir))

    def discovery(self, flow: ArgusFlow) -> DiscoveryState | None:
        m = self.run_store.load_manifest(flow.discovery_run_id) if flow.discovery_run_id else None
        return m and DiscoveryState(run_id=m.run_id, status=m.status, done=m.completed_count + m.failed_count, total=m.company_count)

    def __call__(self, flow: ArgusFlow | None) -> ArgusFlowView:
        if flow is None:
            raise HTTPException(404, "Extraction not found")
        with transaction(require_dsn(self.settings)) as session:
            rows = flow_rows(flow, session=session, run_store=self.run_store, content_store=self.content_store,
                             xbrl_store=XbrlStore(self.settings.xbrl_dir), idmap=self.idmap, principal=self.principal,
                             documents_dir=self.settings.documents_dir)
        return ArgusFlowView(**flow.model_dump(), rows=rows, files=self.files(flow), discovery=self.discovery(flow))


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

    def apply(f: ArgusFlow) -> None:
        if (decisions := changes.pop("decisions", None)) is not None:
            keys = {x.key for x in view.files(f) if not x.duplicate_of}
            if not set(decisions) <= keys:
                raise HTTPException(400, "Unknown file")
            f.decisions.update(decisions)
        if (step := changes.pop("step", None)) is not None:
            f.step = max(f.step, step)
        for k, v in changes.items():
            setattr(f, k, v)

    return view(store.update(flow_id, apply))


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


@router.post("/flows/{flow_id}/documents/upload", dependencies=[Depends(require_role("analyst"))])
async def upload_flow_document(
    flow_id: str, file: UploadFile, company_id: str = Form(...), doc_type: DocType = Form(...),
    store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep), view: Viewer = Depends(),
) -> ArgusFlowView:
    flow = store.get(flow_id)
    if flow is None:
        raise HTTPException(404, "Extraction not found")
    company = next((c for c in flow.companies if c.company_id == company_id), None)
    if company is None:
        raise HTTPException(400, "Not in this extraction")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")
    try:
        path, duplicate_of = save_upload(settings.documents_dir, company_id, doc_type, file.filename or "", data)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc
    check = await asyncio.to_thread(check_document, path, company)
    key = path.relative_to(settings.documents_dir).as_posix()
    stored = FlowFile(key=key, company_id=company_id, doc_type=path.parent.name, file_name=path.name, source="upload",
                      on_disk=True, year=file_year(path.name, check.reporting_year), company_match=check.company_match)

    def add(f: ArgusFlow) -> None:
        f.doc_source = "upload"
        if not any(u.key == key for u in f.uploads):
            f.uploads.append(stored)
        elif duplicate_of:  # the same content again in this flow: a row that says so, never a second file
            f.uploads.append(stored.model_copy(update={"key": f"{key}#{uuid4().hex[:8]}", "duplicate_of": duplicate_of}))

    return view(store.update(flow_id, add))


@router.post("/flows/{flow_id}/documents/find")
async def find_flow_files(
    flow_id: str, req: FindFiles, store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(require_role("analyst")), view: Viewer = Depends(),
) -> ArgusFlowView:
    """Starts one discovery run for the flow's matched companies: official filings only, or filings plus company websites."""
    flow = store.get(flow_id)
    if flow is None:
        raise HTTPException(404, "Extraction not found")
    if (state := view.discovery(flow)) and state.status in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(409, "Already looking for files")
    companies = [c for c in flow.companies if c.entity_id]
    if not companies:
        raise HTTPException(400, "No matched companies")
    run_id = create_discovery_run(companies, None, "manual", run_store)
    JobManager(run_store).set_started_by(run_id, principal.user_id, principal.name)
    asyncio.create_task(execute_discovery_run(run_id, companies, settings=settings, run_store=run_store, include_web=req.include_web))

    def link(f: ArgusFlow) -> None:
        f.discovery_run_id, f.doc_source = run_id, "web" if req.include_web else "filings"

    return view(store.update(flow_id, link))
