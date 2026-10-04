"""Cost and time per 1,000 issuers, read off a finished run's manifest."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from arp.schemas.common import RunManifest


class RunReport(BaseModel):
    run_id: str
    run_type: str
    status: str
    concurrency: int | None
    issuers: int
    completed: int
    failed: int
    review: int
    duration_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_per_1000_usd: float
    minutes_per_1000: float
    issuers_per_minute: float


def run_report(m: RunManifest) -> RunReport:
    duration_s = (datetime.fromisoformat(m.updated_at) - datetime.fromisoformat(m.created_at)).total_seconds()
    issuers = m.completed_count + m.failed_count
    if issuers and duration_s:
        per_1000 = 1000 / issuers
        cost_per_1000, minutes_per_1000 = m.estimated_cost_usd * per_1000, duration_s / 60 * per_1000
        per_minute = issuers / (duration_s / 60)
    else:
        cost_per_1000 = minutes_per_1000 = per_minute = 0.0
    return RunReport(
        run_id=m.run_id,
        run_type=m.run_type,
        status=m.status.value,
        concurrency=m.params.get("concurrency"),
        issuers=issuers,
        completed=m.completed_count,
        failed=m.failed_count,
        review=m.review_count,
        duration_s=duration_s,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        cost_usd=m.estimated_cost_usd,
        cost_per_1000_usd=cost_per_1000,
        minutes_per_1000=minutes_per_1000,
        issuers_per_minute=per_minute,
    )


def render_markdown(reports: list[RunReport], *, title: str, note: str) -> str:
    lines = [
        f"# {title}",
        "",
        note,
        "",
        "| Run | Status | Concurrency | Issuers | Failed | Review | Duration (s) | Tokens in/out | Cost (USD) | USD / 1,000 | Min / 1,000 | Issuers / min |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| {r.run_id} | {r.status} | {r.concurrency if r.concurrency is not None else '-'} | {r.issuers} | {r.failed} | "
            f"{r.review} | {r.duration_s:.1f} | {r.input_tokens}/{r.output_tokens} | {r.cost_usd:.2f} | "
            f"{r.cost_per_1000_usd:.2f} | {r.minutes_per_1000:.2f} | {r.issuers_per_minute:.1f} |"
        )
    return "\n".join(lines) + "\n"
