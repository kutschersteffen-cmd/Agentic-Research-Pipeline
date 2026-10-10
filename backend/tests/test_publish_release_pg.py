from __future__ import annotations

import hashlib
import os

import pytest

from arp.api.auth import Principal
from arp.orchestration.review_queue import append_decision
from arp.publish.candidates import Skip
from arp.publish.release import SYSTEM, publish_run, withdraw
from arp.schemas.common import RunManifest
from arp.schemas.review import ReviewDecision
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.run_store import RunStore
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")

ORIG = {d: f"original {d}".encode() for d in ("d1", "d2", "d3")}
HASH = {d: hashlib.sha256(b).hexdigest() for d, b in ORIG.items()}
KEY = ("ISS", "f1", "2024-12-31", "")
OLD = ("ISS", "f1", "2023-12-31", "")
BOB = Principal(user_id="u_bob", name="Bob", role="approver")


@pytest.fixture(autouse=True)
def _db():
    from arp.storage.postgres import ensure_schema

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    yield
    reset_postgres_tables(DSN)


@pytest.fixture
def store():
    from arp.publish.facts import PublishStore

    return PublishStore(DSN)


@pytest.fixture
def rs(tmp_path):
    return RunStore(tmp_path / "runs")


@pytest.fixture
def blobs(tmp_path):
    b = LocalBlobStore(tmp_path / "blobs")
    for d, data in ORIG.items():
        b.put(HASH[d], data)
    return b


def _field(value, period="2024-12-31", doc="d1", route="auto_accept"):
    cit = {"doc_id": doc, "doc_type": "10-K", "quote": str(value), "grounded": True, "content_key": HASH[doc]}
    return {"field_id": "f1", "field_name": "F1", "value": value, "unit": "EUR", "period_end": period,
            "citations": [cit], "confidence": 0.9, "route": route}


def _run(rs, run_id, day, fields):
    rs.save_manifest(RunManifest(run_id=run_id, run_type="extraction", created_at=f"2026-01-{day:02d}T00:00:00+00:00"))
    rs.append_jsonl(rs._results_path(run_id), {"company_id": "c1", "issuer_key": "ISS", "issuer_scheme": "LEI",
                                              "fields": fields})


def _publish(store, rs, blobs, run_id, principal=BOB):
    return publish_run(store, rs, run_id, principal=principal, blob_store=blobs)


def _rows(store, model):
    from sqlalchemy import func, select

    from arp.storage import postgres_models

    with store.session() as s:
        return s.scalar(select(func.count()).select_from(getattr(postgres_models, model)))


def test_publish_run_end_to_end_pg(store, rs, blobs):
    _run(rs, "r1", 1, [_field(1000)])
    res = _publish(store, rs, blobs, "r1", principal=None)
    [rel] = res.releases
    assert (rel.doc_id, rel.content_key, rel.published_by, rel.published_by_role) == ("d1", HASH["d1"], SYSTEM, SYSTEM)
    assert rel.storage_uri == blobs.uri(HASH["d1"]) and store.get_release(rel.release_id) == rel
    fact = store.current([KEY])[KEY]
    assert (fact.version, fact.value, fact.release_id, fact.reconfirmed_at) == (1, 1000, rel.release_id, None)
    again = _publish(store, rs, blobs, "r1")
    assert again.releases == [] and again.reconfirmed == 1
    assert store.current([KEY])[KEY].reconfirmed_at is not None
    assert len(store.list_releases()) == 1 and _rows(store, "FactEventModel") == 1


def test_missing_original_blocks_release_pg(store, rs, tmp_path):
    _run(rs, "r1", 1, [_field(1000)])
    res = _publish(store, rs, LocalBlobStore(tmp_path / "empty"), "r1")
    assert res.releases == [] and res.blocked[0]["reason"] == "original_missing"
    assert [_rows(store, m) for m in ("ReleaseModel", "PublishedFactModel", "FactEventModel")] == [0, 0, 0]


def test_withdrawal_restores_previous_fact_pg(store, rs, blobs):
    _run(rs, "r1", 1, [_field(1000)])
    _run(rs, "r2", 2, [_field(1100, doc="d2")])
    _publish(store, rs, blobs, "r1")
    [rel_b] = _publish(store, rs, blobs, "r2").releases
    [restored] = withdraw(store, rel_b.release_id, reason="wrong document", principal=BOB)
    assert store.current([KEY])[KEY] == restored and restored.value == 1000
    assert [v.value for v in store.versions(KEY)] == [1000, 1100, 1000]
    got = store.get_release(rel_b.release_id)
    assert got.withdrawn_at and (got.withdrawal_reason, got.withdrawn_by) == ("wrong document", "u_bob")
    assert _rows(store, "FactEventModel") == 4  # published x2, withdrawn, restored
    assert _publish(store, rs, blobs, "r2").blocked == [
        {"doc_id": "d2", "reason": "release_withdrawn", "item_keys": ["ISS:f1:2024-12-31"]}]
    from arp.publish.facts import ConcurrentPublish  # the store refuses a second withdrawal

    with pytest.raises(ConcurrentPublish):
        store.save_withdrawal(got.model_copy(update={"withdrawn_at": None}), [], [], [])
    with pytest.raises(LookupError):
        withdraw(store, "rel_missing", reason="x", principal=BOB)


def test_withdraw_after_restore_skips_withdrawn_release_pg(store, rs, blobs):
    _run(rs, "r1", 1, [_field(1000)])
    _run(rs, "r2", 2, [_field(1100, doc="d2")])
    _run(rs, "r3", 3, [_field(1200, doc="d3")])
    _publish(store, rs, blobs, "r1")
    [rel_b] = _publish(store, rs, blobs, "r2").releases
    [rel_c] = _publish(store, rs, blobs, "r3").releases
    [b_copy] = withdraw(store, rel_c.release_id, reason="bad", principal=BOB)
    assert b_copy.value == 1100 and b_copy.release_id == rel_b.release_id
    [a_copy] = withdraw(store, rel_b.release_id, reason="bad too", principal=BOB)
    current = store.current([KEY])[KEY]
    assert current == a_copy and current.value == 1000 and current.fact_id != b_copy.fact_id
    withdrawn = {rel_b.release_id, rel_c.release_id}
    assert store.get_fact(a_copy.restored_from).release_id not in withdrawn
    assert [v.value for v in store.versions(KEY)] == [1000, 1100, 1200, 1100, 1000]


def _decide(rs, run_id, key, step, who, second=False):
    append_decision(rs, run_id, ReviewDecision(
        item_key=key, decision="approve", reason_code="confirmed", reviewer=who, user_id=who, role="approver",
        snapshot_id="s", step=step, second_required=second))


def test_restated_period_shows_both_versions_pg(store, rs, blobs):
    _run(rs, "r1", 1, [_field(9, period="2023-12-31")])
    _publish(store, rs, blobs, "r1")
    _run(rs, "r2", 2, [_field(8, period="2023-12-31", doc="d2", route="review")])
    rs.append_jsonl(rs._restatements_path("r2"), {
        "candidate_id": "rst_1", "item_key": "ISS:f1:2023-12-31", "issuer_key": "ISS", "field_id": "f1",
        "period_end": "2023-12-31", "previous_value": 9, "previous_run_id": "r1", "new_value": 8, "run_id": "r2",
        "doc_ids": ["d2"]})
    _decide(rs, "r2", "rst_1", "first", "u_alice", second=True)
    _decide(rs, "r2", "rst_1", "second", "u_bob")
    [rel] = _publish(store, rs, blobs, "r2").releases
    v1, v2 = store.versions(OLD)
    assert (v1.restated, v1.value) == (False, 9)
    assert (v2.restated, v2.value, v2.restated_by_doc_id, v2.release_id) == (True, 8, "d2", rel.release_id)


def test_older_run_republished_is_skipped_pg(store, rs, blobs):
    _run(rs, "r1", 1, [_field(1000)])
    _run(rs, "r2", 2, [_field(1100, doc="d2")])
    _publish(store, rs, blobs, "r1")
    _publish(store, rs, blobs, "r2")
    before = store.current([KEY])[KEY]
    res = _publish(store, rs, blobs, "r1")
    assert res.releases == [] and Skip("ISS:f1:2024-12-31", "older_than_published") in res.skipped
    assert store.current([KEY])[KEY] == before


def test_duplicate_fact_key_skipped_not_blocking_pg(store, rs, blobs):
    _run(rs, "r1", 1, [_field(1000)])
    rs.append_jsonl(rs._results_path("r1"), {"company_id": "c2", "issuer_key": "ISS", "issuer_scheme": "LEI",
                                            "fields": [_field(1001)]})
    res = _publish(store, rs, blobs, "r1")
    assert len(res.releases) == 1 and Skip("ISS:f1:2024-12-31", "duplicate_key") in res.skipped
    assert [v.value for v in store.versions(KEY)] == [1000]
    assert _publish(store, rs, blobs, "r1").reconfirmed == 1  # a retry does not fail either


def _three_releases(store, rs, blobs):
    for i, (value, doc) in enumerate([(1000, "d1"), (1100, "d2"), (1200, "d3")], start=1):
        _run(rs, f"r{i}", i, [_field(value, doc=doc)])
    return [_publish(store, rs, blobs, f"r{i}").releases[0] for i in (1, 2, 3)]


def _interleave(store, monkeypatch, other_release_id):
    """Withdraw `other_release_id` between planning a withdrawal and saving it."""
    real = store.save_withdrawal

    def save(*args):
        monkeypatch.setattr(store, "save_withdrawal", real)
        withdraw(store, other_release_id, reason="concurrent", principal=BOB)
        real(*args)

    monkeypatch.setattr(store, "save_withdrawal", save)


def test_concurrent_withdrawal_never_restores_withdrawn_value_pg(store, rs, blobs, monkeypatch):
    from arp.publish.facts import ConcurrentPublish

    _, rel_b, rel_c = _three_releases(store, rs, blobs)
    _interleave(store, monkeypatch, rel_b.release_id)
    with pytest.raises(ConcurrentPublish):
        withdraw(store, rel_c.release_id, reason="bad", principal=BOB)  # planned to restore B's 1100
    assert store.current([KEY])[KEY].value == 1200
    [restored] = withdraw(store, rel_c.release_id, reason="bad", principal=BOB)  # the retry skips B
    assert restored.value == 1000 and store.current([KEY])[KEY] == restored


def test_withdrawal_refused_when_release_regained_current_fact_pg(store, rs, blobs, monkeypatch):
    from arp.publish.facts import ConcurrentPublish

    _, rel_b, rel_c = _three_releases(store, rs, blobs)
    _interleave(store, monkeypatch, rel_c.release_id)  # restores B's value while B's withdrawal is planned
    with pytest.raises(ConcurrentPublish):
        withdraw(store, rel_b.release_id, reason="bad", principal=BOB)
    assert store.current([KEY])[KEY].value == 1100
    [restored] = withdraw(store, rel_b.release_id, reason="bad", principal=BOB)
    assert restored.value == 1000
