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
