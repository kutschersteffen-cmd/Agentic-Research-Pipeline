from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.checks.effectiveness import CheckStat, effectiveness
from arp.orchestration.review_queue import append_decision
from arp.schemas.common import RunManifest
from arp.schemas.review import DecisionReason, ReviewDecision
from arp.storage.run_store import RunStore


def _field(fid, period, version, failed=(), passed=()):
    checks = [{"check_id": c, "layer": 2, "outcome": "fail", "severity": "warn", "detail": ""} for c in failed]
    checks += [{"check_id": c, "layer": 2, "outcome": "pass", "severity": "warn", "detail": ""} for c in passed]
    return {"field_id": fid, "period_end": period, "checks": checks, "provenance": {"field_version": version}}


def _decide(rs, run_id, item_key, kind):
    append_decision(rs, run_id, ReviewDecision(
        item_key=item_key, decision=kind, reason_code=DecisionReason.OTHER, reviewer="Secret Name", user_id="u_secret",
        role="analyst", corrected_value={"value": 1} if kind == "correct" else None, snapshot_id="s", step="first",
    ))


@pytest.fixture
def rs(tmp_path):
    rs = RunStore(tmp_path / "runs")
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    rs.save_manifest(RunManifest(run_id="trial", run_type="extraction", params={"trial": True}))
    rs.append_jsonl(rs.results_path("r1"), {"issuer_key": "I", "company_id": "C", "fields": [
        _field("rev", "2024", 1, failed=["sum", "range"]),  # correct
        _field("rev", "2023", 1, failed=["sum"]),  # reject
        _field("rev", "2022", 1, failed=["sum"]),  # approve
        _field("ebit", "2024", 2, failed=["range"], passed=["sum"]),  # approve
        _field("ebit", "2023", 2, failed=["range"]),  # undecided
        _field("cash", "2024", None, passed=["sum", "range"]),  # never fires
    ]})
    rs.append_jsonl(rs.results_path("trial"), {"issuer_key": "I", "company_id": "C", "fields": [
        _field("rev", "2024", 1, failed=["sum"]),
    ]})
    for run, key, kind in [("r1", "I:rev:2024", "correct"), ("r1", "I:rev:2023", "reject"), ("r1", "I:rev:2022", "approve"),
                           ("r1", "I:ebit:2024", "approve"), ("trial", "I:rev:2024", "correct")]:
        _decide(rs, run, key, kind)
    return rs


def test_report_matches_hand_count(rs):
    assert effectiveness(rs) == [
        CheckStat("range", "ebit", 2, fired=2, decided=1, hits=0, overturns=1, hit_rate=0.0, overturn_rate=1.0),
        CheckStat("range", "rev", 1, fired=1, decided=1, hits=1, overturns=0, hit_rate=1.0, overturn_rate=0.0),
        CheckStat("sum", "rev", 1, fired=3, decided=3, hits=2, overturns=1, hit_rate=2 / 3, overturn_rate=1 / 3),
    ]


def test_run_ids_limits_runs_and_trial_stays_excluded(rs):
    assert effectiveness(rs, run_ids=["nope"]) == []
    assert effectiveness(rs, run_ids=["trial"]) == []


def _client(rs, who):
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


@pytest.fixture(autouse=True)
def _drop_overrides():
    yield
    app.dependency_overrides.pop(get_run_store, None)
    app.dependency_overrides.pop(current_user, None)


def test_endpoint_requires_approver(rs):
    analyst = Principal(user_id="u_a", name="A", role="analyst")
    assert _client(rs, analyst).get("/api/review/check-effectiveness").status_code == 403
    approver = Principal(user_id="u_b", name="B", role="approver")
    r = _client(rs, approver).get("/api/review/check-effectiveness")
    assert r.status_code == 200
    assert r.json()["checks"][2]["hits"] == 2


def test_endpoint_has_no_user_ids(rs):
    approver = Principal(user_id="u_b", name="B", role="approver")
    body = _client(rs, approver).get("/api/review/check-effectiveness").text
    assert "u_secret" not in body and "Secret Name" not in body and "user_id" not in body
