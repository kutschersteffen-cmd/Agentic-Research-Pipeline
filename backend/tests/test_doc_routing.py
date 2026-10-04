from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.planning.doc_routing import route_documents, section_filter
from arp.schemas.common import Citation, CompanyRef, DocType, DocumentChunk, SourceDocument
from arp.schemas.datapoints import DataPointSchema, DocumentRouting, FieldDataType, FieldDefinition, FieldStatus
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry

TEXT = "Acme Corp report. In fiscal 2025, we invested $120 million in green capex."
QUOTE = "invested $120 million in green capex"


def _doc(text=TEXT, key="k1", doc_type=DocType.SUSTAINABILITY_REPORT):
    return SourceDocument(
        company_id="c1", doc_type=doc_type, title="ESG", full_text=text, content_key=key, doc_id="d1"
    )


def _field(version=1, routing=None, instructions="x"):
    return FieldDefinition(
        field_id="f1", name="capex", description="capex", data_type=FieldDataType.NUMBER,
        extraction_instructions=instructions, seed_keywords=["capex"], version=version, document_routing=routing,
    )


def _script():
    draft = ExtractionDraft(
        values=[PeriodValue(
            value=120.0, raw_value_text="$120 million", unit_text="USD million", period_text="fiscal 2025",
            citations=[Citation(doc_id="d1", doc_type=DocType.SUSTAINABILITY_REPORT, quote=QUOTE)],
        )],
        confidence=0.9,
    )
    return {"ExtractionDraft": [draft], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")]}


class _Src(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


async def _run(tmp_path, field, doc, fake_llm, script):
    return await _run_docs(tmp_path, [doc], fake_llm, script, field)


async def _run_docs(tmp_path, docs, fake_llm, script, field=None, *, trial=False, audit=False, **settings_kw):
    field = field or _field()
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "r", schema_registry_dir=tmp_path / "s",
        documents_dir=tmp_path / "d", cache_dir=tmp_path / "c", discovery_state_dir=tmp_path / "x", **settings_kw,
    )
    reg = SchemaRegistry(settings.schema_registry_dir)
    saved = reg.save(DataPointSchema(schema_id="sch1", name="s", fields=[field.model_copy(update={"status": FieldStatus.RELEASED})]))
    saved = reg.release(saved.schema_id, saved.version)
    if audit:
        reg.record_first_audit(field.field_id, field.version, "approver")
    store, llm = RunStore(settings.runs_dir), fake_llm(script)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
    run_id = create_extraction_run(saved, [company], settings, store, trial=trial)
    await execute_extraction_run(
        run_id, saved, [company], llm=llm, registry=DocumentSourceRegistry([_Src(docs)]),
        settings=settings, run_store=store,
    )
    (row,) = store.read_jsonl(store.results_path(run_id))
    return run_id, row["fields"][0], llm


async def test_unchanged_hash_makes_zero_model_calls(tmp_path, fake_llm):
    run1, row1, _ = await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    _, row2, llm2 = await _run(tmp_path, _field(), _doc(), fake_llm, {})
    assert llm2.calls == []
    assert row2["reused_from_run"] == run1 and row2["value"] == row1["value"] == 120.0


async def test_changed_document_reextracts(tmp_path, fake_llm):
    await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    _, row2, llm2 = await _run(tmp_path, _field(), _doc(TEXT + " More.", key="k2"), fake_llm, _script())
    assert llm2.calls and row2["reused_from_run"] is None


async def test_field_version_change_reextracts(tmp_path, fake_llm):
    await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    _, row2, llm2 = await _run(tmp_path, _field(version=2, instructions="new instructions"), _doc(), fake_llm, _script())
    assert llm2.calls and row2["reused_from_run"] is None


def test_routing_prefers_first_doc_type_with_documents():
    f = _field(routing=DocumentRouting(doc_types=[DocType.SUSTAINABILITY_REPORT, DocType.ANNUAL_REPORT_10K]))
    k, s = _doc(doc_type=DocType.ANNUAL_REPORT_10K), _doc(doc_type=DocType.SUSTAINABILITY_REPORT)
    assert route_documents(f, [k]) == [k]
    assert route_documents(f, [k, s]) == [s]


def test_no_routed_type_and_no_fallback_gives_nothing():
    f = _field(routing=DocumentRouting(doc_types=[DocType.SUSTAINABILITY_REPORT], fallback=False))
    assert route_documents(f, [_doc(doc_type=DocType.ANNUAL_REPORT_10K)]) == []


def test_section_filter_with_fallback():
    def chunk(sec):
        return DocumentChunk(doc_id="d", company_id="c", doc_type=DocType.ANNUAL_REPORT_10K, section=sec, text="t", char_start=0, char_end=1)

    a, b = chunk("Item 7 Climate"), chunk("Risk")
    f = _field(routing=DocumentRouting(sections=["climate"]))
    assert section_filter(f, [a, b]) == [a]
    assert section_filter(f, [b]) == [b]
    assert section_filter(_field(routing=DocumentRouting(sections=["climate"], fallback=False)), [b]) == []


def _failing_check_row(tmp_path, run_id):
    import json

    p = RunStore(tmp_path / "r").results_path(run_id)
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    rows[0]["fields"][0]["checks"] = [{"check_id": "c", "layer": 2, "outcome": "fail", "severity": "warn"}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


async def test_prior_failing_check_reextracts(tmp_path, fake_llm):
    run1, _, _ = await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    _failing_check_row(tmp_path, run1)
    _, row2, llm2 = await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    assert llm2.calls and row2["reused_from_run"] is None


async def test_shrunk_document_set_reextracts(tmp_path, fake_llm):
    settings_docs = [_doc(), _doc("Other text about capex.", key="k2")]
    for d, i in zip(settings_docs, ("d1", "d2"), strict=True):
        d.doc_id = i
    _, _, _ = await _run_docs(tmp_path, settings_docs, fake_llm, _script())
    _, row2, llm2 = await _run_docs(tmp_path, settings_docs[:1], fake_llm, _script())
    assert llm2.calls and row2["reused_from_run"] is None


async def test_prior_human_rejection_reextracts(tmp_path, fake_llm):
    from arp.orchestration.review_queue import record_review_decision

    run1, _, _ = await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    store = RunStore(tmp_path / "r")
    (item,) = store.read_jsonl(store.review_queue_path(run1))
    record_review_decision(store, run1, item["item_key"], "reject", "reviewer", None)
    _, row2, llm2 = await _run_docs(tmp_path, [_doc()], fake_llm, _script(), audit=True)
    assert llm2.calls and row2["reused_from_run"] is None


async def test_trial_on_released_audited_field_queues_every_row(tmp_path, fake_llm):
    run_id, row, _ = await _run_docs(tmp_path, [_doc()], fake_llm, _script(), trial=True, audit=True)
    assert row["route"] == "review" and row["route_reasons"][:1] == ["unreleased_version"]
    store = RunStore(tmp_path / "r")
    assert [q["field_id"] for q in store.read_jsonl(store.review_queue_path(run_id))] == ["f1"]


async def test_changed_model_setting_reextracts(tmp_path, fake_llm):
    await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    _, row2, llm2 = await _run_docs(tmp_path, [_doc()], fake_llm, _script(), grounding_fuzzy_threshold=0.5, llm_model="other-model")
    assert llm2.calls and row2["reused_from_run"] is None


async def test_restart_from_extract_reextracts(tmp_path, fake_llm):
    from arp.extraction.steps import restart_overrides

    await _run(tmp_path, _field(), _doc(), fake_llm, _script())
    _, row2, llm2 = await _run_docs(tmp_path, [_doc()], fake_llm, _script(), **restart_overrides("extract"))
    assert llm2.calls and row2["reused_from_run"] is None
