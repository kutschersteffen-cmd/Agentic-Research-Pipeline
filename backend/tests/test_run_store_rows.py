import pytest

from arp.schemas.common import CompanyRef
from arp.storage.run_store import LegacyRunStore

PAIRS = [
    ("results", "result"),
    ("errors", "error"),
    ("review_queue", "review_item"),
    ("decisions", "decision_row"),
    ("cosigns", "cosign"),
    ("restatements", "restatement"),
    ("events", "event"),
]


@pytest.fixture(params=["legacy", "db"])
def store(request, tmp_path):
    if request.param == "legacy":
        return LegacyRunStore(tmp_path)
    return request.getfixturevalue("run_store")


def _row(n):
    return {"_key": f"k{n}", "item_key": f"k{n}", "n": n}


@pytest.mark.parametrize(("read", "append"), PAIRS)
def test_append_then_read_keeps_order(store, read, append):
    assert getattr(store, f"read_{read}")("r1") == []
    getattr(store, f"append_{append}")("r1", _row(1))
    getattr(store, f"append_{append}")("r1", _row(2))
    assert getattr(store, f"read_{read}")("r1") == [_row(1), _row(2)]
    assert getattr(store, f"read_{read}")("other") == []


def test_done_keys(store):
    store.append_result("r1", {"_key": "c0"})
    store.append_error("r1", {"key": "c1", "error": "x", "review": True, "report": {}})
    store.append_error("r1", {"key": "c2", "error": "y"})
    assert store.done_keys("r1") == {"c0"}
    assert store.done_keys("r1", include_errors=True) == {"c0", "c1"}
    assert store.done_keys("unknown") == set()


def test_snapshot_round_trip_and_missing(store):
    assert store.read_snapshot("r1", "snap_a") is None
    store.save_snapshot("r1", "snap_a", {"b": 1, "a": [2]})
    assert store.read_snapshot("r1", "snap_a") == {"a": [2], "b": 1}


def test_companies_round_trip(store):
    assert store.load_companies("r1") is None
    assert not store.has_companies("r1")
    companies = [CompanyRef(company_id="c2", name="Beta"), CompanyRef(company_id="c1", name="Acme")]
    store.save_companies("r1", companies)
    assert store.has_companies("r1")
    loaded = store.load_companies("r1")
    assert [c.model_copy(update={"entity_id": None}) for c in loaded] == companies
