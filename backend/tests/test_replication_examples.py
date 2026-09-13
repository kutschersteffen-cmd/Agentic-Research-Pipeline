import pytest

from arp.replication.examples import list_examples, load_example_spec
from arp.schemas.strategy_replication import SignalType


def test_list_examples_includes_momentum_and_value():
    names = list_examples()
    assert "jegadeesh_titman_1993" in names
    assert "book_to_market_value_premium" in names


def test_momentum_example_loads_and_is_flagged_for_review():
    spec = load_example_spec("jegadeesh_titman_1993")
    assert spec.signal_type == SignalType.MOMENTUM
    assert spec.formation_period_months == 6
    assert spec.holding_period_months == 6
    assert spec.needs_review is True


def test_value_example_loads_with_characteristic_fields_set():
    spec = load_example_spec("book_to_market_value_premium")
    assert spec.signal_type == SignalType.VALUE
    assert spec.characteristic_name == "book_to_market"
    assert spec.characteristic_lag_months > 0
    assert spec.long_leg_portfolio == 1  # highest book-to-market (cheapest) is long
    assert spec.needs_review is True


def test_unknown_example_raises():
    with pytest.raises(FileNotFoundError, match="jegadeesh_titman_1993"):
        load_example_spec("not_a_real_example")
