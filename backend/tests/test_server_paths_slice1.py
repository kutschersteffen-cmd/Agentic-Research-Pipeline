"""server-paths-upload-limits slice 1: a request's `universe_path` names a saved universe only
(AC-7, AC-12, AC-25, AC-66), and the path helper behind it."""
from __future__ import annotations

import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.main import app
from arp.api.routers import (
    discovery,
    emerging_themes,
    extraction,
    financials,
    identity,
    taxonomies,
    tnfd,
    voting,
    xbrl,
)
from arp.config import Settings
from arp.discovery.scheduler import DiscoveryScheduler
from arp.emerging_themes.scheduler import EmergingThemesScheduler
from arp.storage.run_store import RunStore
from arp.storage.safe_path import file_inside
from tests.conftest import PRINCIPAL

SAVED_ONLY = {"detail": "Universe file must be a saved universe."}
UNIVERSE = "company_id,name\nc1,Acme\n"

ROUTES = [  # (route, body) as in the spec's table, routes 1 to 12
    ("/api/themes/runs", {"taxonomy_id": "none"}),
    ("/api/voting/runs", {}),
    ("/api/tnfd/runs", {"as_of": "FY2025"}),
    ("/api/discovery/runs", {}),
    ("/api/emerging-themes/runs", {}),
    ("/api/extraction/runs", {"datapoint_schema": {"name": "x"}}),
    ("/api/extraction/start", {"profile": "tnfd", "as_of": "FY2025"}),
    ("/api/identity/runs", {}),
    ("/api/financials/runs", {}),
    ("/api/taxonomies", {"name": "x"}),
    ("/api/xbrl/runs", {}),
    ("/api/documents/readiness", {}),
]


@pytest.fixture
def env(pg, tmp_path, monkeypatch):
    for name, sub in [("RUNS_DIR", "runs"), ("DOCUMENTS_DIR", "docs"), ("XBRL_DIR", "xbrl"),
                      ("DISCOVERY_STATE_DIR", "disc"), ("EMERGING_THEMES_STATE_DIR", "et")]:
        monkeypatch.setenv(f"ARP_{name}", str(tmp_path / sub))
    from arp.config import get_settings

    get_settings.cache_clear()
    udir = tmp_path / "runs" / "_universes"
    udir.mkdir(parents=True)
    u = udir / "u.csv"
    u.write_text(UNIVERSE)
    outside = tmp_path / "outside.csv"
    outside.write_text(UNIVERSE)

    recorded: list[str] = []

    def record(*args, **kwargs):
        recorded.append("x")
        raise HTTPException(409, "recorded")

    for mod in (voting, tnfd, extraction, identity, financials):
        monkeypatch.setattr(mod, "schedule_llm_run", record)
    monkeypatch.setattr(discovery, "create_discovery_run", record)
    monkeypatch.setattr(emerging_themes, "create_emerging_themes_run", record)
    monkeypatch.setattr(taxonomies, "get_llm_client", record)
    monkeypatch.setattr(xbrl, "create_xbrl_run", record)

    rs = RunStore(pg, tmp_path / "runs")
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    app.dependency_overrides[deps.get_run_store] = lambda: rs
    for dep in (deps.get_registry, deps.get_decision_store, deps.get_xbrl_source, deps.get_edgar_source,
                deps.get_web_search_client, deps.get_llm_client, deps.get_topic_store, deps.get_engagement_store):
        app.dependency_overrides[dep] = lambda: None
    yield TestClient(app, raise_server_exceptions=False), u, outside, recorded
    app.dependency_overrides.clear()


def test_ac7_a_symlink_leaving_the_universes_folder_is_refused(env):
    client, u, outside, recorded = env
    link = u.parent / "link.csv"
    os.symlink(outside, link)
    for route, body in ROUTES:
        r = client.post(route, json={**body, "universe_path": str(link)})
        assert (route, r.status_code, r.json()) == (route, 400, SAVED_ONLY)
    assert recorded == []


def test_ac12_a_saved_universe_still_starts_each_run(env):
    client, u, _outside, recorded = env
    for route, body in ROUTES[:11]:
        r = client.post(route, json={**body, "universe_path": str(u)})
        assert r.status_code < 500, (route, r.status_code, r.text)
        assert r.json() != SAVED_ONLY, route
    # route 1 stops at the unknown taxonomy after the universe step; the other ten reach the recorder
    assert len(recorded) == 10


def _put(router, scheduler_dep, scheduler, settings, path):
    from fastapi import FastAPI

    a = FastAPI()
    a.include_router(router)
    a.dependency_overrides[scheduler_dep] = lambda: scheduler
    a.dependency_overrides[deps.settings_dep] = lambda: settings
    client = TestClient(a)
    current = client.get(path).json()
    return client.put(path, json={**current, "enabled": not current["enabled"]})


def test_ac25_an_operator_set_emerging_themes_path_still_saves(tmp_path):
    outside = tmp_path / "outside.csv"
    outside.write_text(UNIVERSE)
    settings = Settings(runs_dir=tmp_path / "runs", emerging_themes_state_dir=tmp_path / "et",
                        emerging_themes_schedule_universe_path=outside)
    scheduler = EmergingThemesScheduler(settings, None, None, llm_factory=lambda: None)
    r = _put(emerging_themes.router, deps.get_emerging_themes_scheduler, scheduler, settings, "/api/emerging-themes/schedule")
    assert r.status_code == 200
    assert r.json()["universe_path"] == str(outside)


def test_ac66_an_operator_set_discovery_path_still_saves(tmp_path):
    outside = tmp_path / "outside.csv"
    outside.write_text(UNIVERSE)
    settings = Settings(runs_dir=tmp_path / "runs", discovery_state_dir=tmp_path / "disc",
                        discovery_schedule_universe_path=outside)
    scheduler = DiscoveryScheduler(settings, run_store=None)
    r = _put(discovery.router, deps.get_scheduler, scheduler, settings, "/api/discovery/schedule")
    assert r.status_code == 200
    assert r.json()["universe_path"] == str(outside)


def test_file_inside(tmp_path):
    folder = tmp_path / "f"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "a.csv").write_text("x")
    (tmp_path / "b.csv").write_text("x")
    loop = folder / "loop.csv"
    os.symlink(loop, loop)
    assert file_inside(folder / "sub" / "a.csv", folder) == (folder / "sub" / "a.csv").resolve()
    assert file_inside(folder / "sub" / ".." / "sub" / "a.csv", folder) is not None
    assert file_inside(folder / ".." / "b.csv", folder) is None
    assert file_inside(folder / "sub", folder) is None  # a folder
    assert file_inside(folder / "nope.csv", folder) is None
    assert file_inside("a\x00b", folder) is None
    assert file_inside(str(folder / ("x" * 5000)), folder) is None
    assert file_inside(loop, folder) is None
