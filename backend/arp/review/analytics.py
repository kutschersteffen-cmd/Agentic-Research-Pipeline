"""Error analytics (E59): monthly reviewer correction reasons by field, model and document type."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel

from arp.config import Settings
from arp.holdings.intake import previous_month_end
from arp.orchestration.interval_scheduler import IntervalScheduler
from arp.schemas.review import field_item_key, period_key
from arp.storage.atomic_io import atomic_write_text
from arp.storage.run_store import RunStore

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


@dataclass(frozen=True)
class ReasonTotal:
    field_id: str
    model: str | None
    doc_type: str | None
    reason: str
    count: int


def monthly_totals(run_store: RunStore, month: str) -> list[ReasonTotal]:
    """Reviewer decision rows decided in `month` (YYYY-MM) across non-trial extraction runs, counted per
    (field, extractor model, first cited document type, reason). System rows (an escalation a parser upgrade
    caused, `user_id == "system"`) are not reviewer decisions and are left out."""
    counts: Counter[tuple] = Counter()
    for m in run_store.extraction_runs():
        joined = {}
        for row in run_store.read_results(m.run_id):
            for f in row.get("fields", []):
                cites = f.get("citations") or []
                joined[field_item_key(row.get("issuer_key", ""), f["field_id"], period_key(f))] = (
                    f["field_id"], (f.get("provenance") or {}).get("extractor_model"), cites[0].get("doc_type") if cites else None,
                )
        for d in run_store.read_decisions(m.run_id):
            if d.get("user_id") in (None, "system") or not d.get("reason_code") or not str(d.get("decided_at", "")).startswith(month):
                continue
            field_id, model, doc_type = joined.get(d["item_key"]) or (d["item_key"].rsplit(":", 2)[-2], None, None)
            counts[(field_id, model, doc_type, d["reason_code"])] += 1
    return [ReasonTotal(*k, n) for k, n in sorted(counts.items(), key=lambda kv: tuple("" if x is None else x for x in kv[0]))]


def write_month(run_store: RunStore, settings: Settings, month: str) -> Path:
    path = settings.review_analytics_dir / f"{month}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps([asdict(t) for t in monthly_totals(run_store, month)], indent=2))
    return path


def _today() -> date:
    return datetime.now(UTC).date()


class ReviewAnalyticsConfig(BaseModel):
    enabled: bool = False
    interval_hours: int = 24
    last_month: str | None = None


class ReviewAnalyticsScheduler(IntervalScheduler):
    config_cls = ReviewAnalyticsConfig
    job_id = "review-analytics-schedule"

    def __init__(self, settings: Settings, run_store: RunStore) -> None:
        super().__init__(settings.review_analytics_state_dir)
        self.settings = settings
        self.run_store = run_store

    def _default_config(self) -> ReviewAnalyticsConfig:
        return ReviewAnalyticsConfig(enabled=self.settings.review_analytics_schedule_enabled)

    async def _run(self, config: ReviewAnalyticsConfig) -> None:
        month = previous_month_end(_today())[:7]
        if config.last_month != month:
            write_month(self.run_store, self.settings, month)
            config.last_month = month
