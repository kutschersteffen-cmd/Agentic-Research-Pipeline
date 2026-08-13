from arp.orchestration.review_queue import decision_history, latest_decisions, queue_for_review, record_review_decision
from arp.storage.run_store import RunStore


def test_review_queue_roundtrip(tmp_path):
    store = RunStore(tmp_path)
    queue_for_review(store, "run1", "AAPL:activity1", {"confidence": 0.3})
    rows = store.read_jsonl(store.review_queue_path("run1"))
    assert len(rows) == 1
    assert rows[0]["item_key"] == "AAPL:activity1"


def test_latest_decision_wins_on_repeat(tmp_path):
    store = RunStore(tmp_path)
    record_review_decision(store, "run1", "AAPL:activity1", "reject", "analyst_a", None)
    record_review_decision(store, "run1", "AAPL:activity1", "approve", "analyst_b", {"value": "yes"})

    decisions = latest_decisions(store, "run1")
    assert decisions["AAPL:activity1"]["decision"] == "approve"
    assert decisions["AAPL:activity1"]["reviewer"] == "analyst_b"


def test_theme_style_positional_call_without_comment_still_works(tmp_path):
    """Regression guard: themes.py calls record_review_decision with the
    old 6-positional-argument shape (no comment) -- this must keep working
    unmodified after comment was added as a new trailing kwarg."""
    store = RunStore(tmp_path)
    record_review_decision(store, "run1", "AAPL:activity1", "approve", "analyst_a", {"value": "yes"})

    decisions = latest_decisions(store, "run1")
    assert decisions["AAPL:activity1"]["decision"] == "approve"
    assert decisions["AAPL:activity1"]["comment"] is None


def test_comment_roundtrips_through_record_review_decision(tmp_path):
    store = RunStore(tmp_path)
    record_review_decision(
        store, "run1", "DHL:fld_123", "edit", "analyst_a", {"value": 1699.0}, comment="Cross-checked against note 10."
    )

    decisions = latest_decisions(store, "run1")
    assert decisions["DHL:fld_123"]["comment"] == "Cross-checked against note 10."


def test_decision_history_returns_full_audit_trail_oldest_first(tmp_path):
    store = RunStore(tmp_path)
    record_review_decision(store, "run1", "DHL:fld_123", "reject", "analyst_a", None, comment="Looks wrong.")
    record_review_decision(store, "run1", "DHL:fld_123", "edit", "analyst_b", {"value": 1699.0}, comment="Fixed.")
    record_review_decision(store, "run1", "SAP:fld_456", "approve", "analyst_a", None)  # different item_key

    history = decision_history(store, "run1", "DHL:fld_123")
    assert [h["decision"] for h in history] == ["reject", "edit"]
    assert history[0]["comment"] == "Looks wrong."
    assert history[1]["comment"] == "Fixed."

    # latest_decisions still collapses to just the last row per item_key
    assert latest_decisions(store, "run1")["DHL:fld_123"]["decision"] == "edit"
