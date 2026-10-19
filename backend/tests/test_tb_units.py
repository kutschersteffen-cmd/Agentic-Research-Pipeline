from __future__ import annotations

import math

from arp.transition_barrier.units import convert

SRC = {"title": "Fixture rate", "url": "https://example.org/fx"}
RATES = [
    {"from": "CNY", "to": "USD", "rate": 0.139, "year": 2024, "source": SRC},
    {"from": "CNY", "to": "USD", "rate": 0.14, "year": 2025, "source": SRC},
]


def test_same_unit_passes_through():
    assert convert(72.0, "USD/tCO2", "USD/tCO2", 2026, RATES) == (72.0, None)


def test_latest_earlier_year_applies():  # AC-30
    v, r = convert(66.9, "CNY/tCO2", "USD/tCO2", 2026, RATES)
    assert r is None and math.isclose(v, 66.9 * 0.14)


def test_own_year_rate():  # AC-32
    v, _ = convert(66.9, "CNY/tCO2", "USD/tCO2", 2024, RATES)
    assert math.isclose(v, 66.9 * 0.139)


def test_no_earlier_rate():  # AC-33
    assert convert(66.9, "CNY/tCO2", "USD/tCO2", 2023, RATES) == (None, "No CNY to USD rate for 2023 or earlier")


def test_unknown_unit():  # AC-34
    assert convert(66.9, "KRW/tCO2", "USD/tCO2", 2026, RATES) == (None, "Unit not convertible: KRW/tCO2")


def test_rate_to_another_currency_does_not_apply():  # Review Focus 5
    eur = [{"from": "CNY", "to": "EUR", "rate": 0.13, "year": 2025, "source": SRC}]
    assert convert(66.9, "CNY/tCO2", "USD/tCO2", 2026, eur) == (None, "Unit not convertible: CNY/tCO2")


def test_denominator_must_match():
    assert convert(66.9, "CNY/t", "USD/tCO2", 2026, RATES) == (None, "Unit not convertible: CNY/t")


GALLON = {"from": "gallon", "to": "litre", "rate": 3.785411784, "year": 1959, "source": SRC}
MILE = {"from": "mile", "to": "km", "rate": 1.609344, "year": 1959, "source": SRC}


def test_denominator_converts():
    v, r = convert(3.785411784, "USD/gallon", "USD/litre", 2026, [GALLON])
    assert r is None and math.isclose(v, 1.0)


def test_both_sides_convert():
    v, r = convert(10.0, "CNY/mile", "USD/km", 2026, [*RATES, MILE])
    assert r is None and math.isclose(v, 10.0 * 0.14 / 1.609344)


def test_denominator_without_a_row_is_refused():
    assert convert(1.0, "USD/gallon", "USD/km", 2026, [GALLON, MILE]) == (None, "Unit not convertible: USD/gallon")
