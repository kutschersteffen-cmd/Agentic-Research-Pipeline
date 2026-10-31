from arp.checks import runner
from arp.checks.runner import CheckContext, check_format, check_record, run_checks
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import (
    CheckConfig,
    CheckResult,
    DataPointSchema,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
)
from arp.storage.run_store import RunStore
from tests.test_extraction_pipeline import _FixedDocSource, _settings


def _spec(data_type=FieldDataType.NUMBER, **kw):
    return FieldDefinition(
        field_id="f1", name="f1", description="d", data_type=data_type, extraction_instructions="i", **kw
    )


def _field(value, **kw):
    return ExtractedField(field_id="f1", field_name="f1", value=value, confidence=0.9, **kw)


def _ctx(spec, fields):
    schema = DataPointSchema(name="s", fields=[spec])
    return CheckContext(
        company=CompanyRef(company_id="c1", name="Acme"),
        issuer_key="k",
        schema=schema,
        documents_by_id={},
        record_fields=fields,
    )


def _result(severity, check_id="t.x", layer=3):
    return CheckResult(check_id=check_id, layer=layer, outcome="fail", severity=severity)


class _Spy:
    def __init__(self):
        self.calls = 0

    async def __call__(self, spec, field, ctx):
        self.calls += 1
        return [CheckResult(check_id="t.model", layer=5, outcome="pass")]


async def test_layer5_not_called_when_earlier_layer_blocks(monkeypatch):
    monkeypatch.setitem(runner.LAYERS, 3, [lambda s, f, c: [_result("block", "t.block")]])
    monkeypatch.setitem(runner.LAYERS, 4, [lambda s, f, c: [_result("warn", "t.l4", 4)]])
    spec, spy = _spec(), _Spy()
    field = _field(1.0)
    out = await run_checks(spec, field, _ctx(spec, [field]), model_check=spy)
    assert out[-1].check_id == "t.block"
    assert all(r.layer != 4 for r in out)
    assert spy.calls == 0


async def test_layer5_called_when_nothing_blocks(monkeypatch):
    monkeypatch.setitem(runner.LAYERS, 3, [lambda s, f, c: [_result("warn", "t.warn")]])
    spec, spy = _spec(), _Spy()
    field = _field(1.0)
    out = await run_checks(spec, field, _ctx(spec, [field]), model_check=spy)
    assert spy.calls == 1
    assert out[-1].check_id == "t.model"


def test_enum_outside_allowed_values_blocks():
    spec = _spec(FieldDataType.ENUM, allowed_values=["a", "b"])
    field = _field("c")
    res = {r.check_id: r for r in check_format(spec, field, _ctx(spec, [field]))}
    assert res["format.allowed_values"].outcome == "fail"
    assert res["format.allowed_values"].severity == "block"


def test_not_found_format_not_applicable():
    spec = _spec()
    field = _field(None)
    res = check_format(spec, field, _ctx(spec, [field]))
    assert {r.check_id for r in res} == {"format.data_type", "format.allowed_values"}
    assert all(r.outcome == "not_applicable" for r in res)


async def test_failed_check_adds_check_failed_once(monkeypatch):
    monkeypatch.setitem(runner.LAYERS, 2, [lambda s, f, c: [_result("warn", "t.a", 2), _result("warn", "t.b", 2)]])
    spec = _spec()
    field = _field(1.0)
    other = ExtractedField(field_id="unknown", field_name="u", value=1.0, confidence=0.9)
    out = await check_record(DataPointSchema(name="s", fields=[spec]), [field, other], _ctx(spec, [field, other]))
    assert out[0].review_reasons.count("check_failed") == 1
    assert "t.a" in out[0].verifier_notes and "t.b" in out[0].verifier_notes
    assert out[1].checks == [] and out[1].review_reasons == []


async def test_checks_stored_on_results_row(pg, tmp_path, fake_llm):
    spec = FieldDefinition(
        name="alpha", description="alpha", data_type=FieldDataType.NUMBER, extraction_instructions="alpha", seed_keywords=["alphakw"]
    )
    schema = DataPointSchema(name="One", fields=[spec])
    doc = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="alphakw is 1 million.")
    quote = "alphakw is 1 million"
    draft = ExtractionDraft(
        value=1.0, raw_value_text=quote, citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], confidence=0.9
    )
    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")]})
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
    run_id = create_extraction_run(schema, [company], settings, store, trial=True)
    await execute_extraction_run(
        run_id, schema, [company], llm=llm, registry=DocumentSourceRegistry([_FixedDocSource([doc])]),
        settings=settings, run_store=store,
    )
    row = store.read_results(run_id)[0]
    assert "format.data_type" in [c["check_id"] for c in row["fields"][0]["checks"]]


def test_old_field_definition_and_row_load():
    d = FieldDefinition.model_validate(
        {"name": "n", "description": "d", "data_type": "number", "extraction_instructions": "i"}
    )
    assert d.check_config == CheckConfig()
    f = ExtractedField.model_validate({"field_id": "f", "field_name": "f", "value": 1.0, "confidence": 0.5})
    assert f.checks == []


# Spec 2026-10-31-extraction-quick-wins, AC-6 to AC-10 and AC-17
def _fmt(data_type, value, unit=None, canonical_unit=None):
    spec = _spec(data_type)
    row = _field(value, unit=unit, canonical_unit=canonical_unit)
    return next(r for r in check_format(spec, row, _ctx(spec, [row])) if r.check_id == "format.data_type")


def test_ac6_string_bare_number():
    r = _fmt(FieldDataType.STRING, 11115)
    assert (r.outcome, r.severity, r.detail) == ("fail", "block", "string field holds a bare number 11115")


def test_ac6b_string_number_text():
    r = _fmt(FieldDataType.STRING, "1,234.5")
    assert (r.outcome, r.detail) == ("fail", "string field holds a bare number 1,234.5")


def test_ac6c_string_year():
    assert _fmt(FieldDataType.STRING, "2020").outcome == "fail"


def test_ac6d_string_exponent_passes():
    assert _fmt(FieldDataType.STRING, "1e3").outcome == "pass"


def test_ac7_string_prose_passes():
    assert _fmt(FieldDataType.STRING, "EU Taxonomy definition (Regulation (EU) 2020/852)").outcome == "pass"


def test_ac8_currency_with_percent():
    r = _fmt(FieldDataType.CURRENCY_AMOUNT, 27.3, unit="%")
    assert (r.outcome, r.detail) == ("fail", "currency_amount field holds a percentage (unit %)")


def test_ac8b_number_with_percent():
    r = _fmt(FieldDataType.NUMBER, 5, unit="%")
    assert (r.outcome, r.detail) == ("fail", "number field holds a percentage (unit %)")


def test_ac8c_canonical_percent():
    assert _fmt(FieldDataType.CURRENCY_AMOUNT, 27.3, unit="percent", canonical_unit="%").outcome == "fail"


def test_ac9_percentage_with_currency_code():
    r = _fmt(FieldDataType.PERCENTAGE, 39.6, unit="EUR million")
    assert (r.outcome, r.detail) == ("fail", "percentage field holds a currency amount (unit EUR million)")


def test_ac9b_percentage_with_currency_sign():
    r = _fmt(FieldDataType.PERCENTAGE, 39.6, unit="€")
    assert (r.outcome, r.detail) == ("fail", "percentage field holds a currency amount (unit €)")


def test_ac10_percentage_with_percent_passes():
    assert _fmt(FieldDataType.PERCENTAGE, 39.6, unit="%").outcome == "pass"


def test_ac17_boolean_number_still_blocks():
    r = _fmt(FieldDataType.BOOLEAN, 220221)
    assert (r.outcome, r.severity) == ("fail", "block")
