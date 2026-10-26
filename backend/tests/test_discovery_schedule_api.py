"""The discovery schedule API keeps answering after its screen left the UI (spec: simplify navigation, AC-27)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.routers import discovery
from arp.config import Settings
from arp.discovery.scheduler import DiscoveryScheduler


def test_schedule_defaults_when_nothing_saved(tmp_path):
    settings = Settings(anthropic_api_key="unused", discovery_state_dir=tmp_path)
    app = FastAPI()
    app.include_router(discovery.router)
    app.dependency_overrides[deps.get_scheduler] = lambda: DiscoveryScheduler(settings, run_store=None)

    res = TestClient(app).get("/api/discovery/schedule")

    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    assert body["interval_hours"] == 24.0
    assert body["universe_path"] is None
