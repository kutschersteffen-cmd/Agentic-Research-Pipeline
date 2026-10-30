"""Score lineage AC-14..AC-20, AC-27, AC-28: the published-decision lineage, its API and its exports."""

from __future__ import annotations

import csv
import io
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import current_user
from arp.api.deps import authoritative_store_dep, get_decision_store, get_portfolio_store, get_run_store
from arp.api.routers import decision as decision_router
from arp.storage.decision_store import DecisionStore
from tests.conftest import PRINCIPAL
from tests.score_lineage_fixtures import F, seed
from tests.test_score_lineage_engine import s_config

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
HEADER = ("entity_id,name,status,score,tier,rank,reasons,criterion,contribution,imputed,missing_reason,value_id,value,"
          "value_status,value_reason,input,input_value,observation_id,source,provider,period_end,published_fact_id,"
          "doc_id,page,quote")


@pytest.fixture
def env(pg, tmp_path):
    from arp.authoritative.store import AuthoritativeStore

    fx = seed(pg)
    store = DecisionStore(tmp_path / "frameworks")
    app = FastAPI()
    app.include_router(decision_router.router)
    app.dependency_overrides[get_decision_store] = lambda: store
    app.dependency_overrides[get_run_store] = lambda: None
    app.dependency_overrides[get_portfolio_store] = lambda: None
    app.dependency_overrides[authoritative_store_dep] = lambda: AuthoritativeStore(pg)
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        ds = c.post("/api/decision/datasets/from-source", json={"source": "authoritative", "framework_id": F})
        assert ds.status_code == 200, ds.text
        config = store.save(s_config(label_column="Company"))
        store.ratify(config.framework_id, ratified_by="Bob")
        pub = c.post("/api/decision/publish", json={"dataset_id": ds.json()["dataset_id"], "framework_id": config.framework_id})
        assert pub.status_code == 200, pub.text
        yield c, store, fx, pub.json()["snapshot_id"]


def _lineage(c, snapshot, entity):
    r = c.get(f"/api/decision/published/{snapshot}/rows/{entity}/lineage")
    assert r.status_code == 200, r.text
    return r.json()


def _criterion(lineage, column):
    return next(k for k in lineage["criteria"] if k["column"] == column)


def test_ac_14_lineage_reaches_the_citation(env):
    c, _, fx, snap = env
    k = _criterion(_lineage(c, snap, fx["company"]["A"]), "auth_scope1")
    assert (k["link"], k["value_id"], k["value"]["value"]) == ("authoritative", fx["value_id"][("A", "auth_scope1")], 90)
    [inp] = k["inputs"]
    assert (inp["name"], inp["observation_id"], inp["link"]) == ("scope1_tco2e", fx["obs_a_scope1"], "observation")
    assert inp["citations"] == [{"doc_id": "d1", "page": 4, "quote": "Scope 1: 90 tCO2e", "grounded": True}]


def test_ac_15_lineage_keeps_the_value_scored_with(env, pg):
    from sqlalchemy import update

    from arp.authoritative.models import AuthoritativeValue
    from arp.db.session import transaction

    c, _, fx, snap = env
    old = fx["value_id"][("A", "auth_scope1")]
    with transaction(pg) as s:  # a later publish of F closed A's row and inserted 95
        s.execute(update(AuthoritativeValue).where(AuthoritativeValue.id == old).values(valid_to=AuthoritativeValue.valid_from))
    k = _criterion(_lineage(c, snap, fx["company"]["A"]), "auth_scope1")
    assert (k["value_id"], k["value"]["value"], k["value"]["superseded"]) == (old, 90, True)


def test_ac_16_uploaded_table_links_stop_at_the_cell(env, tmp_path):
    c, store, _, _ = env
    path = tmp_path / "u.csv"
    path.write_text("company_id,Company,auth_scope1,auth_capex\nX1,X one,3,4\nX2,X two,5,6\nX3,X three,7,8\n")
    with path.open("rb") as fh:
        ds = c.post("/api/decision/datasets", files={"file": ("u.csv", fh, "text/csv")}).json()["dataset_id"]
    config = store.save(s_config(label_column="Company", framework_id="fw_u"))
    store.ratify(config.framework_id, ratified_by="Bob")
    snap = c.post("/api/decision/publish", json={"dataset_id": ds, "framework_id": "fw_u"}).json()["snapshot_id"]
    assert {k["link"] for k in _lineage(c, snap, "X1")["criteria"]} == {"dataset_cell"}


def test_ac_17_rows_published_before_lineage(env):
    c, store, fx, snap = env
    old = store.get_published(snap)
    for row in old.rows:
        row.criteria = None
    path = store.frameworks_dir / "_published" / f"{snap}.json"
    path.write_text(old.model_dump_json(exclude={"rows": {"__all__": {"criteria"}}}))
    lin = _lineage(c, snap, fx["company"]["A"])
    assert lin["criteria"] == [{"link": "not_recorded"}]
    assert lin["status"] == "scored" and lin["score"] is not None


def test_ac_18_unknown_snapshot_or_entity_is_404(env):
    c, _, _, snap = env
    assert c.get("/api/decision/published/pub_nope/rows/A/lineage").status_code == 404
    assert c.get(f"/api/decision/published/{snap}/rows/nobody/lineage").status_code == 404


def test_ac_19_csv_export(env):
    c, _, _, snap = env
    r = c.get(f"/api/decision/published/{snap}/lineage.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0] == HEADER
    assert len(lines) - 1 == 8


def test_ac_20_json_export_matches_the_row_lineage(env):
    c, _, fx, snap = env
    body = c.get(f"/api/decision/published/{snap}/lineage.json").json()
    assert len(body) == 4
    for row in body:
        assert row == _lineage(c, snap, row["entity_id"])


def test_ac_27_unresolvable_value_id_is_shown_as_missing(env, pg):
    from sqlalchemy import delete

    from arp.authoritative.models import AuthoritativeValue
    from arp.db.session import transaction

    c, _, fx, snap = env
    gone = fx["value_id"][("A", "auth_scope1")]
    with transaction(pg) as s:
        s.execute(delete(AuthoritativeValue).where(AuthoritativeValue.id == gone))
    k = _criterion(_lineage(c, snap, fx["company"]["A"]), "auth_scope1")
    assert (k["link"], k["value_id"], k["value"]) == ("missing", gone, None)


def test_ac_28_input_without_observation(env, pg):
    from arp.authoritative.models import AuthoritativeValue
    from arp.db.session import transaction

    c, _, fx, snap = env
    with transaction(pg) as s:
        row = s.get(AuthoritativeValue, fx["value_id"][("A", "auth_scope1")])
        derivation = dict(row.derivation)
        derivation["inputs"] = {k: {**v, "observation_id": None} for k, v in derivation["inputs"].items()}
        row.derivation = derivation
    [inp] = _criterion(_lineage(c, snap, fx["company"]["A"]), "auth_scope1")["inputs"]
    assert (inp["link"], inp["observation_id"], inp["citations"]) == ("no_observation", None, [])


def test_lineage_does_not_need_the_framework_files(env):
    c, store, fx, snap = env
    for path in (store.frameworks_dir / "fw_s").glob("*"):
        path.unlink()
    assert c.get(f"/api/decision/published/{snap}/rows/{fx['company']['A']}/lineage").status_code == 200


def test_csv_quotes_round_trip(env, pg):
    from arp.db import models as m
    from arp.db.session import transaction

    c, _, fx, snap = env
    with transaction(pg) as s:
        cit = s.query(m.ValueCitation).filter_by(observation_id=fx["obs_a_scope1"]).one()
        cit.quote = 'Scope 1, "direct":\n90 tCO2e'
    text = c.get(f"/api/decision/published/{snap}/lineage.csv").text
    quotes = [r["quote"] for r in csv.DictReader(io.StringIO(text)) if r["quote"]]
    assert quotes == ['Scope 1, "direct":\n90 tCO2e']


def test_review_i1_lineage_export_uses_a_bounded_number_of_queries(env, pg):
    from sqlalchemy import event

    from arp.storage.postgres import get_engine

    c, _, _, snap = env
    count = {"n": 0}

    def tally(*_args, **_kw):
        count["n"] += 1

    engine = get_engine(pg)
    event.listen(engine, "before_cursor_execute", tally)
    try:
        assert c.get(f"/api/decision/published/{snap}/lineage.json").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", tally)
    assert count["n"] <= 3  # values, citations (and nothing per row or criterion)


def test_review_i2_published_list_leaves_out_criteria(env):
    c, _, _, _ = env
    rows = [r for p in c.get("/api/decision/published").json() for r in p["rows"]]
    assert rows and all(r.get("criteria") is None for r in rows)
