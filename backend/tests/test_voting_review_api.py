from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.routers import voting as voting_router
from arp.storage.run_store import RunStore


@pytest.fixture
def client(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    app = FastAPI()
    app.include_router(voting_router.router)
    app.dependency_overrides[get_run_store] = lambda: run_store
    with TestClient(app) as c:
        yield c


def test_co_sign_must_come_from_a_second_person(client):
    """An engagement-alignment flag needs two people. The reviewer signing
    twice under different capitalisation is still one person."""
    body = {"item_key": "SHEL:1", "decision": "approve", "reviewer": "A. Novak", "co_signed_by": " a. novak "}
    response = client.post("/api/voting/runs/r1/review", json=body)
    assert response.status_code == 400
    assert "second person" in response.json()["detail"]
