"""The `nace` link source on Fixture V and Store N (spec 2026-11-02-nace-exiobase-link-design, Acceptance)."""

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_portfolio_store
from arp.api.main import app
from arp.cli import app as cli_app
from arp.holdings import security_master
from arp.research.indirect_exposure.migrate import icio_sectors
from arp.research.value_chain.links import company_nace
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.issuer_sectors import IssuerSectorStore
from arp.storage.portfolio_store import PortfolioStore
from tests.io_tier_fixture import write_fixture_v
from tests.test_value_chain_links import BASE, nodes, runner

ISINS = ["US0378331005", "DE0007164600", "US5949181045"]
HEADER = ",".join(security_master.COLUMNS)
NS_SPLIT = {"kind": "split", "parts": [{"sectors": icio_sectors("B07"), "share": 1}]}
N = {
    "nc": {"country": "CN", "nace_code": "07.29"},
    "nw": {"country": "DE", "nace_code": "35.11"},
    "nr": {"country": "DE", "nace_code": "35.12", "nace_rev": "2.1"},
    "nf": {"country": "DE", "nace_code": "35.11", "nace_rev": "2.1"},
    "ni": {"country": "CN", "isic_code": "2710"},
    "nm": {"country": "CN", "nace_code": "27.11", "isic_code": "C27"},
    "nd": {"country": "CN", "nace_code": "27"},
    "nu": {"nace_code": "07.29"},
    "ng": {"country": "CN", "gics_code": "20104010"},
    "nj": {"country": "CN", "isic_code": "0710"},
    "ns": {"country": "CN", "nace_code": "27.11"},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "vc"
    res = runner.invoke(cli_app, ["io", "build-full", str(write_fixture_v(tmp_path / "src")), "--out", str(out)])
    assert res.exit_code == 0, res.output
    monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", str(out))
    store = PortfolioStore(tmp_path / "pf", IssuerSectorStore(tmp_path / "issuer_sectors.json"))
    for cid, fields in N.items():
        store.save_company(CompanyRef(company_id=cid, name=cid.upper(), **fields))
    idmap = IdentifierMapStore(tmp_path / "idmap.jsonl")
    app.dependency_overrides[get_portfolio_store] = lambda: store
    client = TestClient(app)
    assert client.put(f"{BASE}/links/company/ns", json=NS_SPLIT).status_code == 200

    def master(*rows: str) -> None:  # M(file); a row is issuer,nace_code,nace_rev,isic_code,gics_code
        lines = [f"{r.split(',')[0]},X,{isin},,,,,,,,,{','.join(r.split(',')[1:])}" for r, isin in zip(rows, ISINS, strict=False)]
        security_master.load(store, idmap, ("\n".join([HEADER, *lines]) + "\n").encode(), "m.csv")

    yield client, store, master
    app.dependency_overrides.pop(get_portfolio_store, None)


def L(client, cid):
    res = client.get(f"{BASE}/links/company/{cid}")
    assert res.status_code == 200
    return res.json()


def test_nace_links(env):  # AC-3 to AC-10c
    client, _, _ = env
    nc = L(client, "nc")
    assert (nc["source"], nc["region"], nodes(nc)) == ("nace", "CN", [("CN.1", 0.7143), ("CN.2", 0.2857)])
    assert (nc["unresolved"], nc["rule"], nc["code"], nc["code_scheme"]) == ([], None, "07.29", "nace2")
    for cid, want in [("nw", [("DE.3", 1.0)]), ("nr", [("DE.3", 1.0)]), ("ni", [("CN.4", 1.0)]),
                      ("nm", [("CN.4", 1.0)]), ("nd", [("CN.4", 1.0)])]:
        body = L(client, cid)
        assert (body["source"], nodes(body)) == ("nace", want), cid
    assert (L(client, "nr")["code_scheme"], L(client, "ni")["code"], L(client, "ni")["code_scheme"]) == ("nace21", "2710", "isic4")
    nf = L(client, "nf")
    assert (nf["source"], nf["nodes"], nf["unresolved"]) == ("nace", [], [{"nace_code": "35.11", "nace_rev": "2.1"}])
    nu = L(client, "nu")
    assert (nu["source"], nu["region"], nodes(nu)) == (
        "nace", None, [("CN.1", 0.3704), ("WA.1", 0.2222), ("DE.1", 0.1852), ("CN.2", 0.1481), ("WA.2", 0.0741)])
    ns = L(client, "ns")
    assert (ns["source"], ns["rule"]["kind"], ns["code"], ns["code_scheme"]) == ("split", "split", None, None)
    nj = L(client, "nj")
    assert (nj["source"], nj["nodes"], nj["unresolved"]) == ("nace", [], [{"isic_code": "0710"}])
    ng = L(client, "ng")
    assert (ng["source"], ng["nodes"], ng["code"]) == ("none", [], None)


def test_company_nace_routes():
    def ref(**kw):
        return CompanyRef(company_id="x", name="X", **kw)

    assert company_nace(ref(nace_code="35.12", nace_rev="2.1")) == ("nace21", "35.12", "2.1")
    assert company_nace(ref(nace_code="27.11", isic_code="2710")) == ("nace2", "27.11", "2")
    assert company_nace(ref(isic_code="2710")) == ("isic4", "2710", "2")
    assert company_nace(ref(isic_code="C27")) is None  # an old ICIO code: no NACE route (AC-33)
    assert company_nace(ref(isic_code="07")) == ("isic4", "07", "2")  # a 2-digit ISIC division (AC-32)
    assert company_nace(ref(gics_code="20104010")) is None


def test_master_sector_values_apply_to_links(env):  # AC-18, AC-18c, AC-19
    client, _, master = env
    master("nw,07.29,,,", "ng,,,2710,")
    assert (L(client, "nw")["source"], nodes(L(client, "nw"))) == ("nace", [("DE.1", 1.0)])
    assert (L(client, "ng")["source"], nodes(L(client, "ng"))) == ("nace", [("CN.4", 1.0)])
    master("nw,,,,", "ng,,,,")
    assert nodes(L(client, "nw")) == [("DE.3", 1.0)]


def test_master_revision_alone_reinterprets_the_code(env):  # AC-18b
    client, _, master = env
    master("nr,,2,,")
    nr = L(client, "nr")
    assert (nr["source"], nr["nodes"], nr["unresolved"]) == ("nace", [], [{"nace_code": "35.12", "nace_rev": "2"}])


def test_master_leaves_a_stored_rule_alone(env):  # AC-29
    client, _, master = env
    before = L(client, "ns")["rule"]
    master("ns,07.29,,,")
    after = L(client, "ns")
    assert after["rule"] == before and after["source"] == "split"
    assert {k: after["rule"][k] for k in ("kind", "parts")} == NS_SPLIT


def test_overlay_link_source_is_nace(env):  # AC-20
    client, store, _ = env
    for cid in ("nc", "nw"):
        store.save_security(SecurityRef(security_id=f"s_{cid}", name=cid, asset_class="equity", currency="EUR", company_id=cid))
    store.save_portfolio(Portfolio(portfolio_id="P", name="P"))
    store.save_snapshot("P", "2026-09-30", [
        Holding(holder_id="P", security_id=s, as_of_date="2026-09-30", market_value=v, market_value_eur=v)
        for s, v in (("s_nc", 6e5), ("s_nw", 4e5))])
    body = client.get(f"{BASE}/portfolio/P").json()
    assert [h["link_source"] for h in body["holdings"]] == ["nace", "nace"]
