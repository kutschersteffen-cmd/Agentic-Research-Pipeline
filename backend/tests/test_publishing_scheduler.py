from __future__ import annotations

import asyncio
import json
from datetime import date
from types import SimpleNamespace

from arp.config import Settings
from arp.holdings.intake import ingest
from arp.holdings.validate import validate
from arp.publish import scheduler as S
from arp.publish.facts import Fact
from arp.publish.scheduler import PublishingScheduleConfig, PublishingScheduler, due_jobs, first_business_day_after
from arp.schemas.common import Citation
from arp.schemas.portfolio import HolderConfig
from arp.snapshots import build as B
from arp.snapshots.build import read_manifest
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore


def _settings(**kw):
    return SimpleNamespace(postgres_dsn=None, holdings_api_url=None, holdings_pull_day=2, snapshot_day=1, **kw)


def _api(as_of):
    return HolderConfig(holder_id="IX", kind="index", source="api", as_of=as_of)


def test_first_business_day_after_month_end():
    assert first_business_day_after(date(2026, 10, 31)) == date(2026, 11, 2)
    assert first_business_day_after(date(2026, 10, 31), 2) == date(2026, 11, 3)


def test_snapshot_due_once_per_month():
    c = PublishingScheduleConfig()
    kw = dict(settings=_settings(), holders=[])
    assert "snapshot" in due_jobs(date(2026, 11, 2), c, latest_frozen_month="2026-09", **kw)
    assert "snapshot" not in due_jobs(date(2026, 11, 2), c, latest_frozen_month="2026-10", **kw)
    assert "snapshot" not in due_jobs(date(2026, 11, 1), c, latest_frozen_month="2026-09", **kw)


def test_snapshot_waits_for_pull():
    c, s = PublishingScheduleConfig(), _settings()
    s.holdings_api_url = "https://up.example"
    due = lambda day, as_of: due_jobs(day, c, settings=s, latest_frozen_month="2026-09", holders=[_api(as_of)])  # noqa: E731
    assert "snapshot" not in due(date(2026, 11, 2), "2026-09-30")
    assert "snapshot" in due(date(2026, 11, 2), "2026-10-31")
    assert "snapshot" not in due(date(2026, 11, 1), "2026-10-31")


def test_pull_due_after_pull_day_until_success():
    c, s = PublishingScheduleConfig(), _settings()
    s.holdings_api_url = "https://up.example"
    due = lambda day, as_of: due_jobs(day, c, settings=s, latest_frozen_month=None, holders=[_api(as_of)])  # noqa: E731
    assert "pull" not in due(date(2026, 11, 1), "2026-09-30")
    assert "pull" in due(date(2026, 11, 3), "2026-09-30")
    assert "pull" not in due(date(2026, 11, 3), "2026-10-31")


def test_reground_once_per_day_and_needs_dsn():
    s = _settings()
    day = date(2026, 11, 3)
    kw = dict(latest_frozen_month=None, holders=[])
    assert "reground" not in due_jobs(day, PublishingScheduleConfig(), settings=s, **kw)
    s.postgres_dsn = "postgresql://x"
    assert "reground" in due_jobs(day, PublishingScheduleConfig(), settings=s, **kw)
    done = PublishingScheduleConfig(last_reground_day="2026-11-03")
    assert "reground" not in due_jobs(day, done, settings=s, **kw)


def _fact(fid, key):
    cit = Citation(doc_id="d", doc_type="sustainability_report", quote="q", grounded=True, content_key=key,
                   parser_version="p1", span_text="q", char_start=0, char_end=1, match_method="exact")
    return Fact(fact_id=fid, issuer_key="I", issuer_scheme="LEI", field_id="f", period_end="2024-12-31", value=1.0,
                state="approved", citation=cit, source_run_id="r", observed_at="2026-01-01T00:00:00.000000+00:00",
                item_key=fid, version=1, valid_from="2026-01-01T00:00:00.000000+00:00", release_id="rel")


def test_reground_sample_records_results(tmp_path):
    import hashlib

    orig = b"original"
    key = hashlib.sha256(orig).hexdigest()
    blobs = LocalBlobStore(tmp_path / "blobs")
    blobs.put(key, orig)
    log = tmp_path / "reground.jsonl"
    rows = S.reground_sample(
        [_fact("a", key), _fact("b", "0" * 64)], n=5, day="2026-11-03", blob_store=blobs,
        content_store=DocumentContentStore(tmp_path / "docs"), fuzzy_threshold=0.9, log_path=log,
    )
    assert len(rows) == 2 and len(log.read_text().splitlines()) == 2
    assert [r["result"] for r in rows if r["fact_id"] == "b"] == ["original_missing"]
    assert json.loads(log.read_text().splitlines()[0])["day"] == "2026-11-03"


def test_scheduler_run_builds_snapshot(tmp_path, monkeypatch):
    store, rs = PortfolioStore(tmp_path / "pf"), RunStore(tmp_path / "runs")
    raw = [{"_row": 2, "isin": "US0378331005", "weight": 100, "market_value": 600, "currency": "EUR"}]
    v = validate(raw, kind="index", as_of="2026-10-31", today=date(2026, 11, 2))
    ingest(store, v, kind="index", holder_id="IX1", as_of="2026-10-31", source="file", source_ref="f.csv",
           principal=None, override_reason=None, run_store=rs, idmap=IdentifierMapStore(tmp_path / "idmap.jsonl"))
    settings = Settings(postgres_dsn=None, holdings_api_url=None, snapshot_store_dir=tmp_path / "snaps",
                        publish_state_dir=tmp_path / "state")
    monkeypatch.setattr(S, "_today", lambda: date(2026, 11, 2))
    monkeypatch.setattr(B, "ts_now", lambda: "2026-11-02T08:00:00.000000+00:00")  # the build reads the real clock
    sched, config = PublishingScheduler(settings, store, rs), PublishingScheduleConfig(enabled=True)
    asyncio.run(sched._run(config))
    assert config.last_results["snapshot"]["status"] == "ok"
    assert read_manifest(tmp_path / "snaps", "2026-10", 1) is not None
    assert config.last_run_at
