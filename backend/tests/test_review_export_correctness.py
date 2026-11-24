"""Conflicts held back from the export, the Argus approved count, and the conflict card (spec review-export-correctness, slice 1)."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.argus.flows import ArgusFlow
from arp.argus.rows import flow_rows
from arp.config import Settings
from arp.db.session import engine
from arp.schemas.common import CompanyRef, RunManifest
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.store import XbrlStore
from tests.conftest import PRINCIPAL
from tests.postgres_helpers import pg_dsn

pytestmark = pytest.mark.usefixtures("pg")

ALICE = Principal(user_id="u_alice", name="Alice", role="approver")
D = "2024-12-31"
PARAMS = {"schema_name": "S", "schema_version": "s:v2"}


def _field(field_id, value, route):
    return {"field_id": field_id, "field_name": field_id, "value": value, "confidence": 0.9, "grounded": True, "unit": "USD",
            "canonical_unit": "USD", "value_state": "found", "canonical_value": value, "period_end": D, "route": route,
            "citations": [{"doc_id": "d1", "doc_type": "10-K", "quote": f"Revenue was {value}", "char_start": 10, "char_end": 25,
                           "grounded": True}]}


def _decision(key, decision, **kw):
    return {"item_key": key, "decision": decision, "decided_at": "2026-11-02T00:00:00+00:00", "user_id": "x", **kw}


def _seed_e(rs):
    rs.save_manifest(RunManifest(run_id="R", run_type="extraction", created_at="2026-11-01T09:00:00+00:00", company_count=1, params=PARAMS))
    spec = [  # field_id, value, route, accepted value (a conflict), decisions
        ("plain", 1.0, "auto_accept", None, []),
        ("open", 2.0, "auto_accept", 20.0, []),
        ("taken", 3.0, "auto_accept", 30.0, [_decision("", "approve")]),
        ("kept", 4.0, "auto_accept", 40.0, [_decision("", "reject")]),
        ("rkept", 5.0, "review", 50.0, [_decision("", "reject")]),
        ("undone", 6.0, "auto_accept", None, [_decision("", "reject")]),
        ("fixed", 7.0, "auto_accept", None, [_decision("", "correct", corrected_value={"value": 70.0})]),
        ("esc", 8.0, "auto_accept", 80.0, [_decision("", "escalate")]),
    ]
    fields = [_field(fid, v, route) for fid, v, route, _, _ in spec]
    rs.append_result("R", {"company_id": "c1", "issuer_key": "ISS", "name": "N", "ticker": "T", "needs_review": True, "fields": fields})
    for f, (fid, _, _, accepted, decisions) in zip(fields, spec, strict=True):
        key = f"ISS:{fid}:{D}"
        if accepted is not None:
            rs.append_review_item("R", {
                "item_key": key, "issuer_key": "ISS", "company_id": "c1", "name": "N", "field_id": fid, "period_end": D,
                "basis": "", "field": f, "kind": "conflict", "new_value": f["value"],
                "accepted": {"value": accepted, "fact_id": 1, "status": "approved", "observation_id": 1}})
        for d in decisions:
            rs.append_decision_row("R", {**d, "item_key": key})


@pytest.fixture
def rs(pg, tmp_path):
    store = RunStore(pg, tmp_path / "runs")
    content = DocumentContentStore(tmp_path / "docs", dsn=pg_dsn())
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[get_document_content_store] = lambda: content
    app.dependency_overrides[settings_dep] = lambda: Settings(schema_registry_dir=tmp_path / "reg")
    app.dependency_overrides[current_user] = lambda: ALICE
    yield store
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def _export(run_id):
    r = TestClient(app).get(f"/api/runs/{run_id}/export.csv")
    assert r.status_code == 200, r.text
    return list(csv.DictReader(io.StringIO(r.text)))


def test_export_follows_review_items_and_decisions(rs):
    _seed_e(rs)
    rows = {r["field_name"]: (r["value"], r["canonical_value"], r["review_status"]) for r in _export("R")}
    assert rows == {
        "plain": ("1.0", "1.0", ""),
        "open": ("", "", "awaiting review"),
        "taken": ("3.0", "3.0", "approve"),
        "kept": ("40.0", "", "reject"),
        "rkept": ("50.0", "", "reject"),
        "undone": ("", "", "reject"),
        "fixed": ("70.0", "", "correct"),
        "esc": ("", "", "awaiting review"),
    }


def test_export_of_review_and_hold_routes_is_unchanged(rs):
    rs.save_manifest(RunManifest(run_id="R2", run_type="extraction", params=PARAMS))
    fields = [_field("w", 1.0, "review"), _field("a", 2.0, "review"), _field("h", 3.0, "hold"), _field("o", 4.0, "auto_accept")]
    del fields[3]["route"]
    rs.append_result("R2", {"company_id": "c1", "issuer_key": "ISS", "name": "N", "needs_review": True, "fields": fields})
    rs.append_decision_row("R2", _decision(f"ISS:a:{D}", "approve"))
    rs.append_decision_row("R2", _decision(f"ISS:h:{D}", "reject"))
    got = {r["field_name"]: (r["value"], r["review_status"]) for r in _export("R2")}
    assert got == {"w": ("", "awaiting review"), "a": ("2.0", "approve"), "h": ("", "reject"), "o": ("4.0", "")}


def _flow_row(rs, pg, tmp_path, company):
    class Docs:
        def readiness_by_company(self, ids):
            return {}
    flow = ArgusFlow(flow_id="f", created_at="t", updated_at="t", started_by="u", started_by_name="U", companies=[company])
    with Session(engine(pg)) as session:
        [row] = flow_rows(flow, session=session, run_store=rs, content_store=Docs(), xbrl_store=XbrlStore(tmp_path / "xbrl"),
                          idmap=IdentifierMapStore(tmp_path / "idmap.jsonl"), principal=PRINCIPAL, documents_dir=tmp_path / "d")
    return row.extracted_before


def test_argus_counts_only_decided_values(rs, pg, tmp_path):
    _seed_e(rs)
    prior = _flow_row(rs, pg, tmp_path, CompanyRef(company_id="c1", name="N"))
    assert (prior.approved, prior.waiting, prior.label, prior.date) == (3, 2, "S v2", "2026-11-01")


def test_argus_counts_rows_without_issuer_key(rs, pg, tmp_path):
    rs.save_manifest(RunManifest(run_id="RN", run_type="extraction", created_at="2026-11-01T09:00:00+00:00", params=PARAMS))
    rs.append_result("RN", {"company_id": "c2", "name": "N2", "fields": [_field("n1", 1.0, "auto_accept"), _field("n2", 2.0, "review")]})
    rs.append_decision_row("RN", _decision("c2:n2", "approve"))
    assert _flow_row(rs, pg, tmp_path, CompanyRef(company_id="c2", name="N2")).approved == 2


def test_conflict_card_carries_value_evidence_and_confidence(rs):
    _seed_e(rs)
    r = TestClient(app).get(f"/api/review/runs/R/items/ISS:open:{D}/context")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"]["kind"] == "conflict"
    assert (body["value"]["value"], body["value"]["field_id"]) == (2.0, "open")
    assert [(e["doc_id"], e["quote"], e["char_start"]) for e in body["evidence"]] == [("d1", "Revenue was 2.0", 10)]
    assert body["confidence"]["final"] == 0.9 and body["confidence"]["grounded"] is True
    assert body["conflict"] == {"conflicting_sources": False, "alternatives": []}
    assert body["item"]["payload"]["accepted"]["value"] == 20.0


def test_value_item_context_is_unchanged(rs):
    rs.save_manifest(RunManifest(run_id="R2", run_type="extraction", params=PARAMS))
    f = _field("w", 1.0, "review")
    rs.append_result("R2", {"company_id": "c1", "issuer_key": "ISS", "name": "N", "fields": [f]})
    rs.append_review_item("R2", {"item_key": f"ISS:w:{D}", "issuer_key": "ISS", "company_id": "c1", "name": "N", "field_id": "w",
                                 "period_end": D, "field": f})
    body = TestClient(app).get(f"/api/review/runs/R2/items/ISS:w:{D}/context").json()
    assert (body["item"]["kind"], body["value"]["value"]) == ("value", 1.0)
