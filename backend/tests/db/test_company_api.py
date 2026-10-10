from __future__ import annotations

import time
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from arp.api.main import app
from arp.db import models as m
from arp.db.companies import resolve
from arp.db.documents import DocumentRegistry
from arp.db.observations import CitationIn, ObservationIn, record
from arp.db.providers import ProviderRow, ensure_source, ingest_rows, record_load
from arp.db.session import transaction
from arp.db.to_observations import to_observations
from arp.orchestration.review_queue import record_review_decision
from arp.schemas.common import CompanyRef, JobStatus, RunManifest

FY24, FY23 = date(2024, 12, 31), date(2023, 12, 31)
LEI = "7LTWFZYICNSX8D621K86"


@pytest.fixture
def client(pg):
    return TestClient(app)


@pytest.fixture
def cid(pg):
    with transaction(pg) as s:
        return resolve(s, [(m.IdScheme.LEI, LEI), (m.IdScheme.UNIVERSE, "acme")], name="Acme AG", allow_create=True).company_id


def _obs(cid, value, period=FY24, **kw):
    return ObservationIn(
        company_id=cid, field_id=kw.pop("field_id", "revenue"), field_version=1, source_kind=m.SourceKind.EXTRACTION,
        period_end=period, value=value, value_state=m.ValueState.FOUND, route=m.Route.AUTO_ACCEPT, **kw,
    )


def _record(pg, *obs):
    with transaction(pg) as s:
        return record(s, list(obs))


def test_alias_lookup_is_normalised(client, cid):
    by_uuid = client.get(f"/api/companies/{cid}")
    by_lei = client.get(f"/api/companies/lei: {LEI.lower()}")
    assert by_uuid.status_code == by_lei.status_code == 200
    assert by_lei.json()["id"] == by_uuid.json()["id"] == str(cid)
    assert client.get("/api/companies/UNIVERSE:acme").json()["id"] == str(cid)
    assert [h["id"] for h in client.get("/api/companies?q=acme").json()] == [str(cid)]
    assert [h["id"] for h in client.get("/api/companies?q=7ltw").json()] == [str(cid)]


def test_unknown_company_404(client, cid):
    assert client.get("/api/companies/LEI:NOPE").status_code == 404
    assert client.get("/api/companies/00000000-0000-0000-0000-000000000000/facts").status_code == 404
    assert client.get("/api/companies/garbage").status_code == 404
    assert client.get("/api/facts/999/trail").status_code == 404
    assert client.get("/api/companies", params={"limit": -1}).status_code == 422
    assert client.get(f"/api/companies/{cid}/facts", params={"limit": 0}).status_code == 422
    assert client.get(f"/api/companies/{cid}/facts", params={"offset": -1}).status_code == 422


def test_facts_as_of_returns_historical_value(client, pg, cid):
    _record(pg, _obs(cid, 100))
    time.sleep(0.01)
    between = datetime.now(UTC)
    time.sleep(0.01)
    _record(pg, _obs(cid, 1000.0))
    now = client.get(f"/api/companies/{cid}/facts").json()
    old = client.get(f"/api/companies/{cid}/facts", params={"as_of": between.isoformat()}).json()
    assert [r["value"] for r in now] == [1000.0]
    assert [r["value"] for r in old] == [100]
    naive = client.get(f"/api/companies/{cid}/facts", params={"as_of": between.replace(tzinfo=None).isoformat()}).json()
    assert [r["value"] for r in naive] == [100]
    assert client.get(f"/api/companies/{cid}/facts", params={"as_of": "2000-01-01T00:00:00+00:00"}).json() == []


def test_facts_filters_by_kind_and_period(client, pg, cid):
    _record(pg, _obs(cid, 90, FY23), _obs(cid, 100, FY24), _obs(cid, 5, FY24, field_id="capex"))
    with transaction(pg) as s:
        src = ensure_source(s, "msci", name="MSCI", kind="api", licence=m.Licence.INTERNAL_ONLY, id_scheme="MSCI_ID")
        load = record_load(s, src, b"p", request={}, as_of=FY24)
        ingest_rows(s, load.load_id, [ProviderRow(issuer_ids=[(m.IdScheme.LEI, LEI)], metric_code="SCOPE_1", metric_name="S1",
                                                  unit="tCO2e", data_type="number", period_end=FY24, value=12.5)])
    url = f"/api/companies/{cid}/facts"
    assert len(client.get(url).json()) == 4
    assert {r["field_id"] for r in client.get(url, params={"kind": "extracted"}).json()} == {"revenue", "capex"}
    assert [r["kind"] for r in client.get(url, params={"kind": "provider"}).json()] == ["provider"]
    rows = client.get(url, params={"field_id": "revenue", "period_end": "2023-12-31"}).json()
    assert [(r["field_id"], r["value"]) for r in rows] == [("revenue", 90)]
    assert len(client.get(url, params={"limit": 2}).json()) == 2
    assert len(client.get(url, params={"limit": 2, "offset": 2}).json()) == 2


def test_provider_fact_shows_source_and_licence(client, pg, cid):
    with transaction(pg) as s:
        src = ensure_source(s, "msci", name="MSCI", kind="api", licence=m.Licence.INTERNAL_ONLY, id_scheme="MSCI_ID")
        load = record_load(s, src, b"p", request={}, as_of=FY24)
        ingest_rows(s, load.load_id, [ProviderRow(issuer_ids=[(m.IdScheme.LEI, LEI)], metric_code="SCOPE_1", metric_name="S1",
                                                  unit="tCO2e", data_type="number", period_end=FY24, value=12.5)])
    (row,) = client.get(f"/api/companies/{cid}/facts").json()
    assert row["source_label"] == f"MSCI · {datetime.now(UTC).date().isoformat()}"
    assert row["licence"] == "internal_only" and row["source_kind"] == "provider"
    trail = client.get(f"/api/facts/{row['fact_id']}/trail").json()
    assert trail["versions"][0]["load"]["source_name"] == "MSCI"


def test_trail_contains_citation_page_and_decision(client, run_store, pg, cid):
    DocumentRegistry(pg).register_document(doc_id="doc_a", company_id="acme", doc_type="10-K", content_key="ck1",
                                           title="Annual Report", local_path=None, source_url=None)
    run_store.save_manifest(RunManifest(run_id="r1", run_type="extraction", status=JobStatus.COMPLETED))
    run_store.save_companies("r1", [CompanyRef(company_id="acme", name="Acme")])
    row = {"company_id": "acme", "name": "Acme", "schema_id": "s", "run_id": "r1", "_key": "acme",
           "fields": [{"field_id": "revenue", "field_name": "Revenue", "value": 100.0, "confidence": 0.5,
                       "period_end": "2024-12-31", "route": "review"}]}
    obs = to_observations("extraction", cid, "r1", row, trial=False)
    DocumentRegistry(pg).register_document(doc_id="doc_b", company_id="acme", doc_type="10-K", content_key="ck2",
                                           title="Other", local_path=None, source_url=None)
    obs[0].citations = [CitationIn(doc_id="doc_b", page=3, role=m.CitationRole.CORROBORATING), CitationIn(doc_id="doc_a", page=12, quote="Revenue 100", char_start=5, char_end=16,
                                   passage_id="p3", grounded=True)]
    key = "LEI:X:revenue:2024-12-31"
    run_store.record_company_result(
        "r1", row, observations=obs, company=CompanyRef(company_id="acme", name="Acme", entity_id=cid),
        review_items=[(key, {"item_key": key, "company_id": "acme", "field_id": "revenue", "period_end": "2024-12-31"})],
    )
    record_review_decision(run_store, "r1", key, "approve", "bob", None)
    (fact,) = client.get(f"/api/companies/{cid}/facts").json()
    assert fact["status"] == "approved" and fact["source_label"] == "Annual Report p.12" and fact["licence"] is None
    versions = client.get(f"/api/facts/{fact['fact_id']}/trail").json()["versions"]
    assert [v["status"] for v in versions] == ["pending_review", "approved"]
    version = versions[-1]
    assert [c["role"] for c in version["citations"]] == ["corroborating", "primary"]
    assert version["citations"][1] == {
        "doc_id": "doc_a", "title": "Annual Report", "page": 12, "quote": "Revenue 100", "char_start": 5, "char_end": 16,
        "passage_id": "p3", "role": "primary", "grounded": True}
    assert [(d["decision"], d["reviewer"]) for d in version["decisions"]] == [("approve", "bob")]
    summary = client.get(f"/api/companies/{cid}").json()
    assert summary["fact_counts"] == {"approved": 1} and summary["documents"] == 2 and summary["runs"] == 1
    assert summary["holders_available"] is True and summary["holders"] == []


def test_trail_lists_every_version(client, pg, cid):
    _record(pg, _obs(cid, 100))
    _record(pg, _obs(cid, 120))
    fact_id = client.get(f"/api/companies/{cid}/facts").json()[0]["fact_id"]
    versions = client.get(f"/api/facts/{fact_id}/trail").json()["versions"]
    assert [v["value"] for v in versions] == [100, 120]
    assert versions[0]["superseded_by"] == versions[1]["fact_id"]


def test_holders_matched_by_any_identifier(client, cid, monkeypatch, tmp_path):
    from arp.api.deps import get_portfolio_store
    from arp.schemas.portfolio import HolderConfig, Holding, SecurityRef
    from arp.storage.portfolio_store import PortfolioStore

    store = PortfolioStore(tmp_path / "pf")
    store.save_snapshot("idx1", "2026-01-01", [Holding(holder_id="idx1", kind="index", security_id="S1", as_of_date="2026-01-01",
                                                       issuer_key=LEI, issuer_scheme="LEI", weight_pct=2.5)], kind="index")
    store.save_snapshot("idx2", "2026-01-01", [
        Holding(holder_id="idx2", kind="index", security_id="S3", as_of_date="2026-01-01", issuer_key=str(cid), issuer_scheme="INTERNAL"),
        Holding(holder_id="idx2", kind="index", security_id="S4", as_of_date="2026-01-01", issuer_key="ACME", issuer_scheme="ISIN")], kind="index")
    store.save_holder(HolderConfig(holder_id="idx2", kind="index"))
    store.save_snapshot("pf1", "2026-01-01", [Holding(holder_id="pf1", security_id="S2", as_of_date="2026-01-01", market_value_eur=1.0)])
    store.save_security(SecurityRef(security_id="S2", name="Acme", asset_class="equity", currency="EUR", company_id="acme"))
    store.save_holder(HolderConfig(holder_id="idx1", kind="index"))
    store.save_holder(HolderConfig(holder_id="pf1", kind="portfolio"))
    app.dependency_overrides[get_portfolio_store] = lambda: store
    try:
        holders = client.get(f"/api/companies/{cid}").json()["holders"]
    finally:
        app.dependency_overrides.pop(get_portfolio_store, None)
    assert sorted((h["holder_id"], h["kind"], h["weight_pct"]) for h in holders) == [("idx1", "index", 2.5), ("idx2", "index", None), ("pf1", "portfolio", None)]


def _save_run(run_store, run_id, run_type, created_at, rows):
    run_store.save_manifest(RunManifest(run_id=run_id, run_type=run_type, created_at=created_at, status=JobStatus.COMPLETED))
    run_store.save_companies(run_id, [CompanyRef(company_id=r["company_id"], name=r["name"], ticker=r.get("ticker")) for r in rows])
    for r in rows:
        run_store.append_result(run_id, {**r, "_key": r["company_id"]})


def test_existing_extraction_company_results_shape_unchanged(client, run_store):
    _save_run(run_store, "old", "extraction", "2025-01-01T00:00:00+00:00",
              [{"company_id": "acme", "name": "Acme", "fields": [{"field_name": "x", "value": 1}]},
               {"company_id": "beta", "name": "Beta", "ticker": "B", "fields": []}])
    _save_run(run_store, "new", "extraction", "2025-06-01T00:00:00+00:00",
              [{"company_id": "acme", "name": "Acme Renamed", "ticker": "ACM", "fields": [{"field_name": "x", "value": 2}]}])
    _save_run(run_store, "fin", "financials", "2025-06-01T00:00:00+00:00", [{"company_id": "acme", "name": "Acme"}])
    body = client.get("/api/extraction/companies/acme/results").json()
    assert list(body) == ["results"]
    assert [r["fields"][0]["value"] for r in body["results"]] == [2, 1]  # newest run first
    assert set(body["results"][0]) == {"company_id", "name", "ticker", "fields", "_key"}
    assert client.get("/api/extraction/companies/nonexistent/results").json() == {"results": []}
    assert len(client.get("/api/financials/companies/acme/results").json()["results"]) == 1
    known = client.get("/api/runs/known-companies", params={"run_type": "extraction"}).json()
    assert known == {"companies": [{"company_id": "acme", "name": "Acme Renamed", "ticker": "ACM"},
                                   {"company_id": "beta", "name": "Beta", "ticker": "B"}]}
