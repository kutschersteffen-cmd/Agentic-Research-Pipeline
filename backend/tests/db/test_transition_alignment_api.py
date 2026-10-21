"""GET /api/companies/{ref}/transition and the sector run list over seeded Postgres facts (spec sections 1, 3, 7)."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.main import app
from arp.config import get_settings
from arp.db import models as m
from arp.db.observations import record
from arp.db.session import transaction
from arp.db.to_observations import to_observations
from arp.orchestration.review_queue import record_review_decision
from arp.planning.applicability import plan_fields
from arp.presets.transition_capex import FIELD_IDS, build_transition_capex_schema
from arp.presets.transition_plan_actions import TARGET_FIELDS
from arp.schemas.common import CompanyRef, JobStatus, RunManifest
from arp.storage.document_store import DocumentContentStore
from arp.storage.portfolio_store import PortfolioStore
from arp.transition_barrier import clock
from tests.postgres_helpers import pg_dsn
from tests.test_transition_alignment_plan_extraction import O1, P1, T1, _plan, _record, _script
from tests.transition_alignment_helpers import (  # noqa: F401 - fixtures
    CN,
    EU,
    FY25,
    FY26,
    OFFSETS,
    US,
    action_basis,
    observation,
    publish,
    publish_action,
    publish_item,
    publish_k_net_zero,
    ratify_fta,
    register_documents,
    retire,
    retire_item,
    seed_defaults,
    ta_dirs,
    use_bm_s,
)

AR = "Fixture Steel Annual Report 2025 p."
QUOTE = "Low-carbon capital expenditure was EUR 120 million, 12% of total capex."


@pytest.fixture
def client(pg, ta_dirs, tmp_path, monkeypatch):  # noqa: F811
    """The barrier API reads and writes the test's runs (the `run_store` fixture's directory) and documents."""
    for name, value in {"RUNS_DIR": str(tmp_path / "runs"), "SECOND_REVIEW_SAMPLE_RATE": "0",
                        "BULK_ACCEPT_SAMPLE_RATE": "0", "TRANSITION_BARRIER_REFRESH_ENABLED": "false"}.items():
        monkeypatch.setenv(f"ARP_{name}", value)
    get_settings.cache_clear()
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 20))
    app.dependency_overrides[deps.get_document_content_store] = lambda: DocumentContentStore(tmp_path / "docs", dsn=pg_dsn())
    yield TestClient(app)
    app.dependency_overrides.pop(deps.get_document_content_store, None)


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
    assert (body["regions"], len(body["actions"]), len(body["assumptions"])) == ([EU, US, CN], 3, 2)  # phase 2: AC-24


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


# --- Plan actions and assumptions (phase 2: AC-24..AC-35, AC-46, AC-62, AC-71) ---

TP = "Fixture Steel Transition Plan 2025 p."


@pytest.fixture
def ratified(client, ids):
    ratify_fta(client)
    return ids


def actions(client, cid):
    return transition(client, cid)["actions"]


def test_ac24_api(client, ratified):
    body = transition(client, ratified["C"])
    assert body["regions"] == [EU, US, CN]
    assert [(a["action_id"], a["citation"]) for a in body["actions"]] == [
        ("steel.h2_dri", TP + "12"), ("steel.scrap_eaf", TP + "15"), ("steel.ccus", TP + "16")]
    assert [a["key"] for a in body["actions"]] == [action_basis(n) for n in ("A1", "A2", "A3")]


def test_ac25_api(client, ratified):
    a1 = actions(client, ratified["C"])[0]
    assert [(b["code"], b["region"], b["rating"], b["basis"]) for b in a1["barriers"]] == [
        ("STL-R1", EU, "H", "derived"), ("STL-T1", EU, "M", "derived")]
    price = [(v["value"], v["unit"], v["document"], v["page"]) for v in a1["barriers"][0]["values"] if v["fact"] == "price"]
    assert price == [(72, "USD/tCO2", "EU ETS Market Report 2026", 12)]


def test_ac26_ac29_api(client, ratified):
    a1, a2, _ = actions(client, ratified["C"])
    assert [(b["code"], b["region"], b["rating"], b["basis"], b["evidence"]) for b in a2["barriers"]] == [
        ("STL-R1", US, "L", "hand_rated", "No federal carbon price applies to steel.")]
    assert (a2["act_lever"]["wording"], a1["act_lever"]) == ("More scrap, process efficiency, zero-GHG power", None)


def test_ac31_api(client, ratified):
    carbon, h2 = transition(client, ratified["C"])["assumptions"]
    assert (carbon["kind"], carbon["region"], carbon["year"], carbon["citation"]) == ("carbon_price", EU, 2030, TP + "20")
    assert [(c["code"], c["region"], c["assumption"], c["evidence"], c["gap"], c["reason"]) for c in carbon["comparisons"]] == [
        ("STL-R1", EU, "97.2 USD/tCO2 (90 EUR/tCO2)", "72 USD/tCO2 (EU ETS Market Report 2026, p. 12)", "+25.2 USD/tCO2", None)]
    assert [(c["code"], c["region"], c["assumption"], c["gap"]) for c in h2["comparisons"]] == [  # AC-32
        ("STL-T1", EU, "3 USD/kg H2", "-3 USD/kg H2")]


def test_ac34_api(client, ratified):
    a1, a2, a3 = actions(client, ratified["C"])
    assert {k: (v["met"], v["text"]) for k, v in a1["b02"].items()} == {
        "b": (True, "near term (2028)"), "c": (True, "3.5 MtCO2e/yr"),
        "d": (True, "1500 EUR million needed, 600 EUR million allocated")}
    assert {k: (v["met"], v["text"]) for k, v in a2["b02"].items()} == {  # AC-35
        "b": (True, "implemented (2022)"), "c": (False, "No quantified GHG saving"), "d": (False, "No funding stated")}
    assert (a3["b02"]["b"]["met"], a3["b02"]["b"]["text"]) == (False, "No timeframe: ignored")  # AC-49
    b02a = transition(client, ratified["C"])["b02a"]
    assert (b02a["met"], b02a["text"]) == (False, "not met: 1 implemented, 1 planned with a timeframe (needs 3 and 1)")


def test_ac63_api(client, pg, run_store, ratified):  # money units are the canonical currency (B02.d compares them)
    c = ratified["C"]
    publish(pg, run_store, [(c, "ta_action_capex_allocated", None, 650, "USD million", "P1", 13)], basis=action_basis("A1"))
    d = actions(client, c)[0]["b02"]["d"]
    assert (d["met"], d["text"]) == (False, "Needed and allocated in different currencies")


def test_ac62_older_plan(client, pg, run_store, ratified):
    c = ratified["C"]
    register_documents(pg, "P3")
    publish_action(pg, run_store, c, "A6")
    assert [a["action_id"] for a in actions(client, c)] == ["steel.h2_dri", "steel.scrap_eaf", "steel.ccus"]
    (a6,) = [r for r in client.get(f"/api/companies/{c}/facts", params={"field_id": "ta_action_id"}).json()
             if r["basis"] == action_basis("A6")]
    r = client.get(f"/api/facts/{a6['fact_id']}/trail")
    assert r.status_code == 200, r.text
    assert r.json()["fact_id"] == a6["fact_id"]


def test_ac71_revised_plan(client, pg, run_store, ratified):
    c = ratified["C"]
    register_documents(pg, "P6")
    publish_action(pg, run_store, c, "A7")
    assert [(a["text"], a["citation"]) for a in actions(client, c)] == [
        ("We will build a second DRI plant in Sweden by 2030.", "Fixture Steel Transition Plan 2025 (revised) p.4")]


def test_same_date_later_upload_wins(client, pg, run_store, ids):  # Review Focus 4: P1 has three actions, P6 one
    c = ids["C"]
    register_documents(pg, "P6")
    publish_action(pg, run_store, c, "A7")
    assert [a["key"] for a in actions(client, c)] == [action_basis("A7")]


def _files(d):
    return {p.relative_to(d): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


def test_ac46_barrier_untouched(client, ratified, ta_dirs):  # noqa: F811
    f_ta, _ = ta_dirs
    api = "/api/transition-barrier"

    def barrier():
        scores, cell = client.get(f"{api}/scores"), client.get(f"{api}/cells/STL-R1/{EU}")
        assert scores.status_code == cell.status_code == 200, (scores.text, cell.text)
        return scores.json(), cell.json()

    before, files = barrier(), _files(f_ta)
    assert before[1]["rating"] == "H"
    for _ in range(2):
        transition(client, ratified["C"])
    assert barrier() == before
    assert _files(f_ta) == files


# --- Targets and phase-outs (plan delivery checks: AC-88, AC-115, AC-125) ---


async def _plan_run(tmp_path, fake_llm, **plan):
    """A stub-driven extraction run of sch_transition_plan_actions for C over P1; returns C's entity id."""
    _, _, entity, _ = await _record(tmp_path, fake_llm, _script(_plan(**plan)), docs=(P1,))
    return entity


async def test_ac88_target_pending(client, pg, ids, tmp_path, fake_llm):
    retire_item(pg, ids["C"], "T1")  # the defaults minus T1
    retire_item(pg, ids["C"], "T0")  # and T0, whose ta_target_pct would be a second row
    c = await _plan_run(tmp_path, fake_llm, targets=[T1])
    assert c == ids["C"]
    rows = client.get(f"/api/companies/{c}/facts", params={"field_id": "ta_target_pct"}).json()
    assert [(r["value"], r["status"]) for r in rows] == [(30, "pending_review")]


async def test_ac125_same_basis(client, pg, ids, tmp_path, fake_llm):
    retire_item(pg, ids["C"], "T1")
    retire_item(pg, ids["C"], "T0")  # so the six target rows are the run's T1 only
    c = await _plan_run(tmp_path, fake_llm, targets=[T1])
    rows = [r for r in client.get(f"/api/companies/{c}/facts").json() if r["field_id"] in TARGET_FIELDS]
    assert sorted(r["field_id"] for r in rows) == sorted(TARGET_FIELDS)
    assert len({r["basis"] for r in rows}) == 1


async def test_ac115_phaseout_pending(client, pg, ids, tmp_path, fake_llm):
    retire_item(pg, ids["C"], "O1")  # the defaults minus O1
    c = await _plan_run(tmp_path, fake_llm, phaseouts=[O1])
    rows = client.get(f"/api/companies/{c}/facts", params={"field_id": "ta_phaseout_year"}).json()
    assert [(r["value"], r["status"]) for r in rows] == [(2035, "pending_review")]


async def test_ac114(client, pg, ids, tmp_path, fake_llm):
    retire_item(pg, ids["C"], "T1")
    await _plan_run(tmp_path, fake_llm, targets=[T1])
    assert [t["key"] for t in transition(client, ids["C"])["targets"]] == ["target:P1:23:1"]


# --- Plan delivery checks (spec 2026-10-20: AC-72..AC-117) ---


def test_ac72_api(client, ids):
    ts = transition(client, ids["C"])["targets"]
    assert [(t["key"], t["citation"]) for t in ts] == [("target:P1:22:1", TP + "22"), ("target:P1:23:1", TP + "23")]
    assert [(t["kind"], t["ratio"], t["score"]) for t in ts] == [("running", "0.75", 75), ("past", "0.75", 50)]  # AC-90/91


def test_ac73_api(client, ids):
    assert transition(client, ids["C"])["target_progress"]["text"] == "Target progress 68.75% (ACT GE 1.4)"


def test_ac74_no_2023_scope2(client, pg, ids):  # the emissions series reads counted facts by fiscal year
    retire(pg, ids["C"], ("tp_h_scope2_emissions", date(2023, 12, 31)))
    body = transition(client, ids["C"])
    assert [(t["score"], t["reason"]) for t in body["targets"]][1] == (None, "No emissions for 2023")
    assert body["target_progress"]["text"] == "Target progress 75% (ACT GE 1.4)"  # AC-122


def test_ac94_no_pct(client, pg, ids):  # the target stays listed: its anchor is the year
    retire_item(pg, ids["C"], "T1", "ta_target_pct")
    t1 = transition(client, ids["C"])["targets"][0]
    assert (t1["key"], t1["score"], t1["reason"]) == ("target:P1:22:1", None, "Incomplete target")


def test_target_without_year_still_listed(client, pg, ids):
    retire_item(pg, ids["C"], "T1", "ta_target_year")
    t1 = transition(client, ids["C"])["targets"][0]
    assert (t1["key"], t1["score"], t1["reason"]) == ("target:P1:22:1", None, "Incomplete target")


def test_phaseout_without_activity_still_scored(client, pg, ids):
    retire_item(pg, ids["C"], "O1", "ta_phaseout_activity")
    (o1,) = transition(client, ids["C"])["phaseouts"]
    assert (o1["key"], o1["activity"], o1["share_points"], o1["date_points"], o1["score"]) == (
        "phaseout:P1:24:1", None, 25, 75, 40)


def test_ac77_api(client, ids):
    cov = transition(client, ids["C"])["coverage"]
    assert cov["text"] == "Listed actions cover 58.33% of the 2030 target gap (3.5 of 6 MtCO2e/yr)"
    assert [(a["key"], a["summed"], a["reason"]) for a in cov["actions"]] == [  # AC-101
        (action_basis("A1"), True, None), (action_basis("A2"), False, "No quantified saving"),
        (action_basis("A3"), False, "No quantified saving")]


def test_ac79_ac103_no_target(client, pg, ids):
    retire_item(pg, ids["C"], "T1")
    retire_item(pg, ids["C"], "T0")
    body = transition(client, ids["C"])
    assert (body["targets"], body["target_progress"], body["coverage"]["reason"]) == ([], None, "No running target")


def test_ac80_api(client, ids):
    (o1,) = transition(client, ids["C"])["phaseouts"]
    assert (o1["key"], o1["activity"], o1["method"], o1["citation"]) == (
        "phaseout:P1:24:1", "blast furnace steelmaking", "closure", TP + "24")
    assert (o1["share_points"], o1["date_points"], o1["score"]) == (25, 75, 40)
    assert o1["timeline_text"] == "No ACT Core sector timeline"  # AC-104


def test_ac81_api(client, pg, run_store, ids):
    register_documents(pg, "P7")
    publish_item(pg, run_store, ids, "O2")
    (o2,) = transition(client, ids["P"])["phaseouts"]
    assert (o2["share_points"], o2["date_points"], o2["score"]) == (100, 50, 85)
    assert (o2["timeline_text"], o2["citation"]) == ("Meets the ACT Core timeline (2040)", "Fixture Power Transition Plan 2025 p.4")


def test_ac83_api(client, pg, ids):
    retire_item(pg, ids["C"], "O1")
    assert transition(client, ids["C"])["phaseouts"] == []


def test_ac84_api(client, ids, ta_dirs):  # noqa: F811
    use_bm_s(ta_dirs[1])
    carbon, h2 = transition(client, ids["C"])["assumptions"]
    assert carbon["scenario"] == [{
        "region": EU, "year": 2030, "scenario": "140 USD/tCO2 (IEA NZE 2030, advanced economies)",
        "assumption": "97.2 USD/tCO2 (90 EUR/tCO2)", "gap": "-42.8 USD/tCO2", "reason": None}]
    assert h2["scenario"] == []  # AC-97


def test_no_scenario_without_bm_s(client, ids):  # BM has no scenario_prices: no entry
    assert [a["scenario"] for a in transition(client, ids["C"])["assumptions"]] == [[], []]


def test_ac116_latest_plan(client, pg, run_store, ids):
    register_documents(pg, "P6")
    body = transition(client, ids["C"])
    assert (body["targets"], body["phaseouts"], body["target_progress"]) == ([], [], None)


def test_no_plan_no_delivery(client, ids):  # P has no transition plan stored
    body = transition(client, ids["P"])
    assert (body["targets"], body["phaseouts"], body["coverage"]) == ([], [], None)


def test_ac117_no_model_call(client, ids, monkeypatch):
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
    assert r.status_code == 200 and r.json()["target_progress"]["text"] == "Target progress 68.75% (ACT GE 1.4)"


# --- consistency flags (spec 2026-10-21) ---------------------------------------------------------------------------

def _flags(client, cid):
    return {f["id"]: f for f in transition(client, cid)["flags"]}


def _fact_ids(client, cid, field_id):
    return [r["fact_id"] for r in client.get(f"/api/companies/{cid}/facts", params={"field_id": field_id}).json()]


def test_ac130_api(client, ids):
    assert [(f["id"], f["title"]) for f in transition(client, ids["C"])["flags"]] == [
        ("no_lowcarbon_capex", "Falling emissions claimed, no low-carbon capex"),
        ("net_zero_no_phaseout", "Net zero without phase-out"),
        ("expansion_vs_net_zero", "Expansion against net zero"),
        ("regions_left_out", "Regions left out"),
        ("offsets_emphasised", "Offsets emphasised"),
    ]


def test_ac133_api(client, ids):
    out = transition(client, ids["C"])
    assert out["flags_header"] == "Consistency: 1 of 5 checks raise a flag"
    assert [f["state"] for f in out["flags"]] == ["clear"] * 4 + ["raised"]


def test_ac143_q(client, ids):
    out = transition(client, ids["Q"])
    assert (out["flags"], out["flags_header"]) == ([], None)


def test_ac144_no_model_call(client, ids, monkeypatch):
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
    assert r.status_code == 200 and r.json()["flags_header"] == "Consistency: 1 of 5 checks raise a flag"


def test_ac145_trail(client, ids):
    (fact_id,) = _flags(client, ids["C"])["offsets_emphasised"]["fact_ids"]
    r = client.get(f"/api/facts/{fact_id}/trail")
    assert r.status_code == 200 and r.json()["field_id"] == OFFSETS
    (citation,) = r.json()["versions"][-1]["citations"]
    assert (citation["doc_id"], citation["page"]) == ("P1", 26)


def test_ac158_api(client, pg, run_store, ids):
    c = ids["C"]
    retire(pg, c, ("tc_new_blast_furnace", FY25))
    publish(pg, run_store, [(c, "tc_new_blast_furnace", FY25, True, None, "P2", 48)])
    f = _flags(client, c)["expansion_vs_net_zero"]
    assert f["state"] == "raised"
    assert f["fact_ids"] == _fact_ids(client, c, "tp_a_ambition_3") + _fact_ids(client, c, "tc_new_blast_furnace")


def test_ac160_k(client, pg, run_store, ids):
    publish_k_net_zero(pg, run_store, ids)
    f = _flags(client, ids["K"])["expansion_vs_net_zero"]
    assert (f["state"], f["text"]) == ("not checked", "No redline for this sector")


def test_ac166_api(client, ids):
    c = ids["C"]
    t1 = sorted(r["fact_id"] for r in client.get(f"/api/companies/{c}/facts").json()
                if r["field_id"] in TARGET_FIELDS and r["basis"] == "target:P1:22:1")
    assert len(t1) == 6 and _flags(client, c)["no_lowcarbon_capex"]["fact_ids"] == t1
