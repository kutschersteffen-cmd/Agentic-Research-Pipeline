"""Showcase fixes, R&D Lab: universe upload answers in plain words (spec showcase-themes-fixes, section 11)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.routers import universe as universe_router
from arp.config import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(runs_dir=tmp_path / "runs")
    app = FastAPI()
    app.include_router(universe_router.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    return TestClient(app)


def _upload(client, name: str, body: str):
    return client.post("/api/universe/upload", files={"file": (name, body, "text/plain")})


def test_regimes_column_is_split(client):  # AC-48
    r = _upload(client, "u.csv", "company_id,name,regimes\nA,Acme,\nB,Beta,CSRD; SFDR\n")
    assert r.status_code == 200, r.text
    assert [c["regimes"] for c in r.json()["sample"]] == [[], ["CSRD", "SFDR"]]


def test_json_regimes_list_is_kept(client):
    r = _upload(client, "u.json", '[{"company_id": "A", "name": "Acme", "regimes": ["CSRD"]}]')
    assert r.json()["sample"][0]["regimes"] == ["CSRD"]


def test_bad_row_named_in_plain_words(client):  # AC-49; text as showcase-stewardship-fixes AC-165 (spec question on #429)
    r = _upload(client, "u.csv", "company_id,name\nA,Acme\nB,\n")
    assert r.status_code == 422
    assert r.json()["detail"] == "Row 2: name is required."


def test_unsupported_suffix(client):  # AC-91
    r = _upload(client, "u.xlsx", "PK")
    assert r.status_code == 422
    assert r.json()["detail"] == 'Unsupported file type ".xlsx". Upload a .csv or .json file.'


def test_not_json(client):  # AC-92
    r = _upload(client, "u.json", "{not json")
    assert r.status_code == 422
    assert r.json()["detail"] == "The file is not valid JSON."
