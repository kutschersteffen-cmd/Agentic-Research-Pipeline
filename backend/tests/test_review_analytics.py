from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.review import analytics as A
from arp.review.analytics import ReasonTotal, ReviewAnalyticsScheduler, monthly_totals, write_month
from arp.schemas.common import RunManifest
from arp.storage.run_store import RunStore


def _field(fid, period, model, doc_type):
    return {"field_id": fid, "period_end": period, "provenance": {"extractor_model": model},
            "citations": [{"doc_type": doc_type}, {"doc_type": "other"}]}


def _row(key, reason, at, user="u_a"):
    return {"item_key": key, "decision": "correct", "reason_code": reason, "user_id": user, "decided_at": at}


@pytest.fixture
def rs(tmp_path):
    rs = RunStore(tmp_path / "runs")
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    rs.save_manifest(RunManifest(run_id="r2", run_type="extraction"))
    rs.save_manifest(RunManifest(run_id="trial", run_type="extraction", params={"trial": True}))
    rs.append_jsonl(rs._results_path("r1"), {"issuer_key": "LEI:X", "fields": [
        _field("rev", "2024", "m1", "annual_report_10k"), _field("rev", "2023", "m1", "annual_report_10k"),
        _field("ebit", "2024", "m2", "press_release"),
    ]})
    rs.append_jsonl(rs._results_path("r2"), {"issuer_key": "Y", "fields": [_field("rev", "2024", "m2", "press_release")]})
    rs.append_jsonl(rs._results_path("trial"), {"issuer_key": "Z", "fields": [_field("rev", "2024", "m1", "press_release")]})
    d = rs.append_jsonl
    d(rs._review_decisions_path("r1"), _row("LEI:X:rev:2024", "wrong_period", "2026-09-03T10:00:00+00:00"))
    d(rs._review_decisions_path("r1"), _row("LEI:X:rev:2023", "wrong_period", "2026-09-04T10:00:00+00:00"))
    d(rs._review_decisions_path("r1"), _row("LEI:X:rev:2024", "other", "2026-09-30T23:59:59+00:00"))
    d(rs._review_decisions_path("r1"), _row("LEI:X:ebit:2024", "wrong_value", "2026-09-05T10:00:00+00:00"))
    d(rs._review_decisions_path("r1"), _row("LEI:X:ebit:2024", "wrong_value", "2026-09-10T10:00:00+00:00", user="u_b"))
    d(rs._review_decisions_path("r1"), _row("LEI:X:rev:2024", "wrong_value", "2026-10-01T00:00:00+00:00"))  # another month
    # system escalation rows are not reviewer decisions
    d(rs._review_decisions_path("r1"), _row("LEI:X:rev:2024", "span_moved", "2026-09-06T10:00:00+00:00", user="system"))
    d(rs._review_decisions_path("r2"), _row("Y:rev:2024", "wrong_value", "2026-09-07T10:00:00+00:00"))
    d(rs._review_decisions_path("r2"), _row("Y:rev:2024", "wrong_value", "2026-09-08T10:00:00+00:00"))
    d(rs._review_decisions_path("trial"), _row("Z:rev:2024", "wrong_value", "2026-09-09T10:00:00+00:00"))
    return rs


def test_totals_match_hand_count(rs):
    # 7 September reviewer decisions over 2 fields, 2 models, 2 doc types; the system row, the trial run
    # and the October decision are left out.
    assert monthly_totals(rs, "2026-09") == [
        ReasonTotal("ebit", "m2", "press_release", "wrong_value", 2),
        ReasonTotal("rev", "m1", "annual_report_10k", "other", 1),
        ReasonTotal("rev", "m1", "annual_report_10k", "wrong_period", 2),
        ReasonTotal("rev", "m2", "press_release", "wrong_value", 2),
    ]


def test_write_month_file(rs, tmp_path):
    s = Settings(anthropic_api_key="x", review_analytics_dir=tmp_path / "an")
    path = write_month(rs, s, "2026-09")
    assert path == tmp_path / "an" / "2026-09.json"
    rows = json.loads(path.read_text())
    assert len(rows) == 4 and rows[0] == {"field_id": "ebit", "model": "m2", "doc_type": "press_release", "reason": "wrong_value", "count": 2}


def test_scheduler_off_by_default(tmp_path):
    s = Settings(anthropic_api_key="x", review_analytics_state_dir=tmp_path / "st", review_analytics_dir=tmp_path / "an")
    sched = ReviewAnalyticsScheduler(s, RunStore(tmp_path / "runs"))
    assert sched.load_config().enabled is False and not sched._ready(sched.load_config())


def test_scheduler_writes_previous_month_once(rs, tmp_path, monkeypatch):
    s = Settings(anthropic_api_key="x", review_analytics_state_dir=tmp_path / "st", review_analytics_dir=tmp_path / "an")
    sched = ReviewAnalyticsScheduler(s, rs)
    config = sched.load_config()
    config.enabled = True
    days = iter([date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 31), date(2026, 11, 1)])
    monkeypatch.setattr(A, "_today", lambda: next(days))
    written = []
    for _ in range(5):
        before = set((tmp_path / "an").glob("*.json")) if (tmp_path / "an").exists() else set()
        asyncio.run(sched._run(config))
        written.append(sorted(p.name for p in set((tmp_path / "an").glob("*.json")) - before))
    # 09-30: previous month is August (written, empty); 10-01: September; later October days: nothing new
    assert written == [["2026-08.json"], ["2026-09.json"], [], [], ["2026-10.json"]]
    assert config.last_month == "2026-10"


def test_analytics_endpoint_requires_approver(rs, tmp_path):
    s = Settings(anthropic_api_key="x", review_analytics_dir=tmp_path / "an")
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[settings_dep] = lambda: s
    try:
        app.dependency_overrides[current_user] = lambda: Principal(user_id="u1", name="A", role="analyst")
        assert TestClient(app).get("/api/review/analytics?month=2026-09").status_code == 403
        app.dependency_overrides[current_user] = lambda: Principal(user_id="u2", name="B", role="approver")
        r = TestClient(app).get("/api/review/analytics?month=2026-09")
        assert r.status_code == 200 and len(r.json()["totals"]) == 4 and "u_a" not in r.text
        assert TestClient(app).get("/api/review/analytics?month=2026-9").status_code == 422
    finally:
        for dep in (get_run_store, settings_dep, current_user):
            app.dependency_overrides.pop(dep, None)
