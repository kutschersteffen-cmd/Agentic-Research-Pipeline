"""Score lineage AC-1, AC-2 and the never-published case: the from_authoritative dataset source."""

from __future__ import annotations

import os

import pytest

from tests.score_lineage_fixtures import F, seed

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")


@pytest.fixture
def fx(pg):
    return seed(pg)


def _build(pg, framework_id=F):
    from arp.authoritative.store import AuthoritativeStore
    from arp.decision.sources import from_authoritative

    return from_authoritative(AuthoritativeStore(pg), framework_id, None, None)


def _row(ds, company_id):
    return next(r for r in ds.rows if r["company_id"] == company_id)


def test_ac_1_rows_values_reasons_and_ids(pg, fx):
    ds = _build(pg)
    assert ds.source == "authoritative" and ds.source_ref == F
    assert len(ds.rows) == 4
    c = _row(ds, fx["company"]["C"])
    assert c["auth_scope1"] == ""
    assert c["auth_scope1__reason"] == "not_in_dataset"
    assert c["auth_scope1__value_id"] == str(fx["value_id"][("C", "auth_scope1")])
    a = _row(ds, fx["company"]["A"])
    assert a["auth_scope1"] == "90"
    assert a["Company"] == "Company A"
    assert ds.columns[:2] == ["company_id", "Company"]


def test_ac_2_ids_and_reasons_are_never_proposed_as_criteria(pg, fx):
    from arp.decision.mechanism import derive_mechanism

    config, _audit = derive_mechanism(_build(pg))
    assert not [c.column for c in config.criteria if c.column.endswith(("__reason", "__value_id"))]


def test_never_published_framework_is_refused(pg, fx):
    with pytest.raises(ValueError, match="No authoritative values published for fw_x"):
        _build(pg, "fw_x")


def test_large_values_keep_every_digit(pg, fx):
    from sqlalchemy import update

    from arp.authoritative.models import AuthoritativeValue
    from arp.db.session import transaction

    with transaction(pg) as s:
        s.execute(update(AuthoritativeValue).where(AuthoritativeValue.id == fx["value_id"][("D", "auth_scope1")])
                  .values(value=1234567.5))
    assert _row(_build(pg), fx["company"]["D"])["auth_scope1"] == "1234567.5"
