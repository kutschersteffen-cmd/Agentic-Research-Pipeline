from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from arp.schemas.common import now_iso
from arp.schemas.review import ReviewDecision
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
    review keys at "{issuer_key}:{field_id}:{period}" (older runs: bare
    company_id); this function has no opinion
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


FINAL_STATES = frozenset({"second_done", "final"})

PUBLIC_KEYS = (
    "item_key", "decision", "reason_code", "role", "decided_at", "comment",
    "corrected_value", "correction_citation", "snapshot_id", "step", "edited_value",
)


@dataclass
class ItemState:
    state: str = "pending"
    escalated: bool = False
    first: dict | None = None
    second: dict | None = None
    effective: dict | None = None
    rows: list[dict] = field(default_factory=list)  # every row of the item, oldest first


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def same_value(a, b) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        return math.isclose(fa, fb, rel_tol=1e-9)
    return str(a).strip() == str(b).strip()


def _kind(row: dict) -> str | None:
    return "correct" if row.get("decision") == "edit" else row.get("decision")


def _value(row: dict):
    return (row.get("corrected_value") or row.get("edited_value") or {}).get("value")


def agrees(first: dict, second: dict) -> bool:
    if _kind(first) != _kind(second):
        return False
    return _kind(first) != "correct" or same_value(_value(first), _value(second))


def item_state(rows: list[dict], *, cosigned_at: set[str], cosign_required: set[str]) -> ItemState:
    """Fold one item's decision rows, oldest first, into its review state."""
    s = ItemState(rows=list(rows))
    for row in rows:
        step, decision = row.get("step"), row.get("decision")
        if step == "second":
            ok = s.first is not None and agrees(s.first, row)
            s.state, s.effective, s.second = ("second_done", s.first, row) if ok else ("disagreed", None, row)
        elif step == "resolution":
            s.state, s.effective, s.escalated = "final", row, False
        else:  # "first" or a legacy row (no step): starts a new round
            s.first, s.second, s.effective = row, None, None
            s.escalated = decision == "escalate"
            if s.escalated:
                s.state = "pending"
            elif step == "first":
                s.state = "first_done" if row.get("second_required") else "final"
            elif decision in cosign_required:
                s.state = "second_done" if row.get("decided_at") in cosigned_at else "first_done"
            else:
                s.state = "final"
            if s.state in FINAL_STATES:
                s.effective = row
    return s


def item_states(run_store: RunStore, run_id: str, *, cosign_required: set[str]) -> dict[str, ItemState]:
    rows: dict[str, list[dict]] = defaultdict(list)
    for r in run_store.read_jsonl(run_store.review_decisions_path(run_id)):
        rows[r["item_key"]].append(r)
    signed: dict[str, set[str]] = defaultdict(set)
    for c in run_store.read_jsonl(run_store.review_cosigns_path(run_id)):
        signed[c["item_key"]].add(c["decision_decided_at"])
    return {k: item_state(v, cosigned_at=signed[k], cosign_required=cosign_required) for k, v in rows.items()}


def effective_decisions(run_store: RunStore, run_id: str, *, cosign_required: set[str]) -> dict[str, dict]:
    """The effective row of every item in a final state; a `correct` row also carries
    `edited_value` so existing readers keep working."""
    out = {}
    for k, s in item_states(run_store, run_id, cosign_required=cosign_required).items():
        if s.state in FINAL_STATES:
            row = s.effective
            out[k] = {**row, "edited_value": row["corrected_value"]} if row.get("decision") == "correct" else row
    return out


def append_decision(run_store: RunStore, run_id: str, d: ReviewDecision) -> None:
    run_store.append_jsonl(run_store.review_decisions_path(run_id), d.model_dump(mode="json"))


def public_decision(row: dict, principal: Principal | None) -> dict:
    """What clients may see of a decision row: never `user_id`, never `reviewer`."""
    return {k: row.get(k) for k in PUBLIC_KEYS} | {"mine": principal is not None and row.get("user_id") == principal.user_id}


def blind_for(s: ItemState, principal: Principal, *, high_risk: bool) -> bool:
    return (
        high_risk
        and s.state == "first_done"
        and principal.role != "approver"
        and principal.user_id != s.first.get("user_id")
    )
