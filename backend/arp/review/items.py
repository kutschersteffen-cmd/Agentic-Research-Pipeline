from __future__ import annotations

from typing import TYPE_CHECKING

from arp.extraction.pipeline import load_run_schema
from arp.orchestration.review_queue import FINAL_STATES, ItemState, blind_for, item_states, public_decision
from arp.schemas.common import RunManifest
from arp.schemas.review import ReviewItem, ReviewItemKind, held_item_key
from arp.storage.run_store import RunStore

if TYPE_CHECKING:
    from arp.api.auth import Principal

REVIEWABLE_RUN_TYPES = ("theme", "extraction", "financials", "identity", "transition_plan", "tnfd")  # never voting
LEGACY_COSIGN = {"extraction": {"edit"}}


def cosign_rule(run_type: str) -> set[str]:
    return LEGACY_COSIGN.get(run_type, set())


def _queue_kind(run_type: str, row: dict) -> ReviewItemKind:
    if run_type == "extraction":
        return ReviewItemKind.VALUE if "field" in row or "fields" in row else ReviewItemKind.OTHER  # else a PreStepFailed report
    if run_type == "identity":
        return ReviewItemKind.IDENTITY
    if run_type == "theme" and row.get("kind") == "sector_code":
        return ReviewItemKind.SECTOR_CODE
    return ReviewItemKind.OTHER


def run_items(run_store: RunStore, manifest: RunManifest, principal: Principal) -> list[ReviewItem]:
    """Every review item of one run, in any state."""
    run_id, run_type = manifest.run_id, manifest.run_type
    rows = [(q["item_key"], _queue_kind(run_type, q), q) for q in run_store.read_jsonl(run_store.review_queue_path(run_id))]
    if run_type == "extraction":
        for r in run_store.read_jsonl(run_store.results_path(run_id)):
            extra = {"company_id": r.get("company_id"), "name": r.get("name"), "issuer_key": r.get("issuer_key")}
            rows += [(held_item_key(r["company_id"], d["doc_id"]), ReviewItemKind.QUARANTINED_DOCUMENT, {**d, **extra})
                     for d in r.get("held_documents", [])]
        rows += [(c["candidate_id"], ReviewItemKind.RESTATEMENT_CANDIDATE, c)
                 for c in run_store.read_jsonl(run_store.restatements_path(run_id))]
    states = item_states(run_store, run_id, cosign_required=cosign_rule(run_type))
    schema = load_run_schema(run_store, run_id)
    risky = {f.field_id for f in schema.fields if f.high_risk} if schema else set()
    items = []
    for key, kind, payload in rows:
        s = states.get(key) or ItemState()
        if kind is ReviewItemKind.OTHER and s.rows:  # legacy kinds: any decision is final (today's rule)
            s = ItemState(state="final", effective=s.rows[-1], rows=s.rows)
        high_risk = kind in (ReviewItemKind.VALUE, ReviewItemKind.RESTATEMENT_CANDIDATE) and payload.get("field_id") in risky
        row = s.first if s.state == "first_done" else (s.effective or s.second)
        blind = row is None or blind_for(s, principal, high_risk=high_risk)
        items.append(ReviewItem(
            item_key=key, kind=kind, run_id=run_id, run_type=run_type, payload=payload, state=s.state,
            escalated=s.escalated, high_risk=high_risk, decision=None if blind else public_decision(row, principal),
        ))
    return items


def list_open_items(run_store: RunStore, principal: Principal, *, run_id: str | None = None) -> list[ReviewItem]:
    # ponytail: reads every reviewable run's files per call; keep an open-items index if run count makes this slow
    manifests = [run_store.load_manifest(run_id)] if run_id else run_store.list_runs()
    return [
        i for m in manifests if m is not None and m.run_type in REVIEWABLE_RUN_TYPES
        for i in run_items(run_store, m, principal) if i.state not in FINAL_STATES
    ]


def get_item(run_store: RunStore, run_id: str, item_key: str, principal: Principal) -> ReviewItem | None:
    m = run_store.load_manifest(run_id)
    if m is None or m.run_type not in REVIEWABLE_RUN_TYPES:
        return None
    return next((i for i in run_items(run_store, m, principal) if i.item_key == item_key), None)
