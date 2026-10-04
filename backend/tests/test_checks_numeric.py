import pytest

from arp.checks.numeric import check_caption_scale, check_number_in_span, check_row_label, parse_number
from arp.checks.runner import CheckContext
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldDataType, FieldDefinition


def _spec(name="Scope 1 emissions", **kw):
    return FieldDefinition(
        field_id="f1", name=name, description="d", data_type=FieldDataType.NUMBER, extraction_instructions="i", **kw
    )


def _run(check, spec, text, quote, *, value, raw, method="exact", span=None, scale=None):
    doc = SourceDocument(doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=text)
    start = text.index(quote)
    cit = Citation(
        doc_id="d1", doc_type=DocType.SUSTAINABILITY_REPORT, quote=quote, grounded=True, span_text=span or quote,
        char_start=start, char_end=start + len(quote), match_method=method,
    )
    field = ExtractedField(
        field_id="f1", field_name="f1", value=value, raw_value_text=raw, confidence=0.9,
        value_state="found", citations=[cit], scale_applied=scale,
    )
    ctx = CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key="k",
        schema=DataPointSchema(name="s", fields=[spec]), documents_by_id={"d1": doc}, record_fields=[field],
    )
    (r,) = check(spec, field, ctx)
    return r


def test_fuzzy_quote_with_changed_digit_fails():
    q = "Scope 1 emissions of 4,270 tCO2e"
    r = _run(check_number_in_span, _spec(), q, q, value=4210.0, raw="4,210", method="fuzzy")
    assert (r.check_id, r.outcome, r.severity) == ("numeric.in_span", "fail", "block")


def test_exact_number_in_span_passes():
    q = "Scope 1 emissions of 4,210 tCO2e"
    r = _run(check_number_in_span, _spec(), q, q, value=4210.0, raw="4,210")
    assert r.outcome == "pass"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1,234.5", 1234.5), ("4.210,5", 4210.5), ("4 210,5", 4210.5), ("(1,234)", -1234.0),
        ("−1,234", -1234.0), ("1'234", 1234.0), ("1,5", 1.5), ("12.5%", 12.5), ("1.234.567", 1234567.0),
    ],
)
def test_parse_number_formats(text, expected):
    assert parse_number(text) == expected


_CAP = "Emissions (in thousands of tonnes)\nScope 1  1,234  1,100\n"


def test_caption_in_thousands_without_scale_warns():
    r = _run(check_caption_scale, _spec(), _CAP, "Scope 1  1,234", value=1234.0, raw="1,234")
    assert (r.check_id, r.outcome, r.severity) == ("numeric.caption_scale", "fail", "warn")


def test_caption_scale_applied_passes():
    r = _run(check_caption_scale, _spec(), _CAP, "Scope 1  1,234", value=1234000.0, raw="1,234", scale=1000.0)
    assert r.outcome == "pass"


def test_row_label_mismatch_warns():
    spec = _spec(seed_keywords=["scope 1"])
    t = "Water withdrawal  1,234  1,100\n"
    r = _run(check_row_label, spec, t, "1,234", value=1234.0, raw="1,234")
    assert (r.check_id, r.outcome) == ("numeric.row_label", "fail")
    t = "Scope 1 emissions  1,234  1,100\n"
    assert _run(check_row_label, spec, t, "1,234", value=1234.0, raw="1,234").outcome == "pass"
    t = "Water use rose to 1,234 last year.\n"
    assert _run(check_row_label, spec, t, "1,234", value=1234.0, raw="1,234").outcome == "not_applicable"
