from __future__ import annotations

import pytest

from arp.schemas.common import CompanyRef
from arp.schemas.issuer import IdentifierMap
from arp.storage.identifier_map import IdentifierMapStore
from arp.universe_workbench.mapping import MasterIndex
from arp.universe_workbench.routing import country_market, route_company, route_universe

LEI = "529900ABCDEFGHIJ1234"
NO_SRC = "no XBRL source for JP yet"
UNROUTED = "no country or identifier: add an ISIN, LEI or CIK, or load it into the security master"


def _r(index=None, **kw):
    return route_company(CompanyRef(company_id="X", name="X", **kw), index)


@pytest.mark.parametrize("country,market", [
    ("Germany", "esef"), ("DE", "esef"), ("DEU", "esef"), ("de", "esef"),
    ("United States", "sec"), ("us", "sec"), ("USA", "sec"), ("United States of America", "sec"),
    ("United Kingdom", "esef"), ("GB", "esef"), ("UK", "esef"), ("Great Britain", "esef"),
    ("Norway", "esef"), ("IS", "esef"), ("Atlantis", None), ("", None), (None, None),
])
def test_country_decides(country, market):
    assert country_market(country) == market
    if market:
        r = _r(country=country)
        assert (r.market, r.status, r.basis) == (market, "routed", "country")


def test_home_country_beats_cik():
    r = _r(country="DE", cik="320193")
    assert (r.market, r.basis) == ("esef", "country")


@pytest.mark.parametrize("isin,market,status,basis,detail", [
    ("US0378331005", "sec", "routed", "isin_prefix", None),
    ("DE000BASF111", "esef", "routed", "isin_prefix", None),
    ("JP3633400001", None, "no_source", "isin_prefix", NO_SRC),
    ("XS1234567890", None, "unrouted", None, UNROUTED),
])
def test_isin_prefix(isin, market, status, basis, detail):
    r = _r(isin=isin)
    assert (r.market, r.status, r.basis) == (market, status, basis)
    if detail:
        assert r.detail == detail


def test_country_beats_isin_prefix():
    r = _r(country="US", isin="DE000BASF111")
    assert (r.market, r.basis) == ("sec", "country")


def test_cik_beats_lei_without_country():
    r = _r(cik="320193", lei=LEI)
    assert (r.market, r.basis) == ("sec", "cik")


def test_lei_alone_gives_esef():
    r = _r(lei=LEI)
    assert (r.market, r.basis) == ("esef", "lei")


def test_lowercase_and_spaced_identifiers():
    assert _r(isin=" de000basf111 ").basis == "isin_prefix"
    assert _r(cik=" 0000320193 ").basis == "cik"
    assert _r(lei=" 5299 00abcdefghij1234").basis == "lei"


def test_unrecognised_country_is_ignored_and_noted():
    r = _r(country="Atlantis", cik="320193")
    assert (r.market, r.basis) == ("sec", "cik")
    assert "country 'Atlantis' not recognised" in r.detail


def _master(tmp_path, *rows):
    s = IdentifierMapStore(tmp_path / "idmap.jsonl")
    for scheme, value in rows:
        s.add(IdentifierMap(issuer_key="I1", scheme=scheme, value=value))
    return MasterIndex.build(s)


def test_master_enrichment_then_reroute(tmp_path):
    idx = _master(tmp_path, ("ISIN", "XS1234567890"), ("CIK", "320193"))
    r = _r(idx, isin="XS1234567890")
    assert (r.status, r.market, r.basis) == ("routed", "sec", "master")
    assert r.company.cik == "320193"


def test_no_source_isin_prefix_is_final_even_if_master_knows_the_issuer(tmp_path):
    idx = _master(tmp_path, ("ISIN", "CA0679011084"), ("CIK", "320193"))
    r = _r(idx, isin="CA0679011084")
    assert (r.status, r.market) == ("no_source", None)


def test_master_hit_without_deciding_identifiers(tmp_path):
    idx = _master(tmp_path, ("ISIN", "XS1234567890"))
    assert _r(idx, isin="XS1234567890").status == "unrouted"
    assert _r(idx, isin="XS1234567890", ticker="ABC").basis == "ticker_fallback"


def test_ticker_fallback():
    r = _r(ticker="AAPL")
    assert (r.market, r.basis) == ("sec", "ticker_fallback")


def test_unrouted():
    r = _r()
    assert (r.market, r.status, r.basis, r.detail) == (None, "unrouted", None, UNROUTED)


def test_route_universe_keeps_order_and_duplicates():
    cs = [CompanyRef(company_id=i, name=i, **kw) for i, kw in
          (("a", {"country": "DE"}), ("b", {}), ("a", {"country": "DE"}))]
    rs = route_universe(cs)
    assert [r.company.company_id for r in rs] == ["a", "b", "a"]
    assert [r.status for r in rs] == ["routed", "unrouted", "routed"]
