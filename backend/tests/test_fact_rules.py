"""Spec §2.7 current-fact rules, one test per row. Pure: no database."""

from arp.db.models import CompanyFact, FactStatus, ValueState
from arp.db.observations import decide

A, P, H = FactStatus.AUTO_ACCEPTED, FactStatus.PENDING_REVIEW, FactStatus.HELD
FOUND, MISS = ValueState.FOUND, ValueState.NOT_FOUND


def _fact(value, status=A):
    return CompanyFact(value=value, status=status)


def test_new_key_inserts():
    assert decide(None, 1000, A, FOUND) == "insert"


def test_same_value_same_status_noop():
    assert decide(_fact(1000), 1000, A, FOUND) == "noop"
    assert decide(_fact({"verdict": "include"}), {"verdict": "include"}, A, FOUND) == "noop"


def test_equal_numeric_values_do_not_supersede():
    assert decide(_fact(1000), 1000.0, A, FOUND) == "noop"


def test_different_accepted_value_supersedes():
    assert decide(_fact(1000), 1200, A, FOUND) == "supersede"
    assert decide(_fact(1000, P), 1000, FactStatus.APPROVED, FOUND) == "supersede"


def test_pending_value_keeps_current():
    assert decide(_fact(1000), 1200, P, FOUND) == "keep"


def test_not_found_keeps_current():
    assert decide(_fact(1000), None, A, MISS) == "keep"
    assert decide(None, None, A, MISS) == "noop"


def test_held_does_not_displace_accepted_fact():
    for status in (A, FactStatus.APPROVED, FactStatus.EDITED):
        assert decide(_fact(1000, status), 1200, H, FOUND) == "keep"


def test_held_replaces_pending_fact():
    assert decide(None, 1200, H, FOUND) == "insert"
    assert decide(_fact(1000, P), 1200, H, FOUND) == "supersede"
    assert decide(_fact(1000, H), 1200, H, FOUND) == "supersede"
