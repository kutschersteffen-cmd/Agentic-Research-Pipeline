from arp.checks.consistency import check_entity, check_period
from arp.checks.runner import CheckContext
from arp.schemas.common import Citation, CompanyRef, DocType, PeriodPlan, SourceDocument
from arp.schemas.datapoints import CheckOutcome, DataPointSchema, ExtractedField, FieldDefinition, Severity

SPEC = FieldDefinition(field_id="rev", name="rev", description="d", data_type="number", extraction_instructions="i")


def _doc(**kw):
    return SourceDocument(doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text="x", **kw)


def _run(check, doc, period_end=None, grounded=True):
    cite = Citation(doc_id="d1", doc_type=DocType.ANNUAL_REPORT_10K, quote="q", grounded=grounded)
    field = ExtractedField(
        field_id="rev", field_name="rev", value=1.0, confidence=0.9, citations=[cite], period_end=period_end
    )
    ctx = CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key="lei:K1",
        schema=DataPointSchema(name="s", fields=[SPEC]), documents_by_id={"d1": doc}, record_fields=[field],
    )
    (res,) = check(SPEC, field, ctx)
    return res


def test_subsidiary_report_for_wrong_entity_fails():
    r = _run(check_entity, _doc(match_status="mismatch", covered_entity="Acme Energy GmbH"))
    assert (r.check_id, r.layer, r.outcome, r.severity) == ("consistency.entity", 4, CheckOutcome.FAIL, Severity.BLOCK)
    assert "Acme Energy GmbH" in r.detail


def test_confirmed_doc_passes():
    assert _run(check_entity, _doc(match_status="confirmed")).outcome == CheckOutcome.PASS


def test_ambiguous_doc_warns():
    r = _run(check_entity, _doc(match_status="ambiguous"))
    assert (r.outcome, r.severity) == (CheckOutcome.FAIL, Severity.WARN)


def test_legacy_doc_without_status_not_applicable():
    assert _run(check_entity, _doc()).outcome == CheckOutcome.NOT_APPLICABLE
    assert _run(check_entity, _doc(match_status="mismatch"), grounded=False).outcome == CheckOutcome.NOT_APPLICABLE


def test_period_not_in_plan_fails():
    doc = _doc(period_plan=PeriodPlan(current="2024-12-31", comparatives=["2023-12-31"]))
    r = _run(check_period, doc, "2019-12-31")
    assert (r.check_id, r.layer, r.outcome, r.severity) == ("consistency.period", 4, CheckOutcome.FAIL, Severity.WARN)
    assert r.detail == "period 2019-12-31 not reported by d1"


def test_period_in_plan_passes():
    doc = _doc(period_plan=PeriodPlan(current="2024-12-31", comparatives=["2023-12-31"]))
    assert _run(check_period, doc, "2023-12-31").outcome == CheckOutcome.PASS


def test_period_not_applicable_without_plan_or_period():
    assert _run(check_period, _doc(), "2023-12-31").outcome == CheckOutcome.NOT_APPLICABLE
    doc = _doc(period_plan=PeriodPlan(current="2024-12-31"))
    assert _run(check_period, doc, None).outcome == CheckOutcome.NOT_APPLICABLE
