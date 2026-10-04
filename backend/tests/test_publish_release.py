from __future__ import annotations

import hashlib

import pytest

from arp.publish.facts import Fact, FactCandidate, Release, fact_key
from arp.publish.release import WithdrawalError, plan_release, plan_withdrawal, split_by_gate
from arp.schemas.common import Citation
from arp.storage.document_blob_store import LocalBlobStore

T0 = "2026-01-01T00:00:00.000000+00:00"
T1 = "2026-02-01T00:00:00.000000+00:00"
NOW = "2026-03-01T00:00:00.000000+00:00"
DOCS = {d: hashlib.sha256(f"original {d}".encode()).hexdigest() for d in ("d1", "d2")}


def _cit(doc="d1"):
    return Citation(doc_id=doc, doc_type="10-K", quote="1000", grounded=True, content_key=DOCS[doc])


def _cand(key="k1", doc="d1", field="f1", issuer="ISS", value=1000, **kw):
    return FactCandidate(
        issuer_key=issuer, issuer_scheme="LEI", field_id=field, period_end="2024-12-31", value=value,
        state="approved", citation=_cit(doc) if doc else None, source_run_id="r1", observed_at=T0, item_key=key, **kw,
    )


def _plan(group, current=None):
    return plan_release(group, current or {}, run_id="r1", published_by="u1", published_by_role="approver",
                        storage_uri="file:///blob", now=NOW)


def _fact(fact_id, release_id, value, version, valid_from, **kw):
    c = _cand(value=value)
    return Fact(**c.model_dump(exclude={"citation"}), citation=c.citation, fact_id=fact_id, release_id=release_id,
                version=version, valid_from=valid_from, **kw)


def _release(release_id="rel_b", **kw):
    return Release(release_id=release_id, doc_id="d1", content_key=DOCS["d1"], storage_uri="file:///blob",
                   issuer_key="ISS", issuer_scheme="LEI", run_id="r2", published_at=T1, published_by="u1",
                   published_by_role="approver", **kw)


@pytest.fixture
def blobs(tmp_path):
    store = LocalBlobStore(tmp_path / "blobs")
    for d, key in DOCS.items():
        store.put(key, f"original {d}".encode())
    return store


def test_one_release_per_document(blobs):
    cands = [_cand("k1", "d1", "f1"), _cand("k2", "d1", "f2"), _cand("k3", "d2", "f3")]
    groups, blocked = split_by_gate(cands, blobs, withdrawn_docs=set())
    assert blocked == [] and set(groups) == {("ISS", "d1"), ("ISS", "d2")}
    releases = []
    for group in groups.values():
        rel, plans, events = _plan(group)
        releases.append(rel)
        assert all(p.fact.release_id == rel.release_id for p in plans)
        assert [e.event_type for e in events] == ["published"] * len(group)
    assert {r.doc_id for r in releases} == {"d1", "d2"}
    assert all(r.content_key == DOCS[r.doc_id] for r in releases)


def test_republish_unchanged_creates_no_release():
    c = _cand()
    first, plans, _ = _plan([c])
    current = {fact_key(c): plans[0].fact}
    rel, plans, events = _plan([c], current)
    assert rel is None and events == [] and [p.kind for p in plans] == ["reconfirm"]


def test_restated_insert_emits_restated_event():
    c = _cand()
    _, plans, _ = _plan([c])
    rel, plans, events = _plan([_cand(value=8, restated=True, restated_by_doc_id="d1")], {fact_key(c): plans[0].fact})
    assert rel is not None and [e.event_type for e in events] == ["restated"]
    assert plans[0].fact.version == 2 and plans[0].closes is not None


def test_missing_original_blocks_whole_document(tmp_path):
    store = LocalBlobStore(tmp_path / "blobs")
    store.put(DOCS["d2"], b"original d2")
    groups, blocked = split_by_gate([_cand("k1"), _cand("k2", field="f2"), _cand("k3", "d2")], store,
                                    withdrawn_docs=set())
    assert blocked == [{"doc_id": "d1", "reason": "original_missing", "item_keys": ["k1", "k2"]}]
    assert list(groups) == [("ISS", "d2")]


def test_candidate_without_citation_blocked_alone(blobs):
    groups, blocked = split_by_gate([_cand("k1", doc=None), _cand("k2")], blobs, withdrawn_docs=set())
    assert blocked == [{"doc_id": None, "reason": "no_grounded_citation", "item_keys": ["k1"]}]
    assert [c.item_key for c in groups[("ISS", "d1")]] == ["k2"]


def test_withdrawn_document_not_republished(blobs):
    groups, blocked = split_by_gate([_cand("k1"), _cand("k3", "d2")], blobs, withdrawn_docs={"d1"})
    assert blocked == [{"doc_id": "d1", "reason": "release_withdrawn", "item_keys": ["k1"]}]
    assert list(groups) == [("ISS", "d2")]


def test_document_cited_by_two_issuers_gets_two_releases(blobs):
    groups, _ = split_by_gate([_cand("k1", issuer="ISS"), _cand("k2", issuer="OTHER")], blobs, withdrawn_docs=set())
    assert set(groups) == {("ISS", "d1"), ("OTHER", "d1")}
    rels = [_plan(g)[0] for g in groups.values()]
    assert sorted(r.issuer_key for r in rels) == ["ISS", "OTHER"] and len({r.release_id for r in rels}) == 2


def test_withdrawal_restores_previous_fact():
    v1 = _fact("fact_v1", "rel_a", 1000, 1, T0, valid_to=T1, superseded_by="fact_v2")
    v2 = _fact("fact_v2", "rel_b", 1100, 2, T1)
    rel, closes, restores, events = plan_withdrawal(_release(), [v2], {v2.fact_id: v1}, reason="wrong doc",
                                                    withdrawn_by="u2", now=NOW)
    [closed], [copy] = closes, restores
    assert closed.fact_id == "fact_v2" and closed.valid_to == NOW and closed.superseded_by == copy.fact_id
    assert copy.fact_id not in ("fact_v1", "fact_v2")
    assert (copy.value, copy.version, copy.restored_from, copy.release_id) == (1000, 3, "fact_v1", "rel_a")
    assert (copy.valid_from, copy.valid_to, copy.superseded_by, copy.reconfirmed_at) == (NOW, None, None, None)
    assert [e.event_type for e in events] == ["withdrawn", "restored"]
    assert (rel.withdrawn_at, rel.withdrawal_reason, rel.withdrawn_by) == (NOW, "wrong doc", "u2")


def test_withdrawal_without_reason_refused():
    with pytest.raises(WithdrawalError, match="a withdrawal needs a reason"):
        plan_withdrawal(_release(), [], {}, reason="  ", withdrawn_by="u2", now=NOW)


def test_withdrawn_twice_refused():
    with pytest.raises(WithdrawalError, match="release already withdrawn"):
        plan_withdrawal(_release(withdrawn_at=T1, withdrawal_reason="x", withdrawn_by="u2"), [], {},
                        reason="again", withdrawn_by="u2", now=NOW)


def test_withdraw_first_version_leaves_no_current():
    v1 = _fact("fact_v1", "rel_b", 1000, 1, T0)
    _, [closed], restores, events = plan_withdrawal(_release(), [v1], {}, reason="r", withdrawn_by="u2", now=NOW)
    assert restores == [] and closed.valid_to == NOW and closed.superseded_by is None
    assert [e.event_type for e in events] == ["withdrawn"]


def test_superseded_version_not_reopened():
    v2 = _fact("fact_v2", "rel_b", 1100, 2, T0, valid_to=T1, superseded_by="fact_v3")
    v1 = _fact("fact_v1", "rel_a", 1000, 1, T0, valid_to=T0, superseded_by="fact_v2")
    _, closes, restores, events = plan_withdrawal(_release(), [v2], {v2.fact_id: v1}, reason="r", withdrawn_by="u2",
                                                  now=NOW)
    assert closes == [] and restores == [] and events == []
