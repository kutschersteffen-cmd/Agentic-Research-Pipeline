from __future__ import annotations

import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.routers import universe as universe_router
from arp.config import Settings
from arp.schemas.common import CompanyRef


@pytest.fixture
def env(tmp_path):
    settings = Settings(runs_dir=tmp_path / "runs")
    app = FastAPI()
    app.include_router(universe_router.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    return TestClient(app), settings


def upload(client, rows):
    return client.post("/api/universe/upload", files={"file": ("u.json", json.dumps(rows), "application/json")})


def co(cid, **kw):
    return {"company_id": cid, "name": cid, **kw}


def test_unknown_nace_rejected_and_nothing_stored(env):  # AC-13, AC-13c
    client, settings = env
    r = upload(client, [co("ok1", nace_code="07.29"), co("nb", nace_code="99.99")])
    assert r.status_code == 422
    assert r.json()["detail"] == "unknown NACE Rev. 2 code '99.99' for company 'nb'"
    assert list((settings.runs_dir / "_universes").iterdir()) == []


def test_unknown_nace_rev_21(env):  # AC-13b
    r = upload(env[0], [co("nb2", nace_code="99.99", nace_rev="2.1")])
    assert r.status_code == 422
    assert r.json()["detail"] == "unknown NACE Rev. 2.1 code '99.99' for company 'nb2'"


def test_class_suffix_cut(env):  # AC-14
    r = upload(env[0], [co("nk", nace_code="35.11.1")])
    assert r.status_code == 200
    assert r.json()["sample"][0]["nace_code"] == "35.11"
    assert r.json()["sample"][0]["nace_rev"] == "2"


def test_bad_gics(env):  # AC-15
    r = upload(env[0], [co("nq", gics_code="5510101")])
    assert r.status_code == 422
    assert r.json()["detail"] == "bad GICS code '5510101' for company 'nq'"


def test_all_codes_kept(env):  # AC-16
    r = upload(env[0], [co("ny", nace_code="07.29", isic_code="0729", gics_code="55101010")])
    s = r.json()["sample"][0]
    assert (r.status_code, s["nace_code"], s["nace_rev"], s["isic_code"], s["gics_code"]) == (
        200, "07.29", "2", "0729", "55101010")


def test_old_layout(env):  # AC-26
    r = upload(env[0], [co("a"), co("b"), co("c")])
    assert r.status_code == 200 and r.json()["company_count"] == 3
    for s in r.json()["sample"]:
        assert (s["nace_code"], s["nace_rev"], s["gics_code"]) == (None, "2", None)


def test_unpadded_code_normalised(env):
    r = upload(env[0], [co("a", nace_code=" 0729 ")])
    assert r.json()["sample"][0]["nace_code"] == "07.29"


def test_json_number_rejected_not_padded(env):
    r = upload(env[0], [co("n", nace_code=7.29)])
    assert r.status_code == 422
    assert r.json()["detail"] == "unknown NACE Rev. 2 code '7.29' for company 'n'"


def test_blank_codes_are_none(env):
    r = upload(env[0], [co("a", nace_code="  ", gics_code="")])
    s = r.json()["sample"][0]
    assert r.status_code == 200 and s["nace_code"] is None and s["gics_code"] is None


@pytest.mark.skipif(not os.environ.get("ARP_TEST_POSTGRES_DSN"), reason="ARP_TEST_POSTGRES_DSN not set")
def test_postgres_round_trip(pg, tmp_path):
    from arp.storage.portfolio_store import PortfolioStore
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    store = PostgresPortfolioStore(pg, PortfolioStore(tmp_path / "files"))
    store.save_company(CompanyRef(company_id="x", name="X", nace_code="07.29", nace_rev="2.1", gics_code="55101010"))
    got = store.get_company("x")
    assert (got.nace_code, got.nace_rev, got.gics_code) == ("07.29", "2.1", "55101010")


def test_duplicate_company_id_upload_is_422(env):
    client, _ = env
    r = upload(client, [co("A"), co("A")])
    assert (r.status_code, r.json()["detail"]) == (422, "duplicate company_id 'A'")
