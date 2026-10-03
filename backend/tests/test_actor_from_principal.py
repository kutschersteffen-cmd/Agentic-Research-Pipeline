"""Who did something is the signed-in principal, never a name the client sends."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.routers import engagement, portfolio, stewardship, taxonomies
from arp.config import Settings
from arp.schemas.taxonomy import DerivationMethod
from arp.stewardship.process import StreamStore
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.conftest import PRINCIPAL
from tests.test_taxonomy_store import _theme

MALLORY = "Mallory"


def _client(router, overrides) -> TestClient:
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides.update(overrides)
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    return TestClient(app)


def test_taxonomy_ratify_ignores_supplied_ratified_by(tmp_path):
    store = TaxonomyStore(tmp_path)
    tax = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT)
    client = _client(taxonomies, {deps.get_taxonomy_store: lambda: store})
    res = client.post(f"/api/taxonomies/{tax.taxonomy_id}/ratify", json={"version": 1, "ratified_by": MALLORY})
    assert res.status_code == 200 and res.json()["ratified_by"] == PRINCIPAL.name


def test_engagement_validate_and_verify_ignore_supplied_names(tmp_path):
    store = EngagementStore(tmp_path)
    _, issue = store.open_issue("ACME", "Acme", theme="climate_transition")
    client = _client(engagement, {deps.get_engagement_store: lambda: store})
    base = f"/api/engagement/records/ACME/issues/{issue.issue_id}"
    res = client.post(f"{base}/log-meeting-summary-validated", json={"summary": "Met", "commitments": ["Cut"], "validated_by": MALLORY})
    assert res.status_code == 200
    [entry] = [c for i in res.json()["issues"] for c in i["correspondence"] if c["type"] == "meeting"]
    assert entry["logged_by"] == PRINCIPAL.name
    commitment_id = res.json()["issues"][0]["commitments"][0]["commitment_id"]
    res = client.post(f"{base}/verify-commitment", json={"commitment_id": commitment_id, "verified_by": MALLORY})
    assert res.status_code == 200
    assert res.json()["issues"][0]["commitments"][0]["validated_by"] == PRINCIPAL.name


def test_portfolio_governance_ignores_supplied_names(tmp_path):
    store = PortfolioStore(tmp_path)
    client = _client(portfolio, {deps.get_portfolio_store: lambda: store, deps.settings_dep: lambda: Settings()})
    res = client.put(
        "/api/portfolio/governance/policy",
        json={"setting_name": "climate_validation_tolerance_pct", "new_value": 0.1, "changed_by": MALLORY},
    )
    assert res.status_code == 200 and res.json()["changed_by"] == PRINCIPAL.name
    res = client.put("/api/portfolio/governance/owners/climate_conflict", json={"owner": "sam", "assigned_by": MALLORY})
    assert res.status_code == 200 and res.json()["assigned_by"] == PRINCIPAL.name


@pytest.fixture
def stew(tmp_path):
    streams, engagements = StreamStore(tmp_path / "s"), EngagementStore(tmp_path / "e")
    client = _client(
        stewardship,
        {
            deps.get_stream_store: lambda: streams,
            deps.get_engagement_store: lambda: engagements,
            deps.settings_dep: lambda: Settings(),
        },
    )
    return client, streams, engagements


def test_put_universe_works_without_set_by_and_records_the_principal(stew):
    client, streams, _ = stew
    res = client.put("/api/stewardship/universe", json={"source": "sample"})
    assert res.status_code == 200 and res.json()["set_by"] == PRINCIPAL.name
    res = client.put("/api/stewardship/universe", json={"source": "sample", "set_by": MALLORY})
    assert res.json()["set_by"] == PRINCIPAL.name


def test_stewardship_commitment_benchmark_and_run_ignore_supplied_names(stew, monkeypatch):
    client, _, engagements = stew
    _, issue = engagements.open_issue("ACME", "Acme", theme="climate_transition")
    res = client.post(
        "/api/stewardship/tracking/commitments",
        json={"company_id": "ACME", "issue_id": issue.issue_id, "text": "Cut", "recorded_by": MALLORY},
    )
    assert res.status_code == 200 and res.json()["recorded_by"] == PRINCIPAL.name

    csv = (
        "Fund Holdings as of,\"Sep 26, 2026\"\n\n"
        "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Location\n"
        "AAPL,APPLE INC,Information Technology,Equity,100,60,United States\n"
    )
    monkeypatch.setattr(stewardship, "parse_ishares_holdings", lambda _t: {"name": "F", "as_of": "2026-09-26", "constituents": []})
    res = client.post("/api/stewardship/benchmarks", json={"text": csv, "uploaded_by": MALLORY})
    assert res.status_code == 200 and res.json()["uploaded_by"] == PRINCIPAL.name

    stream_id = client.post("/api/stewardship/streams", json={"name": "Fund"}).json()["stream_id"]
    seen = {}

    def fake_record_run(stream, kpis, by):
        seen["by"] = by
        return {**stream, "program_runs": [{"recorded_by": by}]}

    monkeypatch.setattr(stewardship, "record_run", fake_record_run)
    monkeypatch.setattr(stewardship, "monitor", lambda *a: {})
    res = client.post(f"/api/stewardship/streams/{stream_id}/program/runs", json={"recorded_by": MALLORY})
    assert res.status_code == 200 and seen["by"] == PRINCIPAL.name
