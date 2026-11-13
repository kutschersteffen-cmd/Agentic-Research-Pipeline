"""Step 4: where each company of the flow's run stands, in the spec's fixed statuses."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from pydantic import BaseModel

# Graph nodes in the order a company passes them, by the stage they belong to (arp.extraction.steps.STEP_INFO).
_STAGES = (
    ("Reading documents", 25, ("identity", "content_search", "document_mgmt", "parse_index", "try_tagged", "gather_evidence")),
    ("Extracting", 50, ("extract", "answer", "finalize_no_evidence")),
    ("Checking the answers", 75, ("verify", "adjudicate", "finalize_answer_error", "aggregate", "company", "rules")),
)
_ACTIVE = ("pending", "running")


class CompanyProgress(BaseModel):
    company_id: str
    name: str
    status: str
    percent: int
    reason: str | None = None
    document_problem: bool = False
    needs_you: int = 0
    retryable: bool = False  # Retry accepts this company


class FlowProgress(BaseModel):
    run_id: str
    started_at: str
    done: int
    finished: int  # rows that read Done or Failed; `done` leaves out a company stopped for review
    total: int
    minutes_left: int | None
    cost_usd: float
    status: str
    stopping: bool  # Stop was requested and the run has not ended yet
    companies: list[CompanyProgress]


def company_status(raw: str, run_status: str, steps: dict[str, int]) -> tuple[str, int]:
    """(status, percent) from the run's per-company outcome (done/review/failed/waiting), the run's status and the
    steps counted for the company so far (empty once the API restarted: only the stored outcome is known then)."""
    if raw in ("done", "review"):
        return "Done", 100
    if raw == "failed":
        return "Failed", 0
    if run_status not in _ACTIVE:  # the run is over and this company never started: stopped
        return "Stopped", 0
    for label, percent, nodes in reversed(_STAGES):
        if any(steps.get(n) for n in nodes):
            return label, percent
    return "Waiting", 0


def minutes_left(started: datetime, now: datetime, *, done: int, total: int, reached: float = 0.0) -> int | None:
    """Elapsed time per finished company times the companies left. Before one has finished, the stages reached
    stand in for it: `reached` is the companies' percent / 100 summed, used from a quarter of a company on."""
    progress = done or reached
    if progress < 0.25:
        return None
    started = started if started.tzinfo else started.replace(tzinfo=UTC)  # a stored time without a zone is UTC
    return max(0, math.ceil((now - started).total_seconds() / 60 / progress * (total - progress)))  # never negative on a skewed clock
