import csv
import re
from pathlib import Path

import pytest

from arp.normalise import fx

CSV = Path(__file__).parent.parent / "arp" / "normalise" / "tables" / "fx_v1.csv"
with open(CSV, encoding="utf8", newline="") as _f:
    ROWS = list(csv.DictReader(_f))


@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"{r['currency']}{r['year']}")
def test_every_fx_row(row):
    assert re.fullmatch("[A-Z]{3}", row["currency"])
    assert 2019 <= int(row["year"]) <= 2025
    assert float(row["usd_per_unit"]) > 0
    assert row["source"].startswith("https://www.federalreserve.gov/releases/g5a/")
    got = fx.rate(row["currency"], "USD", int(row["year"]))
    assert got.rate == float(row["usd_per_unit"])
    assert got.ref == f"fx_v1:{row['currency']}->USD:{row['year']}"


def test_no_duplicate_rows():
    keys = [(r["currency"], r["year"]) for r in ROWS]
    assert len(keys) == len(set(keys))


def test_cross_rate_via_usd(monkeypatch):
    monkeypatch.setattr(fx, "_usd_per_unit", lambda: {("EUR", 2024): 1.08, ("GBP", 2024): 1.28})
    assert fx.rate("EUR", "GBP", 2024).rate == 1.08 / 1.28
    assert fx.rate("USD", "EUR", 2024).rate == 1 / 1.08
    assert fx.convert_amount(100.0, "EUR", "USD", 2024)[0] == pytest.approx(108.0)


def test_missing_rate_is_none(monkeypatch):
    monkeypatch.setattr(fx, "_usd_per_unit", lambda: {("EUR", 2024): 1.08})
    assert fx.rate("EUR", "GBP", 2024) is None
    assert fx.rate("EUR", "USD", 1999) is None
    assert fx.convert_amount(1.0, "EUR", "GBP", 2024) == (None, None)
