from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights, load_universe_from_holdings


def test_load_universe_from_holdings_dedupes_by_ticker(tmp_path):
    path = tmp_path / "holdings.csv"
    path.write_text("ticker,name,sector\nAAA,Acme Corp,Tech\nAAA,Acme Corp,Tech\nBBB,Beta Inc,Industrials\n")

    companies = load_universe_from_holdings(path)
    assert len(companies) == 2
    assert {c.company_id for c in companies} == {"AAA", "BBB"}
    assert companies[0].sector == "Tech"


def test_load_universe_from_holdings_falls_back_to_name_when_no_ticker(tmp_path):
    path = tmp_path / "holdings.csv"
    path.write_text("name,sector\nAcme Corp,Tech\n")
    companies = load_universe_from_holdings(path)
    assert len(companies) == 1
    assert companies[0].company_id == "Acme Corp"
    assert companies[0].ticker is None


def test_load_holdings_with_weights_parses_percent_and_fraction(tmp_path):
    path = tmp_path / "holdings.csv"
    path.write_text("Ticker,Name,Weight (%)\nAAA,Acme Corp,12.5\nBBB,Beta Inc,7\n")

    rows = load_holdings_with_weights(path)
    assert len(rows) == 2
    by_ticker = {r.ticker: r for r in rows}
    assert by_ticker["AAA"].weight == 0.125
    assert by_ticker["BBB"].weight == 0.07


def test_load_holdings_with_weights_skips_rows_with_no_identifier(tmp_path):
    path = tmp_path / "holdings.csv"
    path.write_text("weight\n5\n")
    rows = load_holdings_with_weights(path)
    assert rows == []
