"""Re-grounding of stored extraction citations after a parser upgrade (E51).

A citation's offsets index the text one parser version produced. When the
parser changes, the original is re-parsed with the current parser and the
stored quote grounded again; a moved or lost span goes to review. Results
files are never rewritten: the outcome lives in runs/<id>/regrounds.jsonl."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from arp.ingestion.local_files import parse_file_to_text_with_pages, parser_version
from arp.orchestration.review_queue import FINAL_STATES, append_decision, item_states, queue_for_review
from arp.publish.gate import blob_key, lineage_error, reground_match
from arp.schemas.common import Citation
from arp.schemas.review import DecisionReason, ReviewDecision, field_item_key, period_key
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

FLAGGED = ("offset_moved", "not_grounded")
LINEAGE = ("original_missing", "hash_mismatch")  # re-parsing cannot fix these: logged once, never retried
SETTLED = ("ok", *FLAGGED, *LINEAGE)  # only text_unavailable is retried on the next run
COSIGN_REQUIRED = {"edit"}  # extraction's legacy co-sign rule (review/items.py LEGACY_COSIGN)


@dataclass
class RegroundReport:
    checked: int = 0
    unchanged: int = 0
    moved: int = 0
    lost: int = 0
    queued: int = 0
    unavailable: int = 0


def _is_edgar(version: str) -> bool:
    # EDGAR filings are stamped "logic=N|trafilatura=..." (edgar._edgar_parser_version) and never re-parse here
    return "|trafilatura=" in version and "docling=" not in version


def _reopen(run_store: RunStore, run_id: str, key: str, old: str, new: str) -> None:
    """A decided or never-decided item goes back to review: a system first-step escalate starts a
    new round, so an auto-accepted value is no longer publishable nor bulk-acceptable."""
    with run_store.lock(run_id):
        state = item_states(run_store, run_id, cosign_required=COSIGN_REQUIRED).get(key)
        if state is None or state.state in FINAL_STATES:
            append_decision(run_store, run_id, ReviewDecision(
                item_key=key, step="first", decision="escalate", reason_code=DecisionReason.SPAN_MOVED,
                reviewer="system", user_id="system", role="system", snapshot_id="",
                comment=f"span_moved: parser {old}\u2192{new}",
            ))


def _span(c: Citation | None, version: str) -> dict:
    c = c if c is not None and c.grounded else None
    return {"char_start": c and c.char_start, "char_end": c and c.char_end, "page": c and c.page,
            "parser_version": version}


def _reparse(c: Citation, version: str, *, blob_store, content_store) -> None:
    """Stores the current parser's text of c's original under (content_key, version).
    Only local-file formats re-parse; an EDGAR filing (no filename) raises, so it
    reports text_unavailable."""
    ref = content_store.resolve_document(c.doc_id)
    name = (ref.local_path if ref is not None else None) or c.source_filename
    if not name:
        raise ValueError("no original filename")
    suffix = Path(name).suffix.lower()
    data = blob_store.get(blob_key(c, content_store))

    def parse():
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / f"original{suffix}"
            path.write_bytes(data)
            return parse_file_to_text_with_pages(path)

    content_store.get_or_compute(c.content_key, key_kind="file_bytes", parser_version=version,
                                 source_suffix=suffix, byte_size=len(data), compute=parse)


def _outcome(c: Citation, version: str, *, blob_store, content_store, fuzzy_threshold) -> tuple[str, Citation | None]:
    if err := lineage_error(c, blob_store, content_store=content_store):
        return err, None
    try:
        _reparse(c, version, blob_store=blob_store, content_store=content_store)
    except Exception:  # noqa: BLE001 - an original that cannot be re-parsed is reported, never fails the job
        return "text_unavailable", None
    return reground_match(c.model_copy(update={"parser_version": version}), blob_store=blob_store,
                          content_store=content_store, fuzzy_threshold=fuzzy_threshold)


def reground_runs(run_store: RunStore, *, settings, blob_store, content_store, run_ids=None) -> RegroundReport:
    version = parser_version()
    report = RegroundReport()
    ids = run_ids if run_ids is not None else [m.run_id for m in run_store.list_runs("extraction")]
    for run_id in ids:
        manifest = run_store.load_manifest(run_id)
        if manifest is not None and manifest.params.get("trial"):
            continue  # known-answer runs have text but no stored original, and never publish
        log = run_store.run_dir(run_id) / "regrounds.jsonl"
        # ponytail: no run lock while re-parsing (can take minutes); two concurrent re-grounds can duplicate rows
        done = [r for r in run_store.read_jsonl(log) if r["outcome"] in SETTLED]
        seen = {(r["item_key"], r["doc_id"], r["old"]["parser_version"], r["old"]["char_start"],
                 r["new"]["parser_version"]) for r in done}
        queued = {(r["item_key"], r["new"]["parser_version"]) for r in done if r["outcome"] in FLAGGED}
        for row in run_store.read_jsonl(run_store.results_path(run_id)):
            issuer = row.get("issuer_key", "")
            for f in row.get("fields", []):
                key = field_item_key(issuer, f["field_id"], period_key(f))
                for raw in f.get("citations", []):
                    c = Citation.model_validate(raw)
                    old = c.parser_version
                    if not c.grounded or not old or old == version or _is_edgar(old) or old.startswith("xbrl_companyfacts"):
                        continue
                    if (key, c.doc_id, old, c.char_start, version) in seen:
                        continue
                    outcome, g = _outcome(c, version, blob_store=blob_store, content_store=content_store,
                                          fuzzy_threshold=settings.grounding_fuzzy_threshold)
                    report.checked += 1
                    report.unchanged += outcome == "ok"
                    report.moved += outcome == "offset_moved"
                    report.lost += outcome == "not_grounded"
                    report.unavailable += outcome not in SETTLED
                    if outcome in LINEAGE:
                        logger.warning("Re-grounding %s/%s: %s; not retried", run_id, c.doc_id, outcome)
                    if outcome in FLAGGED and f.get("route") != "hold" and (key, version) not in queued:  # held: approver only
                        reasons = [*f.get("review_reasons", []), "span_moved"]
                        queue_for_review(run_store, run_id, key, {
                            "issuer_key": issuer, "issuer_scheme": row.get("issuer_scheme", ""),
                            "company_id": row.get("company_id"), "name": row.get("name"),
                            "schema_id": row.get("schema_id"), "run_id": run_id, "field_id": f["field_id"],
                            "period_end": f.get("period_end"), "field": f, "review_reasons": reasons,
                            "reason_codes": reasons, "route_reasons": f.get("route_reasons", []),
                        })
                        _reopen(run_store, run_id, key, old, version)
                        queued.add((key, version))
                        report.queued += 1
                    run_store.append_jsonl(log, {
                        "item_key": key, "doc_id": c.doc_id, "old": _span(c, old),
                        "new": _span(g, version), "outcome": outcome,
                    })
                    if outcome in SETTLED:
                        seen.add((key, c.doc_id, old, c.char_start, version))
    return report


def reground_if_parser_changed(
    run_store: RunStore, *, settings, blob_store=None, content_store=None
) -> RegroundReport | None:
    """Re-grounds every run unless publish_state_dir/parser_version.txt already
    holds the current parser version; records it once nothing was left unavailable."""
    path = Path(settings.publish_state_dir) / "parser_version.txt"
    version = parser_version()
    if path.exists() and path.read_text().strip() == version:
        return None
    if (blob_store is None or content_store is None) and run_store.list_runs("extraction"):
        from arp.ingestion.indexing_config import IndexingConfig
        from arp.retrieval.content_store_factory import content_store_for
        from arp.storage.document_blob_store import blob_store_for

        blob_store = blob_store or blob_store_for(IndexingConfig.from_settings(settings))
        content_store = content_store or content_store_for(settings)
    report = reground_runs(run_store, settings=settings, blob_store=blob_store, content_store=content_store)
    if not report.unavailable:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(version)
    return report
