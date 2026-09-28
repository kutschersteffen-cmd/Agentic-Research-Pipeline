"""The Decision Studio handoff: a ratified result is published once, then
read as company fields by stewardship coverage and index construction."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_decision_store, get_index_store, get_portfolio_store, get_run_store, settings_dep
from arp.api.routers import decision as decision_router
from arp.api.routers import index as index_router
from arp.config import Settings
from arp.stewardship.process import load_sample
from arp.stewardship.tiers import tier_contexts
from arp.storage.decision_store import DecisionStore
from arp.storage.index_store import IndexStore
from arp.storage.run_store import RunStore

SAMPLE = Path(__file__).resolve().parents[1] / "arp" / "decision" / "sample_data" / "example_transition_universe.csv"


@pytest.fixture
def client(tmp_path):
    settings = Settings(frameworks_dir=tmp_path / "frameworks", runs_dir=tmp_path / "runs")
    settings.ensure_dirs()
    store = DecisionStore(settings.frameworks_dir)
    app = FastAPI()
    app.include_router(decision_router.router)
    app.include_router(index_router.router)
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_decision_store] = lambda: store
    app.dependency_overrides[get_run_store] = lambda: RunStore(settings.runs_dir)
    app.dependency_overrides[get_portfolio_store] = lambda: None
    app.dependency_overrides[get_index_store] = lambda: IndexStore(tmp_path / "indices")
    with TestClient(app) as c:
        c.frameworks_dir = settings.frameworks_dir
        yield c


def _framework(client, tmp_path) -> tuple[str, str]:
    """The example table with a Company_Id column: row 1 is a stewardship
    issuer, row 2 an index demo candidate, the rest match nothing."""
    rows = list(csv.reader(SAMPLE.open()))
    ids = ["SYN01", "demo000"] + [f"X{i}" for i in range(len(rows) - 3)]
    path = tmp_path / "with_ids.csv"
    with path.open("w", newline="") as fh:
        csv.writer(fh).writerows([["Company_Id", *rows[0]]] + [[i, *r] for i, r in zip(ids, rows[1:], strict=True)])
    with path.open("rb") as fh:
        dataset_id = client.post("/api/decision/datasets", files={"file": (path.name, fh, "text/csv")}).json()["dataset_id"]
    config = client.post("/api/decision/mechanisms/derive", json={"dataset_id": dataset_id, "name": "Climate", "save": True}).json()["config"]
    return dataset_id, config["framework_id"]


def test_publish_needs_a_ratified_framework_then_freezes_rows_by_id(client, tmp_path):
    dataset_id, framework_id = _framework(client, tmp_path)
    body = {"dataset_id": dataset_id, "framework_id": framework_id, "published_by": "A. Reviewer"}

    assert client.post("/api/decision/publish", json=body).status_code == 422  # draft framework

    client.post(f"/api/decision/mechanisms/{framework_id}/ratify", params={"ratified_by": "A. Reviewer"})
    assert client.post("/api/decision/publish", json={**body, "published_by": " "}).status_code == 422

    published = client.post("/api/decision/publish", json=body)
    assert published.status_code == 200, published.text
    snapshot = published.json()
    assert snapshot["id_column"] == "Company_Id"
    assert {r["entity_id"] for r in snapshot["rows"]} >= {"SYN01", "demo000"}
    assert client.get("/api/decision/published").json()[0]["snapshot_id"] == snapshot["snapshot_id"]

    # Stewardship: the matched issuer carries the tier as a company field the coverage rules can read.
    row = next(r for r in snapshot["rows"] if r["entity_id"] == "SYN01")
    contexts = {c["issuer_id"]: c for c in tier_contexts(load_sample(client.frameworks_dir), [])}
    assert contexts["SYN01"]["issuer"]["decision"][framework_id]["tier"] == row["tier"]
    assert "decision" not in contexts["SYN02"]["issuer"]

    # Index: the published score joins the matching candidate; the review records what it read.
    spec = client.get("/api/index/presets/exclusion_only").json()
    run = {"review_date": "2999-01-01", "spec": spec, "decision_snapshot_ids": [snapshot["snapshot_id"]]}
    review = client.post("/api/index/run", json=run)
    assert review.status_code == 200, review.text
    assert review.json()["decision_snapshot_ids"] == [snapshot["snapshot_id"]]
    assert "matched 1 of 60 candidates" in review.json()["input_notes"][0]

    # A review dated before the publication cannot read it.
    early = client.post("/api/index/run", json={**run, "review_date": "2000-01-01"})
    assert early.status_code == 400
    assert "did not exist yet" in early.json()["detail"]
