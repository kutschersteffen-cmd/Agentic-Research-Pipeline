from __future__ import annotations

from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.config import Settings
from arp.orchestration.review_queue import append_decision
from arp.review.context import build_context, similar_decisions
from arp.schemas.common import RunManifest
from arp.schemas.datapoints import DataPointSchema, FieldDefinition
from arp.schemas.review import ReviewDecision
from arp.storage.run_store import RunStore

CAROL = Principal(user_id="u_carol", name="Carol Approver", role="approver")
ISSUER = "ARP:9f1c"  # provisional issuer keys contain ':'


def _field(period, doc_type="annual_report", value=100, **kw):
    return {"field_id": "f1", "field_name": "Scope 1", "value": value, "confidence": 0.7, "period_end": period,
            "citations": [{"doc_id": "d1", "doc_type": doc_type, "quote": "100", "grounded": True}], **kw}


def _run(rs, run_id, created_at, field, issuer=ISSUER, trial=False, decide=True):
    rs.save_manifest(RunManifest(run_id=run_id, run_type="extraction", created_at=created_at,
                                 params={"trial": True} if trial else {}))
    rs.append_jsonl(rs._results_path(run_id), {"company_id": "C1", "issuer_key": issuer, "fields": [field]})
    key = f"{issuer}:f1:{field['period_end']}"
    if decide:
        append_decision(rs, run_id, ReviewDecision(
            item_key=key, decision="approve", reason_code="confirmed", reviewer="Alice", user_id="u_alice",
            role="approver", snapshot_id="s", step="first"))
    return key


def test_similar_matches_field_issuer_doc_type(tmp_path):
    rs = RunStore(tmp_path)
    key = _run(rs, "cur", "2024-06-01T00:00:00Z", _field("2024-12-31"), decide=False)
    match = _run(rs, "r1", "2024-01-01T00:00:00Z", _field("2023-12-31", value=90))
    _run(rs, "r2", "2024-02-01T00:00:00Z", _field("2023-12-31", doc_type="sustainability_report"))
    _run(rs, "r3", "2024-03-01T00:00:00Z", _field("2023-12-31"), issuer="ISS2")
    [hit] = similar_decisions(rs, run_id="cur", item_key=key)
    assert hit["run_id"] == "r1" and hit["item_key"] == match and hit["period"] == "2023-12-31" and hit["value"] == 90
    assert hit["decision"]["decision"] == "approve"
    assert "user_id" not in hit["decision"] and "reviewer" not in hit["decision"] and "user_id" not in hit


def test_similar_excludes_current_run_and_trials(tmp_path):
    rs = RunStore(tmp_path)
    key = _run(rs, "cur", "2024-06-01T00:00:00Z", _field("2024-12-31"))  # decided, but the current run
    _run(rs, "trial", "2024-05-01T00:00:00Z", _field("2023-12-31"), trial=True)
    _run(rs, "old", "2023-01-01T00:00:00Z", _field("2022-12-31"))
    _run(rs, "new", "2024-04-01T00:00:00Z", _field("2023-12-31"))
    assert [h["run_id"] for h in similar_decisions(rs, run_id="cur", item_key=key)] == ["new", "old"]
    assert similar_decisions(rs, run_id="cur", item_key=key, limit=1)[0]["run_id"] == "new"


def test_similar_endpoint_and_404(tmp_path):
    rs = RunStore(tmp_path)
    key = _run(rs, "cur", "2024-06-01T00:00:00Z", _field("2024-12-31"), decide=False)
    _run(rs, "r1", "2024-01-01T00:00:00Z", _field("2023-12-31"))
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[current_user] = lambda: CAROL
    try:
        c = TestClient(app)
        r = c.get(f"/api/extraction/items/{key}/similar", params={"run_id": "cur"})
        assert r.status_code == 200 and [h["run_id"] for h in r.json()["items"]] == ["r1"]
        assert "user_id" not in r.text and "Alice" not in r.text
        assert c.get(f"/api/extraction/items/{key}/similar", params={"run_id": "nope"}).status_code == 404
        assert c.get("/api/extraction/items/C1/similar", params={"run_id": "cur"}).status_code == 404
        assert c.get(f"/api/extraction/items/{ISSUER}:f9:2024-12-31/similar", params={"run_id": "cur"}).status_code == 404
    finally:
        app.dependency_overrides.pop(get_run_store, None)
        app.dependency_overrides.pop(current_user, None)


def _context_with(tmp_path, alternatives, schema_fields=None):
    rs = RunStore(tmp_path / "runs")
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    if schema_fields:
        (rs.run_dir("ext1") / "schema.json").write_text(
            DataPointSchema(schema_id="s1", name="s", fields=schema_fields).model_dump_json())
    field = _field("2024-12-31", alternatives=alternatives)
    key = f"{ISSUER}:f1:2024-12-31"
    rs.append_jsonl(rs._review_queue_path("ext1"), {"item_key": key, "issuer_key": ISSUER, "company_id": "C1",
                                                   "field_id": "f1", "period_end": "2024-12-31", "field": field})
    rs.append_jsonl(rs._results_path("ext1"), {"company_id": "C1", "issuer_key": ISSUER, "schema_id": "s1",
                                              "fields": [field]})
    settings = Settings(schema_registry_dir=tmp_path / "reg")
    return build_context(rs, "ext1", key, CAROL, settings=settings, content_store=None)["suggested_correction"]


def test_suggested_correction_carries_the_printed_number(tmp_path):
    cited = [{"doc_id": "d1", "doc_type": "annual_report", "quote": "110", "grounded": False}]
    alts = [
        {"value": 95, "raw_value_text": "95", "source": "extractor", "citations": []},
        {"value": 110, "source": "verifier", "citations": cited},  # a bare number: its scale is unknown
        {"value": 120, "raw_value_text": "$120 million", "source": "adjudicator", "citations": cited},
    ]
    assert _context_with(tmp_path / "a", alts) == {"value": "$120 million", "citations": cited}
    assert _context_with(tmp_path / "b", alts[:2]) is None  # numeric with no printed text: no prefill


def test_suggested_correction_text_field_takes_the_value(pg, tmp_path):
    spec = FieldDefinition(field_id="f1", name="f1", description="d", data_type="string", extraction_instructions="x")
    alts = [{"value": "Deloitte", "source": "verifier", "citations": []}]
    assert _context_with(tmp_path, alts, [spec]) == {"value": "Deloitte", "citations": []}



