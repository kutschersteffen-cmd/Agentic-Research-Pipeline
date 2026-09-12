from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from arp.api.deps import get_llm_client, get_reporting_store
from arp.reporting.datasets import parse_tabular_upload
from arp.reporting.service import ReportingService
from arp.reporting.style_profile import ingest_template
from arp.schemas.reporting import ReportPlan, ReportRequest
from arp.storage.reporting_store import ReportingStore

router = APIRouter(prefix="/api/reports", tags=["reporting"])

_CONTENT_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def _get_manifest_or_404(store: ReportingStore, report_id: str):
    manifest = store.load_manifest(report_id)
    if manifest is None:
        raise HTTPException(404, "Report not found")
    return manifest


# ---- Template ingestion -----------------------------------------------------


@router.post("/templates")
async def upload_template(file: UploadFile, store: ReportingStore = Depends(get_reporting_store)) -> dict:
    """Ingests a .pptx template so the Content Planner and DeckBuilder can
    match its style (layouts, theme colors/fonts) for every subsequent
    presentation generated with this template_id."""
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(400, "Template must be a .pptx file")
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pptx") as tmp:
        tmp.write(content)
        tmp.flush()
        style = ingest_template(store, Path(tmp.name), file.filename)
    return style.model_dump(mode="json")


@router.get("/templates")
def list_templates(store: ReportingStore = Depends(get_reporting_store)) -> dict:
    return {"templates": [t.model_dump(mode="json") for t in store.list_template_styles()]}


@router.get("/templates/{template_id}")
def get_template(template_id: str, store: ReportingStore = Depends(get_reporting_store)) -> dict:
    style = store.load_template_style(template_id)
    if style is None:
        raise HTTPException(404, "Template not found")
    return style.model_dump(mode="json")


# ---- Dataset upload helper ---------------------------------------------------


@router.post("/datasets/upload")
async def upload_dataset(file: UploadFile, name: str | None = None) -> dict:
    """Parses an uploaded CSV/XLSX into a QuantitativeDataset the caller
    then includes in a ReportRequest.datasets -- kept separate from
    POST /api/reports so the frontend can preview/adjust column kinds
    before committing to a generation run."""
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    content = await file.read()
    try:
        dataset = parse_tabular_upload(file.filename, content, name=name)
    except Exception as exc:  # noqa: BLE001 -- surfaced as a 400 with the parser's own message, not swallowed
        raise HTTPException(400, f"Could not parse {file.filename}: {exc}") from exc
    return dataset.model_dump(mode="json")


# ---- Report generation -------------------------------------------------------


@router.post("")
async def create_report(
    request: ReportRequest,
    render: bool = True,
    store: ReportingStore = Depends(get_reporting_store),
) -> dict:
    """Drafts a ReportPlan from the request (the one LLM call in this
    pipeline). By default also renders it immediately (`render=true`); pass
    `render=false` to stop after planning so the plan can be reviewed/
    edited (GET/PUT .../plan) before a separate POST .../render call."""
    llm = get_llm_client()
    service = ReportingService(store)
    manifest = await service.create_and_plan(request, llm)
    if render:
        manifest = service.render_from_plan(manifest.report_id)
    return manifest.model_dump(mode="json")


@router.get("")
def list_reports(store: ReportingStore = Depends(get_reporting_store)) -> dict:
    return {"reports": [m.model_dump(mode="json") for m in store.list_reports()]}


@router.get("/{report_id}")
def get_report(report_id: str, store: ReportingStore = Depends(get_reporting_store)) -> dict:
    return _get_manifest_or_404(store, report_id).model_dump(mode="json")


@router.get("/{report_id}/plan")
def get_plan(report_id: str, store: ReportingStore = Depends(get_reporting_store)) -> dict:
    _get_manifest_or_404(store, report_id)
    plan = store.load_plan(report_id)
    if plan is None:
        raise HTTPException(404, "No plan drafted yet for this report")
    return plan.model_dump(mode="json")


@router.put("/{report_id}/plan")
def update_plan(report_id: str, plan: ReportPlan, store: ReportingStore = Depends(get_reporting_store)) -> dict:
    """Lets a human edit the Content Planner's draft (reorder/add/remove
    sections, swap a chart_type, tweak narrative text) before the final
    render -- the key lever for "large flexibility" without re-prompting
    the model: the next POST .../render renders exactly this plan."""
    _get_manifest_or_404(store, report_id)
    store.save_plan(report_id, plan)
    return plan.model_dump(mode="json")


@router.post("/{report_id}/render")
def render_report(report_id: str, store: ReportingStore = Depends(get_reporting_store)) -> dict:
    service = ReportingService(store)
    try:
        manifest = service.render_from_plan(report_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return manifest.model_dump(mode="json")


@router.get("/{report_id}/download")
def download_report(report_id: str, store: ReportingStore = Depends(get_reporting_store)) -> FileResponse:
    manifest = _get_manifest_or_404(store, report_id)
    if manifest.output_filename is None:
        raise HTTPException(409, "Report has not been rendered yet")
    path = store.output_path(report_id, manifest.output_filename)
    if not path.exists():
        raise HTTPException(404, "Output file missing on disk")
    ext = manifest.output_filename.rsplit(".", 1)[-1]
    return FileResponse(
        path,
        filename=f"{manifest.title or report_id}.{ext}",
        media_type=_CONTENT_TYPES.get(ext, "application/octet-stream"),
    )
