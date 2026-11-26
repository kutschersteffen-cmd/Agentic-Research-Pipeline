from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from arp.api.auth import require_role
from arp.api.deps import get_registry, get_run_store, settings_dep
from arp.config import Settings
from arp.db.company_view import known_companies
from arp.db.session import transaction
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import NotResumable, RunBusy, check_resumable, get_job_launcher, resume_run, run_lease
from arp.orchestration.review_queue import effective_decisions
from arp.research.pipeline import load_theme_run_matches, rank_theme_matches
from arp.research.results_diff import diff_theme_results
from arp.schemas.common import JobStatus
from arp.schemas.review import results_field_key
from arp.schemas.thematic import CompanyMatch
from arp.schemas.transition_barrier import BarrierRefreshFinding
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


@router.get("/known-companies")
def get_known_companies(run_type: str) -> dict:
    """Powers the Data Library's "By company" picker -- only meaningful for
    run types whose result rows are keyed by company_id (extraction,
    financials); registered here (not on those routers) so it's not
    duplicated per run type, and here because /api/runs is already the
    cross-run-type home (list_runs, export, etc)."""
    with transaction() as s:
        return {"companies": known_companies(s, run_type)}


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


@router.post("/{run_id}/resume", dependencies=[Depends(require_role("analyst"))])
async def resume_run_endpoint(
    run_id: str,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
) -> dict:
    """Continues a killed, failed or cancelled run of any batch run type in
    the background (see arp.orchestration.jobs.resume_run)."""
    if run_store.load_manifest(run_id) is None:
        raise HTTPException(404, "Run not found")
    try:
        with run_lease(run_store, run_id):  # busy now -> 409 here, not a log line later
            pass
    except RunBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        check_resumable(run_store, run_id)
    except NotResumable as exc:
        raise HTTPException(400, str(exc)) from exc
    # The launcher holds the lease for the job, so the job takes none itself.
    get_job_launcher().launch(
        run_id,
        lambda: resume_run(run_id, settings=settings, run_store=run_store, registry=registry, lease=False),
        run_store=run_store,
    )
    return {"run_id": run_id, "status": "resumed"}


@router.get("/{run_id}/errors")
def get_run_errors(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return {"errors": [{k: v for k, v in row.items() if k != "traceback"} for row in run_store.read_errors(run_id)]}


class CompanyError(BaseModel):
    key: str
    error: str
    traceback: str | None


class RunFailure(BaseModel):
    run_id: str
    status: JobStatus
    error: str | None
    traceback: str | None
    company_errors: list[CompanyError]


@router.get("/{run_id}/failure", response_model=RunFailure, dependencies=[Depends(require_role("analyst"))])
def get_run_failure(run_id: str, run_store: RunStore = Depends(get_run_store)) -> RunFailure:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    # Review rows are not failures; a dict keeps the first-seen position of a key and the last row's value.
    latest = {}
    for row in run_store.read_errors(run_id):
        # Derived rows (invalid_value, unregistered_citation, identity_conflict) carry no key.
        if "key" in row and not row.get("review"):
            latest[row["key"]] = row
    traceback = None
    for event in run_store.read_events(run_id):
        if event.get("type") == "run_failed":
            traceback = event.get("traceback")
    return RunFailure(
        run_id=run_id,
        status=manifest.status,
        error=manifest.error,
        traceback=traceback,
        company_errors=[
            CompanyError(key=r["key"], error=r["error"], traceback=r.get("traceback")) for r in latest.values()
        ],
    )


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


def _reviewed_value(record: dict, f: dict, decided: dict[str, dict], queued: dict[str, dict], decided_keys: set[str]) -> tuple[object, object, str]:
    """A field's value and canonical value as an export may carry them, and its review status. A value is held back
    while a person still has to decide on it: it was routed to review or hold, has a review item in the run's queue
    (a conflict with an accepted fact, say) or has a decision row. It leaves the app once a person approved it (as
    corrected, when it was corrected); a kept conflict exports the accepted value. Anything else is exported as it is."""
    key = results_field_key(record, f)
    if f.get("route") not in ("review", "hold") and key not in queued and key not in decided_keys:
        return f["value"], f.get("canonical_value"), ""
    decision = decided.get(key)
    kind = decision["decision"] if decision else "awaiting review"
    if kind == "approve":
        return f["value"], f.get("canonical_value"), kind
    if kind in ("correct", "edit"):
        corrected = decision.get("corrected_value") or decision.get("edited_value") or {}
        return corrected.get("value"), None, kind  # the canonical value belonged to the value that was replaced
    row = queued.get(key)
    if kind == "reject" and row and row.get("kind") == "conflict" and "accepted" in row:
        return row["accepted"].get("value"), None, kind
    return None, None, kind


_TNFD_CSV_HEADER = [
    "company_id", "ticker", "name", "as_of", "framework_version", "item_type", "pillar", "recommendation_id", "category",
    "metric_kind", "sector_name", "sector_guidance_status", "sector_guidance_version", "metric_no", "is_core_sector_metric",
    "metric_name", "leap_stage", "disclosed", "summary", "consideration", "materiality_basis", "disclosure_scope",
    "location_specificity", "cross_framework_links", "time_horizons", "iplc_engagement_described", "value", "unit",
    "baseline_year", "confidence", "grounded", "verifier_notes", "review_flags", "overall_confidence", "needs_review",
    "review_status",
]
# What an item found, as opposed to which item it is: held back while a person still has to decide on the record.
_TNFD_HELD_BACK = _TNFD_CSV_HEADER[_TNFD_CSV_HEADER.index("disclosed"):_TNFD_CSV_HEADER.index("verifier_notes") + 1]


def _tnfd_horizons(horizons: dict | None) -> list[tuple[str, str]]:
    """Run results sit in Postgres JSONB, which does not keep a dict's key order: short, medium, long first, then the rest."""
    horizons = horizons or {}
    named = [k for k in ("short", "medium", "long") if k in horizons]
    return [(k, horizons[k]) for k in named + [k for k in horizons if k not in named]]


def _tnfd_csv_rows(records: list[dict], decided: dict[str, dict], queued: set[str], decided_keys: set[str]) -> list[list]:
    """One row per disclosure, core metric, sector metric, LEAP consideration and general-requirements block, per
    company. A record that waits for review (or was rejected, corrected or escalated) keeps its identity columns and
    loses what its items found; `review_status` says why."""
    from arp.schemas.tnfd import PILLAR_BY_RECOMMENDATION, RecommendationId

    def joined(values: list | None) -> str:
        return "; ".join(str(v) for v in values or [])

    out: list[list] = []
    for rec in records:
        key = rec["company_id"]
        start = len(out)
        status, held = "", False
        if rec.get("needs_review") or key in queued or key in decided_keys:
            decision = decided.get(key)
            status = decision["decision"] if decision else "awaiting review"
            held = status != "approve"
        record_cols = {
            "company_id": key, "ticker": rec.get("ticker"), "name": rec["name"], "as_of": rec["as_of"],
            "framework_version": rec["framework_version"], "overall_confidence": rec["overall_confidence"],
            "needs_review": rec["needs_review"], "review_status": status,
        }

        def add(item_type: str, *, _cols=record_cols, _held=held, **cells) -> None:
            row = {**_cols, "item_type": item_type, **cells}
            if _held:
                row.update({c: None for c in _TNFD_HELD_BACK})
            out.append([row.get(c) for c in _TNFD_CSV_HEADER])

        for d in rec.get("disclosures", []):
            rid = RecommendationId(d["recommendation_id"])
            add("disclosure", pillar=PILLAR_BY_RECOMMENDATION[rid].value, recommendation_id=rid.value,
                leap_stage=d.get("leap_stage_reference"), disclosed=d["disclosed"], summary=d.get("summary"),
                materiality_basis=d.get("materiality_basis"), disclosure_scope=d.get("disclosure_scope"),
                confidence=d["confidence"], grounded=d["grounded"], verifier_notes=d.get("verifier_notes"),
                review_flags=joined(d.get("review_flags")))
        for m in rec.get("core_global_metrics", []):
            add("core_metric", category=m["category"], metric_kind=m["metric_kind"], metric_name=m["metric_name"],
                value=m.get("value"), unit=m.get("unit"), baseline_year=m.get("baseline_year"), confidence=m["confidence"],
                grounded=m["grounded"], verifier_notes=m.get("verifier_notes"), review_flags=joined(m.get("review_flags")))
        for m in rec.get("sector_metrics", []):
            add("sector_metric", sector_name=m["sector_name"], sector_guidance_status=m["sector_guidance_status"],
                sector_guidance_version=m["sector_guidance_version"], metric_no=m.get("metric_no"),
                is_core_sector_metric=m["is_core_sector_metric"], metric_name=m["metric_name"], value=m.get("value"),
                unit=m.get("unit"), baseline_year=m.get("baseline_year"), confidence=m["confidence"],
                grounded=m["grounded"], verifier_notes=m.get("verifier_notes"), review_flags=joined(m.get("review_flags")))
        for c in rec.get("sector_leap_considerations", []):
            add("leap_consideration", sector_name=c["sector_name"], leap_stage=c["leap_stage"],
                consideration=c["consideration"], review_flags=joined(c.get("review_flags")))
        if g := rec.get("general_requirements"):
            add("general_requirements", materiality_basis=g["materiality_approach"], disclosure_scope=g["disclosure_scope"],
                location_specificity=g["location_specificity"], cross_framework_links=joined(g.get("cross_framework_links")),
                time_horizons="; ".join(f"{k}={v}" for k, v in _tnfd_horizons(g.get("time_horizons_defined"))),
                iplc_engagement_described=g["iplc_engagement_described"])
        if len(out) == start:
            add("none")
    return out


@router.get("/{run_id}/export.csv")
def export_run_csv(run_id: str, run_store: RunStore = Depends(get_run_store)) -> StreamingResponse:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    rows = run_store.read_results(run_id)

    buf = io.StringIO()
    if manifest.run_type == "theme":
        writer = csv.writer(buf)
        writer.writerow(_THEME_CSV_HEADER)
        for m in rank_theme_matches(load_theme_run_matches(run_store, run_id) or []):
            writer.writerow(_theme_csv_row(m))
    elif manifest.run_type == "extraction":
        writer = csv.writer(buf)
        writer.writerow(["company_id", "ticker", "name", "field_name", "value", "confidence", "grounded", "needs_review", "verifier_notes",
             "value_state", "unit", "canonical_value", "canonical_unit", "period_start", "period_end", "basis", "review_status"])
        decided = effective_decisions(run_store, run_id)
        queued = {r["item_key"]: r for r in run_store.read_review_queue(run_id) if r.get("item_key")}
        decided_keys = {d["item_key"] for d in run_store.read_decisions(run_id)}
        for record in rows:
            for f in record.get("fields", []):
                value, canonical, status = _reviewed_value(record, f, decided, queued, decided_keys)
                writer.writerow(
                    [record["company_id"], record.get("ticker"), record["name"], f["field_name"], value,
                     f["confidence"], f["grounded"], record["needs_review"], f.get("verifier_notes"),
                     f.get("value_state"), f.get("unit"), canonical, f.get("canonical_unit"),
                     f.get("period_start"), f.get("period_end"), f.get("basis"), status]
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
    elif manifest.run_type == "transition_barrier_refresh":
        writer = csv.writer(buf)
        writer.writerow(
            ["code", "region", "source_key", "outcome", "current_rating", "proposed_rating",
             "needs_review", "detail", "source_quote", "checked_at"]
        )
        for record in rows:
            # A proposed_rating is advisory only -- it is queued for review, never applied.
            writer.writerow(
                [record["code"], record["region"], record["source_key"], record["outcome"],
                 record["current_rating"], record.get("proposed_rating"),
                 BarrierRefreshFinding.model_validate(record).needs_review,
                 record.get("detail"), record.get("source_quote"), record.get("checked_at")]
            )
    elif manifest.run_type == "tnfd":
        writer = csv.writer(buf)
        writer.writerow(_TNFD_CSV_HEADER)
        queued = {r["item_key"] for r in run_store.read_review_queue(run_id) if r.get("item_key")}
        decided_keys = {d["item_key"] for d in run_store.read_decisions(run_id)}
        writer.writerows(_tnfd_csv_rows(rows, effective_decisions(run_store, run_id), queued, decided_keys))
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
