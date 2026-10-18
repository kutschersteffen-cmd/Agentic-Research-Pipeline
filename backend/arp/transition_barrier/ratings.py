"""A cell's current rating: its latest ratified derivation result, else the bundled hand rating."""

from __future__ import annotations

from typing import Literal

from arp.orchestration.review_queue import FINAL_STATES, item_states
from arp.schemas.common import JobStatus
from arp.schemas.transition_barrier import BarrierScore, Region
from arp.storage.run_store import RunStore
from arp.transition_barrier import RUN_TYPE
from arp.transition_barrier.dataset import data_dir, filter_scores
from arp.transition_barrier.engine import Result, cell_evidence, cell_source
from arp.transition_barrier.rule_book import load_rule_book

_FINISHED = {JobStatus.COMPLETED, JobStatus.PARTIALLY_COMPLETED}


class CellView(BarrierScore):
    basis: Literal["hand_rated", "derived"]
    ratified_by: str | None = None
    ratified_at: str | None = None
    result: Result | None = None  # the ratified result


def item_key(code: str, region: str) -> str:
    return f"{code}:{region}"


def result_for(run_store: RunStore, run_id: str, code: str, region: str) -> Result | None:
    key = item_key(code, region)
    row = next((r for r in run_store.read_results(run_id) if r.get("_key") == key), None)
    return None if row is None else Result.model_validate(row)


def latest_result(run_store: RunStore, code: str, region: str) -> Result | None:
    """The result of the newest finished derivation run that covered the cell."""
    for m in run_store.list_runs(RUN_TYPE):  # newest first
        if m.status in _FINISHED and (found := result_for(run_store, m.run_id, code, region)):
            return found
    return None


def current_cell(code: str, region: str, run_store: RunStore) -> CellView:
    """Ratified means a `changed` or `unchanged` item that is final with an effective `approve`;
    the newest final decision wins. `ratified_by` is whoever made that decision final.

    shortcut: scans every derivation run per call, fine while runs are few; index ratified cells when it isn't.
    """
    key = item_key(code, region)
    best: tuple[str, dict, Result] | None = None
    for m in run_store.list_runs(RUN_TYPE):
        s = item_states(run_store, m.run_id).get(key)
        if s is None or s.state not in FINAL_STATES or s.effective.get("decision") != "approve":
            continue
        deciding = s.second if s.state == "second_done" else s.effective
        item = next((r for r in run_store.read_review_queue(m.run_id) if r["item_key"] == key), None)
        if item is None or item["kind"] not in ("changed", "unchanged") or (best and deciding["decided_at"] <= best[0]):
            continue
        if result := result_for(run_store, m.run_id, code, region):
            best = (deciding["decided_at"], deciding, result)

    bundled = next(iter(filter_scores(code=code, region=Region(region))))
    if best is None:
        return CellView(**bundled.model_dump(), basis="hand_rated")
    decided_at, row, result = best
    rules = load_rule_book(data_dir())[0].criteria[code]
    return CellView(
        **{**bundled.model_dump(), "rating": result.rating, "confidence": result.confidence,
           "evidence": cell_evidence(result), "source": cell_source(result, rules), "last_verified": decided_at[:10]},
        basis="derived", ratified_by=row["user_id"], ratified_at=decided_at, result=result,
    )
