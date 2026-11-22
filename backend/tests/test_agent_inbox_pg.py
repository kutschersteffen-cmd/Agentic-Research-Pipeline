"""The Agent screen's inbox route (spec agent-panel-code-mode, AC-30)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.routers import agent, plans
from arp.db.runs import RunStore
from arp.orchestration.plan_store import PlanStore
from arp.schemas.common import RunManifest

SCRIPT = 'u = universe_build(taxonomy_id="t", source="u.csv")\ne = extraction(universe_run_id=u.run_id, schema_id="s")\n'


@pytest.fixture
def store(pg):
    return PlanStore(pg)


@pytest.fixture
def run_store(pg, tmp_path):
    return RunStore(pg, tmp_path / "runs")


@pytest.fixture
def client(store, run_store):
    app = FastAPI()
    app.include_router(agent.router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    app.dependency_overrides[get_run_store] = lambda: run_store
    return TestClient(app)


def _awaiting_review(store, run_store, plan_id, seq, kind, run_id, run_type):
    run_store.save_manifest(RunManifest(run_id=run_id, run_type=run_type))
    store.record_call(plan_id, seq=seq, kind=kind, params={}, status="awaiting_review")
    store.update_call(plan_id, seq, run_id=run_id)
    store.set_status(plan_id, "awaiting_review")


def test_draft_then_step_review_oldest_first(client, store, run_store):  # AC-30
    b = store.create("plan b", SCRIPT)
    store.approve(b, "alice")
    store.record_call(b, seq=1, kind="universe_build", params={}, status="done")
    a = store.create("plan a", SCRIPT)  # created before B's call seq 2 starts
    _awaiting_review(store, run_store, b, 2, "extraction", "r_2", "extraction")

    rows = client.get("/api/agent/inbox").json()

    assert [{k: r[k] for k in ("kind", "plan_id", "seq", "exploration_id", "href")} for r in rows] == [
        {"kind": "plan_approval", "plan_id": a, "seq": None, "exploration_id": None, "href": f"#/agent/{a}"},
        {"kind": "step_review", "plan_id": b, "seq": 2, "exploration_id": None, "href": "#/review/extraction/r_2"},
    ]
    assert [r["title"] for r in rows] == ["plan a", "extraction step 2"]


def test_plan_approval_title_is_the_briefs_first_60_characters(client, store):
    store.create("x" * 80, SCRIPT)
    assert client.get("/api/agent/inbox").json()[0]["title"] == "x" * 60


def test_report_step_opens_the_agent_screen(client, store, run_store):
    p = store.create("report", 'r = report_render(source_ids=["e_1"])\n')
    _awaiting_review(store, run_store, p, 1, "report_render", "rep_1", "report")
    assert client.get("/api/agent/inbox").json() == [
        {"kind": "step_review", "plan_id": p, "seq": 1, "exploration_id": None, "title": "report_render step 1",
         "href": f"#/agent/{p}"}]


def test_nothing_waiting(client, store):
    store.approve(store.create("b", SCRIPT), "alice")
    assert client.get("/api/agent/inbox").json() == []
