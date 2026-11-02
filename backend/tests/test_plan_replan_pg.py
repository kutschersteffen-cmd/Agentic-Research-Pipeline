"""Research Orchestrator re-planning (spec research-orchestrator-replan AC-1..AC-16, AC-21)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.routers import plans
from arp.cli import plan as plan_cli
from arp.orchestration.plan_executor import run_plan
from arp.orchestration.plan_planner import PlanScript
from arp.orchestration.plan_store import PlanStore

CHAIN = """u = universe_build(taxonomy_id="t", source="u.csv")
e = extraction(universe_run_id=u.run_id, schema_id="green_capex")
d = decision_score(source_run_id=e.run_id)
"""
REMAINING = PlanScript(script="""e = extraction(universe_run_id=previous[0].run_id, schema_id="green_capex_v2")
d = decision_score(source_run_id=e.run_id)
""")
BAD = PlanScript(script="import os\n")
BAD2 = PlanScript(script="w = x * 2\n")


class Stubs:
    def __init__(self, fail_kind=None):
        self.fail_kind = fail_kind
        self.started: list[tuple[str, dict]] = []

    def all(self):
        def step(kind):
            def fn(**params):
                self.started.append((kind, params))
                if kind == self.fail_kind:
                    raise RuntimeError("schema green_capex has no field capex")
                n = len(self.started)
                return {"id": f"{kind}_{n}", "run_id": f"r_{n}", "companies": [{"id": "c1"}, {"id": "c2"}]}
            return fn
        return {k: step(k) for k in ("universe_build", "extraction", "decision_score")}


@pytest.fixture
def store(pg):
    return PlanStore(pg)


@pytest.fixture(autouse=True)
def _cli(monkeypatch):
    monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(plan_cli, "_context", lambda: "CONTEXT")


def _failed(store, cancelled=False) -> str:
    """seq 1 done (run id r_1), seq 2 failed; optionally a cancelled call at seq 3."""
    plan_id = store.create("grid storage capex", CHAIN)
    store.approve(plan_id, "alice")
    assert run_plan(plan_id, store, Stubs(fail_kind="extraction").all(), lambda c: True) == "failed"
    if cancelled:
        store.record_call(plan_id, seq=3, kind="decision_score", params={}, status="cancelled")
    return plan_id


def _replan(store, plan_id, fake_llm, monkeypatch, outputs=(REMAINING,)):
    llm = fake_llm({"PlanScript": list(outputs)})
    monkeypatch.setattr(plan_cli, "_llm", lambda: llm)
    return CliRunner().invoke(plan_cli.plan_app, ["replan", plan_id]), llm


def test_cli_replan_drafts_next_version(store, fake_llm, monkeypatch):  # AC-2, AC-3, AC-5, AC-6
    plan_id = _failed(store)
    old_error = store.get(plan_id)["error"]
    result, _ = _replan(store, plan_id, fake_llm, monkeypatch)
    assert result.exit_code == 0, result.stdout
    assert result.stdout.splitlines()[0] == "version 2"
    plan = store.get(plan_id)
    assert (plan["status"], plan["version"], plan["approved_by"]) == ("draft", 2, None)
    [entry] = plan["previous_scripts"]
    assert entry["version"] == 1 and entry["script"] == CHAIN and entry["error"] == old_error
    assert "schema green_capex has no field capex" in entry["error"]
    assert plan["dry_run"][0]["params"]["universe_run_id"] == "r_1"
    assert plan["dry_run"][0]["seq"] == 2


def test_replan_keeps_only_done_calls(store, fake_llm, monkeypatch):  # AC-4
    plan_id = _failed(store, cancelled=True)
    assert _replan(store, plan_id, fake_llm, monkeypatch)[0].exit_code == 0
    calls = store.calls(plan_id)
    assert [(c["seq"], c["status"], c["run_id"]) for c in calls] == [(1, "done", "r_1")]


def test_replanned_draft_is_not_runnable(store, fake_llm, monkeypatch):  # AC-7
    plan_id = _failed(store)
    _replan(store, plan_id, fake_llm, monkeypatch)
    monkeypatch.setattr(plan_cli, "_runtime", lambda: (Stubs().all(), lambda c: True))
    result = CliRunner().invoke(plan_cli.plan_app, ["run", plan_id])
    assert result.exit_code == 1 and "plan is not approved" in result.stdout
    assert len(store.calls(plan_id)) == 1


def test_run_replanned_plan(store, fake_llm, monkeypatch):  # AC-8, AC-9, AC-10
    plan_id = _failed(store)
    _replan(store, plan_id, fake_llm, monkeypatch)
    store.approve(plan_id, "alice")
    stubs = Stubs()
    monkeypatch.setattr(plan_cli, "_runtime", lambda: (stubs.all(), lambda c: True))
    result = CliRunner().invoke(plan_cli.plan_app, ["run", plan_id])
    assert result.exit_code == 0, result.stdout
    assert [c["seq"] for c in store.calls(plan_id)] == [1, 2, 3]
    assert [k for k, _ in stubs.started] == ["extraction", "decision_score"]
    assert stubs.started[0][1]["universe_run_id"] == "r_1"
    assert store.get(plan_id)["status"] == "done"


def test_resume_replanned_plan_keeps_previous(store, fake_llm, monkeypatch):
    plan_id = _failed(store)
    _replan(store, plan_id, fake_llm, monkeypatch)
    store.approve(plan_id, "alice")
    assert run_plan(plan_id, store, Stubs(fail_kind="decision_score").all(), lambda c: True) == "failed"
    stubs = Stubs()
    assert run_plan(plan_id, store, stubs.all(), lambda c: True) == "done"  # resume: seq 2 reused
    assert [k for k, _ in stubs.started] == ["decision_score"]


def test_replan_twice_keeps_all_done_calls(store, fake_llm, monkeypatch):
    plan_id = _failed(store)
    _replan(store, plan_id, fake_llm, monkeypatch)
    store.approve(plan_id, "alice")
    run_plan(plan_id, store, Stubs(fail_kind="decision_score").all(), lambda c: True)
    third = PlanScript(script="d = decision_score(source_run_id=previous[1].run_id)\n")
    result, _ = _replan(store, plan_id, fake_llm, monkeypatch, [third])
    assert result.stdout.splitlines()[0] == "version 3"
    plan = store.get(plan_id)
    assert plan["dry_run"][0]["seq"] == 3 and plan["dry_run"][0]["params"]["source_run_id"] == "r_1"
    assert [e["version"] for e in plan["previous_scripts"]] == [1, 2]


def test_cli_rejected_twice_leaves_plan(store, fake_llm, monkeypatch):  # AC-13
    plan_id = _failed(store)
    result, _ = _replan(store, plan_id, fake_llm, monkeypatch, [BAD, BAD2])
    assert result.exit_code == 1
    assert "line 1: arithmetic not allowed" in result.stdout


def test_prompt_holds_brief_script_error_and_kept_calls(store, fake_llm, monkeypatch):  # AC-14
    plan_id = _failed(store)
    _, llm = _replan(store, plan_id, fake_llm, monkeypatch)
    prompt = llm.prompts[0]
    assert "grid storage capex" in prompt and CHAIN in prompt and "CONTEXT" in prompt
    assert "schema green_capex has no field capex" in prompt
    assert "- previous[0]: step 1 universe_build {'source': 'u.csv', 'taxonomy_id': 't'} run_id=r_1 companies=2" in prompt
    assert "step 2" not in prompt.split("Finished steps")[1].split("Write a script")[0]


def test_failed_run_is_not_replanned_automatically(store, fake_llm, monkeypatch):  # AC-15
    llm = fake_llm({"PlanScript": [REMAINING]})
    monkeypatch.setattr(plan_cli, "_llm", lambda: llm)
    plan_id = _failed(store)
    plan = store.get(plan_id)
    assert (plan["status"], plan["version"], plan["previous_scripts"]) == ("failed", 1, [])
    assert llm.calls == []


def test_v1_run_unchanged(store):  # AC-21
    plan_id = store.create("b", CHAIN)
    store.approve(plan_id, "alice")
    stubs = Stubs()
    assert run_plan(plan_id, store, stubs.all(), lambda c: True) == "done"
    assert [(c["seq"], c["kind"], c["status"]) for c in store.calls(plan_id)] == [
        (1, "universe_build", "done"), (2, "extraction", "done"), (3, "decision_score", "done")]
    plan = store.get(plan_id)
    assert (plan["version"], plan["previous_scripts"]) == (1, [])


def test_check_rejects_assigning_previous(tmp_path):  # AC-16
    path = tmp_path / "s.py"
    path.write_text("previous = []\n")
    result = CliRunner().invoke(plan_cli.plan_app, ["check", str(path)])
    assert result.exit_code == 1
    assert "line 1: name previous cannot be assigned" in result.stdout


def test_seed_demo_replanned(pg, tmp_path, monkeypatch):  # AC-19 backend half
    from arp.config import get_settings

    monkeypatch.setenv("ARP_INDICES_DIR", str(tmp_path / "indices"))
    get_settings.cache_clear()
    result = CliRunner().invoke(plan_cli.plan_app, ["seed-demo", "--replanned"])
    assert result.exit_code == 0, result.stdout
    plan = PlanStore(pg).get(result.stdout.splitlines()[0])
    assert plan["version"] == 2 and plan["status"] == "draft"
    [entry] = plan["previous_scripts"]
    assert entry["version"] == 1 and entry["script"] and entry["error"]


@pytest.fixture
def client(store, fake_llm, monkeypatch):
    app = FastAPI()
    app.include_router(plans.router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="approver")
    monkeypatch.setattr(plans, "_context", lambda: "")

    def use(outputs):
        llm = fake_llm({"PlanScript": list(outputs)})
        monkeypatch.setattr("arp.api.deps.get_llm_client", lambda: llm)
        return llm
    with TestClient(app) as c:
        c.use_llm = use
        yield c


@pytest.mark.parametrize("status", ["draft", "approved", "running", "done", "cancelled"])
def test_api_only_failed_can_be_replanned(client, store, status):  # AC-1
    llm = client.use_llm([REMAINING])
    plan_id = store.create("b", CHAIN)
    store.set_status(plan_id, status)
    r = client.post(f"/api/plans/{plan_id}/replan")
    assert r.status_code == 409
    assert r.json() == {"detail": "only a failed plan can be re-planned"}
    assert llm.calls == []


def test_api_replan(client, store):
    client.use_llm([REMAINING])
    plan_id = _failed(store)
    r = client.post(f"/api/plans/{plan_id}/replan")
    assert r.status_code == 200, r.text
    assert (r.json()["version"], r.json()["status"]) == (2, "draft")
    assert store.get(plan_id)["previous_scripts"][0]["replanned_by"] == "alice"


def test_api_rejected_twice(client, store):  # AC-11, AC-12
    client.use_llm([BAD, BAD2])
    plan_id = _failed(store)
    calls_before = store.calls(plan_id)
    r = client.post(f"/api/plans/{plan_id}/replan")
    assert r.status_code == 422
    assert r.json() == {"detail": ["line 1: arithmetic not allowed"]}
    plan = store.get(plan_id)
    assert (plan["status"], plan["version"]) == ("failed", 1)
    assert store.calls(plan_id) == calls_before
