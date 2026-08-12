from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from arp.api.deps import get_run_store
from arp.orchestration.job_manager import JobManager
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(run_type: str | None = None, run_store: RunStore = Depends(get_run_store)) -> dict:
    return {"runs": [m.model_dump(mode="json") for m in run_store.list_runs(run_type)]}


@router.get("/{run_id}")
def get_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """Requests a cooperative stop: no further items start once the
    currently in-flight ones finish and checkpoint. Works for any run type
    (theme, extraction) since both run through the same batch runner."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    if manifest.status not in ("running", "pending"):
        raise HTTPException(400, f"Run {run_id} is already {manifest.status.value} -- nothing to cancel.")
    updated = JobManager(run_store).request_cancel(run_id)
    return updated.model_dump(mode="json")


@router.get("/{run_id}/errors")
def get_run_errors(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return {"errors": run_store.read_jsonl(run_store.errors_path(run_id))}


@router.get("/{run_id}/export.csv")
def export_run_csv(run_id: str, run_store: RunStore = Depends(get_run_store)) -> StreamingResponse:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    rows = run_store.read_jsonl(run_store.results_path(run_id))

    buf = io.StringIO()
    if manifest.run_type == "theme":
        writer = csv.writer(buf)
        writer.writerow(["company_id", "ticker", "name", "activity_name", "verdict", "exposure_estimate", "confidence", "flagged_for_review", "rationale"])
        for row in rows:
            for m in row.get("company_matches", []):
                writer.writerow(
                    [m["company_id"], m.get("ticker"), m["name"], m["activity_name"], m["verdict"],
                     m["exposure_estimate"], m["confidence"], m["flagged_for_review"], m["adjudicator_rationale"]]
                )
    elif manifest.run_type == "extraction":
        writer = csv.writer(buf)
        writer.writerow(["company_id", "ticker", "name", "field_name", "value", "confidence", "grounded", "needs_review", "verifier_notes"])
        for record in rows:
            for f in record.get("fields", []):
                writer.writerow(
                    [record["company_id"], record.get("ticker"), record["name"], f["field_name"], f["value"],
                     f["confidence"], f["grounded"], record["needs_review"], f.get("verifier_notes")]
                )
    else:  # discovery
        writer = csv.writer(buf)
        writer.writerow(["company_id", "name", "homepage_used", "doc_type", "url", "local_path"])
        for row in rows:
            for d in row.get("documents_found", []):
                writer.writerow([row["company_id"], row["name"], row.get("homepage_used"), d["doc_type"], d["url"], d.get("local_path")])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={run_id}.csv"},
    )
