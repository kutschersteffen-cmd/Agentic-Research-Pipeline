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


# --- R3 unit_scale --------------------------------------------------------

def _urow(unit, quote, value=2.794, raw=None, grounded=True, field_id="capex", **kw) -> ExtractedField:
    return _nrow(quote, field_id=field_id, value=value, grounded=grounded).model_copy(
        update={"unit": unit, "raw_value_text": raw, **kw})


def _scale(row):
    return _fill([row])[0]


def _uc(out):
    return [c for c in out.corrections if c.rule == "unit_scale"]  # quotes with a year also get R2


BILLION = "Capital expenditures were $2.794 billion during 2025"


def test_billion_quote_rewrites_millions_unit():
    row = _urow("USD millions", BILLION)
    out = _scale(row)
    assert out.unit == "USD billions"
    assert _uc(out) == [Correction(rule="unit_scale", attribute="unit", original="USD millions",
                                          corrected="USD billions", reason='The quote says "billion" next to 2.794.')]
    assert (out.canonical_value, out.canonical_unit, out.scale_applied) == (2794000000.0, "USD", 1e9)
    assert ReasonCode.AUTO_CORRECTED in out.review_reasons
    assert row.unit == "USD millions" and row.corrections == []  # input not mutated


def test_case_is_kept():
    assert _scale(_urow("Millions of dollars", BILLION)).unit == "Billions of dollars"


def test_no_scale_word_no_correction():
    out = _scale(_urow("USD millions", "Capital expenditures were 2.794 during 2025"))
    assert out.unit == "USD millions" and _uc(out) == []


def test_already_converted_scale_is_left_alone():
    out = _scale(_urow("USD", BILLION, raw="$2.794 billion", canonical_value=2794000000.0, canonical_unit="USD",
                       scale_applied=1e9))
    assert out.unit == "USD" and _uc(out) == [] and out.canonical_value == 2794000000.0


def test_two_scale_words_no_correction():
    out = _scale(_urow("USD millions", "Capex was $2.794 billion, or 2.794 million in the old report"))
    assert out.unit == "USD millions" and _uc(out) == []


def test_stale_scale_conflict_is_cleared():
    out = _scale(_urow("USD millions", BILLION, raw="$2.794 billion",
                       review_reasons=[ReasonCode.CHECK_FAILED], verifier_notes="scale stated twice and differs"))
    assert out.unit == "USD billions"
    assert ReasonCode.CHECK_FAILED not in out.review_reasons
    assert out.verifier_notes is None
    assert ReasonCode.AUTO_CORRECTED in out.review_reasons


def test_separators_in_printed_value():
    out = _scale(_urow("USD thousands", "capex was $2,479 million in 2025", value=2479.0))
    assert out.unit == "USD millions" and _uc(out)[0].reason == 'The quote says "million" next to 2,479.'
    out = _scale(_urow("USD millions", "capex was 2,794 billion in 2025"))  # 2.794 is not 2,794
    assert _uc(out) == []


def test_currency_symbol_unit_gets_word_appended():
    out = _scale(_urow("$", "capex was $2.8 billion in 2025", value=2.8))
    assert out.unit == "$ billion" and len(_uc(out)) == 1


def test_percentage_rows_untouched():
    f = FieldDefinition(field_id="pct", name="Pct", description="d", data_type=FieldDataType.PERCENTAGE,
                        extraction_instructions="x")
    row = _urow("% millions", "share was 2.794 billion", field_id="pct")
    (out,) = apply_corrections(DataPointSchema(schema_id="s", name="S", fields=[f]), [row], documents_by_id={},
                               fiscal_year_end=None, input_hashes={})
    assert out.unit == "% millions" and _uc(out) == []


def test_ungrounded_quote_no_correction():
    out = _scale(_urow("USD millions", BILLION, grounded=False))
    assert out.unit == "USD millions" and _uc(out) == []


def test_unit_scale_twice_changes_nothing():
    once = _fill([_urow("USD millions", BILLION)])
    assert _fill(once) == once


@pytest.mark.parametrize("quote,word,unit", [
    ("Capital expenditures were $2.794 Billion during 2025", "Billion", "USD billions"),
    ("Capital expenditures were $2.794 BILLION during 2025", "BILLION", "USD billions"),
    ("Capital expenditures were $2.794bn during 2025", "bn", "USD bn"),
    ("Capital expenditures were $2.794B during 2025", "B", "USD b"),
])
def test_scale_word_case_and_attached_to_number(quote, word, unit):
    out = _scale(_urow("USD millions", quote))
    assert out.unit == unit  # the unit keeps the case of the word it replaces, not the quote's
    assert _uc(out)[0].reason == f'The quote says "{word}" next to 2.794.'


def test_attached_scale_word_with_value_2_8():
    out = _scale(_urow("USD millions", "capex was $2.8bn in 2025", value=2.8))
    assert out.unit == "USD bn" and _uc(out)[0].reason == 'The quote says "bn" next to 2.8.'
    assert out.canonical_value == 2.8e9


def test_attached_scale_word_must_end_at_a_word_boundary():
    out = _scale(_urow("USD millions", "Capital expenditures were $2.794bnx during 2025"))
    assert _uc(out) == []
