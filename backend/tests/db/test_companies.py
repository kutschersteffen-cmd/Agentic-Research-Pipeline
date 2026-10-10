from __future__ import annotations

from sqlalchemy import func, select

from arp.db.companies import (
    Resolution,
    ensure_universe_company,
    identifiers_of,
    lookup,
    merge,
    resolve,
    resolve_company,
)
from arp.db.models import Company, CompanyIdentifier, IdScheme, Run, RunCompany
from arp.db.session import transaction
from arp.schemas.common import CompanyRef
from arp.schemas.issuer import issuer_key
from arp.universe import resolve_universe

LEI_A = "5493001KJTIIGC8Y1R13"
LEI_B = "529900T8BM49AURSDO55"


def _ref(**kw):
    return CompanyRef(**{"company_id": "SIE", "name": "Siemens", **kw})


def test_new_universe_row_creates_company_with_all_identifiers(pg):
    with transaction(pg) as s:
        r = resolve_company(s, _ref(lei=LEI_A, isin="de0007236101", cik="0000123", ticker="SIE"))
        assert r.created and r.company_id
        got = {(i.scheme, i.value) for i in s.scalars(select(CompanyIdentifier))}
    assert got == {("LEI", LEI_A), ("ISIN", "DE0007236101"), ("CIK", "123"), ("UNIVERSE", "SIE"), ("TICKER", "SIE")}
    assert [s for s, _ in identifiers_of(_ref(lei=LEI_A, isin="X", cik="1", ticker="T"))] == [
        IdScheme.LEI,
        IdScheme.ISIN,
        IdScheme.CIK,
        IdScheme.UNIVERSE,
        IdScheme.TICKER,
    ]


def test_renamed_universe_id_same_lei_attaches(pg):
    with transaction(pg) as s:
        a = resolve_company(s, _ref(lei=LEI_A))
        b = resolve_company(s, _ref(company_id="SIE2", lei=LEI_A))
        assert b.company_id == a.company_id and b.created is False
        active = set(
            s.scalars(
                select(CompanyIdentifier.value).where(
                    CompanyIdentifier.scheme == "UNIVERSE", CompanyIdentifier.valid_to.is_(None)
                )
            )
        )
    assert active == {"SIE", "SIE2"}


def test_conflicting_identifiers_return_conflict(pg):
    with transaction(pg) as s:
        a = resolve_company(s, _ref(company_id="A", lei=LEI_A)).company_id
        b = resolve_company(s, _ref(company_id="B", isin="DE0000000001")).company_id
        n = s.scalar(select(func.count()).select_from(CompanyIdentifier))
        r = resolve_company(s, _ref(company_id="C", lei=LEI_A, isin="DE0000000001"))
        assert r.company_id is None and set(r.conflict) == {a, b}
        assert s.scalar(select(func.count()).select_from(CompanyIdentifier)) == n


def test_provider_row_never_creates(pg):
    with transaction(pg) as s:
        r = resolve(s, [(IdScheme.LEI, LEI_A)], name="x", allow_create=False)
        assert r == Resolution(None, False, [])
        assert s.scalar(select(func.count()).select_from(Company)) == 0


def test_resolution_order_lei_first(pg):
    with transaction(pg) as s:
        a = resolve_company(s, _ref(lei=LEI_A)).company_id
        r = resolve_company(s, _ref(company_id="NEW", lei=LEI_A))
        assert r.company_id == a


def test_merge_moves_identifiers_and_rows(pg):
    with transaction(pg) as s:
        keep = resolve_company(s, _ref(company_id="K", lei=LEI_A)).company_id
        drop = resolve_company(s, _ref(company_id="D", lei=LEI_B)).company_id
        s.add(Run(run_id="r1", run_type="t", status="running"))
        s.flush()
        s.add(RunCompany(run_id="r1", company_id=drop))
        s.flush()
        merge(s, keep, drop)
        assert lookup(s, IdScheme.LEI, LEI_B) == keep
        assert s.scalar(select(RunCompany.company_id).where(RunCompany.run_id == "r1")) == keep
        assert lookup(s, IdScheme.MERGED_INTO, str(drop)) == keep


def test_issuer_key_is_stable_across_security_master_upload(pg):
    with transaction(pg) as s:
        c = _ref(lei=LEI_A)
        before = issuer_key(c, session=s)
        resolve(s, [(IdScheme.LEI, LEI_A), (IdScheme.ISIN, "DE0007236101")], name="x", allow_create=False)
        assert issuer_key(_ref(lei=LEI_A, isin="DE0007236101"), session=s) == before
        assert before[1] == "INTERNAL"


def test_ensure_universe_company(pg):
    with transaction(pg) as s:
        existing = resolve_company(s, _ref()).company_id
        assert ensure_universe_company(s, "SIE") == existing
        new = ensure_universe_company(s, "NEW", name="New Co")
        assert ensure_universe_company(s, "NEW") == new != existing


def test_resolve_universe_splits_conflicts(pg):
    with transaction(pg) as s:
        resolve_company(s, _ref(company_id="A", lei=LEI_A))
        resolve_company(s, _ref(company_id="B", isin="DE0000000001"))
        ok, bad = resolve_universe([_ref(company_id="A", lei=LEI_A), _ref(company_id="C", lei=LEI_A, isin="DE0000000001")], s)
    assert [c.company_id for c in ok] == ["A"] and ok[0].entity_id
    assert bad[0]["kind"] == "identity_conflict" and bad[0]["company_id"] == "C" and len(bad[0]["conflict"]) == 2


def test_two_companies_merge_into_one_keep(pg):
    with transaction(pg) as s:
        k, a, b = (
            resolve_company(s, _ref(company_id=i, lei=lei)).company_id
            for i, lei in (("K", LEI_A), ("A", LEI_B), ("B", "7H6GLXDRUGQFU57RNE97"))
        )
        merge(s, k, a)
        merge(s, k, b)
        assert lookup(s, IdScheme.MERGED_INTO, str(a)) == k and lookup(s, IdScheme.MERGED_INTO, str(b)) == k


def test_concurrent_resolution_of_same_new_company(pg):
    import threading

    barrier = threading.Barrier(2)
    ids = []

    def work():
        with transaction(pg) as s:
            orig = s.scalar
            calls = []

            def synced(*a, **k):  # both sessions finish reading before either inserts
                r = orig(*a, **k)
                calls.append(1)
                if len(calls) == 2:
                    barrier.wait(timeout=10)
                return r

            s.scalar = synced
            ids.append(resolve_company(s, _ref(lei=LEI_A)).company_id)
            s.scalar = orig

    ts = [threading.Thread(target=work) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ids) == 2 and ids[0] == ids[1]
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(Company)) == 1
