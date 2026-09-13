import pytest

from arp.replication.characteristics_data import CsvCharacteristicSource


def test_csv_characteristic_source_reads_levels_directly(tmp_path):
    csv_path = tmp_path / "book_to_market.csv"
    csv_path.write_text(
        "date,AAA,BBB\n"
        "2000-01-01,1.5,0.4\n"
        "2000-02-01,1.6,0.5\n"
        "2000-03-01,1.4,0.6\n"
    )
    source = CsvCharacteristicSource(csv_path)
    panel = source.get_values(["AAA", "BBB"], "2000-01-01", "2000-03-01")

    assert panel.period_ends == ["2000-01-01", "2000-02-01", "2000-03-01"]
    # Unlike price data, characteristic levels are used as-is -- no return
    # derivation, no forced None at index 0.
    assert panel.values["AAA"] == [1.5, 1.6, 1.4]
    assert panel.values["BBB"] == [0.4, 0.5, 0.6]
    assert panel.tickers() == ["AAA", "BBB"]


def test_csv_characteristic_source_missing_ticker_column_raises(tmp_path):
    csv_path = tmp_path / "book_to_market.csv"
    csv_path.write_text("date,AAA\n2000-01-01,1.5\n")
    source = CsvCharacteristicSource(csv_path)
    with pytest.raises(ValueError, match="ZZZ"):
        source.get_values(["ZZZ"], "2000-01-01", "2000-01-01")


def test_csv_characteristic_source_missing_value_becomes_none(tmp_path):
    csv_path = tmp_path / "book_to_market.csv"
    csv_path.write_text("date,AAA\n2000-01-01,1.5\n2000-02-01,\n")
    source = CsvCharacteristicSource(csv_path)
    panel = source.get_values(["AAA"], "2000-01-01", "2000-02-01")
    assert panel.values["AAA"] == [1.5, None]


def test_csv_characteristic_source_filters_to_requested_window(tmp_path):
    csv_path = tmp_path / "book_to_market.csv"
    csv_path.write_text("date,AAA\n2000-01-01,1.0\n2000-02-01,1.1\n2000-03-01,1.2\n")
    source = CsvCharacteristicSource(csv_path)
    panel = source.get_values(["AAA"], "2000-02-01", "2000-03-01")
    assert panel.period_ends == ["2000-02-01", "2000-03-01"]
    assert panel.values["AAA"] == [1.1, 1.2]
