from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.orchestration.review_queue import append_decision
from arp.review.context import build_context, page_of, page_window, write_snapshot
from arp.schemas.common import RunManifest
from arp.schemas.datapoints import DataPointSchema, FieldDefinition
from arp.schemas.review import ReviewDecision
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore

pytestmark = pytest.mark.usefixtures("pg")

ALICE = Principal(user_id="u_alice", name="Alice Reviewer", role="analyst")
BOB = Principal(user_id="u_bob", name="Bob Builder", role="analyst")
CAROL = Principal(user_id="u_carol", name="Carol Approver", role="approver")
TEXT = "Emissions (in thousands of tonnes)\nScope 1  1,234  1,100\nScope 2  500  400\n"
KEY = "ISS1:f1:2024-12-31"
START = TEXT.index("1,234")


def _citation(**kw):
    return {
        "doc_id": "d1", "doc_type": "sustainability_report", "quote": "1,234", "grounded": True,
        "company_id": "C1", "source_filename": "sr.pdf", "content_key": "ck1", "parser_version": "p1",
        "span_text": "1,234", "char_start": START, "char_end": START + 5, "match_method": "exact", **kw,
    }


FIELD = {
    "field_id": "f1", "field_name": "Scope 1", "value": 1234, "confidence": 0.7, "extractor_confidence": 0.8,
    "verifier_confidence": 0.6, "grounded": True, "period_end": "2024-12-31", "citations": [_citation()],
    "alternatives": [{"value": 1100, "source": "extractor", "citations": [_citation(quote="1,100", char_start=START + 7,
                                                                                    char_end=START + 12)]}],
    "conflicting_sources": True,
    "checks": [
        {"check_id": "numeric.in_span", "layer": 2, "outcome": "fail", "severity": "block", "detail": "x"},
        {"check_id": "format.data_type", "layer": 1, "outcome": "pass", "severity": "info"},
    ],
    "route_reasons": ["check_failed"],
}
DOC = {"doc_id": "d1", "doc_type": "sustainability_report", "title": "SR 2024", "company_id": "C1",
       "content_key": "ck1", "parser_version": "p1", "source_filename": "sr.pdf"}


def _schema(description="Direct emissions", high_risk=False):
    return DataPointSchema(schema_id="sch1", name="s", fields=[FieldDefinition(
        field_id="f1", name="Scope 1", description=description, data_type="number", extraction_instructions="x",
        high_risk=high_risk)])


@pytest.fixture
def env(tmp_path):
    rs = RunStore(tmp_path / "runs")
    store = DocumentContentStore(tmp_path / "docs")
    store.store("ck1", key_kind="file", parser_version="p1", source_suffix=".pdf", byte_size=1, text=TEXT, page_breaks=[])
    settings = Settings(schema_registry_dir=tmp_path / "reg")
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    (rs.run_dir("ext1") / "schema.json").write_text(_schema().model_dump_json())
    rs.append_jsonl(rs._review_queue_path("ext1"), {
        "item_key": KEY, "issuer_key": "ISS1", "company_id": "C1", "name": "Acme", "field_id": "f1",
        "period_end": "2024-12-31", "field": FIELD, "route_reasons": FIELD["route_reasons"],
    })
    rs.append_jsonl(rs._results_path("ext1"), {
        "company_id": "C1", "name": "Acme", "issuer_key": "ISS1", "schema_id": "sch1", "run_id": "ext1",
        "fields": [FIELD, {"field_id": "f1", "field_name": "Scope 1", "value": 1000, "confidence": 1.0,
                           "period_end": "2023-12-31"}],
        "documents": [DOC],
    })
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[get_document_content_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    yield rs, store, settings
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def _client(who=CAROL):
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def _ctx(who=CAROL):
    r = _client(who).get(f"/api/review/runs/ext1/items/{KEY}/context")
    assert r.status_code == 200, r.text
    return r.json()


def _decide(rs, who, decision="correct", reason="wrong_value", step="first", value=1100):
    append_decision(rs, "ext1", ReviewDecision(
        item_key=KEY, decision=decision, reason_code=reason, reviewer=who.name, user_id=who.user_id, role=who.role,
        corrected_value={"value": value} if decision == "correct" else None, snapshot_id="s1", step=step,
        second_required=step == "first",
    ))


def test_table_value_highlights_cell(env):
    e = _ctx()["evidence"][0]
    assert e["page_text"][e["char_start"] - e["page_start"]: e["char_end"] - e["page_start"]] == "1,234"
    line_start = e["page_text"].rfind("\n", 0, e["char_start"] - e["page_start"]) + 1
    line_end = e["page_text"].index("\n", e["char_end"] - e["page_start"])
    assert e["page_text"][line_start:line_end] == "Scope 1  1,234  1,100"
    assert e["title"] == "SR 2024" and e["page"] == 1


def test_failed_checks_in_plain_words(env):
    checks = _ctx()["failed_checks"]
    assert checks == [{"check_id": "numeric.in_span", "severity": "block",
                       "plain": "The number is not in the quoted source text.", "detail": "x"}]


def test_conflict_alternatives_with_sources(env):
    conflict = _ctx()["conflict"]
    assert conflict["conflicting_sources"] is True
    [alt] = conflict["alternatives"]
    assert alt["source"] == "extractor" and alt["citations"][0]["grounded"] is True


def test_prior_and_published_values(env):
    rs = env[0]
    rs.save_manifest(RunManifest(run_id="ext0", run_type="extraction", created_at="2020-01-01T00:00:00Z"))
    rs.append_jsonl(rs._results_path("ext0"), {"company_id": "C1", "issuer_key": "ISS1", "fields": [
        {"field_id": "f1", "field_name": "Scope 1", "value": 1200, "confidence": 0.9, "period_end": "2024-12-31"}]})
    rs.append_jsonl(rs._review_queue_path("ext0"), {"item_key": KEY})
    append_decision(rs, "ext0", ReviewDecision(
        item_key=KEY, decision="approve", reason_code="confirmed", reviewer="A", user_id="u_a", role="approver",
        snapshot_id="s0", step="first"))
    ctx = _ctx()
    assert ctx["prior_period"] == {"value": 1000, "period_end": "2023-12-31"}
    assert ctx["published"] == {"value": 1200, "run_id": "ext0", "decided_by": "human"}


def test_confidence_components(env):
    rs = env[0]
    c = _ctx()["confidence"]
    assert (c["final"], c["extractor"], c["verifier"], c["grounded"]) == (0.7, 0.8, 0.6, True)
    assert c["match_methods"] == ["exact"] and c["auto_accept_min"] == 0.9
    legacy = {"field_id": "f1", "field_name": "Scope 1", "value": 5, "confidence": 0.5, "period_end": "2022-12-31"}
    rs.append_jsonl(rs._review_queue_path("ext1"), {"item_key": "ISS1:f1:2022-12-31", "company_id": "C1",
                                                   "field_id": "f1", "field": legacy})
    r = _client().get("/api/review/runs/ext1/items/ISS1:f1:2022-12-31/context").json()["confidence"]
    assert r["extractor"] is None and r["verifier"] is None


def test_field_definition_from_run_snapshot(env):
    fd = _ctx()["field_definition"]
    assert fd["description"] == "Direct emissions" and fd["first_audit_passed"] is False


def test_text_unavailable_gives_none(env, tmp_path):
    rs, _, settings = env
    off = DocumentContentStore(tmp_path / "off", enabled=False)
    bundle = build_context(rs, "ext1", KEY, CAROL, settings=settings, content_store=off)
    e = bundle["evidence"][0]
    assert e["page_text"] is None and e["page_start"] is None and e["quote"] == "1,234"
    assert build_context(rs, "ext1", KEY, CAROL, settings=settings, content_store=None)["evidence"][0]["page_text"] is None


def test_paginated_text_page_window_and_page_of():
    text = "a" * 60
    assert page_window(text, [0, 20, 45], 1) == (0, 20, 3)
    assert page_window(text, [0, 20, 45], 3) == (45, 60, 3)
    assert page_of(text, [0, 20, 45], 25) == 2
    long = ("x" * 99 + "\n") * 150  # 15,000 chars, no page breaks
    start, end, pages = page_window(long, [], 1)
    assert (start, end, pages) == (0, 10_000, 2) and long[end - 1] == "\n"
    assert page_of(long, [], 12_000) == 2


def test_source_page_endpoint(env):
    c = _client()
    r = c.get(f"/api/review/runs/ext1/items/{KEY}/source", params={"doc_id": "d1", "page": 1})
    assert r.status_code == 200, r.text
    assert r.json()["page_text"] == TEXT and r.json()["pages"] == 1 and r.json()["title"] == "SR 2024"
    assert c.get(f"/api/review/runs/ext1/items/{KEY}/source", params={"doc_id": "nope"}).status_code == 404
    assert c.get(f"/api/review/runs/ext1/items/{KEY}/source", params={"doc_id": "d1", "page": 2}).status_code == 404


def _high_risk(rs):
    (rs.run_dir("ext1") / "schema.json").write_text(_schema(high_risk=True).model_dump_json())


def test_blind_view_hides_first_decision(env):
    rs = env[0]
    _high_risk(rs)
    _decide(rs, ALICE)
    bob = _ctx(BOB)
    assert bob["decisions"] == [] and bob["blind"] is True
    for who in (ALICE, CAROL):
        ctx = _ctx(who)
        assert len(ctx["decisions"]) == 1 and ctx["blind"] is False


def test_blind_history_and_decisions_hidden(env):
    rs = env[0]
    _high_risk(rs)
    _decide(rs, ALICE)
    c = _client(BOB)
    assert c.get("/api/extraction/runs/ext1/review-history", params={"item_key": KEY}).json()["history"] == []
    got = c.get("/api/extraction/runs/ext1/review-decisions").json()
    assert KEY not in got["decisions"] and got["states"][KEY]["state"] == "first_done"


def test_no_user_id_in_review_responses(env):
    rs = env[0]
    _decide(rs, ALICE)
    _decide(rs, BOB, step="second")
    c = _client(CAROL)
    for url, params in [(f"/api/review/runs/ext1/items/{KEY}/context", None),
                        ("/api/extraction/runs/ext1/review-decisions", None),
                        ("/api/extraction/runs/ext1/review-history", {"item_key": KEY})]:
        text = c.get(url, params=params).text
        assert KEY in text
        assert "user_id" not in text and "Alice Reviewer" not in text and "Bob Builder" not in text


def test_snapshot_reopens_identical_after_field_definition_change(env):
    rs, store, settings = env
    bundle = build_context(rs, "ext1", KEY, CAROL, settings=settings, content_store=store)
    sid = write_snapshot(rs, "ext1", bundle)
    c = _client()
    first = c.get(f"/api/review/runs/ext1/snapshots/{sid}")
    assert first.status_code == 200 and first.headers["content-type"] == "application/json"
    (rs.run_dir("ext1") / "schema.json").write_text(_schema("New wording", high_risk=True).model_dump_json())
    again = c.get(f"/api/review/runs/ext1/snapshots/{sid}")
    assert again.content == first.content
    assert json.loads(again.content)["field_definition"]["description"] == "Direct emissions"
    assert _ctx()["field_definition"]["description"] == "New wording"
    assert c.get("/api/review/runs/ext1/snapshots/snap_missing").status_code == 404
    assert c.get("/api/review/runs/ext1/snapshots/..bad").status_code == 400


def test_etag_stable_and_changes_with_state(env):
    rs = env[0]
    first = _ctx()["etag"]
    assert _ctx()["etag"] == first
    _decide(rs, ALICE)
    assert _ctx()["etag"] != first


def test_context_unknown_item_404(env):
    assert _client().get("/api/review/runs/ext1/items/nope/context").status_code == 404
