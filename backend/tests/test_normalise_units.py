import csv
from pathlib import Path

import pytest

from arp.normalise.units import convert, lookup_unit, split_unit

TABLES = Path(__file__).parent.parent / "arp" / "normalise" / "tables"


def _rows(name):
    with open(TABLES / name, encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("row", _rows("units_v1.csv"), ids=lambda r: r["alias"])
def test_every_unit_row_converts_to_canonical(row):
    if row["dimension"] != "currency":
        got = convert(1.0, row["alias"], row["canonical"])
        assert got.value == pytest.approx(float(row["factor"]))
    info = lookup_unit(row["alias"])
    assert info.canonical == row["canonical"]
    assert info.dimension == row["dimension"]
    if row["ambiguous"] == "1":
        assert info.ambiguous is True
        assert convert(1.0, row["alias"], row["canonical"]).ambiguous is True


@pytest.mark.parametrize("row", _rows("scale_v1.csv"), ids=lambda r: r["word"])
def test_every_scale_row(row):
    factor, ambiguous, base = split_unit(f"{row['word']} tonnes")
    assert factor == float(row["factor"])
    assert ambiguous is (row["ambiguous"] == "1")
    assert base == "tonnes"


def test_lookup_is_case_and_whitespace_insensitive():
    assert lookup_unit("  TONNES   co2e ").canonical == "tCO2e"
    assert lookup_unit("furlongs") is None


def test_thousand_tonnes_to_tco2e():
    got = convert(1234.0, "thousand tonnes CO2e", "tCO2e")
    assert got.value == 1_234_000.0
    assert got.scale_applied == 1000.0
    assert split_unit("USD millions") == (1e6, False, "USD")


def test_dimension_mismatch():
    assert convert(1.0, "MWh", "tCO2e").reason == "dimension_mismatch"


def test_unknown_unit_and_needs_fx():
    assert convert(1.0, "furlongs", "t").reason == "unknown_unit"
    got = convert(1.0, "EUR m", "USD")
    assert got.reason == "needs_fx" and got.value is None and got.from_canonical == "EUR"
    assert convert(2.0, "USD millions", "USD thousand").value == 2000.0
