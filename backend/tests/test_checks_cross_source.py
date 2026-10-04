
from arp.checks import runner
from arp.checks.cross_source import Reference, check_cross_source
from arp.checks.runner import CheckContext, run_checks
from arp.extraction.pipeline import build_references
from arp.ingestion.xbrl import XbrlFactSource
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import CheckConfig, DataPointSchema, ExtractedField, FieldDefinition

IK, END = "lei:K1", "2024-12-31"
KEY = f"{IK}:rev:{END}"


def _spec(tags=None, **cfg):
    return FieldDefinition(
        field_id="rev", name="rev", description="d", data_type="number", extraction_instructions="i",
        xbrl_tags=tags or [], check_config=CheckConfig(**cfg),
    )


def _field(v, method="extracted", unit="USD"):
    return ExtractedField(
        field_id="rev", field_name="rev", value=v, confidence=0.9, value_state="found",
        canonical_value=v, canonical_unit=unit, period_end=END, method=method,
    )


def _ctx(spec, field, refs):
    return CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key=IK, schema=DataPointSchema(name="s", fields=[spec]),
        documents_by_id={}, record_fields=[field], references=refs,
    )


def _run(refs, v=100.0):
    spec, f = _spec(), _field(v)
    return check_cross_source(spec, f, _ctx(spec, f, {KEY: refs}))


def test_tagged_and_text_differ_beyond_tolerance_fails():
    (r,) = _run([Reference(source="tagged", value=103.0, unit="USD")])
    assert (r.outcome, r.severity, r.layer, r.check_id) == ("fail", "warn", 5, "cross_source")
    assert "tagged" in r.detail and "103" in r.detail and "100" in r.detail
    (r,) = _run([Reference(source="tagged", value=100.5, unit="USD")])
    assert r.outcome == "pass"


def test_published_reference_compared():
    (r,) = _run([Reference(source="published", value=150.0, unit="USD")])
    assert r.outcome == "fail" and "published" in r.detail


def test_unit_mismatch_ignored():
    (r,) = _run([Reference(source="tagged", value=999.0, unit="EUR")])
    assert r.outcome == "not_applicable"
    (r,) = _run([Reference(source="tagged", value=999.0, unit=None)])
    assert r.outcome == "fail"


def test_not_applicable_without_references_or_value():
    assert _run([])[0].outcome == "not_applicable"
    spec, f = _spec(), _field(None)
    assert check_cross_source(spec, f, _ctx(spec, f, {KEY: [Reference(source="text", value=1.0, unit=None)]}))[0].outcome == (
        "not_applicable"
    )


class _History:
    def last_rows(self, company_id, field_id):
        return [
            {"field_id": "rev", "period_end": END, "method": "tagged", "canonical_value": 1.0},
            {"field_id": "rev", "period_end": END, "method": "extracted", "canonical_value": 90.0, "canonical_unit": "USD"},
            {"field_id": "rev", "period_end": "2023-12-31", "method": "extracted", "canonical_value": 5.0},
        ]


FACTS = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"form": "10-K", "fp": "FY", "fy": 2024, "val": 103.0, "end": "2024-12-29", "start": "2024-01-01", "filed": "2025-02-01"}
]}}}}}


def _build(fields, specs, **kw):
    args = dict(xbrl_facts=FACTS, cik="1", history=_History(), published={}, company_id="c1", issuer_key=IK, specs=specs)
    return build_references(fields, **{**args, **kw})


def test_build_references_rules():
    spec = _spec(tags=["us-gaap:Revenues"])
    # a tagged field gets the prior text value from history (not the tagged history row)
    refs = _build([_field(103.0, method="tagged")], {"rev": spec})
    assert refs == {KEY: [Reference(source="text", value=90.0, unit="USD")]}
    # an extracted field with a tag fact (end within +-7 days) gets a tagged reference
    refs = _build([_field(100.0)], {"rev": spec}, history=None)
    assert refs == {KEY: [Reference(source="tagged", value=103.0, unit="USD")]}
    # no tags / no facts: nothing; no published map: no published reference
    assert _build([_field(100.0)], {"rev": _spec()}, history=None) == {}
    assert _build([_field(100.0)], {"rev": spec}, history=None, xbrl_facts=None) == {}
    # published values become references
    refs = _build([_field(100.0)], {"rev": _spec()}, history=None, published={KEY: (120.0, "USD")})
    assert refs == {KEY: [Reference(source="published", value=120.0, unit="USD")]}


def test_fact_matches_what_xbrl_source_returns():
    assert XbrlFactSource.fact_for_tags(FACTS, ["us-gaap:Revenues"], fiscal_year=2024).value == 103.0


async def test_layer5_runs():
    assert runner.LAYERS[5]
    spec, f = _spec(), _field(100.0)
    out = await run_checks(spec, f, _ctx(spec, f, {KEY: [Reference(source="tagged", value=200.0, unit="USD")]}))
    assert [r.outcome for r in out if r.check_id == "cross_source"] == ["fail"]
