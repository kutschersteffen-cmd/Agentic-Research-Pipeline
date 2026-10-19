"""GET /api/companies/{ref}/transition and the sector run list over seeded Postgres facts (spec sections 1, 3, 7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.main import app
from arp.db import models as m
from arp.db.observations import record
from arp.db.session import transaction
from arp.db.to_observations import to_observations
from arp.orchestration.review_queue import record_review_decision
from arp.planning.applicability import plan_fields
from arp.presets.transition_capex import FIELD_IDS, build_transition_capex_schema
from arp.schemas.common import CompanyRef, JobStatus, RunManifest
from arp.storage.portfolio_store import PortfolioStore
from tests.transition_alignment_helpers import (  # noqa: F401 - fixtures
    FY25,
    FY26,
    observation,
    publish,
    retire,
    seed_defaults,
    ta_dirs,
)

AR = "Fixture Steel Annual Report 2025 p."
QUOTE = "Low-carbon capital expenditure was EUR 120 million, 12% of total capex."


@pytest.fixture
def client(pg, ta_dirs):  # noqa: F811
    return TestClient(app)


@pytest.fixture
def ids(seed_defaults):  # noqa: F811
    return seed_defaults


def transition(client, cid):
    r = client.get(f"/api/companies/{cid}/transition")
    assert r.status_code == 200, r.text
    return r.json()


def _save_run(run_store, run_id, ref):
    run_store.save_manifest(RunManifest(run_id=run_id, run_type="extraction", status=JobStatus.COMPLETED))
    run_store.save_companies(run_id, [ref])


def test_ac9_api(client, ids):
    body = transition(client, ids["C"])
    c = body["capex"]
    assert (body["in_scope"], body["reason"], body["sector"]) == (True, None, "Steel")
    assert (c["reporting_year"], c["share_used"], c["rule"]) == (2025, 20, "RY+1 higher: RY+1 used")
    assert (c["benchmark"]["value"], c["ratio_shown"]) == (80, "0.25")
    assert (body["benchmarks_version"], body["rule_book_version"]) == (3, 7)
    assert (body["regions"], body["actions"], body["b02a"], body["assumptions"]) == ([], [], None, [])


def test_ac15_ac65_api(client, ids):
    c = transition(client, ids["C"])["capex"]
    (ci,) = [a for a in c["amounts"] if a["field_id"] == "tc_carbon_intensive_capex"]
    assert (ci["year"], ci["shown"], ci["citation"]) == (2025, "300 EUR million", AR + "46")
    assert [(r["id"], r["status"], r["citation"]) for r in c["redlines"]] == [("stl_bf", "not breached", AR + "48")]


def test_ac19_api(client, pg, run_store, ids):
    publish(pg, run_store, [(ids["P"], "tc_new_unabated_coal", FY25, True, None, "P4", 9)])
    (r,) = transition(client, ids["P"])["capex"]["redlines"]
    assert (r["id"], r["status"], r["citation"]) == ("pwr_coal", "breached", "Fixture Power Annual Report 2025 p.9")


def test_ac21_no_model_call(client, ids, monkeypatch):
    class Raising:
        def __getattr__(self, name):
            raise AssertionError(f"model client called: {name}")

    def refuse(*a, **k):
        raise AssertionError("model client built")

    monkeypatch.setattr("arp.llm.factory.build_llm_client", refuse)
    monkeypatch.setattr(deps, "build_llm_client", refuse)
    app.dependency_overrides[deps.get_llm_client] = Raising
    try:
        r = client.get(f"/api/companies/{ids['C']}/transition")
    finally:
        app.dependency_overrides.pop(deps.get_llm_client, None)
    assert r.status_code == 200 and r.json()["capex"]["ratio_shown"] == "0.25"


def test_ac22_ac58_out_of_scope(client, ids):
    q = transition(client, ids["Q"])
    assert (q["in_scope"], q["reason"], q["capex"], q["actions"]) == (
        False, "ISIC 1050 is not in a transition-barrier sector", None, [])
    n = transition(client, ids["N"])
    assert (n["in_scope"], n["reason"], n["sector"], n["capex"], n["actions"]) == (False, "No ISIC code", None, None, [])


def test_unknown_company_404(client, ids):
    r = client.get("/api/companies/UNIVERSE:nope/transition")
    assert (r.status_code, r.json()["detail"]) == (404, "Company not found")


def test_pending_version_ignored(client, pg, run_store, ids):  # Review Focus 3
    c = ids["C"]
    with transaction(pg) as s:  # a newer pending 2025 share over the approved one, and a held planned share
        record(s, [observation(s, c, "tc_lowcarbon_capex_share_pct", FY25, 50, "%", "P2", 45),
                   observation(s, c, "tc_lowcarbon_capex_share_pct_planned", FY26, 50, "%", "P1", 18, held=True)])
    cx = transition(client, c)["capex"]
    assert (cx["share_ry"]["value"], cx["share_ry"]["source"], cx["share_ry1"]["value"]) == (12, "disclosed", 20)
    # with no counted version left, the pending and held facts are current, yet still never count
    retire(pg, c, ("tc_lowcarbon_capex_share_pct", FY25), ("tc_lowcarbon_capex_share_pct_planned", FY26))
    with transaction(pg) as s:
        record(s, [observation(s, c, "tc_lowcarbon_capex_share_pct", FY25, 50, "%", "P2", 45),
                   observation(s, c, "tc_lowcarbon_capex_share_pct_planned", FY26, 50, "%", "P1", 18, held=True)])
    statuses = {(r["field_id"], r["status"]) for r in client.get(f"/api/companies/{c}/facts").json()}
    assert {("tc_lowcarbon_capex_share_pct", "pending_review"), ("tc_lowcarbon_capex_share_pct_planned", "held")} <= statuses
    cx = transition(client, c)["capex"]
    assert (cx["share_ry"]["value"], cx["share_ry"]["source"], cx["share_ry1"]) == (12, "computed from amounts", None)
    assert cx["rule"] == "Only RY known: RY used"


def test_basis_blank_preferred(client, pg, run_store, ids):  # R4: basis "" first, else lowest fact_id
    c = ids["C"]
    retire(pg, c, ("tc_lowcarbon_capex_share_pct", FY25))
    publish(pg, run_store, [(c, "tc_lowcarbon_capex_share_pct", FY25, 30, "%", "P2", 45)], basis="taxonomy")
    publish(pg, run_store, [(c, "tc_lowcarbon_capex_share_pct", FY25, 12, "%", "P2", 45)])
    rows = client.get(f"/api/companies/{c}/facts", params={"field_id": "tc_lowcarbon_capex_share_pct"}).json()
    by_basis = {r["basis"]: r["fact_id"] for r in rows}
    assert by_basis["taxonomy"] < by_basis[""]
    share = transition(client, c)["capex"]["share_ry"]
    assert (share["value"], share["fact_ids"]) == (12, [by_basis[""]])


def test_no_facts_in_scope(client, ids):  # Review Focus 4
    cx = transition(client, ids["K"])["capex"]
    assert cx["headline"] == "Capex not scored: No reporting-year low-carbon capex share"
    assert [t["not_scored"] for t in cx["rnd_tests"]] == ["No reporting-year R&D figures"]
    assert cx["redlines"] == []  # Cement defines no redline
    assert cx["reporting_year"] is None


def test_no_redline_fact_is_no_disclosure(client, ids):
    (r,) = transition(client, ids["P"])["capex"]["redlines"]
    assert (r["status"], r["citation"], r["fact_id"]) == ("no disclosure", None, None)


def test_ac23_run_to_fact(client, pg, run_store, ids):
    c = ids["C"]
    retire(pg, c, *[(f, FY25) for f in ("tc_capex_total", "tc_lowcarbon_capex", "tc_lowcarbon_capex_share_pct")])
    ref = CompanyRef(company_id="c", name="Fixture Steel AG", entity_id=c)
    _save_run(run_store, "r1", ref)
    field = {"field_id": "tc_lowcarbon_capex_share_pct", "field_name": "Low-carbon capex share", "value": 12.0, "unit": "%",
             "confidence": 0.5, "value_state": "found", "period_end": "2025-12-31", "route": "review",
             "citations": [{"doc_id": "P2", "doc_type": "other", "quote": QUOTE, "page": 45, "grounded": True}]}
    row = {"company_id": "c", "name": "Fixture Steel AG", "schema_id": "sch_transition_capex", "run_id": "r1", "_key": "c",
           "fields": [field]}
    key = "UNIVERSE:C:tc_lowcarbon_capex_share_pct:2025-12-31"
    run_store.record_company_result(
        "r1", row, observations=to_observations("extraction", c, "r1", row, trial=False), company=ref,
        review_items=[(key, {"item_key": key, "company_id": "c", "field_id": "tc_lowcarbon_capex_share_pct",
                             "period_end": "2025-12-31"})],
    )
    record_review_decision(run_store, "r1", key, "approve", "bob", None)
    (fact,) = client.get(f"/api/companies/{c}/facts", params={"field_id": "tc_lowcarbon_capex_share_pct"}).json()
    assert (fact["period_end"], fact["value"], fact["status"], fact["source_label"]) == (
        "2025-12-31", 12, "approved", AR + "45")


def test_ac45_green_fact_unchanged(client, run_store, ids):
    c = ids["C"]
    ref = CompanyRef(company_id="c", name="Fixture Steel AG", entity_id=c, isic_code="2410")
    _save_run(run_store, "r1", ref)
    fields = [{"field_id": f, "field_name": f, "value": None, "confidence": 0.0, "value_state": "not_found"} for f in FIELD_IDS]
    row = {"company_id": "c", "name": "Fixture Steel AG", "schema_id": "sch_transition_capex", "run_id": "r1", "_key": "c",
           "fields": fields}
    run_store.record_company_result("r1", row, observations=to_observations("extraction", c, "r1", row, trial=False),
                                    company=ref, review_items=[])
    rows = client.get(f"/api/companies/{c}/facts", params={"field_id": "green_capex_share_pct"}).json()
    assert [(r["period_end"], r["value"], r["status"], r["source_label"]) for r in rows] == [
        ("2025-12-31", 15, "approved", AR + "47")]


def test_ac48_api(client, run_store, ids):
    q = ids["Q"]
    ref = CompanyRef(company_id="q", name="Fixture Foods SA", entity_id=q, isic_code="1050")
    to_extract, skipped = plan_fields(build_transition_capex_schema(), ref)
    assert to_extract == [] and len(skipped) == len(FIELD_IDS)
    _save_run(run_store, "r1", ref)
    fields = [{**f.model_dump(mode="json"), "route": "auto_accept"} for f in skipped]  # as routing marks not_applicable_by_rule
    row = {"company_id": "q", "name": "Fixture Foods SA", "schema_id": "sch_transition_capex", "run_id": "r1", "_key": "q",
           "fields": fields}
    run_store.record_company_result("r1", row, observations=to_observations("extraction", q, "r1", row, trial=False),
                                    company=ref, review_items=[])
    rows = client.get(f"/api/companies/{q}/facts").json()
    assert [(r["field_id"], r["period_end"], r["value"], r["status"], r["source_label"]) for r in rows] == [
        ("capex_total", "2025-12-31", 200, "approved", "Fixture Foods Report 2025 p.8")]


def test_sector_companies(tmp_path):  # Review Focus 5; the bundled benchmarks, which list all nine sectors
    client = TestClient(app)
    store = PortfolioStore(tmp_path / "pf")
    c = CompanyRef(company_id="c", name="Fixture Steel AG", isic_code="2410")
    store.save_company(c)
    store.save_company(CompanyRef(company_id="q", name="Fixture Foods SA", isic_code="1050"))
    app.dependency_overrides[deps.get_portfolio_store] = lambda: store
    try:
        steel = client.get("/api/transition-alignment/sectors/Steel/companies")
        minerals = client.get("/api/transition-alignment/sectors/Critical%20Minerals%20%26%20Mining/companies")
        unknown = client.get("/api/transition-alignment/sectors/Aluminium/companies")
    finally:
        app.dependency_overrides.pop(deps.get_portfolio_store, None)
    assert steel.status_code == 200 and steel.json() == [c.model_dump(mode="json")]
    assert minerals.status_code == 200 and minerals.json() == []
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "Unknown sector: Aluminium")


def test_fact_row_carries_unit(client, ids):  # R8
    (row,) = client.get(f"/api/companies/{ids['C']}/facts", params={"field_id": "tc_carbon_intensive_capex"}).json()
    assert row["unit"] == "EUR million"
    assert m.FactStatus(row["status"]) == m.FactStatus.APPROVED
