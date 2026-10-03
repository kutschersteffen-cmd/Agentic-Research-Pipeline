from __future__ import annotations

from typing import TYPE_CHECKING

from arp.schemas.common import now_iso
from arp.storage.run_store import RunStore

if TYPE_CHECKING:  # runtime import would cycle: api.auth -> api.deps -> research.pipeline -> here
    from arp.api.auth import Principal


def queue_for_review(run_store: RunStore, run_id: str, item_key: str, payload: dict) -> None:
    """Append a flagged item (low confidence, ungrounded citation, uncertain
    verdict) to the run's review queue for human sign-off. Never silently
    dropped and never silently included in the trusted output.
    """
    row = {"item_key": item_key, "queued_at": now_iso(), **payload}
    run_store.append_jsonl(run_store.review_queue_path(run_id), row)


def record_review_decision(
    run_store: RunStore,
    run_id: str,
    item_key: str,
    decision: str,
    reviewer: str | None,
    edited_value: dict | None,
    comment: str | None = None,
    *,
    principal: Principal | None = None,
) -> None:
    """decision: 'approve' | 'edit' | 'reject' | 'escalate'. Decisions are appended, never
    mutated in place, so the review queue keeps a full audit trail; the
    latest decision per item_key wins when results are materialized.

    item_key granularity is entirely up to the caller -- the Theme Builder
    keys at "{company_id}:{activity_id}", the Extraction Engine's per-field
    review keys at "{company_id}:{field_id}"; this function has no opinion
    on it. `comment` is a trailing optional kwarg specifically so existing
    positional call sites (e.g. themes.py) keep working unmodified.
    """
    if principal is not None:
        reviewer = principal.name
    row = {
        "item_key": item_key,
        "decision": decision,
        "reviewer": reviewer,
        "user_id": principal.user_id if principal else None,
        "role": principal.role if principal else None,
        "edited_value": edited_value,
        "comment": comment,
        "decided_at": now_iso(),
    }
    run_store.append_jsonl(run_store.review_decisions_path(run_id), row)


def latest_decisions(run_store: RunStore, run_id: str) -> dict[str, dict]:
    rows = run_store.read_jsonl(run_store.review_decisions_path(run_id))
    latest: dict[str, dict] = {}
    for row in rows:
        latest[row["item_key"]] = row  # later rows overwrite earlier ones (JSONL append order)
    return latest


def decision_history(run_store: RunStore, run_id: str, item_key: str) -> list[dict]:
    """Every decision ever recorded for item_key, oldest first -- the full
    audit trail that latest_decisions() collapses to just the last row.
    """
    rows = run_store.read_jsonl(run_store.review_decisions_path(run_id))
    return [r for r in rows if r["item_key"] == item_key]


def record_cosign(run_store: RunStore, run_id: str, item_key: str, principal: Principal) -> None:
    """Second sign-off on the latest decision for item_key. Bound to that
    decision's decided_at, so any later decision invalidates it."""
    decision = latest_decisions(run_store, run_id).get(item_key)
    if decision is None:
        raise ValueError("nothing to co-sign")
    if principal.user_id == decision.get("user_id"):  # legacy rows lack user_id: allowed
        raise ValueError("co-sign must be a different person")
    run_store.append_jsonl(
        run_store.review_cosigns_path(run_id),
        {
            "item_key": item_key,
            "user_id": principal.user_id,
            "name": principal.name,
            "role": principal.role,
            "decision_decided_at": decision["decided_at"],
            "cosigned_at": now_iso(),
        },
    )


def effective_decisions(run_store: RunStore, run_id: str, *, cosign_required: set[str]) -> dict[str, dict]:
    """latest_decisions minus decisions in cosign_required that lack a matching co-sign."""
    signed = {(r["item_key"], r["decision_decided_at"]) for r in run_store.read_jsonl(run_store.review_cosigns_path(run_id))}
    return {
        k: d
        for k, d in latest_decisions(run_store, run_id).items()
        if d.get("decision") not in cosign_required or (k, d.get("decided_at")) in signed
    }
