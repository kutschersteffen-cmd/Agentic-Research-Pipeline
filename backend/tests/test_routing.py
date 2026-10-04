from arp.extraction.routing import route
from arp.schemas.common import Citation, DocType
from arp.schemas.datapoints import (
    CheckOutcome,
    CheckResult,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
    FieldQuality,
    FieldStatus,
    RouteKind,
    Severity,
    ValueState,
)
from arp.schemas.review import ReasonCode


def _spec(**kw) -> FieldDefinition:
    return FieldDefinition(
        field_id="f1", name="f1", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="i",
        status=FieldStatus.RELEASED, auto_accept_min=0.9, **kw,
    )


_AUDITED = FieldQuality(field_id="f1", version=1, first_audit_passed=True)


def _field(**kw) -> ExtractedField:
    base = dict(
        field_id="f1", field_name="f1", value=5.0, value_state=ValueState.FOUND, confidence=0.95, grounded=True,
        citations=[Citation(doc_id="d1", doc_type=DocType.ANNUAL_REPORT_10K, quote="5", grounded=True)],
        checks=[CheckResult(check_id="format.data_type", layer=1, outcome=CheckOutcome.PASS, severity=Severity.BLOCK)],
    )
    return ExtractedField(**{**base, **kw})


def test_auto_accept_when_all_pass():
    r = route(_field(), _AUDITED, _spec())
    assert (r.kind, r.reasons) == (RouteKind.AUTO_ACCEPT, [])


def test_new_field_never_auto_accepts():
    r = route(_field(), FieldQuality(field_id="f1", version=1), _spec())
    assert r.kind == RouteKind.REVIEW and "first_audit_pending" in r.reasons


def test_failed_check_reviews():
    def fail(sev):
        return CheckResult(check_id="plausibility.sum_identity", layer=3, outcome=CheckOutcome.FAIL, severity=sev)

    r = route(_field(checks=[fail(Severity.WARN)]), _AUDITED, _spec())
    assert r.kind == RouteKind.REVIEW and "check:plausibility.sum_identity" in r.reasons
    assert route(_field(checks=[fail(Severity.INFO)]), _AUDITED, _spec()).kind == RouteKind.AUTO_ACCEPT


def test_below_auto_accept_min_reviews():
    r = route(_field(confidence=0.85), _AUDITED, _spec())
    assert r.kind == RouteKind.REVIEW and r.reasons == ["below_auto_accept_min"]


def test_review_reason_reviews():
    r = route(_field(review_reasons=[ReasonCode.NOT_GROUNDED]), _AUDITED, _spec())
    assert r.kind == RouteKind.REVIEW and "not_grounded" in r.reasons


def test_not_found_high_risk_reviews():
    nf = _field(value=None, value_state=ValueState.NOT_FOUND, confidence=0.0, citations=[], grounded=False)
    r = route(nf, _AUDITED, _spec(high_risk=True))
    assert r.kind == RouteKind.REVIEW and r.reasons == ["high_risk_not_found"]
    assert route(nf, _AUDITED, _spec(high_risk=False)).kind == RouteKind.AUTO_ACCEPT


def test_entity_mismatch_holds():
    r = route(_field(), _AUDITED, _spec(), held="entity_mismatch")
    assert (r.kind, r.reasons) == (RouteKind.HOLD, ["entity_mismatch"])


def test_unreleased_version_reviews_never_auto_accepts():
    r = route(_field(), _AUDITED, _spec().model_copy(update={"status": FieldStatus.DRAFT}))
    assert r.kind == RouteKind.REVIEW and r.reasons[:1] == ["unreleased_version"]


def test_rule_skip_auto_accepts_even_unaudited():
    skipped = _field(
        value=None, value_state=ValueState.NOT_APPLICABLE, confidence=0.0, citations=[], checks=[],
        route_reasons=["not_applicable_by_rule"],
    )
    r = route(skipped, FieldQuality(field_id="f1", version=1), _spec())
    assert (r.kind, r.reasons) == (RouteKind.AUTO_ACCEPT, ["not_applicable_by_rule"])


def test_old_field_definition_and_row_load_with_defaults():
    spec = FieldDefinition.model_validate({"name": "x", "description": "d", "data_type": "number", "extraction_instructions": "i"})
    assert (spec.auto_accept_min, spec.high_risk) == (0.9, False)
    assert ExtractedField.model_validate({"field_id": "f", "field_name": "f", "value": 1, "confidence": 0.5}).route is None
