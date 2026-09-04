from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from arp.api.deps import get_run_store
from arp.orchestration.job_manager import JobManager
from arp.research.pipeline import load_theme_run_matches, rank_theme_matches
from arp.research.results_diff import diff_theme_results
from arp.schemas.thematic import CompanyMatch
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/runs", tags=["runs"])

_THEME_CSV_HEADER = [
    "company_id", "ticker", "name", "activity_id", "activity_name", "verdict", "exposure_estimate", "confidence",
    "company_role", "revenue_pct", "revenue_source", "indirect_upstream", "indirect_downstream",
    "rd_intensity_pct", "news_mentions_score", "arbitration_composite_score", "arbitration_disagree",
    "arbitration_mid_band", "flagged_for_review", "rationale", "citation_count", "citations_json",
]


def _theme_csv_row(m: CompanyMatch) -> list:
    revenue = m.revenue_exposure.revenue if m.revenue_exposure else None
    indirect = m.indirect_exposure
    rd = m.rd_exposure
    arb = m.arbitration
    return [
        m.company_id, m.ticker, m.name, m.activity_id, m.activity_name, m.verdict.value, m.exposure_estimate.value,
        m.confidence,
        m.company_role.value if m.company_role else None,
        revenue.value_pct if revenue else None,
        revenue.source if revenue else None,
        indirect.upstream_exposure if indirect else None,
        indirect.downstream_exposure if indirect else None,
        rd.rd_intensity.value_pct if rd else None,
        rd.news_mentions.value_pct if rd else None,
        arb.composite_score if arb else None,
        arb.methods_disagree if arb else None,
        arb.mid_band if arb else None,
        m.flagged_for_review,
        m.adjudicator_rationale,
        len(m.citations),
        json.dumps([c.model_dump(mode="json") for c in m.citations]) if m.citations else "",
    ]


def _load_ranked_theme_matches(run_id: str, run_store: RunStore) -> list[CompanyMatch]:
    matches = load_theme_run_matches(run_store, run_id)
    if matches is None:
        raise HTTPException(404, "Run not found or not a theme run.")
    return rank_theme_matches(matches)


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


@router.get("/{run_id}/results")
def get_theme_run_results(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """The ranked-list output (Step 5): every CompanyMatch for a theme run,
    sorted by arbitration.composite_score descending. 404s for a run_id
    that doesn't exist or isn't a theme run -- other run types don't
    produce CompanyMatch rows to rank."""
    matches = _load_ranked_theme_matches(run_id, run_store)
    return {"run_id": run_id, "matches": [m.model_dump(mode="json") for m in matches]}


@router.get("/{run_id_a}/diff/{run_id_b}")
def diff_theme_runs(run_id_a: str, run_id_b: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    """Deterministic diff between two theme runs' results (added/dropped/
    verdict-changed/confidence-changed company x activity pairs), keyed by
    '{company_id}:{activity_id}' -- see arp/research/results_diff.py. Not
    limited to two runs of literally the same theme_id; any two theme runs'
    results can be compared, same as the runs are otherwise unrelated in
    this file-based storage model."""
    matches_a = load_theme_run_matches(run_store, run_id_a)
    if matches_a is None:
        raise HTTPException(404, f"Run not found or not a theme run: {run_id_a}")
    matches_b = load_theme_run_matches(run_store, run_id_b)
    if matches_b is None:
        raise HTTPException(404, f"Run not found or not a theme run: {run_id_b}")
    diff = diff_theme_results(run_id_a, run_id_b, matches_a, matches_b)
    return diff.model_dump(mode="json")


@router.get("/{run_id}/export.csv")
def export_run_csv(run_id: str, run_store: RunStore = Depends(get_run_store)) -> StreamingResponse:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    rows = run_store.read_jsonl(run_store.results_path(run_id))

    buf = io.StringIO()
    if manifest.run_type == "theme":
        writer = csv.writer(buf)
        writer.writerow(_THEME_CSV_HEADER)
        for m in rank_theme_matches(load_theme_run_matches(run_store, run_id) or []):
            writer.writerow(_theme_csv_row(m))
    elif manifest.run_type == "extraction":
        writer = csv.writer(buf)
        writer.writerow(["company_id", "ticker", "name", "field_name", "value", "confidence", "grounded", "needs_review", "verifier_notes"])
        for record in rows:
            for f in record.get("fields", []):
                writer.writerow(
                    [record["company_id"], record.get("ticker"), record["name"], f["field_name"], f["value"],
                     f["confidence"], f["grounded"], record["needs_review"], f.get("verifier_notes")]
                )
    elif manifest.run_type == "financials":
        writer = csv.writer(buf)
        writer.writerow(
            ["company_id", "ticker", "name", "currency", "fiscal_period",
             "segment_name", "segment_description", "segment_revenue", "segment_income", "segment_assets", "segment_grounded",
             "capex_total", "capex_description", "capex_grounded",
             "rnd_total", "rnd_description", "rnd_grounded",
             "overall_confidence", "needs_review"]
        )
        for record in rows:
            segments = record.get("segments") or [None]
            for s in segments:
                writer.writerow(
                    [record["company_id"], record.get("ticker"), record["name"], record.get("currency"), record.get("fiscal_period"),
                     s["name"] if s else None, s.get("description") if s else None,
                     s["revenue"]["value"] if s else None, s["income"]["value"] if s else None, s["assets"]["value"] if s else None,
                     s["grounded"] if s else None,
                     record["capex"]["total"]["value"], record["capex"].get("description"), record["capex"]["grounded"],
                     record["rnd"]["total"]["value"], record["rnd"].get("description"), record["rnd"]["grounded"],
                     record["overall_confidence"], record["needs_review"]]
                )
    elif manifest.run_type == "transition_plan":
        writer = csv.writer(buf)
        writer.writerow(
            ["company_id", "ticker", "name", "indicator_number", "identifier", "category", "walk_or_talk",
             "question", "verdict", "answer", "grounded", "needs_review", "disclosed_count", "overall_confidence"]
        )
        for record in rows:
            for ind in record.get("indicators", []):
                writer.writerow(
                    [record["company_id"], record.get("ticker"), record["name"], ind["number"], ind["identifier"],
                     ind["category"], ind["walk_or_talk"], ind["question"], ind["verdict"], ind["answer"],
                     ind["grounded"], ind["needs_review"], record["disclosed_count"], record["overall_confidence"]]
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


@router.get("/{run_id}/export.xlsx")
def export_theme_run_xlsx(run_id: str, run_store: RunStore = Depends(get_run_store)) -> StreamingResponse:
    """Theme runs only (for now -- the other run types' CSV branches above
    aren't retrofitted here). Two sheets: "Matches" (the same ranked,
    full-field row set as export.csv, minus the JSON-encoded citations
    cell) and "Citations" (one row per citation, keyed back to its match
    by company_id/activity_id) -- Excel affords a clean multi-sheet
    citations table, avoiding the JSON-in-a-cell workaround the flat CSV
    format needs.
    """
    from openpyxl import Workbook

    matches = _load_ranked_theme_matches(run_id, run_store)

    wb = Workbook()
    matches_sheet = wb.active
    matches_sheet.title = "Matches"
    matches_sheet.append(_THEME_CSV_HEADER[:-1])  # every column except citations_json
    for m in matches:
        matches_sheet.append(_theme_csv_row(m)[:-1])

    citations_sheet = wb.create_sheet("Citations")
    citations_sheet.append(["company_id", "activity_id", "doc_id", "doc_type", "quote", "grounded", "page", "sheet"])
    for m in matches:
        for c in m.citations:
            citations_sheet.append([m.company_id, m.activity_id, c.doc_id, c.doc_type.value, c.quote, c.grounded, c.page, c.sheet])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={run_id}.xlsx"},
    )
