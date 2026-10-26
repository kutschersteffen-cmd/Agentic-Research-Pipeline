import pytest

from arp.extraction.corrections import apply_corrections
from arp.schemas.common import Citation, DocType, PeriodPlan, SourceDocument
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


# --- R2 period_fill -------------------------------------------------------

def _num_schema() -> DataPointSchema:
    kw = dict(description="d", data_type=FieldDataType.CURRENCY_AMOUNT, extraction_instructions="x")
    return DataPointSchema(schema_id="s", name="S", fields=[
        FieldDefinition(field_id="capex", name="Capex", planned_field_id="capex_planned", **kw),
        FieldDefinition(field_id="capex_planned", name="Capex planned", **kw),
        FieldDefinition(field_id="flag", name="Flag", description="d", data_type=FieldDataType.BOOLEAN,
                        extraction_instructions="x"),
        FieldDefinition(field_id="kind", name="Kind", description="d", data_type=FieldDataType.ENUM,
                        extraction_instructions="x", allowed_values=ALLOWED)])


def _cite(quote, grounded=True, doc_id="d1") -> Citation:
    return Citation(doc_id=doc_id, doc_type=DocType.ANNUAL_REPORT_10K, quote=quote, grounded=grounded)


def _nrow(quote="", field_id="capex", period_end=None, grounded=True, value=2479.0) -> ExtractedField:
    return ExtractedField(field_id=field_id, field_name=field_id, value=value, confidence=0.9,
                          value_state=ValueState.FOUND, period_end=period_end,
                          citations=[_cite(quote, grounded)] if quote else [])


def _docs(current="2025-12-31"):
    doc = SourceDocument(doc_id="d1", company_id="c", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text="x",
                         period_plan=PeriodPlan(current=current))
    return {"d1": doc}


def _fill(rows, docs=None, fye=None):
    return apply_corrections(_num_schema(), rows, documents_by_id=docs or {}, fiscal_year_end=fye, input_hashes={})


QUOTE_2025 = "capital expenditures were $2,479 million in 2025"


def test_single_year_in_quote():
    row = _nrow(QUOTE_2025)
    (out,) = _fill([row])
    assert (out.period_end, out.period_start) == ("2025-12-31", "2025-01-01")
    assert out.corrections == [Correction(rule="period_fill", attribute="period_end", original=None,
                                          corrected="2025-12-31", reason="The quote names only 2025.")]
    assert out.review_reasons == [ReasonCode.AUTO_CORRECTED]
    assert row.period_end is None and row.corrections == []  # input not mutated


def test_fiscal_year_end_march():
    (out,) = _fill([_nrow(QUOTE_2025)], fye="03-31")
    assert (out.period_end, out.period_start) == ("2025-03-31", "2024-04-01")


def test_no_year_takes_report_period_end():
    (out,) = _fill([_nrow("capital expenditures were $2,479 million")], docs=_docs())
    assert out.period_end == "2025-12-31" and out.period_start == "2025-01-01"
    assert out.corrections[0].reason == "No year in the quote; taken from the report's period end 2025-12-31."


def test_two_years_flags_period_missing():
    (out,) = _fill([_nrow("capex was $2,479 million in 2025 and $2,100 million in 2024")], docs=_docs())
    assert out.period_end is None and out.corrections == []
    assert out.review_reasons == [ReasonCode.PERIOD_MISSING]


def test_no_year_no_report_period_flags():
    (out,) = _fill([_nrow("capital expenditures were $2,479 million")], docs=_docs(current=None))
    assert out.period_end is None and out.corrections == []
    assert out.review_reasons == [ReasonCode.PERIOD_MISSING]


def test_planned_field_never_takes_report_period_end():
    (out,) = _fill([_nrow("we plan to spend $3,000 million", field_id="capex_planned")], docs=_docs())
    assert out.period_end is None and out.corrections == []
    assert out.review_reasons == [ReasonCode.PERIOD_MISSING]


def test_fill_that_would_duplicate_a_period_flags_instead():
    existing = _nrow("x", period_end="2025-12-31")
    clash = _nrow(QUOTE_2025)
    rows = _fill([existing, clash])
    assert [r.period_end for r in rows] == ["2025-12-31", None]
    assert rows[0].review_reasons == [] and rows[1].corrections == []
    assert rows[1].review_reasons == [ReasonCode.PERIOD_MISSING]


def test_two_period_less_rows_for_one_year_are_both_flagged():
    rows = _fill([_nrow(QUOTE_2025), _nrow(QUOTE_2025, value=1.0)])
    assert [r.period_end for r in rows] == [None, None]
    assert all(r.review_reasons == [ReasonCode.PERIOD_MISSING] for r in rows)


def test_ungrounded_quotes_do_not_fill():
    (out,) = _fill([_nrow(QUOTE_2025, grounded=False)])
    assert out.period_end is None and out.review_reasons == [ReasonCode.PERIOD_MISSING]


def test_enum_and_boolean_rows_are_not_filled():
    rows = [_nrow(QUOTE_2025, field_id="flag", value=True), _nrow(QUOTE_2025, field_id="kind", value="other")]
    out = _fill(rows)
    assert out == rows


def test_period_fill_twice_changes_nothing():
    once = _fill([_nrow(QUOTE_2025), _nrow("no year", field_id="capex_planned")])
    assert _fill(once) == once
