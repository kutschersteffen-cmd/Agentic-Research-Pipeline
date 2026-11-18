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


def test_draft_accepts_existing_file_outside_saved(client, tmp_path):  # AC-118
    path = tmp_path / "elsewhere.csv"
    path.write_text("company_id,name\nA,Acme\n")
    client.use_llm([_script(str(path))])
    assert client.post("/api/plans", json={"brief": "b"}).status_code == 200


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

    async def fake_run(theme, companies, **kw):
        return JobManager(run_store).create_run("theme", {}, len(companies), companies=companies).run_id

    monkeypatch.setattr(ts, "released_run_schema", lambda *a: (NS(theme="t", taxonomy_id="tax", version=1), None))
    monkeypatch.setattr(research, "run_thematic_universe", fake_run)
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
