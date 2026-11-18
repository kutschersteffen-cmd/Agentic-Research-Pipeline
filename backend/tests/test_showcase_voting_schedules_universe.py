"""Spec showcase-stewardship-fixes, PR B: override reason, schedule interval, universe upload errors."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.routers import calibration, taxonomy_researcher, universe
from arp.api.routers import voting as voting_router
from arp.config import Settings
from arp.schemas.calibration import CalibrationScheduleConfig
from arp.storage.run_store import RunStore
from tests.test_interval_scheduler import _Scheduler, _settings

# --- G8: an override needs a reason (AC-134..136) ---


@pytest.fixture
def voting(tmp_path, pg):
    run_store = RunStore(pg, tmp_path / "runs")
    app = FastAPI()
    app.include_router(voting_router.router)
    app.dependency_overrides[deps.get_run_store] = lambda: run_store
    with TestClient(app) as c:
        yield c, run_store


@pytest.mark.parametrize("comment", [None, "  "])
def test_override_without_reason_is_refused(voting, comment):  # AC-134
    client, run_store = voting
    body = {"item_key": "SHEL:1", "decision": "edit", "reviewer": "Ana", "vote": "against"}
    if comment is not None:
        body["comment"] = comment
    before = client.get("/api/voting/runs/r1/review-queue").json()
    res = client.post("/api/voting/runs/r1/review", json=body)
    assert (res.status_code, res.json()["detail"]) == (400, "An override needs a reason.")
    assert client.get("/api/voting/runs/r1/review-queue").json() == before


def test_override_with_reason_and_plain_approve_are_recorded(voting):  # AC-135, 136
    client, _ = voting
    edit = {"item_key": "SHEL:1", "decision": "edit", "reviewer": "Ana", "vote": "against", "comment": "Board lacks independence"}
    assert client.post("/api/voting/runs/r1/review", json=edit).json() == {"status": "recorded"}
    approve = {"item_key": "SHEL:2", "decision": "approve", "reviewer": "Ana"}
    assert client.post("/api/voting/runs/r1/review", json=approve).json() == {"status": "recorded"}


# --- G13: schedule interval of at least 1 hour (AC-156..161, 172) ---


def _schedule_client(tmp_path) -> TestClient:
    settings = Settings(calibration_agent_state_dir=tmp_path / "cal", taxonomy_researcher_state_dir=tmp_path / "tax")
    app = FastAPI()
    app.include_router(calibration.router)
    app.include_router(taxonomy_researcher.router)
    app.dependency_overrides[deps.get_calibration_scheduler] = lambda: _Scheduler(settings)
    tax = taxonomy_researcher.TaxonomyResearcherScheduler(settings, None, None, lambda: None, None)
    app.dependency_overrides[deps.get_taxonomy_researcher_scheduler] = lambda: tax
    return TestClient(app)


def test_calibration_interval_below_one_hour_is_refused(tmp_path):  # AC-156, 157, 158, 160
    client = _schedule_client(tmp_path)
    before = client.get("/api/calibration/schedule").json()
    for enabled in (True, False):
        res = client.put("/api/calibration/schedule", json={"enabled": enabled, "interval_hours": 0})
        assert (res.status_code, res.json()["detail"]) == (422, "Interval must be at least 1 hour.")
    assert client.get("/api/calibration/schedule").json() == before
    for hours in (1, 1.5):
        assert client.put("/api/calibration/schedule", json={"enabled": False, "interval_hours": hours}).status_code == 200
        assert client.get("/api/calibration/schedule").json()["interval_hours"] == hours


def test_taxonomy_researcher_interval_below_one_hour_is_refused(tmp_path):  # AC-159
    client = _schedule_client(tmp_path)
    for hours in (0, 0.5):
        res = client.put("/api/taxonomy-researcher/schedule", json={"enabled": True, "interval_hours": hours})
        assert res.status_code == 422


def test_stored_zero_interval_loads_and_runs_hourly(tmp_path, monkeypatch):  # AC-161, 172
    (tmp_path / "schedule.json").write_text(json.dumps({"enabled": True, "interval_hours": 0}))
    s = _Scheduler(_settings(tmp_path))
    app = FastAPI()
    app.include_router(calibration.router)
    app.dependency_overrides[deps.get_calibration_scheduler] = lambda: s
    res = TestClient(app).get("/api/calibration/schedule")
    assert (res.status_code, res.json()["interval_hours"]) == (200, 0)
    assert json.loads((tmp_path / "schedule.json").read_text())["interval_hours"] == 0

    sleeps, runs = [], []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 2:
            raise asyncio.CancelledError
        await real_sleep(0)

    async def run(config):
        runs.append(1)

    s._run = run
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(s._tick(s._interval(s.load_config())))
    assert sleeps[1] >= 3600  # no second run within an hour of the first
    assert CalibrationScheduleConfig.model_validate_json((tmp_path / "schedule.json").read_text()).interval_hours == 0


# --- G13: universe upload errors (AC-165..168) ---


def _upload(tmp_path, name: str, text: str):
    app = FastAPI()
    app.include_router(universe.router)
    app.dependency_overrides[deps.settings_dep] = lambda: Settings(runs_dir=tmp_path)
    return TestClient(app).post("/api/universe/upload", files={"file": (name, text.encode())})


@pytest.mark.parametrize(
    ("name", "text", "detail"),
    [
        ("u.csv", "name\nAcme\n", "Row 1: company_id is required."),
        ("u.csv", "company_id,name\nA,Acme\n,Beta\n,Gamma\n", "Row 2: company_id is required."),
    ],
)
def test_universe_names_the_first_bad_row(tmp_path, name, text, detail):  # AC-165, 166
    res = _upload(tmp_path, name, text)
    assert (res.status_code, res.json()["detail"]) == (422, detail)


def test_universe_bad_value_is_named_without_pydantic_text(tmp_path):  # AC-167
    res = _upload(tmp_path, "u.json", json.dumps([{"company_id": "A", "name": 5}]))
    detail = res.json()["detail"]
    assert res.status_code == 422 and detail.startswith("Row 1: name is not valid")
    assert not any(s in detail for s in ("pydantic", "input_value", "validation error"))


def test_good_universe_still_uploads(tmp_path):  # AC-168 (must not change)
    res = _upload(tmp_path, "u.csv", "company_id,name\nA,Acme\n")
    assert res.status_code == 200 and res.json()["company_count"] == 1 and "path" in res.json() and "sample" in res.json()
