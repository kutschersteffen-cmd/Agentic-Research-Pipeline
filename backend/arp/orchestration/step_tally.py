"""Counts how many items pass through each node of a run's per-item graphs,
and how long they spend there -- for the whole run and per company.

`run_company_batch` opens a tally for its run and marks which company each
worker is on; every per-item graph run through `run_graph` inside it adds
to the node it visits. Asyncio tasks inherit context variables, so the
pipelines pass nothing down. The tally is live in memory while the run
executes and saved to the run folder when it finishes.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from arp.llm.base import LLMUsage
from arp.storage.run_store import RunStore


@dataclass
class _Tally:
    counts: Counter = field(default_factory=Counter)
    seconds: Counter = field(default_factory=Counter)
    companies: dict[str, dict[str, Counter]] = field(default_factory=dict)
    # Per company, per company-level step: what the step found (documents,
    # bytes, a verdict...). Summed across companies for the run view.
    details: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    run_store: RunStore | None = None
    run_id: str | None = None
    # batch_id -> the wait of each Message Batch this run has open (a run can
    # have several: extraction's extractor and verifier clients batch apart).
    batch_waits: dict[str, dict] = field(default_factory=dict)

    def add(self, company_id: str | None, node: str, seconds: float) -> None:
        self.counts[node] += 1
        self.seconds[node] += seconds
        if company_id:
            per = self.companies.setdefault(company_id, {"counts": Counter(), "seconds": Counter()})
            per["counts"][node] += 1
            per["seconds"][node] += seconds

    def view(self, company_id: str | None) -> dict:
        if company_id is None:
            summed: dict[str, dict[str, Any]] = {}
            for per_company in self.details.values():
                for node, found in per_company.items():
                    into = summed.setdefault(node, {})
                    for key, value in found.items():
                        # Counts and yes/no findings add up; a score such as
                        # a confidence does not, so floats are left out.
                        if isinstance(value, bool | int):
                            into[key] = into.get(key, 0) + int(value)
            return {"counts": dict(self.counts), "seconds": _rounded(self.seconds), "details": summed}
        per = self.companies.get(company_id, {"counts": Counter(), "seconds": Counter()})
        return {"counts": dict(per["counts"]), "seconds": _rounded(per["seconds"]), "details": self.details.get(company_id, {})}

    def dump(self) -> dict:
        return {
            "counts": dict(self.counts),
            "seconds": _rounded(self.seconds),
            "companies": {c: {"counts": dict(p["counts"]), "seconds": _rounded(p["seconds"])} for c, p in self.companies.items()},
            "details": self.details,
        }

    @classmethod
    def load(cls, data: dict) -> _Tally:
        tally = cls(Counter(data.get("counts", {})), Counter(data.get("seconds", {})))
        for c, p in data.get("companies", {}).items():
            tally.companies[c] = {"counts": Counter(p["counts"]), "seconds": Counter(p["seconds"])}
        tally.details = data.get("details", {})
        return tally


def _rounded(seconds: Counter) -> dict[str, float]:
    return {k: round(v, 2) for k, v in seconds.items()}


_current: ContextVar[_Tally | None] = ContextVar("step_tally", default=None)
_company: ContextVar[str | None] = ContextVar("step_tally_company", default=None)
# ponytail: in-process only; a server restart mid-run loses the live counts
# until the run is re-run. Persist periodically if that starts to matter.
_live: dict[str, _Tally] = {}

_FILE = "step_counts.json"


@contextmanager
def tally_run(run_store: RunStore, run_id: str) -> Iterator[None]:
    tally = _live.setdefault(run_id, _Tally(run_store=run_store, run_id=run_id))
    token = _current.set(tally)
    try:
        yield
    finally:
        _current.reset(token)
        (run_store.run_dir(run_id) / _FILE).write_text(json.dumps(tally.dump()))
        _live.pop(run_id, None)


@contextmanager
def on_company(company_id: str) -> Iterator[None]:
    token = _company.set(company_id)
    try:
        yield
    finally:
        _company.reset(token)


async def run_graph(graph: Any, state: dict) -> dict:
    """`graph.ainvoke(state)`, counting each node the item visits. A node's
    time is measured from the previous node's finish, which holds because
    each item walks its graph one node at a time."""
    tally = _current.get()
    if tally is None:
        return await graph.ainvoke(state)
    company_id = _company.get()
    final = state
    started = time.monotonic()
    async for mode, chunk in graph.astream(state, stream_mode=["updates", "values"]):
        if mode == "updates":
            now = time.monotonic()
            for node in chunk:
                tally.add(company_id, node, now - started)
            started = now
        else:
            final = chunk
    return final


def record_step(node: str, seconds: float, details: dict[str, Any] | None = None) -> None:
    """A company-level step (one that runs once per company, outside the
    per-item graphs) reports itself: one visit, its time, what it found."""
    tally = _current.get()
    if tally is None:
        return
    company_id = _company.get()
    tally.add(company_id, node, seconds)
    if company_id and details is not None:
        tally.details.setdefault(company_id, {})[node] = details


def record_cost(model: str, usage: LLMUsage) -> None:
    """An LLM call a company-level step made, added to the run's tokens and cost."""
    tally = _current.get()
    if tally is None or tally.run_store is None or tally.run_id is None:
        return
    from arp.orchestration.cost_tracker import estimate_cost_usd
    from arp.orchestration.job_manager import JobManager

    JobManager(tally.run_store).record_progress(
        tally.run_id,
        usage=usage,
        cost_delta_usd=estimate_cost_usd(model, usage),
    )


def record_batch_wait(batch_id: str, wait: dict | None) -> None:
    """A Message Batch of this run opened (`wait`) or ended (None). The run's
    status line shows every open one combined: their requests summed, the
    earliest submitted; None once none is open."""
    tally = _current.get()
    if tally is None or tally.run_store is None or tally.run_id is None:
        return
    from arp.orchestration.job_manager import JobManager

    if wait is None:
        tally.batch_waits.pop(batch_id, None)
    else:
        tally.batch_waits[batch_id] = wait
    waits = list(tally.batch_waits.values())
    combined = None
    if waits:
        combined = {**min(waits, key=lambda w: w["submitted_at"]), "request_count": sum(w["request_count"] for w in waits)}
    JobManager(tally.run_store)._update(tally.run_id, lambda m: setattr(m, "batch_wait", combined))


def current_run_id() -> str | None:
    """The run this code runs inside; None outside a run."""
    tally = _current.get()
    return tally.run_id if tally is not None else None


def cancel_requested() -> bool:
    """Whether someone asked to cancel the current run; False outside a run."""
    tally = _current.get()
    if tally is None or tally.run_store is None or tally.run_id is None:
        return False
    manifest = tally.run_store.load_manifest(tally.run_id)
    return manifest is not None and manifest.cancel_requested


def step_counts(run_store: RunStore, run_id: str, company_id: str | None = None) -> tuple[dict, bool]:
    """({"counts", "seconds"} per node, for the run or one company;
    whether the run is still counting)."""
    if run_id in _live:
        return _live[run_id].view(company_id), True
    path = run_store.run_dir(run_id) / _FILE
    if not path.exists():
        return {"counts": {}, "seconds": {}, "details": {}}, False
    return _Tally.load(json.loads(path.read_text())).view(company_id), False
