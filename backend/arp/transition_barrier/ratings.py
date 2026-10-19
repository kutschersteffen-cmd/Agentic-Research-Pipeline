"""A cell's current rating: its latest ratified derivation result, else the bundled hand rating."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from functools import cached_property

from arp.orchestration.review_queue import FINAL_STATES, item_states
from arp.schemas.common import JobStatus
from arp.schemas.transition_barrier import BarrierScore
from arp.storage.run_store import RunStore
from arp.transition_barrier import RUN_TYPE, store
from arp.transition_barrier.dataset import data_dir, load_criteria, load_scores
from arp.transition_barrier.engine import Result, cell_evidence, cell_source
from arp.transition_barrier.rule_book import CriterionRules, load_rule_book

_FINISHED = {JobStatus.COMPLETED, JobStatus.PARTIALLY_COMPLETED}


class CellView(BarrierScore):
    ratified_at: str | None = None
    result: Result | None = None  # the ratified result


def item_key(code: str, region: str) -> str:
    return f"{code}:{region}"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class Ratings:
    """One pass over the derivation runs, then an answer for any cell.

    Ratified means a `changed` or `unchanged` item that is final with an effective `approve`;
    the newest final decision wins. `ratified_by` is whoever made that decision final.

    shortcut: scans every derivation run per instance, fine while runs are few; index ratified cells when it isn't.
    """

    def __init__(self, run_store: RunStore) -> None:
        self._latest: dict[str, dict] = {}  # key -> the newest finished derivation's result row
        self._ratified: dict[str, list[tuple[str, dict, Result]]] = defaultdict(list)  # (decided_at, decision, result)
        self._decisions: dict[str, list[tuple[str, dict]]] = defaultdict(list)  # (run_id, decision row)
        for m in run_store.list_runs(RUN_TYPE):  # newest first
            results = {r["_key"]: r for r in run_store.read_results(m.run_id)}
            if m.status in _FINISHED:
                for key, row in results.items():
                    self._latest.setdefault(key, row)
            queue = None
            for key, s in item_states(run_store, m.run_id).items():
                self._decisions[key] += [(m.run_id, r) for r in s.rows]
                if s.state not in FINAL_STATES or s.effective.get("decision") != "approve" or key not in results:
                    continue
                queue = queue or {r["item_key"]: r for r in run_store.read_review_queue(m.run_id)}
                if key in queue and queue[key]["kind"] in ("changed", "unchanged"):
                    deciding = s.second if s.state == "second_done" else s.effective
                    self._ratified[key].append((deciding["decided_at"], deciding, Result.model_validate(results[key])))
        for rows in self._ratified.values():
            rows.sort(key=lambda r: r[0])
        self._bundled = {(s.code, s.region.value): s for s in load_scores()}

    @cached_property
    def _criteria(self) -> dict[str, CriterionRules]:
        return load_rule_book(data_dir())[0].criteria

    def latest(self, code: str, region: str) -> Result | None:
        """The result of the newest finished derivation run that covered the cell."""
        row = self._latest.get(item_key(code, region))
        return None if row is None else Result.model_validate(row)

    def cell(self, code: str, region: str) -> CellView:
        key = item_key(code, region)
        bundled = self._bundled[(code, region)].model_dump()
        flags = []
        if (latest := self.latest(code, region)) and latest.rating == "not_rated":
            if latest.missing_facts:
                flags.append("Not re-derived: missing " + ", ".join(latest.missing_facts))
            if latest.open_params:
                flags.append("Not re-derived: open threshold " + ", ".join(latest.open_params))
        if not self._ratified.get(key):
            return CellView(**{**bundled, "flags": flags})
        decided_at, row, result = self._ratified[key][-1]
        rules = CriterionRules.model_validate(result.snapshot)  # the rules it was derived with, not today's
        if rules.model_dump(mode="json") != self._criteria[code].model_dump(mode="json"):  # only this criterion's rules count
            flags.append(f"Rules changed since this rating (v{result.rule_book_version})")
        return CellView(
            **{**bundled, "rating": result.rating, "confidence": result.confidence, "evidence": cell_evidence(result),
               "source": cell_source(result, rules), "last_verified": decided_at[:10], "basis": "derived",
               "ratified_by": row["user_id"], "ratified_at": decided_at, "result": result, "flags": flags}
        )

    def history(self, code: str, region: str) -> list[dict]:
        """Everything that happened to the cell, oldest first."""
        key = item_key(code, region)
        bundled = self._bundled[(code, region)]
        registry = next(c for c in load_criteria() if c.code == code).primary_sources
        facts = store.cell_facts(code, region)
        labels = store.fact_labels(facts, registry)
        out = [{"at": bundled.last_verified, "by": None, "kind": "rating", "rating": bundled.rating.value, "basis": "hand_rated"}]
        out += [
            {"at": _iso(f["entered_at"]), "by": f["entered_by"], "kind": "fact", "fact": f["fact"], "value": labels[str(f["id"])]}
            for f in facts
        ]
        out += [
            {"at": _iso(c["chosen_at"]), "by": c["chosen_by"], "kind": "choice", "fact": c["fact"], "value": labels[c["fact_id"]], "reason": c["reason"]}
            for c in store.cell_choices(code, region)
        ]
        out += [
            {"at": d["decided_at"], "by": d["user_id"], "kind": "decision", "decision": d["decision"], "run_id": run_id}
            for run_id, d in self._decisions.get(key, [])
        ]
        out += [
            {"at": decided_at, "by": d["user_id"], "kind": "rating", "rating": result.rating, "basis": "derived"}
            for decided_at, d, result in self._ratified.get(key, [])
        ]
        return sorted(out, key=lambda e: e["at"])  # stable: a decision stays ahead of the rating it made


def current_cell(code: str, region: str, run_store: RunStore) -> CellView:
    return Ratings(run_store).cell(code, region)
