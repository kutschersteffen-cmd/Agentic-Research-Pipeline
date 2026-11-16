"""One count of everything waiting on a person's decision, for the top bar's badge."""

from __future__ import annotations

from pydantic import BaseModel

from arp.api.auth import Principal
from arp.orchestration.review_queue import latest_decisions
from arp.review.items import list_open_items
from arp.storage.run_store import RunStore

DECISION_STAGES = {"checkpoint", "tracking"}


class WaitingCounts(BaseModel):
    review: int
    decisions: int
    ballots: int
    total: int


def waiting_counts(run_store: RunStore, principal: Principal, house_flow: dict) -> WaitingCounts:
    review = len(list_open_items(run_store, principal))
    decisions = sum(len(s["decisions"]) for s in house_flow["stages"] if s["id"] in DECISION_STAGES)
    ballots = sum(
        len({q["item_key"] for q in run_store.read_review_queue(m.run_id)} - set(latest_decisions(run_store, m.run_id)))
        for m in run_store.list_runs()
        if m.run_type == "proxy_voting"
    )
    return WaitingCounts(review=review, decisions=decisions, ballots=ballots, total=review + decisions + ballots)
