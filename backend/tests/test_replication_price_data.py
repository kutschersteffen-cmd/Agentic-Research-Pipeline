import pytest

from arp.replication.price_data import CsvPriceSource


def test_csv_price_source_derives_returns_from_prices(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,AAA,BBB\n"
        "2000-01-01,100,50\n"
        "2000-02-01,110,49\n"
        "2000-03-01,121,48\n"
    )
    source = CsvPriceSource(csv_path, kind="price")
    panel = source.get_monthly_returns(["AAA", "BBB"], "2000-01-01", "2000-03-01")

    assert panel.period_ends == ["2000-01-01", "2000-02-01", "2000-03-01"]
    assert panel.returns["AAA"][0] is None
    assert panel.returns["AAA"][1] == pytest.approx(0.10)
    assert panel.returns["AAA"][2] == pytest.approx(0.10)
    assert panel.returns["BBB"][1] == pytest.approx(49 / 50 - 1)


def test_csv_price_source_return_kind_uses_values_directly_but_nulls_first_row(tmp_path):
    csv_path = tmp_path / "returns.csv"
    csv_path.write_text("date,AAA\n2000-01-01,0.05\n2000-02-01,-0.02\n")
    source = CsvPriceSource(csv_path, kind="return")
    panel = source.get_monthly_returns(["AAA"], "2000-01-01", "2000-02-01")
    assert panel.returns["AAA"][0] is None  # first period never has a "return into" it
    assert panel.returns["AAA"][1] == pytest.approx(-0.02)


def test_csv_price_source_missing_ticker_column_raises(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text("date,AAA\n2000-01-01,100\n")
    source = CsvPriceSource(csv_path)
    with pytest.raises(ValueError, match="ZZZ"):
        source.get_monthly_returns(["ZZZ"], "2000-01-01", "2000-01-01")


def test_csv_price_source_filters_to_requested_window(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text("date,AAA\n2000-01-01,100\n2000-02-01,110\n2000-03-01,90\n")
    source = CsvPriceSource(csv_path)
    panel = source.get_monthly_returns(["AAA"], "2000-02-01", "2000-03-01")
    assert panel.period_ends == ["2000-02-01", "2000-03-01"]
