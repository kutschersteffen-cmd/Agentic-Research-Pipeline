"""Auto-corrections in the extraction pipeline (extraction-auto-corrections spec: AC-11, 12, 13, 17, 21-24, 32)."""
from __future__ import annotations

import pytest

from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import _extract_company, create_extraction_run, execute_extraction_run
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMUsage
from arp.presets.transition_capex import SCHEMA_ID as CAPEX_ID
from arp.presets.transition_capex import build_transition_capex_schema
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.storage.run_store import RunStore
from tests.test_extraction_pipeline import _FixedDocSource, _released_run, _settings

pytestmark = pytest.mark.usefixtures("pg")

COMPANY = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")


def _doc(text: str, company: CompanyRef = COMPANY) -> SourceDocument:
    # The single year in the title makes the report's period end (period_plan.current) 2025-12-31; the company's
    # name in it confirms the entity; the content key lets an unchanged input be reused.
    return SourceDocument(company_id=company.company_id, doc_type=DocType.SUSTAINABILITY_REPORT,
                          title=f"{company.name} Annual Report 2025", full_text=text, doc_id=f"d-{company.company_id}",
                          content_key=f"k-{company.company_id}")


class _LLM:
    """Extraction answers keyed by a prompt substring (no match: nothing found); the verifier always agrees."""

    def __init__(self, answers: dict[str, tuple]):
        self.answers, self.calls = answers, []

    async def complete_structured(self, *, system, prompt, output_model, **kw):
        self.calls.append(output_model.__name__)
        if output_model is VerifierOutput:
            return VerifierOutput(agrees=True, confidence=0.95, notes="ok"), LLMUsage(provider="fake")
        key = next((k for k in self.answers if k in prompt), None)
        values = []
        if key:
            value, quote, unit, period = self.answers[key]
            doc_id = prompt.split("[doc_id=", 1)[1].split(" ", 1)[0]  # the evidence's own document
            values = [PeriodValue(
                value=value, raw_value_text=str(value), unit_text=unit, period_text=period,
                citations=[Citation(doc_id=doc_id, doc_type=DocType.SUSTAINABILITY_REPORT, quote=quote)],
            )]
        return ExtractionDraft(values=values, confidence=0.95), LLMUsage(provider="fake")


def _capex(*field_ids: str, schema_id: str = CAPEX_ID) -> DataPointSchema:
    """Preset fields without the sector filter or the high-risk flag, so a plain company gets them."""
    preset = {f.field_id: f for f in build_transition_capex_schema().fields}
    fields = [preset[i].model_copy(update={"applicability_rules": None, "high_risk": False}) for i in field_ids]
    return DataPointSchema(schema_id=schema_id, name="Capex", fields=fields)


def _field(name: str) -> str:
    return f"Field: {name}\n"


async def _run(tmp_path, schema, docs, answers, *, trial=True, companies=(COMPANY,)):
    settings = _settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
    store = RunStore(settings.postgres_dsn, settings.runs_dir)
    if trial:
        run_id = create_extraction_run(schema, list(companies), settings, store, trial=True)
    else:
        run_id = _released_run(schema, list(companies), settings, store)
    llm = _LLM(answers)
    await execute_extraction_run(
        run_id, schema, list(companies), llm=llm, registry=DocumentSourceRegistry([_ByCompany(docs)]),
        settings=settings, run_store=store,
    )
    return run_id, store, llm


class _ByCompany(DocumentSource):
    name = "by-company"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return [d for d in self._docs if d.company_id == company.company_id]


def _rows(store, run_id, company_id="c1"):
    (rec,) = [r for r in store.read_results(run_id) if r["company_id"] == company_id]
    return rec["fields"]


def _row(store, run_id, field_id, period_end=None, company_id="c1"):
    (row,) = [f for f in _rows(store, run_id, company_id) if f["field_id"] == field_id
              and (period_end is None or f["period_end"] == period_end)]
    return row


DENOM_DOC = "Annual Report 2025. Capex denominator: cash-flow capex."


async def test_corrected_rows_route_to_review(tmp_path):  # AC-11
    answers = {_field("Capex denominator"): ("cash-flow capex", "Capex denominator: cash-flow capex", None, None)}
    run_id, store, _ = await _run(tmp_path, _capex("tc_capex_denominator"), [_doc(DENOM_DOC)], answers)
    row = _row(store, run_id, "tc_capex_denominator")
    assert row["value"] == "cash_flow"
    assert "auto_corrected" in row["review_reasons"] and row["route"] == "review"
    (q,) = store.read_review_queue(run_id)
    assert "auto_corrected" in q["reason_codes"]


async def test_rows_needing_no_correction_are_unchanged(tmp_path):  # AC-12
    text = "Annual Report 2025. Capex denominator: cash_flow. Capital expenditures were $2,479 million in 2025."
    answers = {
        _field("Capex denominator"): ("cash_flow", "Capex denominator: cash_flow", None, "2025"),
        _field("Total capex"): (2479.0, "capital expenditures were $2,479 million in 2025", "USD millions", "2025"),
    }
    run_id, store, _ = await _run(tmp_path, _capex("tc_capex_total", "tc_capex_denominator"), [_doc(text)], answers)
    denom = _row(store, run_id, "tc_capex_denominator")
    capex = _row(store, run_id, "tc_capex_total")
    assert (denom["value"], denom["corrections"]) == ("cash_flow", [])
    assert (capex["value"], capex["unit"], capex["period_end"], capex["corrections"]) == (
        2479.0, "USD millions", "2025-12-31", [])
    for row in (denom, capex):
        assert row["route"] == "review" and "unreleased_version" in row["route_reasons"]
        assert not {"auto_corrected", "period_missing"} & set(row["review_reasons"])


async def test_reused_row_keeps_one_correction(tmp_path):  # AC-13
    answers = {_field("Capex denominator"): ("cash-flow capex", "Capex denominator: cash-flow capex", None, None)}
    schema, docs = _capex("tc_capex_denominator"), [_doc(DENOM_DOC)]
    run1, _, _ = await _run(tmp_path, schema, docs, answers, trial=False)  # only non-trial runs are reused
    run2, store, llm2 = await _run(tmp_path, schema, docs, answers, trial=False)
    row = _row(store, run2, "tc_capex_denominator")
    assert llm2.calls == [] and row["reused_from_run"] == run1
    assert [c["rule"] for c in row["corrections"]] == ["label_map"]
    assert row["review_reasons"].count("auto_corrected") == 1


async def test_moved_row_is_reused_under_planned_field(tmp_path):  # AC-9, AC-17
    quote = "Capital expenditures for 2026 are estimated to be approximately $2.5 billion"
    answers = {_field("Total capex"): (2.5, quote, "USD billions", "2026")}
    schema, docs = _capex("tc_capex_total", "tc_capex_total_planned"), [_doc(f"Annual Report 2025. {quote}.")]
    run1, store, _ = await _run(tmp_path, schema, docs, answers, trial=False)  # only non-trial runs are reused
    moved = _row(store, run1, "tc_capex_total_planned", "2026-12-31")
    assert moved["value"] == 2.5 and [(c["rule"], c["attribute"]) for c in moved["corrections"]] == [("planned_move", "field_id")]
    run2, store, _ = await _run(tmp_path, schema, docs, answers, trial=False)
    planned = _row(store, run2, "tc_capex_total_planned", "2026-12-31")
    assert planned["reused_from_run"] == run1
    assert [c["rule"] for c in planned["corrections"]] == ["planned_move"]
    actual = [f for f in _rows(store, run2) if f["field_id"] == "tc_capex_total" and f["period_end"] == "2026-12-31"]
    assert all(f["value"] is None for f in actual)


async def test_released_schema_auto_accepts_uncorrected_twin_only(tmp_path):  # AC-32
    field = FieldDefinition(
        field_id="denominator", name="denominator", description="Capex denominator", data_type=FieldDataType.ENUM,
        allowed_values=["cash_flow", "other"], extraction_instructions="Which total the capex figure is.",
        seed_keywords=["capex denominator"], auto_accept_min=0.9,
    )
    schema = DataPointSchema(schema_id="sch_denominator", name="Denominator", fields=[field])
    bolt = CompanyRef(company_id="c2", name="Bolt Corp", ticker="BOLT")
    docs = [_doc("Annual Report 2025. Capex denominator: cash_flow."),
            _doc("Annual Report 2025. Capex denominator: Cash flow.", bolt)]
    answers = {"Capex denominator: cash_flow": ("cash_flow", "Capex denominator: cash_flow", None, None),
               "Capex denominator: Cash flow": ("Cash flow", "Capex denominator: Cash flow", None, None)}
    companies = (COMPANY, bolt)
    run_id, store, _ = await _run(tmp_path, schema, docs, answers, trial=False, companies=companies)
    a = _row(store, run_id, "denominator", company_id="c1")
    b = _row(store, run_id, "denominator", company_id="c2")
    assert a["route"] == "auto_accept"
    assert (b["value"], b["route"]) == ("cash_flow", "review") and "auto_corrected" in b["review_reasons"]


# One answer per rule: R1 (enum label), R2 (no period, the quote names only 2025), R3 (scale word in the quote).
RULES_DOC = ("Annual Report 2025. Capex denominator: Cash flow. Capital expenditures were $2,479 million in 2025. "
             "R&D spend was $2.794 billion.")
RULES_ANSWERS = {
    _field("Capex denominator"): ("Cash flow", "Capex denominator: Cash flow", None, None),
    _field("Total capex"): (2479.0, "Capital expenditures were $2,479 million in 2025", "USD millions", None),
    _field("Total R&D spend"): (2.794, "R&D spend was $2.794 billion", "USD millions", "2025"),
}
RULES_FIELDS = ("tc_capex_denominator", "tc_capex_total", "tc_rnd_total")


def _uncorrected(rows):
    for f in rows:
        assert f["corrections"] == [] and not {"auto_corrected", "period_missing"} & set(f["review_reasons"]), f


def _rules_schema(schema_id: str, field_ids=RULES_FIELDS) -> DataPointSchema:
    schema = _capex(*RULES_FIELDS, schema_id=schema_id)
    fields = [f.model_copy(update={"field_id": i}) for f, i in zip(schema.fields, field_ids, strict=True)]
    return schema.model_copy(update={"fields": fields})


@pytest.mark.parametrize("schema", [
    _rules_schema("transition_plan_indicators"),  # AC-21
    # AC-22: only the ta_operates_* fields of this schema take the per-field path that corrections would act on
    _rules_schema("sch_transition_plan_actions", ("ta_operates_eu", "ta_operates_us", "ta_operates_cn")),
], ids=["indicators", "actions"])
async def test_transition_plan_schemas_get_no_corrections(tmp_path, schema):  # AC-21, AC-22
    run_id, store, _ = await _run(tmp_path, schema, [_doc(RULES_DOC)], RULES_ANSWERS)
    rows = _rows(store, run_id)
    assert {f["value"] for f in rows} == {"Cash flow", 2479.0, 2.794}  # every answer reached the record
    _uncorrected(rows)


async def test_same_answers_are_corrected_in_a_custom_schema(tmp_path):  # control for AC-21 to AC-24
    run_id, store, _ = await _run(tmp_path, _rules_schema(CAPEX_ID), [_doc(RULES_DOC)], RULES_ANSWERS)
    rules = {c["rule"] for f in _rows(store, run_id) for c in f["corrections"]}
    assert rules == {"label_map", "period_fill", "unit_scale"}


async def test_research_callers_get_no_corrections(tmp_path):  # AC-23, AC-24: callers keep the default
    settings = _settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
    result = await _extract_company(
        COMPANY, _rules_schema(CAPEX_ID), registry=DocumentSourceRegistry([_FixedDocSource([_doc(RULES_DOC)])]),
        llm=_LLM(RULES_ANSWERS), settings=settings,
    )
    rows = [f.model_dump(mode="json") for f in result.record.fields]
    assert {f["value"] for f in rows} == {"Cash flow", 2479.0, 2.794}
    _uncorrected(rows)
