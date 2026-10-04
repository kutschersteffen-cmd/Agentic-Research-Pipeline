import pytest

from arp.publish.facts import (
    FactCandidate,
    Release,
    fact_key,
    plan_version,
    public_release,
)
from arp.schemas.common import Citation

T1 = "2026-10-01T09:00:00.000000+00:00"
T2 = "2026-10-02T09:00:00.000000+00:00"
LEI = "5493001KJTIIGC8Y1R12"


def _cit():
    return Citation.model_construct(doc_id="d1", content_key="ck")


def _cand(**kw):
    base = dict(
        issuer_key=LEI, issuer_scheme="LEI", field_id="f1", period_end="2024-12-31",
        value=1050.0, unit="tCO2e", state="approved", citation=_cit(),
        source_run_id="run1", observed_at=T1, item_key="k1",
    )
    base.update(kw)
    return FactCandidate(**base)


def _current(**kw):
    return plan_version(None, _cand(**kw), release_id="rel_1", now=T1).fact


def test_first_value_is_version_1():
    p = plan_version(None, _cand(), release_id="rel_1", now=T1)
    assert p.kind == "insert" and p.closes is None
    assert p.fact.version == 1 and p.fact.valid_from == T1
    assert p.fact.valid_to is None and p.fact.release_id == "rel_1"


def test_same_value_only_reconfirms():
    cur = _current()
    p = plan_version(cur, _cand(value="1050"), release_id="rel_2", now=T2)
    assert p.kind == "reconfirm" and p.closes is None
    assert p.fact.fact_id == cur.fact_id and p.fact.version == 1
    assert p.fact.reconfirmed_at == T2 and p.fact.release_id == "rel_1"


def test_changed_value_new_version_closes_old():
    cur = _current()
    p = plan_version(cur, _cand(value=1100), release_id="rel_2", now=T2)
    assert p.kind == "insert" and p.fact.version == 2 and p.fact.valid_from == T2
    assert p.closes.valid_to == T2 and p.closes.superseded_by == p.fact.fact_id


def test_unit_change_is_new_version():
    cur = _current(unit="tCO2e")
    p = plan_version(cur, _cand(unit="ktCO2e"), release_id="rel_2", now=T2)
    assert p.kind == "insert"


def test_older_run_never_supersedes_newer():
    cur = _current(observed_at=T2)
    p = plan_version(cur, _cand(value=1, observed_at=T1), release_id="r", now=T2)
    assert p.kind == "older" and p.fact is None
    p = plan_version(cur, _cand(observed_at=T1), release_id="r", now=T2)
    assert p.kind == "reconfirm"


def test_restated_candidate_marks_new_version_only():
    cur = _current()
    p = plan_version(
        cur, _cand(value=2, restated=True, restated_by_doc_id="d9"), release_id="r", now=T2
    )
    assert p.fact.restated is True and p.fact.restated_by_doc_id == "d9"
    assert p.closes.restated is False


def test_fact_key_uses_empty_basis():
    assert fact_key(_cand()) == (LEI, "f1", "2024-12-31", "")


def test_public_release_has_no_user_ids():
    r = Release(
        doc_id="d", content_key="c", storage_uri="u", issuer_key="i", issuer_scheme="LEI",
        run_id="r", published_at=T1, published_by="u1", published_by_role="approver",
        withdrawn_by="u2",
    )
    d = public_release(r)
    assert "published_by" not in d and "withdrawn_by" not in d
    assert d["published_by_role"] == "approver"


def test_published_facts_unique_key_version():
    pytest.importorskip("pgvector")
    from sqlalchemy import UniqueConstraint

    from arp.storage.postgres_models import PublishedFactModel

    cols = {
        frozenset(c.name for c in u.columns)
        for u in PublishedFactModel.__table__.constraints
        if isinstance(u, UniqueConstraint)
    }
    assert frozenset({"issuer_key", "field_id", "period_end", "basis", "version"}) in cols
