from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.api.review_endpoints import submit_review
from arp.cli.identity import identity_app
from arp.config import Settings
from arp.extraction.history import PriorValue, RunHistory
from arp.orchestration.review_queue import effective_decisions, item_state
from arp.review.context import build_context
from arp.review.decide import sampled, second_review_reasons
from arp.review.items import get_item, list_open_items
from arp.schemas.common import RunManifest
from arp.storage.document_store import DocumentContentStore
from arp.storage.postgres_company_facts_projection import resolve_extraction_fact
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry
from tests.conftest import PRINCIPAL
from tests.test_review_context import DOC, FIELD, KEY, START, TEXT, _schema

ALICE = Principal(user_id="u_alice", name="Alice Reviewer", role="analyst")
ALICE2 = Principal(user_id="u_alice", name="alice ", role="analyst")
BOB = Principal(user_id="u_bob", name="Bob Builder", role="analyst")
CAROL = Principal(user_id="u_carol", name="Carol Approver", role="approver")
DAVE = Principal(user_id="u_dave", name="Dave Approver", role="approver")
HELD = "held:C1:d1"
CIT = {"doc_id": "d1", "doc_type": "sustainability_report", "quote": "Scope 1  1,234  1,100"}  # a bare number never grounds
CORRECT = {"decision": "correct", "reason_code": "wrong_value", "corrected_value": {"value": 1100}, "correction_citation": CIT}
APPROVE = {"decision": "approve", "reason_code": "confirmed"}


@pytest.fixture
def env(tmp_path):
    rs = RunStore(tmp_path / "runs")
    store = DocumentContentStore(tmp_path / "docs")
    store.store("ck1", key_kind="file", parser_version="p1", source_suffix=".pdf", byte_size=1, text=TEXT, page_breaks=[])
    settings = Settings(schema_registry_dir=tmp_path / "reg", second_review_sample_rate=0.0)
    reg = SchemaRegistry(settings.schema_registry_dir)
    released = reg.release(reg.save(_schema()).schema_id, 1)
    reg.record_first_audit("f1", 1, "auditor")
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    (rs.run_dir("ext1") / "schema.json").write_text(released.model_dump_json())
    rs.append_jsonl(rs.review_queue_path("ext1"), {
        "item_key": KEY, "issuer_key": "ISS1", "company_id": "C1", "name": "Acme", "field_id": "f1",
        "period_end": "2024-12-31", "field": FIELD, "route_reasons": FIELD["route_reasons"],
    })
    rs.append_jsonl(rs.results_path("ext1"), {
        "company_id": "C1", "name": "Acme", "issuer_key": "ISS1", "schema_id": "sch1", "run_id": "ext1",
        "fields": [FIELD], "documents": [DOC], "held_documents": [DOC],
    })
    rs.save_manifest(RunManifest(run_id="idn1", run_type="identity"))
    rs.append_jsonl(rs.review_queue_path("idn1"), {"item_key": "C1", "company_id": "C1", "input_name": "Acme"})
    rs.save_manifest(RunManifest(run_id="thm1", run_type="theme"))
    rs.append_jsonl(rs.review_queue_path("thm1"), {"item_key": "C1:a1", "activity_id": "a1"})
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[get_document_content_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    yield rs, store, settings
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def client(who):
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def ctx(c, key=KEY, run_id="ext1"):
    r = c.get(f"/api/review/runs/{run_id}/items/{key}/context")
    assert r.status_code == 200, r.text
    return r.json()


def decide(who, body, key=KEY, run_id="ext1", etag=None):
    c = client(who)
    etag = etag or ctx(c, key, run_id)["etag"]
    return c.post(f"/api/review/runs/{run_id}/items/{key}/decision", json={**body, "context_etag": etag})


def rows(rs, run_id="ext1"):
    return rs.read_jsonl(rs.review_decisions_path(run_id))


def test_correction_without_citation_is_422(env):
    body = {**CORRECT, "correction_citation": None}
    r = decide(ALICE, body)
    assert r.status_code == 422 and "citation" in r.text
    assert rows(env[0]) == []


def test_edit_decision_is_422(env):
    assert decide(ALICE, {"decision": "edit", "reason_code": "wrong_value", "corrected_value": {"value": 1}}).status_code == 422


def test_approve_needs_confirmed_reason(env):
    assert decide(ALICE, {"decision": "approve", "reason_code": "wrong_value"}).status_code == 422
    assert decide(ALICE, {"decision": "reject", "reason_code": "confirmed"}).status_code == 422


def test_ungrounded_correction_citation_is_422(env):
    r = decide(ALICE, {**CORRECT, "corrected_value": {"value": 9999}, "correction_citation": {**CIT, "quote": "Scope 1  9,999"}})
    assert r.status_code == 422 and "not in the source text" in r.text
    assert rows(env[0]) == []


def test_correction_citation_from_foreign_doc_is_422(env):
    r = decide(ALICE, {**CORRECT, "correction_citation": {**CIT, "doc_id": "d9"}})
    assert r.status_code == 422 and "one of this item's documents" in r.text


def test_correction_number_not_in_span_is_422(env):
    r = decide(ALICE, {**CORRECT, "corrected_value": {"value": 1300}, "correction_citation": {**CIT, "quote": "Scope 1  1,234"}})
    assert r.status_code == 422 and "corrected number" in r.text


def test_source_text_unavailable_is_422(env, tmp_path):
    app.dependency_overrides[get_document_content_store] = lambda: DocumentContentStore(tmp_path / "off", enabled=False)
    r = decide(ALICE, CORRECT)
    assert r.status_code == 422 and "source text unavailable" in r.text


def test_grounded_correction_stored_with_server_offsets(env):
    cit = {**CIT, "quote": "Scope 1  1,234", "grounded": True, "char_start": 0, "char_end": 3, "span_text": "x"}
    r = decide(ALICE, {**CORRECT, "corrected_value": {"value": 1234, "unit": "t"}, "correction_citation": cit})
    assert r.status_code == 200, r.text
    stored = rows(env[0])[-1]["correction_citation"]
    assert (stored["char_start"], stored["char_end"]) == (TEXT.index("Scope 1  1,234"), START + 5)
    assert stored["span_text"] == "Scope 1  1,234"
    assert stored["match_method"] == "exact" and stored["grounded"] is True
    assert stored["source_filename"] == "sr.pdf"  # the published correction can open its source


def test_corrected_keys_checked(env):
    assert decide(ALICE, {**CORRECT, "corrected_value": {"value": 1100, "isic_code": "x"}}).status_code == 422
    assert decide(ALICE, {**CORRECT, "corrected_value": {"unit": "t"}}).status_code == 422


def test_same_user_refused_as_second_reviewer(env):
    r = decide(ALICE, CORRECT)
    assert r.json()["state"] == "first_done" and r.json()["second_reasons"] == ["correction"]
    r = decide(ALICE2, CORRECT)
    assert r.status_code == 409 and "different person" in r.text
    r = decide(BOB, CORRECT)
    assert r.status_code == 200 and r.json() == {**r.json(), "state": "second_done", "second_reasons": []}
    assert rows(env[0])[-1]["step"] == "second" and rows(env[0])[-1]["second_required"] is False


def test_disagreement_goes_to_approver(env):
    decide(ALICE, CORRECT)
    assert decide(BOB, APPROVE).json()["state"] == "disagreed"
    r = decide(BOB, APPROVE)
    assert r.status_code == 403 and "approver" in r.text
    r = decide(CAROL, APPROVE)
    assert r.json()["state"] == "final" and rows(env[0])[-1]["step"] == "resolution"
    eff = effective_decisions(env[0], "ext1", cosign_required={"edit"})[KEY]
    assert eff["decision"] == "approve" and eff["user_id"] == "u_carol"


def test_resolver_cannot_be_a_reviewer(env):
    decide(CAROL, CORRECT)
    decide(BOB, APPROVE)
    r = decide(CAROL, APPROVE)
    assert r.status_code == 409 and "resolver" in r.text
    assert decide(DAVE, APPROVE).status_code == 200


def test_resolution_cannot_escalate(env):
    decide(ALICE, CORRECT)
    decide(BOB, APPROVE)
    assert decide(CAROL, {"decision": "escalate", "reason_code": "needs_expert"}).status_code == 422


def test_escalate_keeps_pending_and_needs_approver(env):
    r = decide(ALICE, {"decision": "escalate", "reason_code": "needs_expert"})
    assert r.json() == {**r.json(), "state": "pending", "second_reasons": []}
    [item] = [i for i in client(BOB).get("/api/review/items").json()["items"] if i["item_key"] == KEY]
    assert item["escalated"] is True
    r = decide(BOB, APPROVE)
    assert r.status_code == 403 and "escalated" in r.text
    assert decide(CAROL, APPROVE).json()["state"] == "final"


@pytest.mark.parametrize(("decision", "kw", "want"), [
    ("correct", {}, ["correction"]),
    ("approve", {"high_risk": True}, ["high_risk"]),
    ("approve", {"prior": 1200}, ["published_change"]),
    ("approve", {"prior": 1234}, []),
    ("reject", {"prior": 1234}, ["published_change"]),
    ("correct", {"prior": 1100}, ["correction"]),
    ("approve", {"first_audit_passed": False}, ["first_audit_pending"]),
    ("approve", {"first_audit_passed": None}, []),
    ("approve", {"sample_rate": 1.0}, ["sample"]),
    ("approve", {"sample_rate": 0.0}, []),
    ("escalate", {"high_risk": True, "sample_rate": 1.0}, []),
    ("approve", {"kind": "restatement_candidate"}, ["published_change"]),
])
def test_second_required_reasons(decision, kw, want):
    prior = kw.pop("prior", None)
    args = {"kind": "value", "item_key": KEY, "high_risk": False, "first_audit_passed": True, "current_value": 1234,
            "corrected_value": {"value": 1100} if decision == "correct" else None, "sample_rate": 0.0,
            "prior": PriorValue(value=prior, canonical_value=None, run_id="r0", decided_by="human") if prior else None, **kw}
    assert second_review_reasons(decision, **args) == want


def test_sample_is_deterministic_per_item_key():
    assert all(sampled(f"k{i}", 0.5) == sampled(f"k{i}", 0.5) for i in range(50))
    share = sum(sampled(f"ISS{i}:f1:2024-12-31", 0.1) for i in range(1000)) / 1000
    assert 0.05 <= share <= 0.15


def test_stale_context_etag_is_409(env):
    old = ctx(client(BOB))["etag"]
    decide(ALICE, CORRECT)
    r = decide(BOB, CORRECT, etag=old)
    assert r.status_code == 409 and "reload" in r.text


def test_two_principals_same_etag_and_text_cache_ignored(env):
    rs, store, settings = env
    decide(CAROL, APPROVE)
    assert ctx(client(CAROL))["decisions"][0]["mine"] is True
    assert ctx(client(CAROL))["etag"] == ctx(client(BOB))["etag"]
    assert (build_context(rs, "ext1", KEY, BOB, settings=settings, content_store=None)["etag"]
            == build_context(rs, "ext1", KEY, BOB, settings=settings, content_store=store)["etag"])


def test_decision_writes_snapshot_of_context(env):
    rs = env[0]
    loaded = ctx(client(ALICE))
    r = decide(ALICE, APPROVE, etag=loaded["etag"])
    assert r.json()["state"] == "final"
    sid = rows(rs)[-1]["snapshot_id"]
    assert r.json()["snapshot_id"] == sid
    assert json.loads(rs.snapshot_path("ext1", sid).read_text()) == loaded


def test_snapshot_strips_mine(env):
    rs = env[0]
    decide(CAROL, {"decision": "reject", "reason_code": "wrong_value"})
    decide(CAROL, APPROVE)
    snap = json.loads(rs.snapshot_path("ext1", rows(rs)[-1]["snapshot_id"]).read_text())
    assert snap["decisions"] and all("mine" not in d for d in snap["decisions"])
    assert "mine" not in snap["item"]["decision"]


def test_quarantined_document_correct_is_422(env):
    assert decide(CAROL, {**CORRECT, "correction_citation": None}, key=HELD).status_code == 422


@pytest.mark.parametrize(("rate", "state", "reasons"), [(1.0, "first_done", ["sample"]), (0.0, "final", [])])
def test_release_held_document_needs_second_when_sampled(env, rate, state, reasons):
    app.dependency_overrides[settings_dep] = lambda: env[2].model_copy(update={"second_review_sample_rate": rate})
    r = decide(CAROL, APPROVE, key=HELD)
    assert r.status_code == 200, r.text
    assert (r.json()["state"], r.json()["second_reasons"]) == (state, reasons)


def test_release_held_document_needs_approver(env):
    r = decide(ALICE, APPROVE, key=HELD)
    assert r.status_code == 403 and "approver" in r.text
    assert decide(ALICE, {"decision": "reject", "reason_code": "wrong_entity"}, key=HELD).status_code == 200


def test_identity_correct_without_citation_needs_comment(env):
    body = {"decision": "correct", "reason_code": "wrong_entity", "corrected_value": {"resolved_website": "https://acme.com"}}
    r = decide(ALICE, body, key="C1", run_id="idn1")
    assert r.status_code == 422 and "comment" in r.text
    empty = {**body, "corrected_value": {"resolved_website": None, "resolved_cik": ""}, "comment": "register"}
    assert decide(ALICE, empty, key="C1", run_id="idn1").status_code == 422
    r = decide(ALICE, {**body, "comment": "company register"}, key="C1", run_id="idn1")
    assert (r.json()["state"], r.json()["second_reasons"]) == ("first_done", ["correction"])


def test_other_kind_refused_400(env):
    r = decide(CAROL, APPROVE, key="C1:a1", run_id="thm1", etag="x")
    assert r.status_code == 400 and "run's review endpoint" in r.text


def test_unknown_item_404(env):
    assert decide(CAROL, APPROVE, key="nope", etag="x").status_code == 404


def test_spoofed_reviewer_body_is_ignored(env):
    r = decide(PRINCIPAL, {**APPROVE, "reviewer": "Mallory"})
    assert r.status_code == 200, r.text
    row = rows(env[0])[-1]
    assert row["user_id"] == "u_test" and row["reviewer"] == "Test"


def test_cli_identity_correct_without_comment_exits_1():
    args = ["review", "r1", "C1", "--decision", "correct", "--website", "https://a.com"]
    res = CliRunner().invoke(identity_app, [*args, "--reason", "wrong_entity"])
    assert res.exit_code == 1 and "--comment" in res.output


@pytest.mark.parametrize("decision", ["reject", "escalate", "correct"])
def test_cli_identity_review_needs_reason(decision):
    res = CliRunner().invoke(identity_app, ["review", "r1", "C1", "--decision", decision])
    assert res.exit_code != 0 and "--reason is required" in res.output


def test_cli_review_queue_dev_mode_without_token(env, monkeypatch):
    import arp.cli.identity as cli

    monkeypatch.delenv("ARP_CLI_TOKEN", raising=False)
    monkeypatch.setattr(cli, "_run_store", lambda: env[0])
    monkeypatch.setattr(cli, "get_settings", lambda: env[2])
    res = CliRunner().invoke(identity_app, ["review-queue", "idn1"])
    assert res.exit_code == 0, res.output
    assert "C1 [pending]" in res.output


def test_old_review_routes_removed(env):
    c = client(CAROL)
    assert c.post("/api/extraction/runs/r1/review", json={"item_key": "k", "decision": "approve"}).status_code in (404, 405)
    assert c.get("/api/extraction/runs/r1/review-queue").status_code in (404, 405)
    assert c.post("/api/identity/runs/r1/review", json={"item_key": "k", "decision": "approve"}).status_code in (404, 405)
    assert c.get("/api/identity/runs/r1/review-queue").status_code in (404, 405)


def test_submit_review_rejects_unknown_decision(tmp_path):
    with pytest.raises(ValueError):
        submit_review(RunStore(tmp_path / "runs"), "r1", item_key="k", decision="maybe", edited_value=None)


def test_legacy_review_routes_refuse_workbench_runs_and_keys(env):
    rs, c = env[0], client(CAROL)
    for url, key in [
        ("/api/financials/runs/ext1/review", KEY), ("/api/financials/runs/ext1/review", "rst_1"),
        ("/api/financials/runs/idn1/review", "C1"), ("/api/voting/runs/ext1/review", KEY),
    ]:
        r = c.post(url, json={"item_key": key, "decision": "approve", "reviewer": "X"})
        assert r.status_code == 400, (url, key)
    assert rs.read_jsonl(rs.review_decisions_path("ext1")) == rs.read_jsonl(rs.review_decisions_path("idn1")) == []
    for key in ("isic:C1", "held:C1:d1", "rst_1"):
        assert c.post("/api/themes/runs/thm1/review", json={"item_key": key, "decision": "approve"}).status_code == 400
    assert c.post("/api/themes/runs/thm1/review", json={"item_key": "C1:a1", "decision": "approve"}).status_code == 200


def test_legacy_review_routes_refuse_holdings_runs(env):
    rs, c = env[0], client(CAROL)
    rs.save_manifest(RunManifest(run_id="hold1", run_type="holdings"))
    rs.append_jsonl(rs.review_queue_path("hold1"), {"item_key": "isin:US0378331005", "isin": "US0378331005"})
    for url in ("/api/financials/runs/hold1/review", "/api/voting/runs/hold1/review"):
        for key in ("isin:US0378331005", "other"):
            r = c.post(url, json={"item_key": key, "decision": "approve", "reviewer": "X"})
            assert r.status_code == 400, (url, key)
    assert c.post("/api/themes/runs/thm1/review", json={"item_key": "isin:US0378331005", "decision": "approve"}).status_code == 400
    assert rs.read_jsonl(rs.review_decisions_path("hold1")) == rs.read_jsonl(rs.review_decisions_path("thm1")) == []


def test_get_item(env):
    rs = env[0]
    item = get_item(rs, "ext1", HELD, ALICE)
    assert item.kind == "quarantined_document" and item.payload["doc_id"] == "d1"
    assert get_item(rs, "ext1", KEY, ALICE).kind == "value"
    assert get_item(rs, "ext1", "nope", ALICE) is None
    assert get_item(rs, "missing", KEY, ALICE) is None
    rs.save_manifest(RunManifest(run_id="vot1", run_type="voting"))
    rs.append_jsonl(rs.review_queue_path("vot1"), {"item_key": "m1"})
    assert get_item(rs, "vot1", "m1", ALICE) is None


def test_stray_second_after_final_keeps_state():
    first = {"item_key": "k", "decision": "approve", "step": "first", "user_id": "a"}
    second = {"item_key": "k", "decision": "reject", "step": "second", "user_id": "b"}
    s = item_state([first, second], cosigned_at=set(), cosign_required=set())
    assert s.state == "final" and s.effective is first


def test_correction_grounded_with_settings_fuzzy_threshold(env):
    quote = "Emissions (in thousands of tonnes) Scope 1  1,234  1,100 zz"  # fuzzy match, score ~0.96
    body = {**CORRECT, "correction_citation": {**CIT, "quote": quote}}
    app.dependency_overrides[settings_dep] = lambda: env[2].model_copy(update={"grounding_fuzzy_threshold": 0.99})
    r = decide(ALICE, body)
    assert r.status_code == 422 and "not in the source text" in r.text
    app.dependency_overrides[settings_dep] = lambda: env[2]
    assert decide(ALICE, body).status_code == 200
    assert rows(env[0])[-1]["correction_citation"]["match_method"] == "fuzzy"


def test_number_checked_without_field_definition(env):
    (env[0].run_dir("ext1") / "schema.json").unlink()
    r = decide(ALICE, {**CORRECT, "corrected_value": {"value": 1300}})
    assert r.status_code == 422 and "corrected number" in r.text


def test_lone_analyst_cannot_overturn_two_person_outcome(env):
    decide(ALICE, CORRECT)
    assert decide(BOB, CORRECT).json()["state"] == "second_done"
    r = decide(ALICE, {"decision": "reject", "reason_code": "wrong_value"})
    assert (r.json()["state"], r.json()["second_reasons"]) == ("first_done", ["published_change"])
    eff = effective_decisions(env[0], "ext1", cosign_required={"edit"})
    assert KEY not in eff


def test_resolved_item_redecided_only_by_approver(env):
    decide(ALICE, CORRECT)
    decide(BOB, APPROVE)
    assert decide(CAROL, APPROVE).json()["state"] == "final"
    r = decide(BOB, {"decision": "reject", "reason_code": "wrong_value"})
    assert r.status_code == 403 and "approver" in r.text
    r = decide(DAVE, {"decision": "reject", "reason_code": "wrong_value"})
    assert (r.json()["state"], r.json()["second_reasons"]) == ("first_done", ["published_change"])


def test_agreeing_redecision_on_final_item_stays_single_reviewer(env):
    assert decide(CAROL, APPROVE).json()["state"] == "final"
    r = decide(ALICE, APPROVE)
    assert (r.json()["state"], r.json()["second_reasons"]) == ("final", [])


AUTO_KEY = "ISS1:f1:2023-12-31"


def _add_auto_accepted(rs, route="auto_accept"):
    path = rs.results_path("ext1")
    row = rs.read_jsonl(path)[0]
    row["fields"].append({**FIELD, "period_end": "2023-12-31", "route": route, "route_reasons": [], "checks": []})
    path.write_text(json.dumps(row) + "\n")


def test_auto_accepted_row_decidable_but_not_listed(env):
    rs = env[0]
    _add_auto_accepted(rs)
    assert AUTO_KEY not in {i.item_key for i in list_open_items(rs, ALICE, run_id="ext1")}
    assert ctx(client(ALICE), AUTO_KEY)["item"]["kind"] == "value"
    assert decide(ALICE, CORRECT, key=AUTO_KEY).json()["state"] == "first_done"
    agree = {**CORRECT, "correction_citation": {**CIT, "quote": rows(rs)[-1]["correction_citation"]["span_text"]}}  # the UI's Agree
    assert decide(BOB, agree, key=AUTO_KEY).json()["state"] == "second_done"
    row = rs.read_jsonl(rs.results_path("ext1"))[0]
    value, status, _ = resolve_extraction_fact("C1", row, effective_decisions(rs, "ext1", cosign_required={"edit"}), {KEY})
    assert status == "pending_review"  # KEY itself is still open
    value, status, _ = resolve_extraction_fact("C1", row, effective_decisions(rs, "ext1", cosign_required={"edit"}), set())
    assert status == "edited" and value["fields"][1]["value"] == 1100


def test_open_review_on_auto_accepted_row_is_not_system_decided(env):
    rs = env[0]
    _add_auto_accepted(rs)
    assert RunHistory.load(rs).last_decided(AUTO_KEY).decided_by == "system"
    assert decide(ALICE, CORRECT, key=AUTO_KEY).json()["state"] == "first_done"
    assert RunHistory.load(rs).last_decided(AUTO_KEY) is None


def _queue_failure(rs):
    rs.append_jsonl(rs.review_queue_path("ext1"), {"item_key": "C2", "company_id": "C2", "name": "Beta", "rationale": "no docs"})


def test_extraction_failure_report_approve_is_final(env):
    rs = env[0]
    _queue_failure(rs)
    assert "C2" in {i.item_key for i in list_open_items(rs, ALICE, run_id="ext1")}
    r = decide(ALICE, APPROVE, key="C2")
    assert r.status_code == 200 and r.json() == {**r.json(), "state": "final", "second_reasons": []}
    assert "C2" not in {i.item_key for i in list_open_items(rs, ALICE, run_id="ext1")}
    assert decide(ALICE, CORRECT, key="C2").status_code == 422


def test_extraction_failure_report_escalate_needs_approver(env):
    rs = env[0]
    _queue_failure(rs)
    assert decide(ALICE, {"decision": "escalate", "reason_code": "needs_expert"}, key="C2").json()["state"] == "pending"
    assert "C2" in {i.item_key for i in list_open_items(rs, ALICE, run_id="ext1")}
    assert decide(BOB, APPROVE, key="C2").status_code == 403
    assert decide(CAROL, {"decision": "reject", "reason_code": "other"}, key="C2").json()["state"] == "final"


def test_held_field_key_is_not_decidable(env):
    rs = env[0]
    _add_auto_accepted(rs, route="hold")
    assert client(ALICE).get(f"/api/review/runs/ext1/items/{AUTO_KEY}/context").status_code == 404
    assert decide(ALICE, APPROVE, key=AUTO_KEY, etag="x").status_code == 404
    assert rows(rs) == []


def test_open_review_on_auto_accepted_row_projects_pending(env):
    rs = env[0]
    _add_auto_accepted(rs)
    assert decide(ALICE, CORRECT, key=AUTO_KEY).json()["state"] == "first_done"
    row = rs.read_jsonl(rs.results_path("ext1"))[0]
    row["fields"] = row["fields"][1:]  # only the auto-accepted field
    open_keys = {AUTO_KEY}  # what materialize adds: latest minus effective decisions
    assert resolve_extraction_fact("C1", row, effective_decisions(rs, "ext1", cosign_required={"edit"}), open_keys)[1] == "pending_review"
    assert resolve_extraction_fact("C1", row, {}, set())[1] == "auto_accepted"
