from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import get_document_content_store, get_identifier_map, get_run_store, settings_dep
from arp.api.routers.universe_workbench import MAX_COMPANIES
from arp.argus.companies import add_companies, parse_rows, register, with_register_ids
from arp.argus.documents import FlowFile, decide, expected_year, flow_files, store_upload
from arp.argus.flows import ArgusFlow, FlowSettings, FlowStore, SchemaChoice, SkippedUpload, get_flow_store
from arp.argus.repeat import RepeatRow, repeat_rows
from arp.argus.rows import FlowRow, flow_rows
from arp.config import Settings
from arp.db.session import require_dsn, transaction
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import DocType
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError
from arp.universe_workbench.availability import availability
from arp.xbrl_pipeline.store import XbrlStore

router = APIRouter(prefix="/api/argus", tags=["argus"])
# A discovery run with no progress for this long is taken as dead (its worker was restarted), so it can be started again.
DISCOVERY_STALE_AFTER = timedelta(minutes=30)


class DiscoveryStatus(BaseModel):
    run_id: str
    status: str


class ArgusFlowView(ArgusFlow):
    rows: list[FlowRow] = []
    files: list[FlowFile] = []
    discovery: DiscoveryStatus | None = None
    repeat_rows: list[RepeatRow] = []


class FlowList(BaseModel):
    flows: list[ArgusFlow]


class FlowPatch(BaseModel):
    identity_run_id: str | None = None
    reporting_year: int | None = Field(default=None, ge=1990, le=2100)
    source: Literal["upload", "import", "filings", "filings_web"] | None = None
    step: int | None = Field(default=None, ge=1, le=5)
    schema_choice: SchemaChoice | None = None
    settings: FlowSettings | None = None
    repeat: dict[str, Literal["skip", "run"]] | None = None


class FileDecision(BaseModel):
    keys: list[str] = []
    state: Literal["kept", "removed"] | None = None
    all_that_pass: bool = False
    all: bool = False


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
        discovery = None
        if flow.discovery_run_id and (m := self.run_store.load_manifest(flow.discovery_run_id)):
            discovery = DiscoveryStatus(run_id=m.run_id, status=str(m.status.value if hasattr(m.status, "value") else m.status))
        files = self.files(flow)
        repeats = []
        if flow.schema_choice:
            xbrl = XbrlStore(self.settings.xbrl_dir)
            avail = availability(flow.companies, run_store=self.run_store, content_store=self.content_store, xbrl_store=xbrl,
                                 documents_dir=self.settings.documents_dir)
            last = {cid: a.extraction.last_run_id for cid, a in avail.items() if a.extraction.last_run_id}
            repeats = repeat_rows(flow, files, last, run_store=self.run_store, principal=self.principal)
        return ArgusFlowView(**flow.model_dump(), rows=rows, files=files, discovery=discovery, repeat_rows=repeats)

    def files(self, flow: ArgusFlow) -> list[FlowFile]:
        return flow_files(flow, documents_dir=self.settings.documents_dir, content_store=self.content_store,
                          checks_dir=self.settings.runs_dir / "_flows" / "_checks",
                          discovery_state_dir=self.settings.discovery_state_dir)


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
    if req.repeat:
        flow = store.get(flow_id)
        if flow and set(req.repeat) - {c.company_id for c in flow.companies}:
            raise HTTPException(400, "That company is not in this extraction.")

    def apply(f: ArgusFlow) -> None:
        for k, v in changes.items():
            if k == "step":
                if v is not None:
                    f.step = max(f.step, v)  # step is the furthest reached
            elif k in ("schema_choice", "settings"):
                setattr(f, k, getattr(req, k) if v is not None else (FlowSettings() if k == "settings" else None))
            elif k == "repeat":
                f.repeat = v or {}
            else:
                setattr(f, k, v)

    flow = store.update(flow_id, apply)
    if flow and "reporting_year" in changes:  # a file kept for the old year may fail for the new one
        failing = {x.key for x in view.files(flow) if not x.passes}

        def unkeep(f: ArgusFlow) -> None:
            f.decisions = {k: v for k, v in f.decisions.items() if not (v == "kept" and k in failing)}

        flow = store.update(flow_id, unkeep)
    return view(flow)


@router.post("/flows/{flow_id}/documents/find", dependencies=[Depends(require_role("analyst"))])
async def find_documents(
    flow_id: str, store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store), principal: Principal = Depends(current_user), view: Viewer = Depends(),
) -> ArgusFlowView:
    """One discovery run for the flow's companies: filings only, or filings plus the companies' websites."""
    flow = store.get(flow_id)
    if flow is None:
        raise HTTPException(404, "Extraction not found")
    if flow.source not in ("filings", "filings_web"):
        raise HTTPException(400, "Choose Official filings or Filings + company websites first.")
    if not flow.companies:
        raise HTTPException(400, "Add companies in step 1 first.")
    m = run_store.load_manifest(flow.discovery_run_id) if flow.discovery_run_id else None
    if m and m.status in ("pending", "running") and datetime.now(UTC) - datetime.fromisoformat(m.updated_at) < DISCOVERY_STALE_AFTER:
        raise HTTPException(409, "Documents are still being searched for.")
    with transaction(require_dsn(settings)) as session:
        companies = [with_register_ids(session, c) for c in flow.companies]
    run_id = create_discovery_run(companies, None, "argus", run_store)
    JobManager(run_store).set_started_by(run_id, principal.user_id, principal.name)
    asyncio.create_task(execute_discovery_run(run_id, companies, settings=settings, run_store=run_store,
                                              web=flow.source == "filings_web", expected_year=expected_year(flow)))
    return view(store.update(flow_id, lambda f: setattr(f, "discovery_run_id", run_id)))


@router.post("/flows/{flow_id}/documents/upload", dependencies=[Depends(require_role("analyst"))])
async def upload_flow_document(
    flow_id: str, file: UploadFile, company_id: str = Form(...), doc_type: DocType = Form(...),
    store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep), view: Viewer = Depends(),
) -> ArgusFlowView:
    flow = store.get(flow_id)
    if flow is None:
        raise HTTPException(404, "Extraction not found")
    if company_id not in {c.company_id for c in flow.companies}:
        raise HTTPException(400, "That company is not in this extraction.")
    if (file.filename or "").startswith("."):  # the file list skips dot files, so the upload would vanish
        raise HTTPException(400, "File names cannot start with a dot.")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")
    try:
        _, duplicate_of = store_upload(settings.documents_dir, company_id, doc_type.value, file.filename or "", data)
    except UnsafeIdentifierError as exc:
        raise HTTPException(400, str(exc)) from exc

    def apply(f: ArgusFlow) -> None:
        f.source = f.source or "upload"
        skipped = SkippedUpload(company_id=company_id, filename=file.filename or "", duplicate_of=duplicate_of or "")
        if duplicate_of and all((x.company_id, x.filename) != (company_id, skipped.filename) for x in f.skipped_uploads):  # one row per key
            f.skipped_uploads.append(skipped)

    return view(store.update(flow_id, apply))


@router.post("/flows/{flow_id}/files", dependencies=[Depends(require_role("analyst"))])
def decide_files(
    flow_id: str, req: FileDecision, store: FlowStore = Depends(get_flow_store), view: Viewer = Depends(),
) -> ArgusFlowView:
    """Keep or remove files in this flow only; the files themselves stay on the company."""
    flow = store.get(flow_id)
    if flow is None:
        raise HTTPException(404, "Extraction not found")
    if not req.all_that_pass and req.state is None:
        raise HTTPException(400, "Say kept or removed.")
    files = view.files(flow)
    return view(store.update(flow_id, lambda f: decide(f, files, keys=req.keys, state=req.state,
                                                        all_that_pass=req.all_that_pass, every=req.all)))


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
