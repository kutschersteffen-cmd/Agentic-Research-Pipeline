from __future__ import annotations

from pydantic import BaseModel

from arp.orchestration.review_queue import decision_history, latest_decisions, record_review_decision
from arp.storage.run_store import RunStore

# Shared logic behind the near-identical review-queue endpoints in
# themes.py, extraction.py, financials.py, voting.py, identity.py --
# functions operating on primitives, not a route-registering factory,
# since each router's path prefix/tags stay explicit and independently
# discoverable. voting.py's review request carries extra fields (vote,
# co_signed_by) and its own validation, so it keeps its own request model
# and only calls submit_review() with the primitives everyone shares.


class ReviewDecisionRequest(BaseModel):
    item_key: str
    decision: str  # approve | edit | reject
    reviewer: str | None = None
    edited_value: dict | None = None
    comment: str | None = None


def get_review_queue(run_store: RunStore, run_id: str) -> dict:
    rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    pending = [r for r in rows if r["item_key"] not in decisions]
    decided = [{"item": r, "decision": decisions[r["item_key"]]} for r in rows if r["item_key"] in decisions]
    return {"pending": pending, "decided": decided}


def get_review_decisions(run_store: RunStore, run_id: str) -> dict:
    """Latest decision per item_key across the whole run -- one call so a
    results table can show every item's review status without a request
    per item."""
    return {"decisions": latest_decisions(run_store, run_id)}


def get_review_history(run_store: RunStore, run_id: str, item_key: str) -> dict:
    return {"item_key": item_key, "history": decision_history(run_store, run_id, item_key)}


def submit_review(
    run_store: RunStore,
    run_id: str,
    *,
    item_key: str,
    decision: str,
    reviewer: str | None,
    edited_value: dict | None,
    comment: str | None = None,
) -> dict:
    record_review_decision(run_store, run_id, item_key, decision, reviewer, edited_value, comment)
    return {"status": "recorded"}
