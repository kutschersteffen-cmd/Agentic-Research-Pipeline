from arp.checks.round_trip import check_round_trip
from arp.checks.runner import CheckContext
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldDataType, FieldDefinition

_SPEC = FieldDefinition(
    field_id="f1", name="Revenue", description="d", data_type=FieldDataType.CURRENCY_AMOUNT,
    extraction_instructions="i", unit="EUR",
)


def _run(spec=_SPEC, **kw):
    kw = {"raw_value_text": "EUR 1.5 million", "canonical_value": 1_500_000.0, "canonical_unit": "EUR",
          "scale_applied": 1e6, "value": 1.5, "value_state": "found", **kw}
    field = ExtractedField(field_id="f1", field_name="f1", confidence=0.9, citations=[], **kw)
    ctx = CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key="k",
        schema=DataPointSchema(name="s", fields=[spec]), documents_by_id={}, record_fields=[field],
    )
    (r,) = check_round_trip(spec, field, ctx)
    return r


def test_round_trip_passes_for_correct_conversion():
    r = _run()
    assert (r.check_id, r.layer, r.outcome) == ("round_trip", 3, "pass")


def test_altered_conversion_fails():
    r = _run(canonical_value=1_600_000.0)
    assert (r.outcome, r.severity) == ("fail", "block")
    assert "1.6" in r.detail and "1.5" in r.detail


def test_round_trip_with_fx():
    spec = _SPEC.model_copy(update={"unit": "USD"})
    r = _run(spec, canonical_value=1_650_000.0, canonical_unit="USD", fx_rate=1.1)
    assert r.outcome == "pass"
    assert _run(spec, canonical_value=1_500_000.0, canonical_unit="USD", fx_rate=1.1).outcome == "fail"


def test_not_applicable_without_canonical():
    assert _run(canonical_value=None).outcome == "not_applicable"
    assert _run(raw_value_text=None).outcome == "not_applicable"
