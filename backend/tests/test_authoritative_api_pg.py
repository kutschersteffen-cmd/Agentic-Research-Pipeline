"""AC-8..AC-10, AC-12, AC-14, AC-15, AC-23, AC-24, AC-26, AC-27, AC-29b through the HTTP routes."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import authoritative_store_dep, get_decision_store, get_portfolio_store, get_run_store
from arp.api.routers import authoritative as authoritative_router
from arp.api.routers import decision as decision_router
from arp.schemas.decision import AuthoritativeOutput
from arp.storage.decision_store import DecisionStore
from tests.authoritative_fixtures import PICKS, add_fact, seed
from tests.test_authoritative_evaluate import F_VALUE, _graph
from tests.test_authoritative_store_pg import f_config

ANN = Principal(user_id="u_ann", name="Ann", role="analyst")
BOB = Principal(user_id="u_bob", name="Bob", role="approver")
SAMPLE = Path(__file__).resolve().parents[1] / "arp" / "decision" / "sample_data" / "example_transition_universe.csv"


@pytest.fixture
def env(pg, tmp_path):
    from arp.authoritative.store import AuthoritativeStore

    fx = seed(pg)
    store = DecisionStore(tmp_path / "frameworks")
    who = {"user": BOB}
    app = FastAPI()
    app.include_router(decision_router.router)
    app.include_router(authoritative_router.router)
    app.dependency_overrides[get_decision_store] = lambda: store
    app.dependency_overrides[get_run_store] = lambda: None
    app.dependency_overrides[get_portfolio_store] = lambda: None
    app.dependency_overrides[authoritative_store_dep] = lambda: AuthoritativeStore(pg)
    app.dependency_overrides[current_user] = lambda: who["user"]
    with TestClient(app) as c:
        yield c, store, fx, who


def _dataset(c, fx, as_of="2026-10-15", company_ids=None) -> str:
    body = {"source": "source_values", "company_ids": company_ids or [fx["A"], fx["B"]], "picks": PICKS, "as_of": as_of}
    r = c.post("/api/decision/datasets/from-source", json=body)
    assert r.status_code == 200, r.text
    return r.json()["dataset_id"]


def _save_f(store, dataset_id, **update):
    config = f_config().model_copy(update={"ratified": False, "dataset_id": dataset_id, **update})
    return store.save(config).framework_id


def _ratify(c, framework_id):
    return c.post(f"/api/decision/mechanisms/{framework_id}/ratify")


def _publish(c, framework_id, dataset_id):
    return c.post("/api/authoritative/publish", json={"framework_id": framework_id, "dataset_id": dataset_id})


def _values(c, **params):
    r = c.get("/api/authoritative/values", params={"framework_id": "fw_f", "output": "auth_scope1", **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_ac_8_analyst_cannot_ratify_authoritative(env):
    c, store, fx, who = env
    fid = _save_f(store, _dataset(c, fx))
    who["user"] = ANN
    assert _ratify(c, fid).status_code == 403


def test_ac_9_analyst_cannot_publish(env):
    c, store, fx, who = env
    ds = _dataset(c, fx)
    fid = _save_f(store, ds)
    assert _ratify(c, fid).status_code == 200
    who["user"] = ANN
    assert _publish(c, fid, ds).status_code == 403
    who["user"] = BOB
    assert _values(c) == []


def test_ac_10_scoring_framework_unchanged_for_analyst(env, tmp_path):
    c, _, _, who = env
    rows = list(csv.reader(SAMPLE.open()))
    path = tmp_path / "ids.csv"
    with path.open("w", newline="") as fh:
        csv.writer(fh).writerows([["Company_Id", *rows[0]]] + [[f"X{i}", *r] for i, r in enumerate(rows[1:])])
    who["user"] = ANN
    with path.open("rb") as fh:
        ds = c.post("/api/decision/datasets", files={"file": (path.name, fh, "text/csv")}).json()["dataset_id"]
    fid = c.post("/api/decision/mechanisms/derive", json={"dataset_id": ds, "name": "Climate", "save": True}).json()["config"]["framework_id"]
    assert _ratify(c, fid).status_code == 200
    assert c.post("/api/decision/publish", json={"dataset_id": ds, "framework_id": fid}).status_code == 200


def test_ac_12_ratify_refuses_missing_output(env):
    c, store, fx, _ = env
    outputs = [AuthoritativeOutput(column="auth_scope1", name="S1"), AuthoritativeOutput(column="auth_scope2", name="S2")]
    fid = _save_f(store, _dataset(c, fx), outputs=outputs)
    r = _ratify(c, fid)
    assert r.status_code == 422
    assert "auth_scope2" in r.json()["detail"]


def test_ac_29b_ratify_refuses_output_named_like_an_input(env):
    c, store, fx, _ = env
    fid = _save_f(store, _dataset(c, fx), rule_graph=_graph(scope1_tco2e="0"),
                  outputs=[AuthoritativeOutput(column="scope1_tco2e", name="S1")])
    r = _ratify(c, fid)
    assert r.status_code == 422
    assert "scope1_tco2e" in r.json()["detail"]


def test_ratify_needs_a_dataset_id(env):
    c, store, _, _ = env
    fid = _save_f(store, None)
    r = _ratify(c, fid)
    assert r.status_code == 422
    assert r.json()["detail"] == "An authoritative framework needs a dataset_id"


def test_publish_needs_ratified_version(env):
    c, store, fx, _ = env
    ds = _dataset(c, fx)
    assert _publish(c, _save_f(store, ds), ds).status_code == 422


def _published(env):
    c, store, fx, _ = env
    ds = _dataset(c, fx)
    fid = _save_f(store, ds)
    assert _ratify(c, fid).status_code == 200
    r = _publish(c, fid, ds)
    assert r.status_code == 200, r.text
    return r.json()["snapshot_id"]


def test_ac_14_15_value_with_derivation(env):
    c, _, fx, _ = env
    snapshot = _published(env)
    [a] = _values(c, company_id=fx["A"])
    got = c.get(f"/api/authoritative/values/{a['id']}").json()
    ext = got["derivation"]["inputs"]["scope1_tco2e"]
    assert (ext["value"], ext["status"], ext["source"], ext["period_end"]) == (90, "approved", "extraction", "2025-12-31")
    assert ext["observation_id"] == fx["a_ext"]
    assert any(n["output"].get("auth_scope1") == 90 and F_VALUE in n["expressions"] for n in got["derivation"]["trace"])
    assert got["framework_version"] == 1
    assert got["dataset_as_of"] == "2026-10-15"
    assert got["snapshot_id"] == snapshot
    assert c.get("/api/authoritative/values/999999").status_code == 404


def test_ac_23_older_dataset_is_409(env):
    c, _, fx, _ = env
    _published(env)
    newer = _dataset(c, fx, as_of="2026-10-20")
    assert _publish(c, "fw_f", newer).status_code == 200
    older = _dataset(c, fx, as_of="2026-10-17")
    assert _publish(c, "fw_f", older).status_code == 409


def test_ac_24_26_27_reads_as_of(env, pg):
    from arp.db.session import transaction

    c, store, fx, _ = env
    _published(env)
    with transaction(pg) as s:
        add_fact(s, fx["A"], "scope1_tco2e", 95, "2025-12-31", valid_from="2026-10-16", status="edited")
    assert [v["value"] for v in _values(c, company_id=fx["A"])] == [90]  # AC-24: no republish, no change

    v2 = f_config(version=2, statuses=("approved", "edited")).model_copy(update={"dataset_id": None})
    store.save(v2)
    store.ratify("fw_f", 2, ratified_by="Bob")
    assert _publish(c, "fw_f", _dataset(c, fx, as_of="2026-10-25")).status_code == 200
    [now] = _values(c, company_id=fx["A"])
    assert now["value"] == 95
    just_before = (datetime.fromisoformat(now["valid_from"]) - timedelta(microseconds=1)).isoformat()
    assert [v["value"] for v in _values(c, company_id=fx["A"], as_of=just_before)] == [90]  # AC-26
    assert _values(c, company_id=fx["A"], as_of="2026-01-01") == []  # AC-27


def test_review_decision_publish_refuses_authoritative_framework(env):
    c, store, fx, who = env
    ds = _dataset(c, fx)
    fid = _save_f(store, ds)
    assert _ratify(c, fid).status_code == 200
    who["user"] = ANN
    r = c.post("/api/decision/publish", json={"dataset_id": ds, "framework_id": fid})
    assert r.status_code == 422
    assert "/api/authoritative/publish" in r.json()["detail"]


def test_review_publish_checks_outputs_on_the_published_dataset(env):
    c, store, fx, _ = env
    fid = _save_f(store, _dataset(c, fx))
    assert _ratify(c, fid).status_code == 200
    only_provider = c.post("/api/decision/datasets/from-source", json={
        "source": "source_values", "company_ids": [fx["A"]], "picks": [{"field_id": "prov:esg_demo:scope1", "alias": "scope1_tco2e"}],
        "as_of": "2026-10-15"}).json()["dataset_id"]
    r = _publish(c, fid, only_provider)  # lacks scope1_tco2e__status, so F's rule cannot produce its output
    assert r.status_code == 422
    assert "auth_scope1" in r.json()["detail"]
