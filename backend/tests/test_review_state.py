from __future__ import annotations

import json

import pytest

from arp.api.auth import Principal
from arp.orchestration.review_queue import (
    PUBLIC_KEYS,
    append_decision,
    blind_for,
    effective_decisions,
    item_states,
    public_decision,
    record_cosign,
    record_review_decision,
    same_value,
)
from arp.schemas.review import ReviewDecision, held_item_key, sector_item_key
from arp.storage.run_store import RunStore

ANA = Principal(user_id="u_ana", name="Ana", role="analyst")
BEN = Principal(user_id="u_ben", name="Ben", role="analyst")
APP = Principal(user_id="u_app", name="Appy", role="approver")
K = "iss:revenue:2024-12-31"
REQ = {"edit"}


@pytest.fixture
def rs(tmp_path):
    return RunStore(tmp_path / "runs")


def _d(rs, who, decision, step, value=None, second_required=False):
    reason = "confirmed" if decision == "approve" else ("needs_expert" if decision == "escalate" else "wrong_value")
    append_decision(
        rs,
        "r1",
        ReviewDecision(
            item_key=K,
            decision=decision,
            reason_code=reason,
            reviewer=who.name,
            user_id=who.user_id,
            role=who.role,
            corrected_value={"value": value} if decision == "correct" else None,
            snapshot_id="snap1",
            step=step,
            second_required=second_required,
            second_reasons=["correction"] if second_required else [],
        ),
    )


def _s(rs, req=REQ):
    return item_states(rs, "r1", cosign_required=req)[K]


def test_item_keys():
    assert held_item_key("c1", "d1") == "held:c1:d1"
    assert sector_item_key("c1") == "isic:c1"


def test_first_approve_without_second_is_final(rs):
    _d(rs, ANA, "approve", "first")
    s = _s(rs)
    assert s.state == "final" and s.effective["decision"] == "approve"
    assert K in effective_decisions(rs, "r1", cosign_required=REQ)


def test_first_correct_requiring_second_is_first_done(rs):
    _d(rs, ANA, "correct", "first", 1050, second_required=True)
    assert _s(rs).state == "first_done"
    assert K not in effective_decisions(rs, "r1", cosign_required=REQ)


def test_agreeing_second_is_second_done_and_effective(rs):
    _d(rs, ANA, "correct", "first", 1050, second_required=True)
    _d(rs, BEN, "correct", "second", 1050)
    s = _s(rs)
    assert s.state == "second_done" and s.effective["user_id"] == "u_ana"
    assert effective_decisions(rs, "r1", cosign_required=REQ)[K]["edited_value"] == {"value": 1050}


def test_disagreeing_second_is_disagreed_not_effective(rs):
    _d(rs, ANA, "correct", "first", 1050, second_required=True)
    _d(rs, BEN, "approve", "second")
    s = _s(rs)
    assert s.state == "disagreed" and s.effective is None
    assert K not in effective_decisions(rs, "r1", cosign_required=REQ)
    _d(rs, ANA, "correct", "first", 1050, second_required=True)
    _d(rs, BEN, "correct", "second", 1060)
    assert _s(rs).state == "disagreed"


def test_resolution_is_final_and_effective(rs):
    _d(rs, ANA, "correct", "first", 1050, second_required=True)
    _d(rs, BEN, "approve", "second")
    _d(rs, APP, "correct", "resolution", 1055)
    s = _s(rs)
    assert s.state == "final" and s.effective["user_id"] == "u_app"
    assert effective_decisions(rs, "r1", cosign_required=REQ)[K]["edited_value"] == {"value": 1055}


def test_escalate_is_pending_and_flags_escalated(rs):
    _d(rs, ANA, "escalate", "first")
    s = _s(rs)
    assert s.state == "pending" and s.escalated is True and s.effective is None
    _d(rs, ANA, "correct", "first", 1050, second_required=True)
    s = _s(rs)
    assert s.state == "first_done" and s.escalated is False


def test_new_round_after_final(rs):
    _d(rs, ANA, "approve", "first")
    _d(rs, BEN, "correct", "first", 1050, second_required=True)
    s = _s(rs)
    assert s.state == "first_done" and len(s.rows) == 2


def test_legacy_extraction_edit_needs_cosign(rs):
    record_review_decision(rs, "r1", K, "edit", None, {"value": 5}, principal=ANA)
    assert _s(rs).state == "first_done"
    record_cosign(rs, "r1", K, APP)
    assert _s(rs).state == "second_done"
    assert effective_decisions(rs, "r1", cosign_required=REQ)[K]["edited_value"] == {"value": 5}


def test_legacy_edit_with_agreeing_second_row_is_second_done(rs):
    record_review_decision(rs, "r1", K, "edit", None, {"value": 5}, principal=ANA)
    _d(rs, BEN, "correct", "second", "5")
    s = _s(rs)
    assert s.state == "second_done" and s.effective["decision"] == "edit"


def test_legacy_identity_edit_is_final(rs):
    record_review_decision(rs, "r1", K, "edit", None, {"value": 5}, principal=ANA)
    assert _s(rs, set()).state == "final"


def test_legacy_approve_reject_final_and_escalate_pending(rs):
    for decision in ("approve", "reject"):
        record_review_decision(rs, "r1", K, decision, None, None, principal=ANA)
        assert _s(rs).state == "final"
    record_review_decision(rs, "r1", K, "escalate", None, None, principal=ANA)
    s = _s(rs)
    assert s.state == "pending" and s.escalated is True
    assert K not in effective_decisions(rs, "r1", cosign_required=REQ)


def test_public_decision_has_no_user_id_or_name(rs):
    _d(rs, ANA, "approve", "first")
    row = _s(rs).effective
    pub = public_decision(row, ANA)
    assert tuple(pub) == PUBLIC_KEYS + ("mine",)
    assert pub["mine"] is True
    assert public_decision(row, BEN)["mine"] is False
    assert public_decision(row, None)["mine"] is False


def test_blind_for(rs):
    _d(rs, ANA, "correct", "first", 1050, second_required=True)
    s = _s(rs)
    assert blind_for(s, BEN, high_risk=True) is True
    assert blind_for(s, ANA, high_risk=True) is False
    assert blind_for(s, APP, high_risk=True) is False
    assert blind_for(s, BEN, high_risk=False) is False
    _d(rs, BEN, "correct", "second", 1050)
    assert blind_for(_s(rs), APP.model_copy(update={"role": "analyst", "user_id": "u_x"}), high_risk=True) is False


def test_record_review_decision_row_unchanged(rs):
    record_review_decision(rs, "r1", K, "approve", None, None, principal=ANA)
    row = json.loads(rs._review_decisions_path("r1").read_text().splitlines()[0])
    assert set(row) == {"item_key", "decision", "reviewer", "user_id", "role", "edited_value", "comment", "decided_at"}


def test_same_value_numeric_and_text():
    assert same_value(1050, "1050.0") is True
    assert same_value("ACME", " ACME ") is True
    assert same_value(True, 1) is False
