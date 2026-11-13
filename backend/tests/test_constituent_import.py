import pytest
from openpyxl import Workbook

from arp.portfolio.constituent_import import (
    ASSET_CLASS,
    COUNTRY,
    SECTOR,
    import_constituent_files,
    import_holdings_file,
    import_holdings_files,
)
from arp.portfolio.loads import latest_load
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.safe_path import safe_id

HEADER = [
    None,
    "Name",
    "ISIN",
    "Country",
    "Currency",
    "Exchange",
    "Type of Security",
    "Rating",
    "Primary Listing",
    "Industry Classification",
    "Weighting",
]


def _xlsx(tmp_path, rows, title="2026-10-02", isin="IE00TESTFUND", name=None):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws["A2"] = "Disclaimer"
    for col, v in enumerate(HEADER, 1):
        ws.cell(row=4, column=col, value=v)
    for i, r in enumerate(rows, 5):
        for col, v in enumerate([None, *r[:2], r[2], r[3], None, r[4], None, None, r[5], r[6]], 1):
            ws.cell(row=i, column=col, value=v)
    path = tmp_path / (name or f"Constituent_{isin}.xlsx")
    wb.save(path)
    return path


# name, isin, country, ccy, type, industry, weight
ROWS = [
    ("Apple", "US0378331005", "Vereinigte Staaten von Amerika", "USD", "Aktien", "Informationstechnologie", 0.5),
    ("Dead Co", "GB00DEAD0001", "Großbritannien (UK)", "GBP", "Aktien", "Finanzen", "N/A"),
    ("Cash EUR", "CASH_EUR", "-", "EUR", "Cash", "-", -0.01),
    ("Index fut", "___ADI2VD0J5", "-", "USD", "Future", "-", 0.02),
    ("Odd", "XS0000000001", "Atlantis", "EUR", "Gizmo", "Industrieunternehmen", 0.1),
]


def test_import(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    path = _xlsx(tmp_path, ROWS)
    s = import_constituent_files(store, [path], 100.0)
    p = s["portfolios"][0]
    assert (p["rows_read"], p["holdings_written"], p["as_of_date"]) == (5, 4, "2026-10-02")
    assert p["skipped_no_weight"] == [{"name": "Dead Co", "isin": "GB00DEAD0001", "weighting": "N/A"}]
    assert p["weight_sum"] == pytest.approx(0.61)
    assert s["untranslated"] == ["Atlantis"] and s["other_asset_classes"] == ["Gizmo"]
    assert store.get_portfolio("portfolio_ie00testfund").name == "Portfolio IE00TESTFUND"
    h = {x.security_id: x for x in store.load_snapshot("portfolio_ie00testfund", "2026-10-02")}
    assert h["US0378331005"].market_value_eur == 50 and h["US0378331005"].weight_pct == 50
    assert h["CASH_EUR"].market_value_eur == -1  # negative kept
    assert store.get_security("CASH_EUR").asset_class == "cash"
    assert store.get_security("___ADI2VD0J5").asset_class == "derivative"
    assert store.get_security("XS0000000001").asset_class == "other"
    c = store.get_company("isin_US0378331005")
    assert (c.country, c.sector) == ("United States", "Information Technology")
    assert store.get_company("isin_CASH_EUR").sector is None
    assert store.get_company("isin_XS0000000001").country == "Atlantis"
    # placeholder ISINs with a leading "_" still give a safe id: the prefix starts it alphanumerically
    assert safe_id(store.get_security("___ADI2VD0J5").company_id) == "isin____ADI2VD0J5"


def test_unsafe_isin_fails_at_import(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    bad = ("Slash", "US03/8331005", "-", "USD", "Aktien", "-", 0.1)
    path = _xlsx(tmp_path, [ROWS[0], bad])
    with pytest.raises(ValueError, match=r"Constituent_IE00TESTFUND\.xlsx row 6: ISIN 'US03/8331005'"):
        import_constituent_files(store, [path], 100.0)


def test_idempotent(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    path = _xlsx(tmp_path, ROWS)
    import_constituent_files(store, [path], 100.0)
    first = store.load_snapshot("portfolio_ie00testfund", "2026-10-02")
    import_constituent_files(store, [path], 100.0)
    assert store.load_snapshot("portfolio_ie00testfund", "2026-10-02") == first
    assert len(store.list_portfolios()) == 1


@pytest.mark.parametrize("title", ["Sheet1", "02.10.2026"])
def test_bad_sheet_title(tmp_path, title):
    with pytest.raises(ValueError, match="ISO date"):
        import_constituent_files(PortfolioStore(tmp_path / "s"), [_xlsx(tmp_path, ROWS, title=title)], 1.0)


def test_bad_file_name(tmp_path):
    path = _xlsx(tmp_path, ROWS)
    bad = path.rename(tmp_path / "holdings.xlsx")
    with pytest.raises(ValueError, match="Constituent_"):
        import_constituent_files(PortfolioStore(tmp_path / "s"), [bad], 1.0)


def test_notional_tag_is_plain_digits(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    import_constituent_files(store, [_xlsx(tmp_path, ROWS[:1])], 1e8)
    assert "sizing:assumed-notional-eur-100000000" in store.get_portfolio("portfolio_ie00testfund").tags


def test_missing_security_type_is_not_reported_as_none(tmp_path):
    rows = [("NoType", "XS0000000002", "Japan", "JPY", None, "Energie", 0.1)]
    s = import_constituent_files(PortfolioStore(tmp_path / "store"), [_xlsx(tmp_path, rows)], 1.0)
    assert s["other_asset_classes"] == ["(blank)"]


def test_two_projects_get_disjoint_tagged_portfolios(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    path = _xlsx(tmp_path, ROWS)
    for proj in ("alpha", "beta"):
        import_constituent_files(store, [path], 100.0, project_id=proj)
    ps = {p.portfolio_id: p for p in store.list_portfolios()}
    assert set(ps) == {"alpha-portfolio-ie00testfund", "beta-portfolio-ie00testfund"}
    assert "project:alpha" in ps["alpha-portfolio-ie00testfund"].tags and "project:beta" not in ps["alpha-portfolio-ie00testfund"].tags
    assert "project:beta" in ps["beta-portfolio-ie00testfund"].tags
    assert len(store.list_companies()) == 5  # shared across projects, not duplicated (the N/A-weight row counts too)


def test_no_project_keeps_old_id_and_no_project_tag(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    import_constituent_files(store, [_xlsx(tmp_path, ROWS)], 100.0)
    (p,) = store.list_portfolios()
    assert p.portfolio_id == "portfolio_ie00testfund"
    assert not any(t.startswith("project:") for t in p.tags)


def test_project_reimport_overwrites(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    path = _xlsx(tmp_path, ROWS)
    for _ in range(2):
        import_constituent_files(store, [path], 100.0, project_id="alpha")
    assert [p.portfolio_id for p in store.list_portfolios()] == ["alpha-portfolio-ie00testfund"]
    assert store.list_snapshot_dates("alpha-portfolio-ie00testfund") == ["2026-10-02"]


@pytest.mark.parametrize("bad", ["Alpha", "-a", "a_b", "../x"])
def test_bad_project_id_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        import_constituent_files(PortfolioStore(tmp_path / "store"), [_xlsx(tmp_path, ROWS)], 100.0, project_id=bad)


# --- showcase-portfolio-data PR 2: any file name, English labels, load record, rows without a weight ---

ENGLISH_ROWS = [
    ("Nvidia", "US67066G1040", "United States", "USD", "Equities", "Technology", 0.4),
    ("Samsung Pref", "KR7005931001", "Korea, Republic of", "KRW", "Preferred Stock", "unknown", 0.2),
    ("Naspers", "ZAE000351946", "Südafrika", "ZAR", "Aktien", "Grundstoffe", 0.2),
    ("A share class", "XS0000000003", "Indien", "INR", "Share Class", "Telecommunications", 0.1),
    ("A right", "XS0000000004", "Polen", "PLN", "Right", "Financials", 0.1),
]


def _events(store, portfolio_id):
    return [e for e in store.list_governance_events() if e.get("event_type") == "load_recorded" and e["source_id"] == portfolio_id]


def test_any_file_name_imports_under_its_own_name_without_a_notional(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    s = import_holdings_files(store, [_xlsx(tmp_path, ROWS, name="My_Index.xlsx")])
    assert s["notional_eur"] == 100_000_000 and s["portfolios"][0]["portfolio_id"] == "portfolio_my_index"
    p = store.get_portfolio("portfolio_my_index")
    assert p.name == "My Index (public ETF holdings, 2026-10-02)"
    assert p.tags == ["source:My_Index.xlsx", "sizing:assumed-notional-eur-100000000"]
    h = {x.security_id: x for x in store.load_snapshot("portfolio_my_index", "2026-10-02")}
    assert h["US0378331005"].market_value_eur == 50_000_000 and h["US0378331005"].weight_pct == 50


def test_fund_isin_and_project_on_a_plain_file(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    path = _xlsx(tmp_path, ROWS, name="DAX.xlsx")
    import_holdings_files(store, [path], fund_isin="IE00BGV5VN51")
    assert "fund_isin:IE00BGV5VN51" in store.get_portfolio("portfolio_dax").tags
    import_holdings_files(store, [path], project_id="p1")
    assert store.get_portfolio("p1-portfolio-dax").tags == ["source:DAX.xlsx", "sizing:assumed-notional-eur-100000000", "project:p1"]


def test_fund_isin_with_two_files_is_refused_before_anything_is_written(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    paths = [_xlsx(tmp_path, ROWS, name="A.xlsx"), _xlsx(tmp_path, ROWS, name="B.xlsx")]
    with pytest.raises(ValueError, match="--fund-isin.*one file only"):
        import_holdings_files(store, paths, fund_isin="X")
    assert store.list_portfolios() == []


def test_constituent_named_file_still_goes_the_old_way(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    import_holdings_files(store, [_xlsx(tmp_path, ROWS)], 50_000_000)
    p = store.get_portfolio("portfolio_ie00testfund")
    assert p.name == "Portfolio IE00TESTFUND"
    assert p.tags == ["source:constituents", "sizing:assumed-notional-eur-50000000", "fund_isin:IE00TESTFUND"]


def test_english_labels_and_the_missing_german_countries(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    s = import_holdings_files(store, [_xlsx(tmp_path, ENGLISH_ROWS, name="AI.xlsx")])
    assert s["untranslated"] == [] and s["other_asset_classes"] == []
    classes = {sec.security_id: sec.asset_class for sec in store.list_securities()}
    assert classes == {"US67066G1040": "equity", "KR7005931001": "equity", "ZAE000351946": "equity",
                       "XS0000000003": "fund", "XS0000000004": "derivative"}
    got = {c.company_id[5:]: (c.country, c.sector) for c in store.list_companies()}
    assert got == {
        "US67066G1040": ("United States", "Technology"),
        "KR7005931001": ("South Korea", "Unknown"),
        "ZAE000351946": ("South Africa", "Basic Materials"),
        "XS0000000003": ("India", "Telecommunications"),
        "XS0000000004": ("Poland", "Financials"),
    }


def test_every_label_of_the_seven_public_files_is_known():
    import openpyxl

    from arp.config import REPO_ROOT

    files = sorted((REPO_ROOT / "data" / "holdings").glob("*.xlsx"))
    assert len(files) == 7
    unknown = set()
    for path in files:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        rows = list(wb.worksheets[0].iter_rows(min_row=4, values_only=True))
        wb.close()
        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        for raw in rows[1:]:
            r = dict(zip(header, raw, strict=False))
            if not r.get("Name") or not r.get("ISIN"):
                continue
            for column, table in (("Country", COUNTRY), ("Industry Classification", SECTOR)):
                if r.get(column) not in (None, "", "-") and str(r[column]).strip() not in table:
                    unknown.add(r[column])
            if r.get("Type of Security") not in ASSET_CLASS:
                unknown.add(r.get("Type of Security"))
    assert unknown == set()


@pytest.mark.parametrize("name", [None, "Plain.xlsx"])
def test_a_row_without_a_weight_registers_its_company_and_security_but_no_holding(tmp_path, name):
    store = PortfolioStore(tmp_path / "store")
    s = import_holdings_files(store, [_xlsx(tmp_path, ROWS, name=name)])
    p = s["portfolios"][0]
    assert p["skipped_no_weight"] == [{"name": "Dead Co", "isin": "GB00DEAD0001", "weighting": "N/A"}]
    assert store.get_company("isin_GB00DEAD0001").country == "United Kingdom"
    assert store.get_security("GB00DEAD0001").company_id == "isin_GB00DEAD0001"
    assert "GB00DEAD0001" not in {h.security_id for h in store.load_snapshot(p["portfolio_id"], "2026-10-02")}
    assert p["holdings_written"] == 4


@pytest.mark.parametrize("name", [None, "Plain.xlsx"])
def test_one_ok_holdings_load_record_per_file_content(tmp_path, name):
    import hashlib

    store = PortfolioStore(tmp_path / "store")
    path = _xlsx(tmp_path, ROWS, name=name)
    pid = import_holdings_files(store, [path])["portfolios"][0]["portfolio_id"]
    import_holdings_files(store, [path])  # the same bytes: no second record
    (event,) = _events(store, pid)
    rec = latest_load(store, "holdings", pid, "2026-10")
    assert (rec.status, rec.detail) == ("ok", f"constituent import {path.name}")
    assert rec.content_hash == hashlib.sha256(path.read_bytes()).hexdigest() == event["content_hash"]
    _xlsx(tmp_path, ROWS[:1], name=path.name)  # changed content: a new record
    import_holdings_files(store, [path])
    assert len(_events(store, pid)) == 2


def test_import_holdings_file_takes_the_id_and_name_it_is_given(tmp_path):
    store = PortfolioStore(tmp_path / "store")
    out = import_holdings_file(store, _xlsx(tmp_path, ROWS, name="x.xlsx"), "portfolio_custom", "Custom")
    assert out["portfolio_id"] == "portfolio_custom" and store.get_portfolio("portfolio_custom").name == "Custom"
    assert store.list_snapshot_dates("portfolio_custom") == ["2026-10-02"]


def test_a_reimport_keeps_the_history_tag(tmp_path):
    from arp.schemas.portfolio import Portfolio

    store = PortfolioStore(tmp_path / "store")
    path = _xlsx(tmp_path, ROWS, name="DAX.xlsx")
    import_holdings_files(store, [path])
    p = store.get_portfolio("portfolio_dax")
    store.save_portfolio(Portfolio(portfolio_id=p.portfolio_id, name=p.name, tags=[*p.tags, "history:simulated"]))
    import_holdings_files(store, [path])
    assert "history:simulated" in store.get_portfolio("portfolio_dax").tags
