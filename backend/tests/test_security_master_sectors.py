from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_identifier_map, get_portfolio_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.holdings import security_master
from arp.schemas.common import CompanyRef
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.issuer_sectors import IssuerSectorStore
from arp.storage.portfolio_store import PortfolioStore

ISIN, ISIN2 = "US0378331005", "DE0007164600"
HEADER = ",".join(security_master.COLUMNS)


def master(*lines: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *lines]) + "\n").encode()


# issuer_id,issuer_name,isin,cusip,sedol,figi,lei,cik,permid,valid_from,valid_to,nace_code,nace_rev,isic_code,gics_code
def row(issuer: str, isin: str, nace="", rev="", isic="", gics="") -> str:
    return f"{issuer},{issuer},{isin},,,,,,,,,{nace},{rev},{isic},{gics}"


@pytest.fixture
def env(tmp_path):
    idmap = IdentifierMapStore(tmp_path / "idmap.jsonl")
    sectors = IssuerSectorStore(tmp_path / "issuer_sectors.json")
    store = PortfolioStore(tmp_path / "pf", sectors)
    store.save_company(CompanyRef(company_id="nw", name="NW", nace_code="35.11"))
    return store, idmap


@pytest.fixture
def client(env):
    store, idmap = env
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[get_identifier_map] = lambda: idmap
    app.dependency_overrides[settings_dep] = lambda: Settings(identifier_map_path=idmap.path)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="Bo", role="approver")
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(c, data: bytes):
    return c.post("/api/security-master/upload", files={"file": ("m.csv", data, "text/csv")})


def messages(r) -> list[str]:
    return [e["message"] for e in r.json()["detail"]["errors"]]


def test_template_lists_sector_columns_last(client):
    assert client.get("/api/security-master/template").text == HEADER + "\n"
    assert HEADER.endswith("valid_from,valid_to,nace_code,nace_rev,isic_code,gics_code")


def test_two_nace_codes_for_one_issuer_are_refused_and_change_nothing(client):
    assert upload(client, master(row("a", ISIN))).status_code == 200
    before = client.get("/api/security-master").json()["issuers"]
    r = upload(client, master(row("nx", ISIN2, nace="07.29"), row("nx", ISIN2, nace="35.11")))
    assert r.status_code == 422 and "issuer 'nx' has two different nace_code values" in messages(r)
    assert client.get("/api/security-master").json()["issuers"] == before


def test_unknown_nace_code_is_refused(client):
    r = upload(client, master(row("nz", ISIN, nace="99.99")))
    assert r.status_code == 422 and "unknown NACE Rev. 2 code '99.99' for company 'nz'" in messages(r)


def test_bad_gics_is_refused(client):
    r = upload(client, master(row("nz", ISIN, gics="12345")))
    assert "bad GICS code '12345' for company 'nz'" in messages(r)


def test_old_eleven_column_master_still_loads(client):
    old = "issuer_id,issuer_name,isin,cusip,sedol,figi,lei,cik,permid,valid_from,valid_to"
    r = upload(client, master(f"a,A,{ISIN},,,,,,,,", header=old))
    assert r.status_code == 200 and (r.json()["identifiers"], r.json()["issuers"]) == (1, 1)


def test_master_sectors_override_stored_company_until_a_master_without_them(client, env):
    store, _ = env
    assert upload(client, master(row("nw", ISIN, nace="07.29"))).status_code == 200
    assert store.get_company("nw").nace_code == "07.29"
    assert [c.nace_code for c in store.list_companies()] == ["07.29"]
    assert upload(client, master(row("nw", ISIN))).status_code == 200
    assert store.get_company("nw").nace_code == "35.11"


def test_issuer_without_company_creates_none(client, env):
    store, _ = env
    upload(client, master(row("ghost", ISIN, nace="07.29")))
    assert store.get_company("ghost") is None and [c.company_id for c in store.list_companies()] == ["nw"]


def test_empty_nace_rev_next_to_a_code_is_rev_2_and_explicit_rev_is_kept(client, env):
    store, idmap = env
    upload(client, master(row("a", ISIN, nace="07.29"), row("b", ISIN2, nace="07.29", rev="2.1")))
    s = IssuerSectorStore(idmap.path.with_name("issuer_sectors.json"))
    assert s.get("a")["nace_rev"] == "2" and s.get("b")["nace_rev"] == "2.1"
    assert upload(client, master(row("a", ISIN, rev="3"))).status_code == 422


def test_nace_rev_without_a_code_is_ignored(client, env):
    store, idmap = env
    store.save_company(CompanyRef(company_id="nw", name="NW", nace_code="35.11", nace_rev="2"))
    assert upload(client, master(row("nw", ISIN, rev="2.1"))).status_code == 200
    assert IssuerSectorStore(idmap.path.with_name("issuer_sectors.json")).get("nw") == {}
    assert store.get_company("nw").nace_rev == "2"


def _pg_settings(pg, tmp_path):
    return Settings(postgres_dsn=pg, portfolios_dir=tmp_path / "pf", identifier_map_path=tmp_path / "idmap.jsonl")


def test_postgres_store_applies_the_master(pg, tmp_path):
    from arp.storage.portfolio_store_factory import build_portfolio_store

    s = _pg_settings(pg, tmp_path)
    store = build_portfolio_store(s)
    store.save_company(CompanyRef(company_id="nw", name="NW", nace_code="35.11"))
    IssuerSectorStore(s.identifier_map_path.with_name("issuer_sectors.json")).replace({"nw": {"nace_code": "07.29", "nace_rev": "2"}})
    assert store.get_company("nw").nace_code == "07.29"
    assert [c.nace_code for c in store.list_companies()] == ["07.29"]
    assert build_portfolio_store(s, merge_master=False).get_company("nw").nace_code == "35.11"


def test_db_import_stores_the_universe_code_not_the_masters(pg, tmp_path):
    from arp.db import importer
    from arp.storage.portfolio_store_factory import build_portfolio_store

    s = _pg_settings(pg, tmp_path)
    PortfolioStore(s.portfolios_dir).save_company(CompanyRef(company_id="nw", name="NW", nace_code="35.11"))
    IssuerSectorStore(s.identifier_map_path.with_name("issuer_sectors.json")).replace({"nw": {"nace_code": "07.29"}})
    importer._import_portfolios(s, importer.ImportReport(), dry_run=False)
    assert build_portfolio_store(s, merge_master=False).get_company("nw").nace_code == "35.11"
