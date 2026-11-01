"""Research Orchestrator plan storage (plan task 5; spec AC-14..AC-17 at the store level)."""
from __future__ import annotations

import pytest

from arp.orchestration.plan_store import PlanNotFound, PlanStore

SCRIPT = 'u = universe_build(theme="grid storage")\n'
TWO = SCRIPT + 'universe_build(theme="batteries")\n'


@pytest.fixture
def store(pg):
    return PlanStore(pg)


def test_create_stores_draft_with_dry_run(store):
    plan_id = store.create("grid storage", SCRIPT)
    plan = store.get(plan_id)
    assert plan["status"] == "draft"
    assert plan["brief"] == "grid storage"
    assert [c["kind"] for c in plan["dry_run"]] == ["universe_build"]
    assert plan["approved_by"] is None and plan["approved_at"] is None


def test_approve_records_who_and_when(store):  # AC-14
    plan_id = store.create("b", SCRIPT)
    store.approve(plan_id, "alice")
    plan = store.get(plan_id)
    assert plan["status"] == "approved"
    assert plan["approved_by"] == "alice"
    assert plan["approved_at"] is not None


def test_edit_resets_approval_and_dry_run(store):  # AC-15, AC-16, AC-17
    plan_id = store.create("b", SCRIPT)
    store.approve(plan_id, "alice")
    store.update_script(plan_id, TWO)
    plan = store.get(plan_id)
    assert plan["status"] == "draft"
    assert plan["approved_by"] is None and plan["approved_at"] is None
    assert [c["kind"] for c in plan["dry_run"]] == ["universe_build", "universe_build"]


def test_rejected_script_is_not_stored(store):
    with pytest.raises(ValueError, match="import not allowed"):
        store.create("b", "import os\n")


def test_calls_are_recorded_and_updated(store):
    plan_id = store.create("b", SCRIPT)
    store.record_call(plan_id, seq=1, kind="universe_build", params={"theme": "x"}, status="running")
    store.update_call(plan_id, 1, status="done", run_id="r_1")
    [call] = store.calls(plan_id)
    assert (call["seq"], call["status"], call["run_id"]) == (1, "done", "r_1")
    assert call["started_at"] is not None


def test_status_and_missing_plan(store):
    plan_id = store.create("b", SCRIPT)
    store.set_status(plan_id, "running")
    assert store.get(plan_id)["status"] == "running"
    with pytest.raises(PlanNotFound):
        store.get("plan_missing")
