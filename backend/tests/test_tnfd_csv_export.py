"""TNFD run CSV export: one row per item, values held back while a record waits for review (spec exploration-accept-tnfd-export)."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.schemas.common import RunManifest
from arp.schemas.tnfd import (
    CoreGlobalMetricExtraction,
    DisclosureExtraction,
    GeneralRequirementsExtraction,
    SectorLeapConsideration,
    SectorMetricExtraction,
    TNFDExtractionRecord,
)
from arp.storage.run_store import RunStore
from tests.test_review_export_correctness import ALICE

pytestmark = pytest.mark.usefixtures("pg")

HELD = ["disclosed", "summary", "consideration", "materiality_basis", "disclosure_scope", "location_specificity",
        "cross_framework_links", "time_horizons", "iplc_engagement_described", "value", "unit", "baseline_year",
        "confidence", "grounded", "verifier_notes"]


def _record(cid, name, ticker, needs_review=False, conf=0.5, **items):
    return TNFDExtractionRecord(company_id=cid, name=name, ticker=ticker, run_id="RT", as_of="2025-12-31",
                                needs_review=needs_review, overall_confidence=conf, **items).model_dump(mode="json")


def _disc(rid, summary, conf, **kw):
    return DisclosureExtraction(recommendation_id=rid, disclosed=True, summary=summary, confidence=conf, **kw)


def _decision(key, decision, **kw):
    return {"item_key": key, "decision": decision, "decided_at": "2026-11-02T00:00:00+00:00", "user_id": "x", **kw}


@pytest.fixture
def rs(pg, tmp_path):
    store = RunStore(pg, tmp_path / "runs")
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: ALICE
    yield store
    app.dependency_overrides.pop(get_run_store, None)
    app.dependency_overrides.pop(current_user, None)


def _seed(rs):
    rs.save_manifest(RunManifest(run_id="RT", run_type="tnfd", status="completed"))
    m1 = CoreGlobalMetricExtraction(category="land_use_change", metric_kind="dependency_impact", metric_name="Land converted",
                                    value=12.5, unit="ha", baseline_year=2020, confidence=0.8, grounded=True)
    s1 = SectorMetricExtraction(sector_name="oil_and_gas", sector_guidance_status="final", sector_guidance_version="2024-06",
                                metric_no="OG.C2.0", is_core_sector_metric=True, metric_name="Hydrocarbon spills", value=3.0,
                                unit="bbl", confidence=0.7, grounded=False,
                                review_flags=["metric_missing_unit_or_baseline", "metric_core_flag_mismatch"])
    g1 = GeneralRequirementsExtraction(materiality_approach="double", disclosure_scope="direct_operations",
                                       location_specificity="site level", cross_framework_links=["TCFD", "GRI 101"],
                                       time_horizons_defined={"short": "0-3y", "long": "10y+"}, iplc_engagement_described=True)
    recs = [
        _record("c1", "Alpha", "T1", conf=0.85, general_requirements=g1, core_global_metrics=[m1], sector_metrics=[s1],
                disclosures=[_disc("governance.A", "Board oversees nature risks", 0.9, materiality_basis="double",
                                   disclosure_scope="full_value_chain", leap_stage_reference="evaluate", grounded=True,
                                   verifier_notes="ok")],
                sector_leap_considerations=[SectorLeapConsideration(sector_name="oil_and_gas", leap_stage="locate",
                                                                    consideration="Screen upstream sites, then rank")]),
        _record("c2", "Beta", None, True, disclosures=[_disc("strategy.A", "Beta strategy", 0.6)]),
        _record("c3", "Gamma", "T3", True, core_global_metrics=[CoreGlobalMetricExtraction(
            category="pollution", metric_kind="risk_opportunity", metric_name="Spills", value=4.0, unit="t",
            baseline_year=2021, confidence=0.7, grounded=True)]),
        _record("c4", "Delta", "T4", True, disclosures=[_disc("governance.B", "Delta governance", 0.4)]),
        _record("c7", "Eta", "T7"),
        _record("c8", "Theta", "T8", True, sector_leap_considerations=[
            SectorLeapConsideration(sector_name="fishing", leap_stage="assess", consideration="Theta note")]),
    ]
    for r in recs:
        rs.append_result("RT", r)
        if r["needs_review"]:
            rs.append_review_item("RT", {"item_key": r["company_id"], **r}) if r["company_id"] != "c8" else None
    for d in (_decision("c3", "approve"), _decision("c4", "reject")):
        rs.append_decision_row("RT", d)


def _export():
    r = TestClient(app).get("/api/runs/RT/export.csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == "attachment; filename=RT.csv"
    return list(csv.DictReader(io.StringIO(r.text))), r.text.splitlines()[0]


def _row(rows, cid, kind):
    return next(r for r in rows if r["company_id"] == cid and r["item_type"] == kind)


def test_header_and_row_order(rs):
    _seed(rs)
    rows, header = _export()
    assert len(header.split(",")) == 36
    assert header.startswith("company_id,ticker,name,as_of,framework_version,item_type,pillar,")
    assert header.endswith(",overall_confidence,needs_review,review_status")
    assert [(r["company_id"], r["item_type"]) for r in rows] == [
        ("c1", "disclosure"), ("c1", "core_metric"), ("c1", "sector_metric"), ("c1", "leap_consideration"),
        ("c1", "general_requirements"), ("c2", "disclosure"), ("c3", "core_metric"), ("c4", "disclosure"),
        ("c7", "none"), ("c8", "leap_consideration")]


def test_item_cells(rs):
    _seed(rs)
    rows, _ = _export()
    full = {k: v for k, v in _row(rows, "c1", "disclosure").items() if v != ""}
    assert full == {
        "company_id": "c1", "ticker": "T1", "name": "Alpha", "as_of": "2025-12-31",
        "framework_version": "v1.1 (October 2023, incl. Additional Guidance)", "item_type": "disclosure", "pillar": "governance",
        "recommendation_id": "governance.A", "leap_stage": "evaluate", "disclosed": "True", "summary": "Board oversees nature risks",
        "materiality_basis": "double", "disclosure_scope": "full_value_chain", "confidence": "0.9", "grounded": "True",
        "verifier_notes": "ok", "overall_confidence": "0.85", "needs_review": "False"}
    sm = _row(rows, "c1", "sector_metric")
    assert (sm["value"], sm["is_core_sector_metric"], sm["grounded"], sm["review_flags"]) == (
        "3.0", "True", "False", "metric_missing_unit_or_baseline; metric_core_flag_mismatch")
    gr = _row(rows, "c1", "general_requirements")
    assert (gr["cross_framework_links"], gr["time_horizons"], gr["iplc_engagement_described"]) == (
        "TCFD; GRI 101", "short=0-3y; long=10y+", "True")
    assert _row(rows, "c1", "core_metric")["value"] == "12.5"
    none = _row(rows, "c7", "none")
    assert (none["ticker"], none["review_status"]) == ("T7", "")
    assert all(none[c] == "" for c in list(none)[6:33])


def test_review_gate(rs):
    _seed(rs)
    rows, _ = _export()
    for cid, kind, status in (("c2", "disclosure", "awaiting review"), ("c4", "disclosure", "reject"),
                              ("c8", "leap_consideration", "awaiting review")):
        r = _row(rows, cid, kind)
        assert r["review_status"] == status and all(r[c] == "" for c in HELD), (cid, r)
    assert _row(rows, "c2", "disclosure")["ticker"] == "" and _row(rows, "c2", "disclosure")["pillar"] == "strategy"
    approved = _row(rows, "c3", "core_metric")
    assert (approved["review_status"], approved["value"], approved["unit"]) == ("approve", "4.0", "t")
    assert _row(rows, "c8", "leap_consideration")["leap_stage"] == "assess"


def test_escalate_and_correct_and_edit_hold_back(rs):
    _seed(rs)
    rs.append_decision_row("RT", _decision("c1", "correct", corrected_value={"value": 1}))
    rs.append_decision_row("RT", _decision("c4", "edit", edited_value={"value": 1}))
    rows, _ = _export()
    c1 = [r for r in rows if r["company_id"] == "c1"]
    assert len(c1) == 5 and all(r["review_status"] == "correct" and all(r[c] == "" for c in HELD) for r in c1)
    assert _row(rows, "c4", "disclosure")["review_status"] == "edit"


def test_escalate_alone_is_awaiting_review(rs):
    _seed(rs)
    rs.append_decision_row("RT", _decision("c7", "escalate"))
    rows, _ = _export()
    assert _row(rows, "c7", "none")["review_status"] == "awaiting review"


def test_discovery_export_unchanged(rs):
    rs.save_manifest(RunManifest(run_id="RD", run_type="discovery"))
    rs.append_result("RD", {"company_id": "d1", "name": "D", "homepage_used": "https://d.example", "documents_found": [
        {"doc_type": "annual_report", "url": "https://d.example/ar.pdf", "local_path": None}]})
    r = TestClient(app).get("/api/runs/RD/export.csv")
    assert r.text.splitlines() == ["company_id,name,homepage_used,doc_type,url,local_path",
                                   "d1,D,https://d.example,annual_report,https://d.example/ar.pdf,"]
