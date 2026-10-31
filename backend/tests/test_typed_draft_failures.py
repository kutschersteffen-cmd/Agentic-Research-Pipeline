"""A failed answer fails only its field (spec 2026-10-31-extraction-quick-wins, AC-19 to AC-19e)."""

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.main import app
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.field_graph import extract_one_field
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.extraction.routing import route
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMUsage
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition, FieldQuality
from arp.storage.run_store import RunStore
from tests.test_extraction_pipeline import _FixedDocSource, _settings

TEXT = "Acme Corp report. Acme has a net zero target. Total capex was 11,887 million euros in 2025."
DOC = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=TEXT)
BOOL = FieldDefinition(field_id="nz", name="Net zero target", description="d", data_type=FieldDataType.BOOLEAN,
                       extraction_instructions="look", seed_keywords=["net zero"], high_risk=True)
CAPEX = FieldDefinition(field_id="cx", name="Total capex", description="d", data_type=FieldDataType.CURRENCY_AMOUNT,
                        extraction_instructions="look", seed_keywords=["capex"])


class _Raw:
    """Answers raw tool inputs, validated against the requested format like the real client
    (whose own retries are tested elsewhere): the yes/no field always gets "Not disclosed"."""

    async def complete_structured(self, *, system, prompt, output_model, **_):
        usage = LLMUsage(provider="fake")
        if output_model.__name__ == "VerifierOutput":
            return output_model(agrees=True, confidence=0.9, notes="ok"), usage
        if output_model.__name__ == "AdjudicatorOutput":
            return output_model(settled=False, notes="undecided"), usage
        quote = "Total capex was 11,887 million euros"
        value = "Not disclosed" if "Field: Net zero target" in prompt else 11887
        raw = {"values": [{"value": value, "raw_value_text": "11,887", "unit_text": "EUR million", "period_text": "2025",
                           "citations": [{"doc_id": DOC.doc_id, "doc_type": "sustainability_report", "quote": quote}]}],
               "confidence": 0.9}
        return output_model.model_validate(raw), usage


@pytest.fixture
def run(tmp_path, pg):
    async def go():
        settings = _settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
        store = RunStore(settings.postgres_dsn, settings.runs_dir)
        schema = DataPointSchema(name="Two", fields=[BOOL, CAPEX])
        company = CompanyRef(company_id="c1", name="Acme Corp")
        run_id = create_extraction_run(schema, [company], settings, store, trial=True)
        await execute_extraction_run(run_id, schema, [company], llm=_Raw(), verifier_llm=_Raw(),
                                     registry=DocumentSourceRegistry([_FixedDocSource([DOC])]),
                                     settings=settings, run_store=store)
        app.dependency_overrides[get_run_store] = lambda: store
        try:
            client = TestClient(app)
            rows = {f["field_id"]: f for f in client.get(f"/api/extraction/runs/{run_id}/results").json()["results"][0]["fields"]}
            manifest = client.get(f"/api/runs/{run_id}").json()
        finally:
            app.dependency_overrides.pop(get_run_store, None)
        return manifest, rows
    return go


async def test_ac19_run_completes(run):
    manifest, _ = await run()
    assert manifest["status"] == "completed"
    assert (manifest["completed_count"], manifest["company_count"]) == (1, 1)


async def test_ac19c_other_field_kept(run):
    _, rows = await run()
    assert rows["cx"]["value"] == 11887.0


async def test_ac19d_failed_field_row(run):
    _, rows = await run()
    nz = rows["nz"]
    assert nz["value_state"] == "not_found" and nz["route"] == "review" and "extraction_failed" in nz["review_reasons"]


class _BlindFails:
    """The extractor answers true; the blind verifier's answer never fits a yes/no."""

    def __init__(self, value):
        self.value = value

    async def complete_structured(self, *, system, prompt, output_model, **_):
        quote = "Acme has a net zero target"
        raw = {"values": [{"value": self.value, "raw_value_text": quote,
                           "citations": [{"doc_id": DOC.doc_id, "doc_type": "sustainability_report", "quote": quote}]}],
               "confidence": 0.9}
        if output_model.__name__ == "AdjudicatorOutput":
            return output_model(settled=False, notes="undecided"), LLMUsage(provider="fake")
        return output_model.model_validate(raw), LLMUsage(provider="fake")


async def _blind():
    trace: dict = {}
    fields, _, _ = await extract_one_field("Acme", BOOL, documents=[DOC], documents_by_id={DOC.doc_id: DOC},
                                           llm=_BlindFails(True), verifier_llm=_BlindFails("YES"),
                                           fuzzy_threshold=0.9, confidence_review_threshold=0.6, trace_sink=trace)
    return fields[0], trace


async def test_ac19b_blind_failure_routes_review():
    row, _ = await _blind()
    assert route(row, FieldQuality(field_id="nz", version=1), BOOL).kind == "review"


async def test_ac19e_blind_failure_is_not_disclosed():
    _, trace = await _blind()
    assert trace["nz"]["verifier"]["verdict"]["disagreement_type"] == "not_disclosed"


def test_extract_failure_draft_is_empty():
    assert ExtractionDraft(confidence=0.0).values == []


class _CountingFails:
    """Every extraction answer is text for a yes/no field; counts calls."""

    def __init__(self):
        self.calls = 0

    async def complete_structured(self, *, system, prompt, output_model, **_):
        self.calls += 1
        return output_model.model_validate({"values": [{"value": "Not disclosed"}], "confidence": 0.9}), LLMUsage()


async def test_failed_extraction_skips_the_verifier():  # review finding: no value may come back via the verifier
    llm, verifier = _CountingFails(), _CountingFails()
    fields, _, _ = await extract_one_field("Acme", BOOL, documents=[DOC], documents_by_id={DOC.doc_id: DOC},
                                           llm=llm, verifier_llm=verifier, fuzzy_threshold=0.9,
                                           confidence_review_threshold=0.6)
    assert (fields[0].value_state, verifier.calls) == ("not_found", 0)
    assert "extraction_failed" in fields[0].review_reasons
