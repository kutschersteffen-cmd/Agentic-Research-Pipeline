"""Daily in-process job: re-ground sample, holdings pull, monthly snapshot, corrections (E74, E77)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from arp.config import Settings
from arp.holdings.api_source import pull_due
from arp.holdings.intake import previous_month_end
from arp.orchestration.interval_scheduler import IntervalScheduler
from arp.orchestration.reground import reground_if_parser_changed
from arp.publish.facts import ConcurrentPublish, Fact, PublishStore, ts_now
from arp.publish.gate import reground, sample
from arp.publish.reader import events_since, facts_as_of
from arp.schemas.portfolio import HolderConfig
from arp.snapshots.build import (
    SnapshotFrozen,
    SnapshotSettling,
    build_correction,
    build_snapshot,
    list_months,
    month_of,
)

logger = logging.getLogger(__name__)


class PublishingScheduleConfig(BaseModel):
    enabled: bool = False
    interval_hours: int = 24
    last_run_at: str | None = None
    last_reground_day: str | None = None
    last_results: dict = Field(default_factory=dict)


def _today() -> date:
    return datetime.now(UTC).date()


def first_business_day_after(month_end: date, n: int = 1) -> date:
    # ponytail: weekdays only, no holiday calendar; add one when a missed holiday matters
    d = month_end
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def due_jobs(
    today: date, config, *, settings, latest_frozen_month: str | None, holders: list[HolderConfig]
) -> list[str]:
    prev = previous_month_end(today)
    due = []
    if settings.postgres_dsn and config.last_reground_day != today.isoformat():
        due.append("reground")
    url = bool(settings.holdings_api_url)
    pull = url and today.day >= settings.holdings_pull_day and any(
        h.source == "api" and (h.as_of or "") < prev for h in holders
    )
    if pull:
        due.append("pull")
    if (
        today >= first_business_day_after(date.fromisoformat(prev), settings.snapshot_day)
        and latest_frozen_month != month_of(prev)
        and not (url and today.day < settings.holdings_pull_day)
    ):  # a failing pull never holds it: the pull runs first, stale holders stay flagged in holder status
        due.append("snapshot")
    if settings.postgres_dsn and latest_frozen_month is not None:
        due.append("corrections")
    return due


def reground_sample(
    facts: list[Fact], *, n: int, day: str, blob_store, content_store, fuzzy_threshold: float, log_path: Path
) -> list[dict]:
    rows = []
    for f in sample(facts, n, seed=day):
        result = reground(f, blob_store=blob_store, content_store=content_store, fuzzy_threshold=fuzzy_threshold)
        if result != "ok":
            logger.warning("Re-ground of fact %s: %s", f.fact_id, result)
        rows.append({"day": day, "fact_id": f.fact_id, "result": result})
    if rows:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in rows)
    return rows


class PublishingScheduler(IntervalScheduler):
    config_cls = PublishingScheduleConfig
    job_id = "publishing-schedule"

    def __init__(self, settings: Settings, portfolio_store, run_store) -> None:
        super().__init__(settings.publish_state_dir)
        self.settings = settings
        self.portfolio_store = portfolio_store
        self.run_store = run_store

    def _default_config(self) -> PublishingScheduleConfig:
        return PublishingScheduleConfig(enabled=self.settings.publishing_schedule_enabled)

    def _facts(self):
        s = self.settings
        if not s.postgres_dsn:
            return lambda _a: [], lambda _a: []
        store = PublishStore(s.postgres_dsn)
        return lambda a: facts_as_of(store, a), lambda a: events_since(store, a)

    def _reground(self, today: date) -> tuple[str, str]:
        from arp.ingestion.indexing_config import IndexingConfig
        from arp.retrieval.content_store_factory import content_store_for
        from arp.storage.document_blob_store import blob_store_for

        s = self.settings
        facts = self._facts()[0](ts_now())
        rows = reground_sample(
            facts, n=s.reground_sample_size, day=today.isoformat(),
            blob_store=blob_store_for(IndexingConfig.from_settings(s)), content_store=content_store_for(s),
            fuzzy_threshold=s.grounding_fuzzy_threshold, log_path=s.publish_state_dir / "reground.jsonl",
        )
        bad = [r["fact_id"] for r in rows if r["result"] != "ok"]
        if bad:
            return "drift", f"{len(bad)} of {len(rows)} not ok: {', '.join(bad[:5])}"
        return "ok", f"{len(rows)} sampled, 0 not ok"

    def _pull(self, today: date) -> tuple[str, str]:
        from arp.snapshots.client import SnapshotClient
        from arp.storage.identifier_map import IdentifierMapStore

        s = self.settings
        out = pull_due(
            self.portfolio_store, settings=s, client=SnapshotClient(s.holdings_api_url, s.holdings_api_token),
            today=today, idmap=IdentifierMapStore(s.identifier_map_path),
        )
        failed = [r for r in out if r["status"] == "failed"]
        return ("failed" if failed else "ok"), f"{len(out)} pulled, {len(failed)} failed"

    def _snapshot(self, today: date) -> tuple[str, str]:
        facts, _ = self._facts()
        try:
            m = build_snapshot(previous_month_end(today), root=self.settings.snapshot_store_dir,
                               portfolio_store=self.portfolio_store, facts_as_of=facts)
        except (SnapshotFrozen, ConcurrentPublish):
            return "skipped", "another run froze this month"
        except SnapshotSettling as exc:
            return "skipped", f"{exc}; retried next tick"
        return "ok", m.snapshot_id

    def _corrections(self, months: list[str]) -> tuple[str, str]:
        facts, events = self._facts()
        built, failed = [], []
        # ponytail: the last 24 frozen months only; older snapshots stop receiving corrections
        for month in reversed(months[-24:]):
            try:
                m = build_correction(month, root=self.settings.snapshot_store_dir,
                                     portfolio_store=self.portfolio_store, facts_as_of=facts, events_since=events)
            except (SnapshotFrozen, ConcurrentPublish):
                continue  # another run froze this revision
            except Exception as exc:  # noqa: BLE001 - one month failing never stops the others
                logger.exception("Correction of %s failed", month)
                failed.append(f"{month}: {str(exc)[:200]}")
                continue
            if m:
                built.append(m.snapshot_id)
        detail = f"built {', '.join(built) or 'nothing'}" + (f"; failed {'; '.join(failed)}" if failed else "")
        return ("failed" if failed else "ok"), detail

    async def _run(self, config: PublishingScheduleConfig) -> None:
        today = _today()
        root = self.settings.snapshot_store_dir
        frozen = [m["month"] for m in list_months(root) if m["status"] == "frozen"]
        latest = frozen[-1] if frozen else None
        due = due_jobs(today, config, settings=self.settings, latest_frozen_month=latest,
                       holders=self.portfolio_store.list_holders())
        jobs = {
            "reground": lambda: self._reground(today),
            "pull": lambda: self._pull(today),
            "snapshot": lambda: self._snapshot(today),
            "corrections": lambda: self._corrections(frozen),
        }
        try:  # every tick; a no-op unless the parser version changed (E51)
            report = await asyncio.to_thread(
                reground_if_parser_changed, self.run_store, settings=self.settings
            )
            if report is not None:
                config.last_results["parser_reground"] = {"status": "ok", "detail": str(report)}
        except Exception as exc:  # noqa: BLE001 - never stops the other jobs
            logger.exception("Parser re-ground failed")
            config.last_results["parser_reground"] = {"status": "failed", "detail": str(exc)[:500]}
        for job in due:
            try:
                status, detail = await asyncio.to_thread(jobs[job])
            except Exception as exc:  # noqa: BLE001 - one failing job never stops the others
                logger.exception("Publishing job %s failed", job)
                status, detail = "failed", str(exc)[:500]
            config.last_results[job] = {"status": status, "detail": detail}
            if job == "reground" and status in ("ok", "drift"):
                config.last_reground_day = today.isoformat()
        config.last_run_at = ts_now()
