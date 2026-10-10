from __future__ import annotations

import pytest

from arp.api.auth import Principal
from arp.orchestration.review_queue import append_decision, record_cosign, record_review_decision
from arp.publish.candidates import Skip, run_candidates
from arp.schemas.common import RunManifest
from arp.schemas.review import ReviewDecision
from arp.storage.run_store import RunStore

KEY = "ISS:f1:2024-12-31"
OLD = "ISS:f1:2023-12-31"
BOB = Principal(user_id="u_bob", name="Bob", role="approver")
CIT1 = {"doc_id": "d1", "doc_type": "10-K", "quote": "1000", "grounded": True, "content_key": "h1"}
CIT2 = {"doc_id": "d2", "doc_type": "10-K", "quote": "8", "grounded": True, "content_key": "h2"}
CORR = {"doc_id": "d9", "doc_type": "10-K", "quote": "1050", "grounded": True, "content_key": "h9"}


def _field(period="2024-12-31", value=1000, route="review", cit=CIT1, **kw):
    return {"field_id": "f1", "field_name": "F1", "value": value, "unit": "EUR", "canonical_value": 1000.0,
            "canonical_unit": "EUR", "period_end": period, "citations": [cit], "confidence": 0.9,
            "route": route, **kw}


@pytest.fixture
def rs(tmp_path):
    return RunStore(tmp_path / "runs")


def _run(rs, fields, *, trial=False, issuer_key="ISS"):
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction", created_at="2026-01-01T00:00:00+00:00",
                                 params={"trial": True} if trial else {}))
    row = {"company_id": "c1", "issuer_key": issuer_key, "issuer_scheme": "LEI", "fields": fields}
    rs.append_jsonl(rs._results_path("r1"), row)


def _decide(rs, key, decision="approve", step="first", second=False, value=None, citation=None, who="u_alice"):
    append_decision(rs, "r1", ReviewDecision(
        item_key=key, decision=decision, reason_code="confirmed" if decision == "approve" else "wrong_value",
        reviewer=who, user_id=who, role="approver", snapshot_id="s", step=step, second_required=second,
        corrected_value=None if value is None else {"value": value}, correction_citation=citation))


def _rst(rs, doc_ids=("d2",)):
    rs.append_jsonl(rs._restatements_path("r1"), {
        "candidate_id": "rst_1", "item_key": OLD, "issuer_key": "ISS", "field_id": "f1", "period_end": "2023-12-31",
        "previous_value": 7, "previous_run_id": "r0", "new_value": 8, "run_id": "r1", "doc_ids": list(doc_ids)})


def test_trial_run_never_published(rs):
    _run(rs, [_field(route="auto_accept")], trial=True)
    assert run_candidates(rs, "r1") == ([], [Skip("*", "trial_run")])


def test_auto_accepted_field_published_as_system(rs):
    _run(rs, [_field(route="auto_accept")])
    cands, skips = run_candidates(rs, "r1")
    assert skips == [] and len(cands) == 1
    c = cands[0]
    assert c.state == "auto_accepted" and c.value == 1000 and c.citation.doc_id == "d1"
    assert (c.issuer_scheme, c.item_key, c.source_run_id, c.observed_at) == ("LEI", KEY, "r1", "2026-01-01T00:00:00+00:00")


def test_legacy_unrouted_field_not_published(rs):
    _run(rs, [_field(route=None)])
    assert run_candidates(rs, "r1") == ([], [Skip(KEY, "not_auto_accepted")])


def test_first_done_correction_not_published(rs):
    _run(rs, [_field()])
    _decide(rs, KEY, "correct", second=True, value=1050, citation=CORR)
    assert run_candidates(rs, "r1") == ([], [Skip(KEY, "not_final")])


def test_agreed_correction_published_with_its_citation(rs):
    _run(rs, [_field()])
    _decide(rs, KEY, "correct", second=True, value=1050, citation=CORR)
    _decide(rs, KEY, "correct", step="second", value=1050, citation=CORR, who="u_bob")
    [c], skips = run_candidates(rs, "r1")
    assert skips == []
    assert c.state == "edited" and c.value == 1050 and c.citation.doc_id == "d9" and c.canonical_value is None


def test_edit_without_correction_citation_has_no_citation(rs):
    _run(rs, [_field(), _field(period="2022-12-31", value=5)])
    _decide(rs, KEY, "correct", value=1050)
    record_review_decision(rs, "r1", "ISS:f1:2022-12-31", "edit", "Alice", {"value": 6})
    record_cosign(rs, "r1", "ISS:f1:2022-12-31", BOB)
    cands, _ = run_candidates(rs, "r1")
    assert [(c.value, c.state, c.citation) for c in cands] == [(1050, "edited", None), (6, "edited", None)]


def test_rejected_and_held_not_published(rs):
    _run(rs, [_field(), _field(period="2022-12-31", route="hold")])
    _decide(rs, KEY, "reject")
    assert run_candidates(rs, "r1") == ([], [Skip(KEY, "rejected"), Skip("ISS:f1:2022-12-31", "held")])


def test_legacy_cosigned_edit_published(rs):
    _run(rs, [_field()])
    record_review_decision(rs, "r1", KEY, "edit", "Alice", {"value": 1100})
    assert run_candidates(rs, "r1") == ([], [Skip(KEY, "not_final")])
    record_cosign(rs, "r1", KEY, BOB)
    [c], _ = run_candidates(rs, "r1")
    assert c.state == "edited" and c.value == 1100


def test_restatement_published_only_after_second_approval(rs):
    _run(rs, [_field(), _field(period="2023-12-31", value=8, cit=CIT2)])
    _rst(rs)
    _decide(rs, KEY, "approve")
    _decide(rs, "rst_1", "approve", second=True)
    cands, skips = run_candidates(rs, "r1")
    assert [c.item_key for c in cands] == [KEY] and skips == [Skip(OLD, "restatement_pending")]
    _decide(rs, "rst_1", "approve", step="second", who="u_bob")
    cands, skips = run_candidates(rs, "r1")
    [r] = [c for c in cands if c.item_key == OLD]
    assert r.restated is True and r.restated_by_doc_id == "d2" and r.value == 8 and r.state == "approved"
    assert len(cands) == 2 and skips == []


def test_value_item_with_candidate_never_published_plainly(rs):
    _run(rs, [_field(period="2023-12-31", value=8, cit=CIT2)])
    _rst(rs)
    _decide(rs, OLD, "approve")
    cands, skips = run_candidates(rs, "r1")
    assert cands == [] and skips == [Skip(OLD, "restatement_pending")]


def test_no_value_and_no_period_skipped(rs):
    _run(rs, [_field(value=None, route="auto_accept"), _field(period=None, route="auto_accept")])
    assert run_candidates(rs, "r1") == ([], [Skip(KEY, "no_value"), Skip("ISS:f1:unspecified", "no_period")])


def test_row_without_issuer_key_skipped(rs):
    _run(rs, [_field(route="auto_accept")], issuer_key="")
    assert run_candidates(rs, "r1") == ([], [Skip("c1", "no_issuer_key")])


def test_field_awaiting_review_is_not_final(rs):
    _run(rs, [_field(route="review")])
    assert run_candidates(rs, "r1") == ([], [Skip(KEY, "not_final")])


def test_legacy_no_step_approve_on_restatement_stays_pending(rs):
    _run(rs, [_field(period="2023-12-31", value=8, cit=CIT2)])
    _rst(rs)
    record_review_decision(rs, "r1", "rst_1", "approve", "Mallory", None)
    assert run_candidates(rs, "r1") == ([], [Skip(OLD, "restatement_pending")])


def test_first_step_restatement_without_second_stays_pending(rs):
    _run(rs, [_field(period="2023-12-31", value=8, cit=CIT2)])
    _rst(rs)
    _decide(rs, "rst_1", "approve")  # step first, second_required False: final, but not a second review
    assert run_candidates(rs, "r1") == ([], [Skip(OLD, "restatement_pending")])


@pytest.mark.parametrize("citation,doc", [(CORR, "d9"), (None, "d7")])
def test_corrected_restatement_published(rs, citation, doc):
    _run(rs, [_field(period="2023-12-31", value=8, cit=CIT2)])
    _rst(rs, doc_ids=("d7",))
    _decide(rs, "rst_1", "correct", second=True, value=9, citation=citation)
    _decide(rs, "rst_1", "correct", step="second", value=9, citation=citation, who="u_bob")
    [c], skips = run_candidates(rs, "r1")
    assert skips == [] and (c.value, c.state, c.restated, c.restated_by_doc_id) == (9, "edited", True, doc)
    assert (c.citation.doc_id if c.citation else None) == (citation and citation["doc_id"])


def test_resolved_restatement_published(rs):
    _run(rs, [_field(period="2023-12-31", value=8, cit=CIT2)])
    _rst(rs)
    _decide(rs, "rst_1", "approve", second=True)
    _decide(rs, "rst_1", "reject", step="second", who="u_bob")
    assert run_candidates(rs, "r1")[1] == [Skip(OLD, "restatement_pending")]  # disagreed
    _decide(rs, "rst_1", "approve", step="resolution", who="u_carol")
    [c], _ = run_candidates(rs, "r1")
    assert c.restated and c.value == 8


def test_rejected_restatement_not_published(rs):
    _run(rs, [_field(period="2023-12-31", value=8, cit=CIT2)])
    _rst(rs)
    _decide(rs, "rst_1", "reject")
    assert run_candidates(rs, "r1") == ([], [Skip(OLD, "rejected")])
