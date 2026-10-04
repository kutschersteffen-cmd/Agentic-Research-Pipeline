import os

import pytest

from arp.publish.facts import FactCandidate, FactEvent, Release, fact_key, plan_version
from arp.schemas.common import Citation
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")

T1 = "2026-10-01T09:00:00.000000+00:00"
T2 = "2026-10-02T09:00:00.000000+00:00"
LEI = "5493001KJTIIGC8Y1R12"


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


def _cand(**kw):
    base = dict(
        issuer_key=LEI, issuer_scheme="LEI", field_id="f1", period_end="2024-12-31",
        value=1050.0, unit="tCO2e", state="approved",
        citation=Citation(doc_id="d1", doc_type="sustainability_report", quote="1,050 tCO2e", grounded=True, content_key="ck"),
        source_run_id="run1", observed_at=T1, item_key="k1",
    )
    base.update(kw)
    return FactCandidate(**base)


def _release(run_id="run1", at=T1):
    return Release(
        doc_id="d1", content_key="ck", storage_uri="s3://bucket/ck.pdf", issuer_key=LEI, issuer_scheme="LEI",
        run_id=run_id, published_at=at, published_by="u1", published_by_role="approver",
    )


def _event(fact, rel, at):
    return FactEvent(
        event_type="published", fact_id=fact.fact_id, issuer_key=fact.issuer_key, field_id=fact.field_id,
        period_end=fact.period_end, basis=fact.basis, release_id=rel.release_id, at=at,
    )


def _publish(store, cand, at, run_id="run1"):
    rel = _release(run_id, at)
    key = fact_key(cand)
    plan = plan_version(store.current([key]).get(key), cand, release_id=rel.release_id, now=at)
    store.save_release(rel, [plan], [_event(plan.fact, rel, at)] if plan.fact else [])
    return rel, plan


def _count(store):
    from sqlalchemy import func, select

    from arp.storage.postgres_models import PublishedFactModel

    with store.session() as s:
        return s.scalar(select(func.count()).select_from(PublishedFactModel))


def test_insert_and_current_pg(store):
    rel, plan = _publish(store, _cand(), T1)
    key = fact_key(plan.fact)
    got = store.current([key])[key]
    assert got == plan.fact
    assert store.get_fact(plan.fact.fact_id) == plan.fact
    assert store.get_release(rel.release_id) == rel
    assert store.list_releases(run_id="run1") == [rel]
    assert store.release_facts(rel.release_id) == [plan.fact]


def test_new_version_closes_old_pg(store):
    _, p1 = _publish(store, _cand(), T1)
    _, p2 = _publish(store, _cand(value=1100.0, observed_at=T2, source_run_id="run2"), T2, "run2")
    key = fact_key(p1.fact)
    v1, v2 = store.versions(key)
    assert v1.fact_id == p1.fact.fact_id and v1.valid_to == T2 and v1.superseded_by == v2.fact_id
    assert v2.version == 2 and v2.valid_to is None
    assert store.current([key])[key] == v2
    assert store.previous_version(v2.fact_id) == v1


def test_reconfirm_updates_only_reconfirmed_at_pg(store):
    _, p1 = _publish(store, _cand(), T1)
    _, p2 = _publish(store, _cand(observed_at=T2), T2, "run2")
    assert p2.kind == "reconfirm"
    assert _count(store) == 1
    got = store.get_fact(p1.fact.fact_id)
    assert got.reconfirmed_at == T2
    assert got.model_dump(exclude={"reconfirmed_at"}) == p1.fact.model_dump(exclude={"reconfirmed_at"})


def test_duplicate_key_version_raises_concurrent_pg(store):
    from arp.publish.facts import ConcurrentPublish

    _publish(store, _cand(), T1)
    rel = _release("run2", T2)
    dup = plan_version(None, _cand(value=9.0), release_id=rel.release_id, now=T2)
    with pytest.raises(ConcurrentPublish):
        store.save_release(rel, [dup], [])
    assert _count(store) == 1
    assert store.get_release(rel.release_id) is None


def test_stale_close_raises_concurrent_pg(store):
    from arp.publish.facts import ConcurrentPublish

    _, p1 = _publish(store, _cand(), T1)
    _publish(store, _cand(value=1100.0, observed_at=T2), T2, "run2")
    rel = _release("run3", T2)
    stale = plan_version(p1.fact, _cand(value=1200.0, observed_at=T2), release_id=rel.release_id, now=T2)
    stale = type(stale)("insert", stale.fact.model_copy(update={"version": 3}), stale.closes)
    with pytest.raises(ConcurrentPublish):
        store.save_release(rel, [stale], [])
    assert _count(store) == 2
    assert store.get_fact(stale.fact.fact_id) is None


def test_lineage_one_join_pg(store):
    from sqlalchemy import event

    rel, plan = _publish(store, _cand(), T1)
    statements = []

    def count(*_a, **_k):
        statements.append(1)

    event.listen(store.engine, "before_cursor_execute", count)
    try:
        got = store.lineage(plan.fact.fact_id)
    finally:
        event.remove(store.engine, "before_cursor_execute", count)
    assert len(statements) == 1
    assert got["storage_uri"] == rel.storage_uri
    assert got["citation"] == plan.fact.citation.model_dump(mode="json")
    assert got["fact"]["fact_id"] == plan.fact.fact_id
    assert got["release_id"] == rel.release_id and got["doc_id"] == "d1" and got["content_key"] == "ck"
    assert got["source_run_id"] == "run1" and got["item_key"] == "k1"
    assert store.lineage("fact_missing") is None
