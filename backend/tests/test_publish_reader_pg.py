from __future__ import annotations

import os

import pytest

from arp.api.auth import Principal
from arp.publish.facts import FactCandidate, FactEvent, Release, fact_key, plan_version
from arp.publish.reader import events_since, facts_as_of, read_events, visible
from arp.publish.release import withdraw
from arp.schemas.common import Citation
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")

T1, T2, T3 = (f"2026-10-0{d}T09:00:00.000000+00:00" for d in (1, 2, 3))
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


def _cand(value, issuer="ISS"):
    return FactCandidate(
        issuer_key=issuer, issuer_scheme="LEI", field_id="f1", period_end="2024-12-31", value=value, unit="EUR",
        state="approved", citation=Citation(doc_id="d1", doc_type="10-K", quote="q", grounded=True, content_key="ck"),
        source_run_id="run1", observed_at=T1, item_key="k1",
    )


def _release(store, rid, at, issuer="ISS"):
    r = Release(release_id=rid, doc_id="d1", content_key="ck", storage_uri="u", issuer_key=issuer,
                issuer_scheme="LEI", run_id="run1", published_at=at, published_by="u_bob", published_by_role="approver")
    return r


def _publish(store, rid, value, now, issuer="ISS"):
    key = ("ISS", "f1", "2024-12-31", "") if issuer == "ISS" else (issuer, "f1", "2024-12-31", "")
    plan = plan_version(store.current([key]).get(key), _cand(value, issuer), release_id=rid, now=now)
    f = plan.fact
    ev = FactEvent(event_type="published", fact_id=f.fact_id, issuer_key=f.issuer_key, field_id=f.field_id,
                   period_end=f.period_end, basis=f.basis, release_id=rid, at=now)
    store.save_release(_release(store, rid, now, issuer), [plan], [ev])
    return f


def test_facts_as_of_sql_matches_visible_pg(store):
    _publish(store, "rel_1", 1, T1)
    _publish(store, "rel_2", 2, T2)
    _publish(store, "rel_3", 9, T1, issuer="OTHER")
    key = ("ISS", "f1", "2024-12-31", "")
    allv = store.versions(key) + store.versions(("OTHER", "f1", "2024-12-31", ""))
    for as_of in ("2026-09-30", "2026-10-01", "2026-10-02T08:00:00+00:00", "2026-10-03"):
        assert facts_as_of(store, as_of) == visible(allv, as_of)
    assert [f.value for f in facts_as_of(store, "2026-10-01", issuer_key="ISS")] == [1]
    assert [f.value for f in facts_as_of(store, "2026-10-02", issuer_key="ISS", field_id="f1")] == [2]
    assert facts_as_of(store, "2026-10-02", field_id="nope") == []
    assert [fact_key(f) for f in facts_as_of(store, "2026-10-03")] == sorted(fact_key(f) for f in facts_as_of(store, "2026-10-03"))


def test_events_written_with_release_and_withdrawal_pg(store):
    _publish(store, "rel_1", 1, T1)
    _publish(store, "rel_2", 2, T2)
    withdraw(store, "rel_2", reason="wrong", principal=BOB, now=T3)
    events = read_events(store)
    assert [e.event_type for e in events] == ["published", "published", "withdrawn", "restored"]
    assert [e.event_id for e in events] == sorted(e.event_id for e in events)
    # a restored event carries the source release's id (rel_1), not the withdrawn one
    assert [e.release_id for e in events[2:]] == ["rel_2", "rel_1"]
    assert [e.event_type for e in events_since(store, T2)] == ["withdrawn", "restored"]
    assert [e.event_id for e in read_events(store, after_id=events[1].event_id)] == [e.event_id for e in events[2:]]
    assert len(read_events(store, limit=1)) == 1


def test_event_ids_follow_commit_order_pg(store):
    """A publish holding its events uncommitted blocks the next one, so a cursor never skips an id."""
    import threading

    from sqlalchemy.orm import Session

    flushed, go = threading.Event(), threading.Event()
    local = threading.local()

    class Slow(Session):
        def commit(self):
            if getattr(local, "slow", False):
                self.flush()  # event id assigned, not yet visible
                flushed.set()
                assert go.wait(10)
            super().commit()

    store.session = lambda: Slow(store.engine)

    def a():
        local.slow = True
        _publish(store, "rel_a", 1, T1, issuer="A")

    ta = threading.Thread(target=a)
    ta.start()
    assert flushed.wait(10)
    tb = threading.Thread(target=lambda: _publish(store, "rel_b", 2, T2, issuer="B"))
    tb.start()
    tb.join(0.5)
    assert tb.is_alive()  # B waits for A's commit
    assert read_events(store) == []
    go.set()
    ta.join(10)
    tb.join(10)
    events = read_events(store)
    assert [e.release_id for e in events] == ["rel_a", "rel_b"]
    ids = [e.event_id for e in events]
    assert ids == list(range(ids[0], ids[0] + 2))
    assert [e.release_id for e in read_events(store, after_id=ids[0])] == ["rel_b"]
