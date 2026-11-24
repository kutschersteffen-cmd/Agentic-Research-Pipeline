"""Plan templates: save, get, instantiate (spec agent-panel-code-mode AC-17 to AC-22c)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.routers import plans
from arp.orchestration.plan_store import PlanStore, with_source

SCRIPT = 'u = universe_build(taxonomy_id="t", source="<S>")\ne = extraction(universe_run_id=u.run_id, schema_id="s")\n'


@pytest.fixture
def store(pg):
    return PlanStore(pg)


@pytest.fixture
def saved_universes(pg, tmp_path, monkeypatch):
    """A plan's source must be a saved universe (spec server-paths-upload-limits D1)."""
    from arp.config import get_settings

    (tmp_path / "runs" / "_universes").mkdir(parents=True)
    for name in ("us_listed.csv", "x.csv"):
        (tmp_path / "runs" / "_universes" / name).write_text("company_id,name\nA,Acme\n")
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    get_settings.cache_clear()


@pytest.fixture
def client(store, saved_universes):
    app = FastAPI()
    app.include_router(plans.router)
    app.include_router(plans.templates_router)
    app.dependency_overrides[plans.plan_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="approver")
    with TestClient(app) as c:
        yield c


def _approved(store, script=SCRIPT) -> str:
    plan_id = store.create("b", script)
    store.approve(plan_id, "alice")
    return plan_id


def test_save_approved_plan(client, store):  # AC-17
    plan_id = _approved(store)
    res = client.post(f"/api/plans/{plan_id}/template", json={"name": "grid_ac17"})
    assert res.status_code == 200
    body = res.json()
    assert (body["name"], body["version"], body["source_plan_id"], body["created_by"]) == \
        ("grid_ac17", 1, plan_id, "alice")
    assert body["script"] == SCRIPT


def test_done_plan_can_be_saved(client, store):
    plan_id = store.create("b", SCRIPT)
    store.set_status(plan_id, "done")
    assert client.post(f"/api/plans/{plan_id}/template", json={"name": "t"}).status_code == 200


def test_second_save_is_version_2_and_first_unchanged(client, store):  # AC-18
    first = _approved(store)
    other = SCRIPT.replace('"s"', '"s2"')
    client.post(f"/api/plans/{first}/template", json={"name": "grid_ac18"})
    body = client.post(f"/api/plans/{_approved(store, other)}/template", json={"name": "grid_ac18"}).json()
    assert body["version"] == 2
    assert client.get("/api/plan-templates/grid_ac18", params={"version": 1}).json()["script"] == SCRIPT
    assert client.get("/api/plan-templates/grid_ac18").json()["script"] == other  # newest when omitted


def test_draft_plan_cannot_be_saved(client, store):  # AC-19
    plan_id = store.create("b", SCRIPT)
    res = client.post(f"/api/plans/{plan_id}/template", json={"name": "grid_ac19"})
    assert res.status_code == 409
    assert res.json() == {"detail": "only an approved or done plan can be saved as a template"}
    assert client.get("/api/plan-templates/grid_ac19").status_code == 404


def test_instantiate_makes_a_draft_with_the_new_source(client, store):  # AC-20, AC-21
    client.post(f"/api/plans/{_approved(store)}/template", json={"name": "grid_ac20"})
    res = client.post("/api/plan-templates/grid_ac20/instantiate", json={"source": "us_listed.csv"})
    assert res.status_code == 200
    plan = res.json()
    assert (plan["status"], plan["template_name"], plan["template_version"]) == ("draft", "grid_ac20", 1)
    assert plan["script"] == SCRIPT.replace('"<S>"', '"us_listed.csv"')
    assert plan["dry_run"][0]["params"]["source"] == "us_listed.csv"
    run = client.post(f"/api/plans/{plan['id']}/run")
    assert (run.status_code, run.json()) == (409, {"detail": "plan is not approved"})


def test_instantiate_given_version(client, store):
    client.post(f"/api/plans/{_approved(store)}/template", json={"name": "v"})
    client.post(f"/api/plans/{_approved(store)}/template", json={"name": "v"})
    body = client.post("/api/plan-templates/v/instantiate", json={"source": "x.csv", "version": 1}).json()
    assert body["template_version"] == 1


def test_template_without_universe_build(client, store):  # AC-22
    script = 'x = xbrl_facts(universe_run_id="r")\n'
    client.post(f"/api/plans/{_approved(store, script)}/template", json={"name": "nub"})
    res = client.post("/api/plan-templates/nub/instantiate", json={"source": "x.csv"})
    assert res.status_code == 422
    assert res.json() == {"detail": "template has no universe_build source to replace"}


def test_unknown_template(client):  # AC-22b
    res = client.post("/api/plan-templates/nope/instantiate", json={"source": "x.csv"})
    assert (res.status_code, res.json()) == (404, {"detail": "template not found"})
    assert client.get("/api/plan-templates/nope").json() == {"detail": "template not found"}


def test_unknown_version(client, store):
    client.post(f"/api/plans/{_approved(store)}/template", json={"name": "one"})
    res = client.post("/api/plan-templates/one/instantiate", json={"source": "x.csv", "version": 2})
    assert (res.status_code, res.json()) == (404, {"detail": "template not found"})
    assert client.get("/api/plan-templates/one", params={"version": 2}).status_code == 404


def test_source_not_a_literal(client, store):  # AC-22c
    script = 'name = "s.csv"\nu = universe_build(taxonomy_id="t", source=name)\n'
    client.post(f"/api/plans/{_approved(store, script)}/template", json={"name": "var"})
    res = client.post("/api/plan-templates/var/instantiate", json={"source": "x.csv"})
    assert (res.status_code, res.json()) == (422, {"detail": "template source is not a string literal"})


def test_with_source_replaces_every_call_and_nothing_else():
    script = ('a = universe_build(taxonomy_id="é", source="ü.csv")  # "ü.csv"\n'
              "b = universe_build(source='b.csv',\n    taxonomy_id=\"t\")\n")
    assert with_source(script, 'n"ew.csv') == (
        'a = universe_build(taxonomy_id="é", source="n\\"ew.csv")  # "ü.csv"\n'
        'b = universe_build(source="n\\"ew.csv",\n    taxonomy_id="t")\n')


def test_with_source_counts_a_lone_carriage_return_as_a_line_break():  # security review finding on PR #627
    script = ('a = 1\rb = 2\nu = universe_build(taxonomy_id="t", source="old.csv")\n'
              'e = extraction(schema_id="sch_one", universe_run_id=u.run_id)\n')
    assert with_source(script, "new.csv") == script.replace('"old.csv"', '"new.csv"')
