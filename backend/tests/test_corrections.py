import pytest

from arp.extraction.corrections import apply_corrections
from arp.schemas.datapoints import Correction, DataPointSchema, ExtractedField, FieldDataType, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode

ALLOWED = ["eu_taxonomy", "cash_flow", "other"]


def _schema() -> DataPointSchema:
    f = FieldDefinition(field_id="f", name="F", description="d", data_type=FieldDataType.ENUM,
                        extraction_instructions="x", allowed_values=ALLOWED)
    return DataPointSchema(schema_id="s", name="S", fields=[f])


def _row(value, state=ValueState.FOUND) -> ExtractedField:
    return ExtractedField(field_id="f", field_name="F", value=value, confidence=0.9, value_state=state)


def _apply(rows):
    return apply_corrections(_schema(), rows, documents_by_id={}, fiscal_year_end=None, input_hashes={})


@pytest.mark.parametrize("value,expected", [
    ("Cash flow", "cash_flow"), ("cash-flow capex", "cash_flow"), ("other $ (millions)", "other"),
    ("cash flow or EU taxonomy", None), ("operating cash", None)])
def test_label_map(value, expected):
    row = _row(value)
    (out,) = _apply([row])
    if expected is None:
        assert out.value == value and out.corrections == []
        assert ReasonCode.AUTO_CORRECTED not in out.review_reasons
    else:
        assert out.value == expected
        assert out.corrections == [Correction(rule="label_map", attribute="value", original=value, corrected=expected,
                                              reason=f'"{value}" maps to the allowed value "{expected}".')]
        assert out.review_reasons.count(ReasonCode.AUTO_CORRECTED) == 1
    assert row.value == value and row.corrections == []  # input not mutated


@pytest.mark.parametrize("value", [None, True])
def test_label_map_leaves_non_string_values_alone(value):
    (out,) = _apply([_row(value)])
    assert out.value is value and out.corrections == []


def test_allowed_value_is_not_corrected():
    (out,) = _apply([_row("cash_flow")])
    assert out.corrections == [] and out.review_reasons == []


def test_label_map_only_applies_to_found_rows():
    (out,) = _apply([_row("Cash flow", ValueState.NOT_FOUND)])
    assert out.value == "Cash flow" and out.corrections == []


def test_apply_twice_adds_no_second_correction():
    once = _apply([_row("Cash flow")])
    assert _apply(once) == once
