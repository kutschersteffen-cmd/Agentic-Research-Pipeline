"""Argus step 3: the flow keeps what to extract, the settings and the repeat choices (spec, Step 3: Schema)."""

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings

LIST = "name,company_id\nApple Inc,aapl\nMicrosoft Corporation,msft\n"


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)


@pytest.fixture
def client(settings):
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


@pytest.fixture
def fid(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", LIST)}).status_code == 200
    return fid


def test_schema_choice_and_settings_round_trip(client, fid):
    body = {"schema_choice": {"kind": "schema", "schema_id": "sch_x", "version": 2},
            "settings": {"mode": "max", "evidence_passages": 3, "batch": True,
                         "decision_framework_id": "fw1", "decision_framework_version": 4}}
    assert client.patch(f"/api/argus/flows/{fid}", json=body).status_code == 200
    flow = client.get(f"/api/argus/flows/{fid}").json()
    assert flow["schema_choice"] == {"kind": "schema", "schema_id": "sch_x", "version": 2, "profile": None}
    assert flow["settings"] == {"mode": "max", "evidence_passages": 3, "batch": True,
                                "decision_framework_id": "fw1", "decision_framework_version": 4}


def test_profile_choice_has_no_schema_id(client, fid):
    r = client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "profile", "profile": "tnfd", "schema_id": "sch_x"}})
    assert r.status_code == 200
    assert r.json()["schema_choice"] == {"kind": "profile", "schema_id": None, "version": None, "profile": "tnfd"}


def test_repeat_choice_only_for_flow_companies(client, fid):
    assert client.patch(f"/api/argus/flows/{fid}", json={"repeat": {"aapl": "skip"}}).json()["repeat"] == {"aapl": "skip"}
    assert client.patch(f"/api/argus/flows/{fid}", json={"repeat": {"nope": "run"}}).status_code == 400
