import pytest
from pydantic import ValidationError

from arp.extraction.derived import evaluate_derived
from arp.schemas.common import Citation, DocType
from arp.schemas.datapoints import (
    CheckOutcome,
    CheckResult,
    DataPointSchema,
    DerivedRule,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
    Severity,
    ValueState,
)
from arp.schemas.review import ReasonCode

T, F, N = "true", "false", "nf"


def row(fid, state, **kw):
    value, vs = {T: (True, ValueState.FOUND), F: (False, ValueState.FOUND), N: (None, ValueState.NOT_FOUND)}[state]
    cits = [Citation(doc_id=f"doc-{fid}", doc_type=DocType.OTHER, quote=f"quote {fid}")] if state != N else []
    return ExtractedField(field_id=fid, field_name=fid, value=value, value_state=vs, confidence=0.95, grounded=True, citations=cits, **kw)


def spec(**rule):
    return FieldDefinition(
        field_id="d", name="d", description="", data_type=FieldDataType.BOOLEAN, extraction_instructions="",
        derived_rule=DerivedRule(**rule),
    )


def run(states, **rule):
    by_id = {fid: row(fid, s) for fid, s in states.items()}
    return evaluate_derived(spec(**rule), by_id)


def test_all_of_true():
    r = run({"a": T, "b": T}, all_of=["a", "b"])
    assert (r.value, r.value_state, r.method, r.confidence, r.grounded) == (True, ValueState.FOUND, "extracted", 1.0, True)
    assert {c.doc_id for c in r.citations} == {"doc-a", "doc-b"}


def test_all_of_one_false():
    r = run({"a": F, "b": N}, all_of=["a", "b"])
    assert (r.value, r.value_state) == (False, ValueState.FOUND)
    assert {c.doc_id for c in r.citations} == {"doc-a"}


def test_all_of_not_found_never_false():
    r = run({"a": T, "b": N}, all_of=["a", "b"])
    assert (r.value, r.value_state, r.citations) == (None, ValueState.NOT_FOUND, [])


def test_any_of_one_true():
    r = run({"a": T, "b": N}, any_of=["a", "b"])
    assert r.value is True and {c.doc_id for c in r.citations} == {"doc-a"}


def test_any_of_all_false():
    r = run({"a": F, "b": F}, any_of=["a", "b"])
    assert r.value is False and {c.doc_id for c in r.citations} == {"doc-a", "doc-b"}


def test_any_of_false_and_not_found_undecided():
    assert run({"a": F, "b": N}, any_of=["a", "b"]).value_state == ValueState.NOT_FOUND


def test_min_true():
    r = run({"a": T, "b": T, "c": N}, all_of=["a"], any_of=["b", "c"], min_true=2)
    assert r.value is True


def test_min_true_unreachable():
    r = run({"a": T, "b": F, "c": F}, all_of=["a"], any_of=["b", "c"], min_true=2)
    assert r.value is False


def test_violated_part_wins_over_undecided_part():
    assert run({"a": F, "b": N}, all_of=["a"], any_of=["b"]).value is False


def test_not_applicable_input_is_undecided():
    by_id = {"a": row("a", T), "b": row("b", N).model_copy(update={"value_state": ValueState.NOT_APPLICABLE})}
    assert evaluate_derived(spec(all_of=["a", "b"]), by_id).value_state == ValueState.NOT_FOUND


def test_missing_input_is_undecided():
    assert run({"a": T}, all_of=["a", "b"]).value_state == ValueState.NOT_FOUND


def test_input_in_review_routes_derived():
    by_id = {"a": row("a", T, review_reasons=[ReasonCode.NOT_GROUNDED]), "b": row("b", T)}
    assert ReasonCode.CHECK_FAILED in evaluate_derived(spec(all_of=["a", "b"]), by_id).review_reasons


def test_input_with_failing_check_routes_derived():
    bad = CheckResult(check_id="x", layer=1, outcome=CheckOutcome.FAIL, severity=Severity.BLOCK)
    by_id = {"a": row("a", T).model_copy(update={"checks": [bad]})}
    assert evaluate_derived(spec(all_of=["a"]), by_id).review_reasons == [ReasonCode.CHECK_FAILED]


def _schema(rule, data_type=FieldDataType.BOOLEAN):
    a = FieldDefinition(field_id="a", name="a", description="", data_type=FieldDataType.BOOLEAN, extraction_instructions="")
    d = FieldDefinition(field_id="d", name="d", description="", data_type=data_type, extraction_instructions="", derived_rule=rule)
    return DataPointSchema(name="s", fields=[a, d])


def test_unknown_field_id_rejected():
    with pytest.raises(ValidationError, match="missing"):
        _schema(DerivedRule(all_of=["a", "missing"]))


def test_derived_must_be_boolean():
    with pytest.raises(ValidationError, match="boolean"):
        _schema(DerivedRule(all_of=["a"]), FieldDataType.STRING)


def test_valid_schema_builds():
    assert _schema(DerivedRule(any_of=["a"])).fields[1].derived_rule.any_of == ["a"]


@pytest.mark.parametrize("rule", [{}, {"min_true": 1}, {"all_of": ["a"], "min_true": 0}, {"all_of": ["a"], "min_true": 2}])
def test_empty_or_unsatisfiable_rule_rejected(rule):
    with pytest.raises(ValidationError):
        DerivedRule(**rule)


def test_input_not_auto_accepted_routes_derived():
    from arp.schemas.datapoints import RouteKind

    by_id = {"a": row("a", T).model_copy(update={"route": RouteKind.REVIEW}), "b": row("b", T).model_copy(update={"route": RouteKind.AUTO_ACCEPT})}
    assert evaluate_derived(spec(all_of=["a", "b"]), by_id).review_reasons == [ReasonCode.CHECK_FAILED]
    by_id["a"] = by_id["a"].model_copy(update={"route": RouteKind.AUTO_ACCEPT})
    assert evaluate_derived(spec(all_of=["a", "b"]), by_id).review_reasons == []


def test_derived_input_must_be_boolean_and_not_derived():
    a = FieldDefinition(field_id="a", name="a", description="", data_type=FieldDataType.NUMBER, extraction_instructions="")
    b = FieldDefinition(field_id="b", name="b", description="", data_type=FieldDataType.BOOLEAN, extraction_instructions="")
    d1 = FieldDefinition(field_id="d1", name="d1", description="", data_type=FieldDataType.BOOLEAN, extraction_instructions="",
                         derived_rule=DerivedRule(all_of=["b"]))
    d2 = d1.model_copy(update={"field_id": "d2", "derived_rule": DerivedRule(all_of=["a"])})
    d3 = d1.model_copy(update={"field_id": "d3", "derived_rule": DerivedRule(any_of=["d1"])})
    with pytest.raises(ValidationError, match="not a boolean"):
        DataPointSchema(name="s", fields=[a, b, d2])
    with pytest.raises(ValidationError, match="itself derived"):
        DataPointSchema(name="s", fields=[a, b, d1, d3])
