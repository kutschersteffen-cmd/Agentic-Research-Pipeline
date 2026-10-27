"""The walkthrough of one stored row: its trace, picked and resolved (argus-walkthrough spec, "The endpoint")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from arp.extraction.pipeline import _moved_from
from arp.ingestion.local_files import parser_version
from arp.presets import transition_plan_actions as plan_preset
from arp.review.context import _text, run_field_names
from arp.storage.safe_path import safe_id
from arp.walkthrough.trace import read_trace

SECTIONS = {
    "financials": {"segments": "Business segments", "capex": "CapEx", "rnd": "R&D"},
    "tnfd": {
        "disclosures": "Disclosures", "core_global_metrics": "Core global metrics", "sector_metrics": "Sector metrics",
        "general_requirements": "General requirements", "sector_leap_considerations": "Sector LEAP considerations",
    },
}


def _record(run_store, run_id: str, company_id: str) -> dict | None:
    return next((r for r in run_store.read_results(run_id) if r.get("company_id") == company_id), None)


def _has_folder(run_store, run_id: str) -> bool:
    """run_dir() creates a missing folder; retention deletes an expired run's folder and must not see it come back."""
    return (run_store.runs_dir / safe_id(run_id, label="run_id")).is_dir()


def _trace(run_store, run_id: str, company_id: str) -> dict:
    return (read_trace(run_store, run_id, company_id) if _has_folder(run_store, run_id) else None) or {}


def _period(row: dict) -> str:
    return row.get("period_end") or "unspecified"


def _origin(run_store, run_id: str, company_id: str, record: dict, row: dict) -> tuple[str, dict, dict]:
    """Follow `reused_from_run` run to run while the earlier run holds the same field, period and basis."""
    seen = {run_id}
    while (prev := row.get("reused_from_run")) and prev not in seen:
        seen.add(prev)
        if run_store.load_manifest(prev) is None:
            break
        prev_record = _record(run_store, prev, company_id) or {}
        prev_row = next((f for f in prev_record.get("fields", []) if f.get("field_id") == row.get("field_id")
                         and _period(f) == _period(row) and f.get("basis") == row.get("basis")), None)
        if prev_row is None:
            break
        run_id, record, row = prev, prev_record, prev_row
    return run_id, record, row


def _not_recorded_reason(run_store, settings, run_id: str, company_id: str) -> str:
    if any(e.get("type") == "trace_write_failed" and e.get("company_id") == company_id
           for e in (run_store.read_events(run_id) if _has_folder(run_store, run_id) else [])):
        return "write_failed"
    created = datetime.fromisoformat(run_store.load_manifest(run_id).created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if datetime.now(UTC) - created > timedelta(days=settings.retention_runs_days):
        return "expired"
    return "before_traces"


def _document(content_store, doc_id: str) -> dict:
    """A document the record does not list (Financials/TNFD records list none), from the document directory."""
    ref = content_store.resolve_document(doc_id) if content_store is not None else None
    return {"title": ref.title, "content_key": ref.content_key, "parser_version": parser_version()} if ref else {}


def _passages(entry: dict, record: dict, content_store) -> list[dict]:
    docs = {d.get("doc_id"): d for d in record.get("documents", [])}
    out = []
    for i, p in enumerate(entry.get("passages", [])):
        doc = docs.get(p["doc_id"]) or _document(content_store, p["doc_id"])
        t = _text(content_store, doc)
        out.append({"rank": i + 1, **p, "doc_title": doc.get("title"),
                    "text": t.full_text[p["char_start"]:p["char_end"]] if t else None})
    return out


def build_walkthrough(run_store, content_store, settings, *, run_id: str, company_id: str, item: str,
                      period_end: str | None, basis: str | None) -> dict:
    """Raises LookupError (404) or ValueError (422); the 404 checks come before the 422 checks, then the row."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise LookupError("run not found")
    record = _record(run_store, run_id, company_id)
    if record is None:
        raise LookupError("company not in this run")
    sections = SECTIONS.get(manifest.run_type)
    trace_run_id = run_id

    if sections is not None:
        if item not in sections:
            raise LookupError("no such section for this run type")
        section = record.get(item)
        rows = section if isinstance(section, list) else [section] if section else []
        item_name = sections[item]
        entry = _trace(run_store, run_id, company_id).get("record")
        trace_record = record
    else:
        fields = record.get("fields", [])
        # retention deletes schema.json with the run's other files; the stored rows still name their fields
        names = ((run_field_names(run_store, run_id) if _has_folder(run_store, run_id) else {})
                 or {f["field_id"]: f.get("field_name") for f in fields})
        if item not in names:
            raise LookupError("field not in this run's schema")
        rows = [f for f in fields if f.get("field_id") == item]
        for f in rows:
            f.setdefault("corrections", [])  # as the results endpoint returns them
        trace_data = _trace(run_store, run_id, company_id)
        is_plan = record.get("schema_id") == plan_preset.SCHEMA_ID and item not in plan_preset.OPERATES_FIELDS
        if not rows and item not in trace_data.get("fields", {}) and not (is_plan and trace_data.get("plans")):
            raise LookupError("no row or trace for this field")
        if period_end is None:
            raise ValueError("period_end is required for a field")
        if is_plan and basis is None:
            raise ValueError("basis is required for a transition-plan list field")
        if is_plan:
            rows = [f for f in rows if f.get("basis") == basis]
        row = next((f for f in rows if _period(f) == period_end), None)
        if row is None:
            raise LookupError("no row for this period")
        item_name = names[item]
        trace_run_id, trace_record, origin = _origin(run_store, run_id, company_id, record, row)
        if trace_run_id != run_id:
            trace_data = _trace(run_store, trace_run_id, company_id)
        if is_plan:
            doc_id = next((c.get("doc_id") for c in origin.get("citations", [])), None)
            plan = trace_data.get("plans", {}).get(doc_id)
            entry = plan and {"skipped": None, "verifier": None, "adjudicator": None, "vision": None, **plan}
        else:
            entry = trace_data.get("fields", {}).get(_moved_from(origin) or item)

    recorded = entry is not None
    entry = entry or {}
    return {
        "run_id": run_id, "run_type": manifest.run_type, "company_id": company_id, "company_name": record.get("name"),
        "item": item, "item_name": item_name,
        "recorded": recorded,
        "trace_run_id": trace_run_id,
        "rows": rows,
        "passages": _passages(entry, trace_record, content_store),
        **{k: entry.get(k) for k in ("extractor", "verifier", "adjudicator", "vision", "skipped")},
        "not_recorded_reason": None if recorded else _not_recorded_reason(run_store, settings, trace_run_id, company_id),
    }
