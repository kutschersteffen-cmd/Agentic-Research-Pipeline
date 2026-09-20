"""Router-level tests for the index endpoints.

Kept separate from the engine suites because these exercise wiring --
request shapes, persistence, and the date arithmetic that turned out to be
running the level series backwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_index_store
from arp.api.routers import index as index_router
from arp.storage.index_store import IndexStore


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(index_router.router)
    app.dependency_overrides[get_index_store] = lambda: IndexStore(tmp_path)
    return TestClient(app)


def _run(client: TestClient, review_date: str = "2026-03-31") -> dict:
    spec = client.get("/api/index/presets/exclusion_only").json()
    response = client.post(
        "/api/index/run",
        json={"index_id": "demo_index", "review_date": review_date, "spec": spec, "persist": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_levels_run_forward_from_the_effective_date(client: TestClient):
    """The defect this replaces: dates were built from the review date's
    month, so the series covered the weeks *before* the rebalance -- the
    index shown doing things it had not yet been constituted to do."""
    review_date = "2026-03-31"
    _run(client, review_date)

    levels = client.get(f"/api/index/demo_index/levels/{review_date}?days=10").json()

    assert len(levels) == 10
    assert all(point["date"] > review_date for point in levels)
    assert [point["date"] for point in levels] == sorted(point["date"] for point in levels)
    assert levels[0]["date"] == "2026-04-01"  # and it crosses the month end correctly


def test_levels_start_from_the_review_and_every_constituent_is_priced(client: TestClient):
    review = _run(client)
    levels = client.get("/api/index/demo_index/levels/2026-03-31?days=5").json()
    assert all(point["constituents_priced"] == len(review["constituents"]) for point in levels)
    assert all(point["level"] > 0 for point in levels)


def test_levels_for_an_unknown_review_are_a_404(client: TestClient):
    assert client.get("/api/index/demo_index/levels/2099-01-01").status_code == 404


def test_a_persisted_review_round_trips_through_the_api(client: TestClient):
    _run(client)
    assert client.get("/api/index/demo_index/reviews").json()["review_dates"] == ["2026-03-31"]
    assert client.get("/api/index/demo_index/reviews/2026-03-31").status_code == 200
