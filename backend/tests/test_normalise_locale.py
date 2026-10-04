from arp.extraction.extractor_agent import PeriodValue
from arp.normalise.locale import context_decimal, decimal_for, detect_language, parse_number
from arp.normalise.value import typed_value
from arp.schemas.datapoints import FieldDataType, FieldDefinition, ValueState


def test_point_and_comma_resolve_by_context():
    assert parse_number("1.234", "comma") == (1234.0, False)
    assert parse_number("1.234", "point") == (1.234, False)
    assert parse_number("1,234", "comma") == (1.234, False)
    assert parse_number("1,234", None) == (1234.0, True)


def test_context_decimal_from_neighbours():
    assert context_decimal(["1.234,56", "7"]) == "comma"
    assert context_decimal(["12.5"]) == "point"
    assert context_decimal(["1,234"]) is None


def test_detect_language_german():
    text = "Die Emissionen des Unternehmens sind nicht gestiegen und wir werden die Ziele mit einer klaren Strategie von 2020 auf 2030 senken."
    assert detect_language(text) == "de"
    assert decimal_for("de") == "comma"
    assert detect_language("too few words") is None


def test_mixed_document_table_context_wins():
    table = context_decimal(["1,234.5", "2,000.25"])
    assert (table or decimal_for("de")) == "point"
    assert parse_number("1,234.5", table) == (1234.5, False)


def test_unit_neighbours_do_not_break_formats():
    assert parse_number("1.2.3") == (None, False)
    assert parse_number("12 apples")[0] == 12.0  # lenient here; to_number stays strict
    assert parse_number("0,125", None) == (0.125, False)


def _field():
    return FieldDefinition(field_id="f", name="n", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="i")


def test_ambiguous_value_flags_review():
    pv = PeriodValue(value="1,234", raw_value_text="1,234", state=ValueState.FOUND)
    assert "number_locale_ambiguous" in typed_value(_field(), pv, fiscal_year_end=None, planned=None).reasons
    tv = typed_value(_field(), pv, fiscal_year_end=None, planned=None, decimal="comma")
    assert "number_locale_ambiguous" not in tv.reasons and tv.value == 1.234
