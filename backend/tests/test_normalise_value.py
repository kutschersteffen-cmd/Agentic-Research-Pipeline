import pytest

from arp.extraction.extractor_agent import PeriodValue
from arp.normalise import fx
from arp.normalise.value import typed_value
from arp.schemas.datapoints import FieldDataType, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode


def _field(data_type=FieldDataType.NUMBER, unit=None):
    return FieldDefinition(name="f", description="f", data_type=data_type, unit=unit, extraction_instructions="f")


def test_tonnes_in_thousands_converts_and_keeps_text():
    pv = PeriodValue(value=1234.0, raw_value_text="1,234", unit_text="thousand tonnes CO2e", period_text="FY2023")
    tv = typed_value(_field(unit="tCO2e"), pv, fiscal_year_end="12-31")
    assert tv.canonical_value == 1_234_000.0
    assert tv.canonical_unit == "tCO2e"
    assert tv.scale_applied == 1000.0
    assert tv.unit == "thousand tonnes CO2e"
    assert tv.value == 1234.0
    assert tv.reasons == []
    assert (tv.period_start, tv.period_end) == ("2023-01-01", "2023-12-31")
    assert tv.reported_precision == 0


def test_scale_stated_twice_differs_is_check_failed():
    pv = PeriodValue(value=1.2, raw_value_text="$1.2bn", unit_text="USD millions", period_text="FY2023")
    tv = typed_value(_field(FieldDataType.CURRENCY_AMOUNT, unit="USD millions"), pv, fiscal_year_end="12-31")
    assert tv.canonical_value is None
    assert tv.reasons == [ReasonCode.CHECK_FAILED]
    assert "scale stated twice and differs" in tv.notes


def test_scale_stated_twice_and_agreeing_is_applied_once():
    pv = PeriodValue(value=1.2, raw_value_text="$1.2bn", unit_text="USD billions", period_text="FY2023")
    tv = typed_value(_field(FieldDataType.CURRENCY_AMOUNT, unit="USD millions"), pv, fiscal_year_end="12-31")
    assert tv.canonical_value == 1200.0
    assert tv.reasons == []


def test_ambiguous_scale_is_check_failed():
    pv = PeriodValue(value=1.2, raw_value_text="1.2", unit_text="m USD", period_text="FY2023")
    tv = typed_value(_field(FieldDataType.CURRENCY_AMOUNT, unit="USD millions"), pv, fiscal_year_end="12-31")
    assert tv.canonical_value is None
    assert tv.reasons == [ReasonCode.CHECK_FAILED]
    assert tv.notes


def test_currency_converted_with_rate_stored(monkeypatch):
    monkeypatch.setattr(fx, "_usd_per_unit", lambda: {("EUR", 2023): 1.1})
    pv = PeriodValue(value=100.0, raw_value_text="100", unit_text="EUR millions", period_text="FY2023")
    tv = typed_value(_field(FieldDataType.CURRENCY_AMOUNT, unit="USD millions"), pv, fiscal_year_end="12-31")
    assert tv.canonical_value == pytest.approx(110.0)
    assert tv.canonical_unit == "USD millions"
    assert tv.fx_rate == 1.1
    assert tv.fx_rate_ref == "fx_v1:EUR->USD:2023"
    assert tv.value == 100.0 and tv.unit == "EUR millions"
    assert tv.reasons == []


def test_missing_fx_rate_flags_check_failed(monkeypatch):
    monkeypatch.setattr(fx, "_usd_per_unit", lambda: {})
    pv = PeriodValue(value=100.0, raw_value_text="100", unit_text="EUR millions", period_text="FY2023")
    tv = typed_value(_field(FieldDataType.CURRENCY_AMOUNT, unit="USD millions"), pv, fiscal_year_end="12-31")
    assert tv.canonical_value is None
    assert tv.fx_rate is None
    assert tv.reasons == [ReasonCode.CHECK_FAILED]
    assert "no FX rate EUR 2023 in fx_v1" in tv.notes


def test_no_field_unit_scales_into_base_unit():
    pv = PeriodValue(value=2.0, raw_value_text="2 million", unit_text="tonnes", period_text="FY2023")
    tv = typed_value(_field(), pv, fiscal_year_end="12-31")
    assert (tv.canonical_value, tv.canonical_unit, tv.scale_applied) == (2_000_000.0, "tonnes", 1_000_000.0)


def test_zero_states():
    found_zero = typed_value(_field(), PeriodValue(value=0.0, unit_text="t"), fiscal_year_end=None)
    assert found_zero.value_state == ValueState.ZERO
    stated_zero = typed_value(_field(), PeriodValue(value=None, state="zero"), fiscal_year_end=None)
    assert stated_zero.value_state == ValueState.ZERO and stated_zero.value == 0.0


def test_assumed_fiscal_year_end_qualifier_and_basis():
    pv = PeriodValue(value="yes", period_text="FY2024", basis_text="market-based", raw_value_text="restated")
    tv = typed_value(_field(FieldDataType.STRING), pv, fiscal_year_end=None)
    assert tv.canonical_value is None
    assert tv.basis == "market_based"
    assert tv.qualifiers == ["restated", "fiscal_year_end_assumed"]


def test_unit_read_from_raw_text_when_unit_text_missing():
    pct = typed_value(_field(FieldDataType.PERCENTAGE, unit="%"), PeriodValue(value=12.5, raw_value_text="12.5%"),
                      fiscal_year_end="12-31")
    assert (pct.canonical_value, pct.canonical_unit, pct.reasons) == (12.5, "%", [])
    t = typed_value(_field(unit="t"), PeriodValue(value=1234.0, raw_value_text="1,234 thousand tonnes"),
                    fiscal_year_end="12-31")
    assert (t.canonical_value, t.canonical_unit, t.scale_applied, t.reasons) == (1_234_000.0, "t", 1000.0, [])


def test_no_unit_anywhere_is_check_failed():
    tv = typed_value(_field(unit="tCO2e"), PeriodValue(value=1234.0, raw_value_text="1,234"), fiscal_year_end="12-31")
    assert tv.canonical_value is None
    assert tv.reasons == [ReasonCode.CHECK_FAILED]
    assert tv.notes and "no unit" in tv.notes[0]


def test_scale_word_needs_a_boundary():
    tv = typed_value(_field(), PeriodValue(value=1234.0, raw_value_text="1,234 m3", unit_text="m3"), fiscal_year_end=None)
    assert tv.reasons == [] and tv.scale_applied == 1.0


def test_numeric_string_is_parsed():
    pv = PeriodValue(value="1,234", raw_value_text="1,234 tonnes", unit_text="tonnes", period_text="FY2023")
    tv = typed_value(_field(), pv, fiscal_year_end="12-31")
    assert tv.value == 1234.0
    assert tv.canonical_value == 1234.0
    assert tv.reasons == ["number_locale_ambiguous"]  # "1,234" with no known locale (E48)
    assert typed_value(_field(), PeriodValue(value="0", raw_value_text="0"), fiscal_year_end=None).value_state == ValueState.ZERO


def test_unparseable_numeric_string_is_check_failed():
    tv = typed_value(_field(), PeriodValue(value="about a third", raw_value_text="about a third"), fiscal_year_end=None)
    assert tv.value == "about a third"
    assert tv.reasons == [ReasonCode.CHECK_FAILED]
    assert tv.canonical_value is None
