"""Showcase fixes, R&D Lab: Research Plans name saved universes (spec showcase-themes-fixes, section 1)."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.routers import plans
from arp.config import get_settings
from arp.orchestration.job_manager import JobManager
from arp.orchestration.plan_executor import run_plan
from arp.orchestration.plan_planner import PlanScript, planner_context
from arp.orchestration.plan_steps import build_steps
from arp.orchestration.plan_store import PlanStore

M1_TAIL = ('is not a saved universe. Save one on the Thematic Universe page ("Save … as a universe") or upload one '
           "there, then name it in the brief. Saved universes: ")


def _script(source: str) -> PlanScript:
    return PlanScript(script=f'u = universe_build(taxonomy_id="t", source="{source}")\n')


@pytest.fixture
def runs_dir(pg, tmp_path, monkeypatch):
    d = tmp_path / "runs"
    monkeypatch.setenv("ARP_RUNS_DIR", str(d))
    get_settings.cache_clear()
    yield d
    get_settings.cache_clear()


@pytest.fixture
def store(pg):
    return PlanStore(pg)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    import arp.llm.factory as factory

    monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(factory, "build_llm_client", lambda *a, **k: None)
    monkeypatch.setattr(factory, "build_verifier_llm_client", lambda *a, **k: None)


@pytest.fixture
def client(store, runs_dir, fake_llm, monkeypatch):
    app = FastAPI()
    app.include_router(plans.router)
    app.include_router(plans.templates_router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="approver")
    monkeypatch.setattr("arp.api.deps.get_decision_store", lambda: type("D", (), {"list_frameworks": lambda s: []})())
    monkeypatch.setattr("arp.api.deps.get_index_store", lambda: type("I", (), {"list_calibrations": lambda s: []})())

    def use(outputs):
        llm = fake_llm({"PlanScript": list(outputs)})
        monkeypatch.setattr("arp.api.deps.get_llm_client", lambda: llm)
        return llm
    with TestClient(app) as c:
        c.use_llm = use
        yield c


def _save(runs_dir, name: str, companies: list[dict]) -> None:
    (runs_dir / "_universes").mkdir(parents=True, exist_ok=True)
    (runs_dir / "_universes" / name).write_text(json.dumps(companies))


def test_context_lists_saved_universes(client, runs_dir):  # AC-1 (unit side)
    _save(runs_dir, "acme_screen_1.json", [{"company_id": "c1", "name": "Acme"}])
    (runs_dir / "_universes" / ".hidden.json").write_text("[]")
    llm = client.use_llm([_script("acme_screen_1.json")])
    r = client.post("/api/plans", json={"brief": "b"})
    assert r.status_code == 200, r.text
    assert r.json()["dry_run"][0]["params"]["source"] == "acme_screen_1.json"  # AC-2
    prompt = llm.prompts[0]
    assert "Saved universes (universe_build source):\n- acme_screen_1.json" in prompt
    assert ".hidden.json" not in prompt


def test_context_none_saved():  # AC-103
    ctx = planner_context([], [], [], [])
    assert ctx.endswith("Saved universes (universe_build source):\n- none saved yet")


def test_draft_refuses_unknown_universe(client, store, runs_dir):  # AC-3..AC-7
    _save(runs_dir, "eu_listed_1.json", [{"company_id": "c1", "name": "Acme"}])
    names = "Nel, ITM Power, Plug Power, thyssenkrupp nucera"
    llm = client.use_llm([_script(names), _script(names)])
    before = len(store.list())
    r = client.post("/api/plans", json={"brief": "b"})
    assert r.status_code == 422
    assert r.json()["detail"] == f'"{names}" {M1_TAIL}eu_listed_1.json.'
    assert len(store.list()) == before
    assert f'"{names}" is not a saved universe.' in llm.prompts[1]  # the planner got its one retry


def test_draft_refuses_with_none_saved(client, runs_dir):  # AC-104
    client.use_llm([_script("EU"), _script("EU")])
    r = client.post("/api/plans", json={"brief": "b"})
    assert r.status_code == 422
    assert r.json()["detail"].startswith('"EU" is not a saved universe.')
    assert r.json()["detail"].endswith("Saved universes: none.")


def test_draft_refuses_existing_file_outside_saved(client, tmp_path):  # server-paths-upload-limits AC-32 (retires AC-118)
    path = tmp_path / "elsewhere.csv"
    path.write_text("company_id,name\nA,Acme\n")
    client.use_llm([_script(str(path)), _script(str(path))])
    r = client.post("/api/plans", json={"brief": "b"})
    assert r.status_code == 422
    assert "is not a saved universe" in r.json()["detail"]


def test_replan_refuses_unknown_universe(client, store, runs_dir):  # AC-11
    plan_id = store.create("b", 'u = universe_build(taxonomy_id="t", source="u.csv")\n')
    store.set_status(plan_id, "failed", error="boom")
    client.use_llm([_script("invented.csv"), _script("invented.csv")])
    r = client.post(f"/api/plans/{plan_id}/replan")
    assert r.status_code == 422
    assert any('"invented.csv" is not a saved universe.' in line for line in r.json()["detail"])


def _stub_theme_run(monkeypatch, run_store):
    from types import SimpleNamespace as NS

    import arp.research.pipeline as research
    import arp.research.taxonomy_schema as ts

    def fake_create(theme, companies, *a, **kw):
        return JobManager(run_store).create_run("theme", {}, len(companies), companies=companies).run_id

    async def fake_execute(run_id, *a, **kw):
        return run_id

    monkeypatch.setattr(ts, "released_run_schema", lambda *a: (NS(theme="t", taxonomy_id="tax", version=1), None))
    monkeypatch.setattr(research, "create_theme_run", fake_create)
    monkeypatch.setattr(research, "execute_theme_run", fake_execute)
    monkeypatch.setattr(research, "load_theme_run_matches", lambda rs, rid: [])
    monkeypatch.setattr("arp.research.indirect_exposure.factory.resolve_indirect_exposure_model", lambda *a, **k: None)
    monkeypatch.setattr("arp.api.deps.get_registry", lambda: None)


def test_universe_build_loads_a_saved_universe(runs_dir, run_store, monkeypatch):  # AC-8
    _save(runs_dir, "acme.json", [{"company_id": "a", "name": "Acme"}, {"company_id": "b", "name": "Beta"}])
    _stub_theme_run(monkeypatch, run_store)
    out = build_steps(get_settings(), run_store)["universe_build"](taxonomy_id="tax", source="acme.json")
    assert run_store.load_manifest(out["run_id"]).company_count == 2
    assert sorted(c.company_id for c in run_store.load_companies(out["run_id"])) == ["a", "b"]


def _run(store, run_store, source) -> dict:
    plan_id = store.create("b", f'u = universe_build(taxonomy_id="t", source="{source}")\n')
    store.approve(plan_id, "alice")
    run_plan(plan_id, store, build_steps(get_settings(), run_store), lambda c: True)
    return store.get(plan_id)


def test_missing_universe_fails_in_plain_words(store, runs_dir, run_store, monkeypatch):  # AC-9, AC-10
    _stub_theme_run(monkeypatch, run_store)
    plan = _run(store, run_store, "missing.csv")
    assert plan["status"] == "failed"
    assert plan["error"].startswith('step 1 universe_build failed: "missing.csv" is not a saved universe.')
    assert "Errno" not in plan["error"] and "Unsupported universe file type" not in plan["error"]


def test_saved_but_unreadable_universe_keeps_its_error(store, runs_dir, run_store, monkeypatch):  # AC-105
    _stub_theme_run(monkeypatch, run_store)
    (runs_dir / "_universes").mkdir(parents=True)
    (runs_dir / "_universes" / "x.xlsx").write_bytes(b"PK")
    plan = _run(store, run_store, "x.xlsx")
    assert 'Unsupported file type ".xlsx". Upload a .csv or .json file.' in plan["error"]
    assert "is not a saved universe" not in plan["error"]


# server-paths-upload-limits slice 2 (D1): a plan's universe `source` is a saved universe only, wherever the
# script comes in or runs.

def _outside(tmp_path, content: str = "company_id,name\nA,Acme\n", name: str = "outside.csv") -> str:
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def test_draft_accepts_a_saved_universe_by_name_or_path(client, runs_dir):  # AC-33
    _save(runs_dir, "eu.json", [{"company_id": "a", "name": "A"}])
    for source in ("eu.json", str(runs_dir / "_universes" / "eu.json")):
        client.use_llm([_script(source)])
        r = client.post("/api/plans", json={"brief": "b"})
        assert r.status_code == 200, (source, r.text)


def test_worker_refuses_a_source_outside_without_reading_it(store, runs_dir, run_store, tmp_path, monkeypatch):  # AC-34
    _stub_theme_run(monkeypatch, run_store)
    plan = _run(store, run_store, _outside(tmp_path, "not json", "bad.json"))
    assert plan["status"] == "failed"
    assert "is not a saved universe" in plan["error"]
    assert "not valid JSON" not in plan["error"]


def test_cli_draft_refuses_a_source_outside(store, runs_dir, tmp_path, fake_llm, monkeypatch):  # AC-35
    from typer.testing import CliRunner

    from arp.cli import plan as plan_cli

    source = _outside(tmp_path)
    monkeypatch.setattr(plan_cli, "_llm", lambda: fake_llm({"PlanScript": [_script(source), _script(source)]}))
    monkeypatch.setattr(plan_cli, "_context", lambda: "CTX")
    result = CliRunner().invoke(plan_cli.plan_app, ["draft", "b"])
    assert result.exit_code != 0
    assert "is not a saved universe" in result.stdout
    assert store.list() == []


def test_cli_replan_refuses_a_source_outside(store, runs_dir, tmp_path, fake_llm, monkeypatch):  # AC-58
    from typer.testing import CliRunner

    from arp.cli import plan as plan_cli

    plan_id = store.create("b", 'e = extraction(universe_run_id="r", schema_id="s")\n')
    store.set_status(plan_id, "failed", error="boom")
    source = _outside(tmp_path)
    monkeypatch.setattr(plan_cli, "_llm", lambda: fake_llm({"PlanScript": [_script(source), _script(source)]}))
    monkeypatch.setattr(plan_cli, "_context", lambda: "CTX")
    result = CliRunner().invoke(plan_cli.plan_app, ["replan", plan_id])
    assert result.exit_code != 0
    assert "is not a saved universe" in result.stdout
    assert store.get(plan_id)["status"] == "failed"


def test_edit_refuses_a_source_outside(client, store, runs_dir, tmp_path):  # AC-59
    _save(runs_dir, "u.csv", [])
    plan_id = store.create("b", 'u = universe_build(taxonomy_id="t", source="u.csv")\n')
    before = client.get(f"/api/plans/{plan_id}").json()
    r = client.put(f"/api/plans/{plan_id}", json={"script": _script(_outside(tmp_path)).script})
    assert r.status_code == 422
    assert "is not a saved universe" in r.json()["detail"]
    assert client.get(f"/api/plans/{plan_id}").json()["script"] == before["script"]


def test_instantiate_refuses_a_source_outside(client, store, runs_dir, tmp_path):  # AC-70
    _save(runs_dir, "u.csv", [])
    plan_id = store.create("b", 'u = universe_build(taxonomy_id="t", source="u.csv")\n')
    store.approve(plan_id, "alice")
    assert client.post(f"/api/plans/{plan_id}/template", json={"name": "tpl70"}).status_code == 200
    before = client.get("/api/plans").json()
    r = client.post("/api/plan-templates/tpl70/instantiate", json={"source": _outside(tmp_path)})
    assert r.status_code == 422
    assert "is not a saved universe" in r.json()["detail"]
    assert client.get("/api/plans").json() == before


def test_replan_and_agent_route_refuse_a_source_outside(client, store, runs_dir, pg, tmp_path, monkeypatch):  # AC-71
    from arp.agent.explorations import ExplorationStore
    from arp.api.routers import agent
    from tests.test_agent_exploration_plan_pg import _exploration

    source = _outside(tmp_path)
    plan_id = store.create("b", 'e = extraction(universe_run_id="r", schema_id="s")\n')
    store.set_status(plan_id, "failed", error="boom")
    client.use_llm([_script(source), _script(source)])
    r = client.post(f"/api/plans/{plan_id}/replan")
    assert r.status_code == 422
    assert "is not a saved universe" in r.json()["detail"][0]
    assert store.get(plan_id)["status"] == "failed"

    client.use_llm([_script(source), _script(source)])
    client.app.include_router(agent.router)
    client.app.dependency_overrides[agent.exploration_store] = lambda: ExplorationStore(pg)
    before = len(store.list())
    r = client.post(f"/api/agent/explorations/{_exploration(pg)}/plan", json={"brief": "b"})
    assert r.status_code == 422
    assert len(store.list()) == before
