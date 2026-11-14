"""refine-chat: the turn log table, manifest fields and turn store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from arp.db import models as m
from arp.db.session import transaction
from arp.refine import turns
from arp.schemas.reporting import ReportManifest


def test_second_running_turn_raises_busy(pg):
    turns.start_turn("rfp", "7", "alice", "shorten A2")
    with pytest.raises(turns.TurnBusy):
        turns.start_turn("rfp", "7", "bob", "again")
    assert turns.start_turn("rfp", "8", "bob", "other doc")
    assert turns.start_turn("deck", "7", "bob", "other kind")


def test_reap_marks_interrupted(pg):
    tid = turns.start_turn("rfp", "7", "alice", "shorten A2")
    turns.save_progress(tid, done=1, total=3, result={"reply": "r", "changed": ["A2"]})
    assert turns.reap_stale_turns() == 1
    out = turns.turn_out(tid)
    assert (out["status"], out["error"], out["changed"], out["done"], out["total"]) == ("failed", "interrupted", ["A2"], 1, 3)
    assert turns.start_turn("rfp", "7", "alice", "retry")


def test_reap_with_now_only_takes_old_turns(pg):
    tid = turns.start_turn("rfp", "7", "alice", "m")
    assert turns.reap_stale_turns(datetime.now(UTC)) == 0
    later = datetime.now(UTC) + timedelta(minutes=turns.REFINE_TURN_TIMEOUT_MIN + 1)
    assert turns.reap_stale_turns(later) == 1
    assert turns.turn_out(tid)["status"] == "failed"


def test_finish_frees_the_document_and_records_error(pg):
    tid = turns.start_turn("rfp", "7", "alice", "m")
    turns.finish_turn(tid, "failed", error="model down")
    out = turns.turn_out(tid)
    assert (out["status"], out["error"], out["reply"], out["check_figures"]) == ("failed", "model down", "", [])
    assert turns.start_turn("rfp", "7", "alice", "m2")


def test_manifest_defaults():
    r = ReportManifest()
    assert r.has_deck is False and r.deck_edited_since_render is False


def test_recent_progress_keeps_old_turn_running(pg):
    tid = turns.start_turn("rfp", "7", "alice", "m")
    with transaction() as s:  # started 11 minutes ago
        s.get(m.RefineTurn, tid).created_at = datetime.now(UTC) - timedelta(minutes=turns.REFINE_TURN_TIMEOUT_MIN + 1)
    assert turns.save_progress(tid, done=1) is True  # progress just now
    assert turns.reap_stale_turns(datetime.now(UTC)) == 0
    assert turns.turn_out(tid)["status"] == "running"


def test_reaped_turn_stays_failed(pg):
    tid = turns.start_turn("rfp", "7", "alice", "m")
    assert turns.reap_stale_turns() == 1
    assert turns.finish_turn(tid, "done") is False
    assert turns.save_progress(tid, done=1, result={"reply": "late"}) is False
    out = turns.turn_out(tid)
    assert (out["status"], out["error"], out["done"], out["reply"]) == ("failed", "interrupted", 0, "")


def test_save_progress_merges_result(pg):
    tid = turns.start_turn("rfp", "7", "alice", "m")
    turns.save_progress(tid, result={"reply": "r"})
    turns.save_progress(tid, result={"changed": [1]})
    assert (turns.turn_out(tid)["reply"], turns.turn_out(tid)["changed"]) == ("r", [1])
