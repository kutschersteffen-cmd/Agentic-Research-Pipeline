from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import _extract_company
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        schema_registry_dir=tmp_path / "schemas",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
    )


def _schema() -> DataPointSchema:
    field = FieldDefinition(
        name="green_capex_usd_m",
        description="Green capex in USD millions for the most recent fiscal year.",
        data_type=FieldDataType.CURRENCY_AMOUNT,
        unit="USD millions",
        extraction_instructions="Find the disclosed green/sustainable capex figure for the latest fiscal year.",
        seed_keywords=["green capex", "sustainable capital expenditure"],
    )
    return DataPointSchema(name="Green Capex", fields=[field])


async def test_extract_company_grounded_value_not_flagged(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1",
        doc_type=DocType.SUSTAINABILITY_REPORT,
        title="ESG report",
        full_text="In fiscal 2025, we invested $120 million in green capex across our facilities.",
    )
    schema = _schema()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    quote = "invested $120 million in green capex"
    draft = ExtractionDraft(
        values=[PeriodValue(
            value=120.0,
            raw_value_text="$120 million in green capex",
            unit_text="USD million",
            period_text="fiscal 2025",
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)],
        )],
        confidence=0.9,
    )
    verifier = VerifierOutput(agrees=True, corrected_value=None, confidence=0.9, notes="Matches the cited text.")

    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company(company, schema, registry=registry, llm=llm, settings=_settings(tmp_path))
    field_result = result.record.fields[0]
    assert field_result.value == 120.0
    assert field_result.grounded is True
    assert (field_result.canonical_value, field_result.canonical_unit) == (120.0, "USD millions")
    assert result.record.needs_review is False


async def test_extract_company_verifier_disagreement_flags_review(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1",
        doc_type=DocType.SUSTAINABILITY_REPORT,
        title="ESG report",
        full_text="In fiscal 2024, we invested $80 million in green capex; fiscal 2025 guidance is $120 million.",
    )
    schema = _schema()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    quote = "invested $80 million in green capex"
    draft = ExtractionDraft(
        value=80.0,
        raw_value_text="$80 million in green capex",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)],
        confidence=0.7,
    )
    # verifier catches that 80M was fiscal 2024, not the most recent year requested
    verifier = VerifierOutput(
        agrees=False, corrected_value=120.0, confidence=0.85, notes="80M was FY2024; instructions require latest FY (2025 guidance = 120M)."
    )

    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company(company, schema, registry=registry, llm=llm, settings=_settings(tmp_path))
    field_result = result.record.fields[0]
    assert field_result.value == 120.0  # verifier's correction wins
    assert result.record.needs_review is True


async def test_extract_company_no_evidence_skips_llm_and_not_flagged(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="We sell shoes.")
    schema = _schema()
    company = CompanyRef(company_id="c1", name="Shoe Co", ticker="SHOE")

    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company(company, schema, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.fields[0].value is None
    assert result.record.needs_review is False
    assert llm.calls == []


async def test_hybrid_retrieval_setting_reaches_evidence_selection(tmp_path, fake_llm, monkeypatch):
    """settings.hybrid_retrieval_enabled must actually reach
    select_relevant_chunks inside field_graph.py's _gather_evidence, not
    just exist on the Settings object -- proven by asserting the local
    embedding model is invoked when it's on, and never invoked when it's
    off (the conftest.py-wide default for this whole suite)."""
    import numpy as np

    from arp.retrieval import embeddings as embeddings_module

    doc = SourceDocument(
        company_id="c1",
        doc_type=DocType.SUSTAINABILITY_REPORT,
        title="ESG report",
        full_text="In fiscal 2025, we invested $120 million in green capex across our facilities.",
    )
    schema = _schema()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = ExtractionDraft(
        value=120.0, raw_value_text="$120 million in green capex",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="$120 million in green capex")],
        confidence=0.9,
    )
    verifier = VerifierOutput(agrees=True, confidence=0.9, notes="")
    embed_calls = []

    def fake_embed(texts):
        embed_calls.append(list(texts))
        return np.zeros((len(texts), 384), dtype=np.float32)

    monkeypatch.setattr(embeddings_module, "embed_texts", fake_embed)
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    settings_off = _settings(tmp_path)
    llm_off = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    await _extract_company(company, schema, registry=registry, llm=llm_off, settings=settings_off)
    assert embed_calls == []  # default-off in this suite (see conftest.py) -- no embedding call at all

    settings_on = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs2", documents_dir=tmp_path / "docs2",
        cache_dir=tmp_path / "cache2", discovery_state_dir=tmp_path / "disc2", hybrid_retrieval_enabled=True,
    )
    llm_on = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    await _extract_company(company, schema, registry=registry, llm=llm_on, settings=settings_on)
    assert embed_calls != []  # explicit constructor kwarg wins over the env-var default -- hybrid actually ran


async def test_a_run_counts_the_items_through_each_step(tmp_path, fake_llm):
    """End to end through run_company_batch: one company has evidence, one does not."""
    from arp.extraction.pipeline import run_extraction
    from arp.orchestration.step_tally import step_counts
    from arp.storage.run_store import RunStore

    class _ByCompany(DocumentSource):
        name = "by-company"

        async def fetch(self, company, doc_types=None):
            text = "In fiscal 2025, we invested $120 million in green capex." if company.company_id == "c1" else "We sell shoes."
            return [SourceDocument(company_id=company.company_id, doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=text)]

    draft = ExtractionDraft(value=120.0, raw_value_text="$120 million", citations=[], confidence=0.9)
    verifier = VerifierOutput(agrees=True, corrected_value=None, confidence=0.9, notes="ok")
    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    settings = _settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
    run_store = RunStore(settings.runs_dir)
    companies = [CompanyRef(company_id="c1", name="Acme"), CompanyRef(company_id="c2", name="Shoe Co")]

    run_id = await run_extraction(
        _schema(), companies, llm=llm, registry=DocumentSourceRegistry([_ByCompany()]), settings=settings, run_store=run_store, trial=True
    )
    view, live = step_counts(run_store, run_id)
    assert live is False
    assert view["counts"] == {"gather_evidence": 2, "extract": 1, "verify": 1, "aggregate": 1, "finalize_no_evidence": 1}
    assert set(view["seconds"]) == set(view["counts"])
    # Per company: the one without evidence never reached the extractor.
    assert step_counts(run_store, run_id, "c2")[0]["counts"] == {"gather_evidence": 1, "finalize_no_evidence": 1}
    assert step_counts(run_store, run_id, "c1")[0]["counts"] == {"gather_evidence": 1, "extract": 1, "verify": 1, "aggregate": 1}


async def test_pipeline_queues_one_row_per_flagged_field(tmp_path, fake_llm):
    from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
    from arp.schemas.issuer import issuer_key
    from arp.storage.run_store import RunStore

    def _f(name, kw):
        return FieldDefinition(
            name=name, description=name, data_type=FieldDataType.NUMBER, extraction_instructions=name, seed_keywords=[kw]
        )

    schema = DataPointSchema(name="Three", fields=[_f("alpha", "alphakw"), _f("beta", "betakw"), _f("gamma", "gammakw")])
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
        full_text="alphakw is 1 million. betakw is 2 million. gammakw is 3 million.",
    )
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    def _draft(v, quote):
        return ExtractionDraft(
            value=v, raw_value_text=quote,
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], confidence=0.9,
        )

    agree = VerifierOutput(agrees=True, confidence=0.9, notes="ok")
    disagree = VerifierOutput(agrees=False, corrected_value=None, confidence=0.9, notes="wrong")
    llm = fake_llm(
        {
            "ExtractionDraft": [_draft(1.0, "alphakw is 1 million"), _draft(2.0, "betakw is 2 million"), _draft(3.0, "gammakw is 3 million")],
            "VerifierOutput": [agree, disagree, disagree],
        }
    )
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    run_id = create_extraction_run(schema, [company], settings, run_store, trial=True)
    await execute_extraction_run(
        run_id, schema, [company], llm=llm, registry=DocumentSourceRegistry([_FixedDocSource([doc])]),
        settings=settings, run_store=run_store,
    )

    rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    key, scheme = issuer_key(company)
    flagged = [f.field_id for f in schema.fields[1:]]
    assert [r["item_key"] for r in rows] == [f"{key}:{fid}:unspecified" for fid in flagged]
    assert rows[0]["reason_codes"] == ["verifier_disagrees"]
    assert rows[0]["issuer_key"] == key and rows[0]["issuer_scheme"] == scheme
    assert rows[0]["field"]["field_id"] == flagged[0] and rows[0]["company_id"] == "c1"
    assert run_store.load_manifest(run_id).review_count == 2


async def test_provenance_records_schema_version(tmp_path, fake_llm):
    from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
    from arp.storage.run_store import RunStore

    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
        full_text="In fiscal 2025, we invested $120 million in green capex across our facilities.",
    )
    quote = "invested $120 million in green capex"
    draft = ExtractionDraft(
        value=120.0, raw_value_text="$120 million",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], confidence=0.9,
    )
    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")]})
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
    schema = _schema()
    run_id = create_extraction_run(schema, [company], settings, run_store, trial=True)
    await execute_extraction_run(
        run_id, schema, [company], llm=llm, registry=DocumentSourceRegistry([_FixedDocSource([doc])]),
        settings=settings, run_store=run_store,
    )
    (row,) = run_store.read_jsonl(run_store.results_path(run_id))
    prov = row["fields"][0]["provenance"]
    assert prov["schema_version"] == f"{schema.schema_id}:v1" and prov["field_version"] == 1


async def test_zero_and_not_found_end_to_end(tmp_path, fake_llm):
    from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
    from arp.storage.run_store import RunStore

    def _f(name, kw):
        return FieldDefinition(
            name=name, description=name, data_type=FieldDataType.NUMBER, extraction_instructions=name, seed_keywords=[kw]
        )

    schema = DataPointSchema(name="Two", fields=[_f("spills", "spills"), _f("fines", "fines")])
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
        full_text="Spills: 0 incidents in FY2024. Regulatory fines are discussed in the legal section.",
    )
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME", fiscal_year_end="12-31")
    zero = ExtractionDraft(
        values=[PeriodValue(
            value=0, state="zero", raw_value_text="0", period_text="FY2024",
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Spills: 0 incidents in FY2024")],
        )],
        confidence=0.9,
    )
    agree = VerifierOutput(agrees=True, confidence=0.9, notes="ok")
    llm = fake_llm({"ExtractionDraft": [zero, ExtractionDraft(values=[], confidence=0.9)], "VerifierOutput": [agree, agree]})
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    run_id = create_extraction_run(schema, [company], settings, run_store, trial=True)
    await execute_extraction_run(
        run_id, schema, [company], llm=llm, registry=DocumentSourceRegistry([_FixedDocSource([doc])]),
        settings=settings, run_store=run_store,
    )
    (row,) = run_store.read_jsonl(run_store.results_path(run_id))
    assert [(f["value_state"], f["value"]) for f in row["fields"]] == [("zero", 0.0), ("not_found", None)]
    assert row["fields"][0]["period_end"] == "2024-12-31" and row["fields"][0]["qualifiers"] == []
    assert row["needs_review"] is False


async def test_review_key_uses_period_end(tmp_path, fake_llm):
    from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
    from arp.storage.run_store import RunStore

    schema = _schema()
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
        full_text="Green capex was 5 in FY2024 and 4 in some earlier time.",
    )
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME", fiscal_year_end="12-31")

    def _pv(v, period, quote):
        return PeriodValue(
            value=v, raw_value_text=str(v), period_text=period,
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)],
        )

    draft = ExtractionDraft(
        values=[_pv(5, "FY2024", "Green capex was 5 in FY2024"), _pv(4, "some earlier time", "4 in some earlier time")],
        confidence=0.9,
    )
    disagree = VerifierOutput(agrees=False, corrected_value=None, confidence=0.9, notes="wrong")
    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [disagree, disagree]})
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    run_id = create_extraction_run(schema, [company], settings, run_store, trial=True)
    await execute_extraction_run(
        run_id, schema, [company], llm=llm, registry=DocumentSourceRegistry([_FixedDocSource([doc])]),
        settings=settings, run_store=run_store,
    )
    rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    assert [(r["item_key"].rsplit(":", 1)[1], r["period_end"]) for r in rows] == [
        ("2024-12-31", "2024-12-31"), ("unspecified", None)
    ]
