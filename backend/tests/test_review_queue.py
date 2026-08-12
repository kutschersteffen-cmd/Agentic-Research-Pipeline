from arp.orchestration.review_queue import latest_decisions, queue_for_review, record_review_decision
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
