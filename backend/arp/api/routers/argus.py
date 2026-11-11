from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from arp.api.auth import Principal, current_user, require_role
from arp.api.deps import (
    get_decision_store,
    get_document_content_store,
    get_identifier_map,
    get_registry,
    get_run_store,
    get_xbrl_source,
    settings_dep,
)
from arp.api.routers import extraction
from arp.api.routers.universe_workbench import MAX_COMPANIES
from arp.argus.companies import add_companies, parse_rows, register, with_register_ids
from arp.argus.documents import FlowFile, decide, expected_year, flow_files, store_upload
from arp.argus.flows import ArgusFlow, FlowSettings, FlowStore, SchemaChoice, SkippedUpload, get_flow_store
from arp.argus.progress import CompanyProgress, FlowProgress, company_status, minutes_left
from arp.argus.repeat import RepeatRow, kept_content, repeat_rows
from arp.argus.rows import FlowRow, flow_rows
from arp.argus.start import StartError, start_request
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.db.session import require_dsn, transaction
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.ingestion.registry import (
    KEPT_NAMES,
    ONLY_DOCUMENTS,
    DocumentSourceRegistry,
    KeptDocuments,
    read_kept_names,
    read_only_documents,
)
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import NotResumable, RunBusy, check_resumable, get_job_launcher, resume_run, run_lease
from arp.orchestration.step_tally import step_counts
from arp.review.items import list_open_items
from arp.schemas.common import DocType, JobStatus
from arp.storage.decision_store import DecisionStore
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
        view = ArgusFlowView(**flow.model_dump(), rows=rows, files=files, discovery=discovery, repeat_rows=self.repeats(flow, files))
        run = self.run_store.load_manifest(flow.run_id) if flow.run_id else None
        if run and str(getattr(run.status, "value", run.status)) not in ("pending", "running"):
            view.step = 5  # the run is over: its results are the flow's furthest step
        return view

    def repeats(self, flow: ArgusFlow, files: list[FlowFile]) -> list[RepeatRow]:
        if not flow.schema_choice or flow.step < 3:  # not while step 2 polls a discovery run
            return []
        # shortcut: scans every run's results on each read of step 3; add a company -> latest run index if runs pile up
        avail = availability(flow.companies, run_store=self.run_store, content_store=self.content_store,
                             xbrl_store=XbrlStore(self.settings.xbrl_dir), documents_dir=self.settings.documents_dir)
        last = {cid: a.extraction.last_run_id for cid, a in avail.items() if a.extraction.last_run_id}
        return repeat_rows(flow, files, last, run_store=self.run_store, principal=self.principal)

    def files(self, flow: ArgusFlow) -> list[FlowFile]:
        return flow_files(flow, documents_dir=self.settings.documents_dir, content_store=self.content_store,
                          checks_dir=self.settings.runs_dir / "_flows" / "_checks",
                          discovery_state_dir=self.settings.discovery_state_dir)


@router.post("/flows")
def create_flow(
    principal: Principal = Depends(require_role("analyst")), store: FlowStore = Depends(get_flow_store), view: Viewer = Depends(),
) -> ArgusFlowView:
    return view(store.create(principal))


@router.delete("/flows/{flow_id}", status_code=204, dependencies=[Depends(require_role("analyst"))])
def delete_flow(flow_id: str, store: FlowStore = Depends(get_flow_store)) -> None:
    """Undo a hand-over that failed after creating its flow: only an unused draft can go."""
    deleted = store.delete_if_empty(flow_id)
    if deleted is None:
        raise HTTPException(404, "Extraction not found")
    if not deleted:
        raise HTTPException(409, "Only an empty draft can be deleted.")


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


@router.post("/flows/{flow_id}/start")
async def start_flow(
    flow_id: str, store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store), registry: DocumentSourceRegistry = Depends(get_registry),
    decision_store: DecisionStore = Depends(get_decision_store), xbrl_source=Depends(get_xbrl_source),
    principal: Principal = Depends(require_role("analyst")), view: Viewer = Depends(),
) -> ArgusFlowView:
    """Starts the flow's run through the same path as `/api/extraction/start`, reading only the kept files."""
    flow = store.get(flow_id)
    if flow is None:
        raise HTTPException(404, "Extraction not found")
    m = run_store.load_manifest(flow.run_id) if flow.run_id else None
    if m and m.status in ("pending", "running"):
        raise HTTPException(409, "This extraction is already running.")
    files = view.files(flow)
    schema = None
    if flow.schema_choice and flow.schema_choice.kind == "schema":
        registry_s = SchemaRegistry(settings.postgres_dsn)
        try:
            schema = registry_s.get(flow.schema_choice.schema_id, flow.schema_choice.version)
            newest = registry_s.get(flow.schema_choice.schema_id).version
        except KeyError:
            raise HTTPException(400, "That schema version does not exist.") from None
        if schema.version != newest:  # a run saves its schema: an older body would be stored as a new version
            raise HTTPException(400, f"Pick the newest version of {schema.name}.")
    try:
        body, only = start_request(flow, files, view.repeats(flow, files), schema)
    except StartError as exc:
        raise HTTPException(400, str(exc)) from exc

    def claim(f: ArgusFlow) -> None:  # under the flow's lock: a second Start meanwhile gets a 409
        if f.starting:
            raise HTTPException(409, "This extraction is already starting.")
        f.starting = True

    store.update(flow_id, claim)
    try:
        started = await extraction.start_extraction(
            extraction.StartRequest(**body), settings=settings, run_store=run_store, registry=KeptDocuments(registry, only, kept_names(files)),
            decision_store=decision_store, xbrl_source=xbrl_source, principal=principal)
    except BaseException:
        store.update(flow_id, lambda f: setattr(f, "starting", False))
        raise
    (run_store.run_dir(started["run_id"]) / ONLY_DOCUMENTS).write_text(json.dumps({k: sorted(v) for k, v in only.items()}))
    (run_store.run_dir(started["run_id"]) / KEPT_NAMES).write_text(json.dumps(kept_names(files)))

    def apply(f: ArgusFlow) -> None:
        f.run_id, f.step, f.starting = started["run_id"], max(f.step, 4), False

    return view(store.update(flow_id, apply))


@router.get("/flows/{flow_id}/progress", dependencies=[Depends(current_user)])
def flow_progress(
    flow_id: str, store: FlowStore = Depends(get_flow_store), run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
) -> FlowProgress:
    """Step 4: the flow's run as a whole and per company."""
    flow = store.get(flow_id)
    m = run_store.load_manifest(flow.run_id) if flow and flow.run_id else None
    if m is None:
        raise HTTPException(404, "This extraction has not started.")
    status = str(getattr(m.status, "value", m.status))
    active = status in ("pending", "running")
    error_rows = run_store.read_errors(m.run_id)
    errors = {r.get("key"): r for r in error_rows if r.get("key")}
    open_items = Counter(str(i.payload.get("company_id")) for i in list_open_items(run_store, principal, run_id=m.run_id))
    companies = []
    for row in extraction.run_companies(run_store, m.run_id, run_store.read_results(m.run_id), error_rows):
        cid = row["company_id"]
        steps = step_counts(run_store, m.run_id, cid)[0]["counts"] if active else {}  # the tally only matters while it runs
        raw = "waiting" if active and row["status"] == "failed" and cid in m.params.get("retrying", []) else row["status"]
        label, percent = company_status(raw, status, steps)
        error = errors.get(cid) if raw in ("failed", "review") else None  # a review stop says why too
        companies.append(CompanyProgress(
            company_id=cid, name=row["name"], status=label, percent=percent, needs_you=open_items.get(cid, 0),
            reason=error.get("error") if error else None,
            document_problem=bool(error and label == "Failed" and error.get("document_problem"))))
    done = m.completed_count + m.failed_count
    since = m.params.get("done_at_restart", 0)  # a Retry or resume: count from its start, not the run's
    started = datetime.fromisoformat(m.params.get("restarted_at") or m.created_at)
    left = minutes_left(started, datetime.now(UTC), done=done - since, total=m.company_count - since)
    return FlowProgress(run_id=m.run_id, started_at=m.created_at, done=done, total=m.company_count, minutes_left=left,
                        cost_usd=m.estimated_cost_usd, status=status, companies=companies)


@router.post("/flows/{flow_id}/companies/{company_id}/retry", dependencies=[Depends(require_role("analyst"))])
async def retry_company(
    flow_id: str, company_id: str, store: FlowStore = Depends(get_flow_store), settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store), registry: DocumentSourceRegistry = Depends(get_registry), view: Viewer = Depends(),
) -> FlowProgress:
    """Re-runs one failed company inside the flow's run, on the files kept for it now (a file replaced in step 2 is used).
    Async: the launcher starts the job on this event loop. Nothing changes until the job holds the run."""
    flow = store.get(flow_id)
    m = run_store.load_manifest(flow.run_id) if flow and flow.run_id else None
    if m is None:
        raise HTTPException(404, "This extraction has not started.")
    run_id = m.run_id
    if m.status in ("pending", "running"):
        raise HTTPException(409, "Retry once the other companies have finished.")
    statuses = {c["company_id"]: c["status"] for c in extraction.get_run_companies(run_id, run_store)["companies"]}
    if statuses.get(company_id) != "failed":
        raise HTTPException(400, "Only a failed company can be retried.")
    try:
        check_resumable(run_store, run_id)
    except NotResumable as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        with run_lease(run_store, run_id):  # another worker on it (a resume from Run History): 409 now, not a lost job
            pass
    except RunBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    files = view.files(flow)
    kept = kept_content(files).get(company_id, set())
    errors = [r for r in run_store.read_errors(run_id) if r.get("key") == company_id]

    with run_store.lock(run_id):  # a second Retry before the job starts sees `pending` and gets a 409
        current = run_store.load_manifest(run_id)
        if current.status in ("pending", "running"):
            raise HTTPException(409, "This company is already being retried.")
        previous, current.status = current.status, JobStatus.PENDING
        current.params = {**current.params, "retrying": [company_id]}  # step 4 shows it Waiting, not Failed, from now on
        run_store.save_manifest(current)

    async def job() -> None:  # runs under the run's lease (LocalJobLauncher)
        run_dir = run_store.run_dir(run_id)
        only = read_only_documents(run_dir) or {}
        only[company_id] = kept
        (run_dir / ONLY_DOCUMENTS).write_text(json.dumps({k: sorted(v) for k, v in only.items()}))
        (run_dir / KEPT_NAMES).write_text(json.dumps({**read_kept_names(run_dir), **kept_names(files)}))
        run_store.clear_errors(run_id, [company_id])
        try:
            await resume_run(run_id, settings=settings, run_store=run_store, registry=registry, lease=False, company_ids=[company_id])
        except Exception:
            # failed before the company ran again (model setup, a crash): put its error back, so it reads Failed, not Stopped
            if company_id not in run_store.done_keys(run_id, include_errors=True) and not any(
                    r.get("key") == company_id for r in run_store.read_errors(run_id)):
                for r in errors:
                    run_store.append_error(run_id, r)
            raise
        finally:
            with run_store.lock(run_id):  # the run is no longer retrying this company, however the job ended
                current = run_store.load_manifest(run_id)
                current.params = {k: v for k, v in current.params.items() if k != "retrying"}
                run_store.save_manifest(current)

    try:
        get_job_launcher().launch(run_id, job, run_store=run_store)
    except Exception:
        with run_store.lock(run_id):
            current = run_store.load_manifest(run_id)
            current.status = previous
            run_store.save_manifest(current)
        raise
    return flow_progress(flow_id, store=store, run_store=run_store, principal=view.principal)


def kept_names(files: list[FlowFile]) -> dict[str, str]:
    """Content key -> file name of the kept files: the run's error names a file it could not read."""
    return {f.content_key: f.filename for f in files if f.state == "kept" and f.content_key}


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
