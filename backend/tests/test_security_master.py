from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_portfolio_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.discovery.match_rules import MatchRule, apply_identifier_rules
from arp.holdings import security_master
from arp.schemas.common import CompanyRef
from arp.schemas.issuer import issuer_key
from arp.schemas.portfolio import HolderConfig, Holding
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore

ISIN, ISIN2, LEI = "US0378331005", "DE0007164600", "5493001KJTIIGC8Y1R12"
HEADER = ",".join(security_master.COLUMNS)


def csv(*lines: str) -> bytes:
    """Rows without a permid (10 fields) get an empty one before the dates."""
    rows = [",".join([*f[:8], "", *f[8:]]) if len(f := line.split(",")) == 10 else line for line in lines]
    return ("\n".join([HEADER, *rows]) + "\n").encode()


@pytest.fixture
def env(tmp_path):
    return PortfolioStore(tmp_path / "pf"), IdentifierMapStore(tmp_path / "idmap.jsonl")


def test_each_identifier_on_a_row_points_at_its_internal_issuer(env):
    store, idmap = env
    out = security_master.load(store, idmap, csv(f"ISS-1,Apple,{ISIN},,,,{LEI},,,", f"ISS-1,Apple,{ISIN2},,,,{LEI},,,"), "m.csv")
    assert out["issuers"] == 1 and out["identifiers"] == 3, "the issuer's LEI is kept once"
    assert idmap.resolve("ISIN", ISIN) == ["ISS-1"] and idmap.resolve("LEI", LEI) == ["ISS-1"]
    assert security_master.status(store, idmap)["last_load"]["status"] == "ok"


@pytest.mark.parametrize("line, column", [
    (f",Apple,{ISIN},,,,,,,", "issuer_id"),
    ("ISS-1,Apple,US0378331006,,,,,,,", "isin"),  # check digit
    ("ISS-1,Apple,,,,,,,,", None),  # no identifier
    (f"ISS-1,Apple,{ISIN},,,,,,2026-13-01,", "valid_from"),
    (f"ISS-1,Apple,{ISIN},,,,,,P123,,", "permid"),  # digits only
])
def test_bad_rows_reject_the_whole_file_and_keep_the_old_master(env, line, column):
    store, idmap = env
    security_master.load(store, idmap, csv(f"ISS-1,Apple,{ISIN},,,,,,,"), "m.csv")
    with pytest.raises(security_master.MasterRejected) as e:
        security_master.load(store, idmap, csv(line), "m.csv")
    assert e.value.errors[0].column == column
    assert idmap.resolve("ISIN", ISIN) == ["ISS-1"], "a rejected file changes nothing"
    assert security_master.status(store, idmap)["last_load"]["status"] == "failed"


def test_one_identifier_on_two_issuers_at_once_is_refused_but_succession_is_fine(env):
    store, idmap = env
    with pytest.raises(security_master.MasterRejected):
        security_master.load(store, idmap, csv(f"ISS-1,A,{ISIN},,,,,,,", f"ISS-2,B,{ISIN},,,,,,,"), "m.csv")
    security_master.load(store, idmap, csv(f"ISS-1,A,{ISIN},,,,,,,2026-01-01", f"ISS-2,B,{ISIN},,,,,,2026-01-01,"), "m.csv")
    assert idmap.resolve("ISIN", ISIN, on="2025-06-30") == ["ISS-1"]
    assert idmap.resolve("ISIN", ISIN, on="2026-06-30") == ["ISS-2"]


def test_a_new_load_replaces_the_master_and_archives_the_old_one(env):
    store, idmap = env
    security_master.load(store, idmap, csv(f"ISS-1,A,{ISIN},,,,,,,"), "m.csv")
    security_master.load(store, idmap, csv(f"ISS-2,B,{ISIN2},,,,,,,"), "m.csv")
    assert idmap.resolve("ISIN", ISIN) == [] and idmap.resolve("ISIN", ISIN2) == ["ISS-2"]
    assert len(list(idmap.path.parent.glob("idmap.*.jsonl"))) == 1


def test_unmatched_lists_held_securities_the_master_does_not_know(env):
    store, idmap = env
    security_master.load(store, idmap, csv(f"ISS-1,A,{ISIN},,,,,,,"), "m.csv")
    store.save_holder(HolderConfig(holder_id="P1", kind="portfolio", as_of="2026-10-31"))
    store.save_snapshot("P1", "2026-10-31", [
        Holding(holder_id="P1", kind="portfolio", security_id=i, as_of_date="2026-10-31", isin=i, issuer_key="x",
                market_value_eur=1.0) for i in (ISIN, ISIN2)
    ], kind="portfolio")
    assert [(r["isin"], r["reason"]) for r in security_master.unmatched(store, idmap)] == [(ISIN2, "not in security master")]


def test_extraction_and_identity_use_the_internal_issuer_when_the_master_knows_the_lei(env):
    _, idmap = env
    company = CompanyRef(company_id="c1", name="Apple", lei=LEI)
    assert issuer_key(company, idmap) == (LEI, "LEI"), "unknown to the master: the LEI as before"
    assert apply_identifier_rules(company, idmap).rule == MatchRule.EXACT_LEI
    security_master.load(env[0], idmap, csv(f"ISS-1,Apple,,,,,{LEI},,,"), "m.csv")
    assert issuer_key(company, idmap) == ("ISS-1", "INTERNAL")
    outcome = apply_identifier_rules(company, idmap)
    assert (outcome.rule, outcome.issuer_key) == (MatchRule.IDENTIFIER_MAP, "ISS-1")


def test_only_an_approver_loads_the_master(tmp_path):
    store, settings = PortfolioStore(tmp_path / "pf"), Settings(identifier_map_path=tmp_path / "idmap.jsonl")
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        c = TestClient(app)
        files = {"file": ("m.csv", csv(f"ISS-1,A,{ISIN},,,,,,,"), "text/csv")}
        app.dependency_overrides[current_user] = lambda: Principal(user_id="u1", name="Ana", role="analyst")
        assert c.post("/api/security-master/upload", files=files).status_code == 403
        app.dependency_overrides[current_user] = lambda: Principal(user_id="u2", name="Bo", role="approver")
        r = c.post("/api/security-master/upload", files=files)
        assert r.status_code == 200, r.text
        assert c.get("/api/security-master").json()["identifiers"]["ISIN"] == 1
        bad = c.post("/api/security-master/upload", files={"file": ("m.csv", csv("ISS-1,A,,,,,,,,"), "text/csv")})
        assert bad.status_code == 422 and bad.json()["detail"]["errors"][0]["row"] == 2
    finally:
        app.dependency_overrides.clear()


def test_feeds_overview_shows_each_feed_and_whether_it_is_behind(env):
    from datetime import date

    from arp.portfolio import feeds
    from arp.portfolio.loads import LoadRecord, record_load

    store, idmap = env
    store.save_holder(HolderConfig(holder_id="P1", kind="portfolio", source="api", as_of="2026-09-30"))
    store.save_holder(HolderConfig(holder_id="IX1", kind="index", source="file", as_of="2026-08-31"))
    record_load(store, LoadRecord(kind="esg", source_id="msci", month="2026-09", status="ok", content_hash="h"))
    record_load(store, LoadRecord(kind="esg", source_id="msci", month="2026-10", status="failed", content_hash=""))
    rows = {(r["feed"], r["source_id"]): r for r in feeds.overview(store, idmap, date(2026, 10, 15))}
    assert rows[("security_master", "file")]["stale"] is True, "no master loaded"
    assert (rows[("holdings", "P1")]["stale"], rows[("holdings", "P1")]["channel"]) == (False, "api")
    assert rows[("index", "IX1")]["stale"] is True
    esg = rows[("esg", "msci")]
    assert (esg["as_of"], esg["stale"], esg["last_load"]["status"]) == ("2026-09", False, "failed"), "last ok month counts"
    assert rows[("news", "default")]["stale"] is True


def test_feeds_include_holdings_loaded_without_a_holder_config(env):
    from datetime import date

    from arp.portfolio import feeds
    from arp.portfolio.loads import LoadRecord, record_load

    store, idmap = env
    record_load(store, LoadRecord(kind="holdings", source_id="pf_seed", month="2026-09", status="ok", content_hash="h"))
    rows = {(r["feed"], r["source_id"]): r for r in feeds.overview(store, idmap, date(2026, 10, 15))}
    assert (rows[("holdings", "pf_seed")]["as_of"], rows[("holdings", "pf_seed")]["stale"]) == ("2026-09", False)
