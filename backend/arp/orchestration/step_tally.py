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

from arp.storage.run_store import RunStore


@dataclass
class _Tally:
    counts: Counter = field(default_factory=Counter)
    seconds: Counter = field(default_factory=Counter)
    companies: dict[str, dict[str, Counter]] = field(default_factory=dict)

    def add(self, company_id: str | None, node: str, seconds: float) -> None:
        self.counts[node] += 1
        self.seconds[node] += seconds
        if company_id:
            per = self.companies.setdefault(company_id, {"counts": Counter(), "seconds": Counter()})
            per["counts"][node] += 1
            per["seconds"][node] += seconds

    def view(self, company_id: str | None) -> dict:
        if company_id is None:
            return {"counts": dict(self.counts), "seconds": _rounded(self.seconds)}
        per = self.companies.get(company_id, {"counts": Counter(), "seconds": Counter()})
        return {"counts": dict(per["counts"]), "seconds": _rounded(per["seconds"])}

    def dump(self) -> dict:
        return {
            "counts": dict(self.counts),
            "seconds": _rounded(self.seconds),
            "companies": {c: {"counts": dict(p["counts"]), "seconds": _rounded(p["seconds"])} for c, p in self.companies.items()},
        }

    @classmethod
    def load(cls, data: dict) -> _Tally:
        tally = cls(Counter(data.get("counts", {})), Counter(data.get("seconds", {})))
        for c, p in data.get("companies", {}).items():
            tally.companies[c] = {"counts": Counter(p["counts"]), "seconds": Counter(p["seconds"])}
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
    tally = _live.setdefault(run_id, _Tally())
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


def step_counts(run_store: RunStore, run_id: str, company_id: str | None = None) -> tuple[dict, bool]:
    """({"counts", "seconds"} per node, for the run or one company;
    whether the run is still counting)."""
    if run_id in _live:
        return _live[run_id].view(company_id), True
    path = run_store.run_dir(run_id) / _FILE
    if not path.exists():
        return {"counts": {}, "seconds": {}}, False
    return _Tally.load(json.loads(path.read_text())).view(company_id), False
