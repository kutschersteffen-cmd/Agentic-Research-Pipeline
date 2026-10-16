from arp.extraction.extractor_agent import ExtractionDraft, FieldDraft, GroupDraft, PeriodValue, extract_group
from arp.extraction.field_graph import merge_evidence
from arp.extraction.pipeline import _extract_company
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, DocumentChunk, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from tests.test_extraction_pipeline import _FixedDocSource, _settings

_DOC = SourceDocument(
    company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
    full_text="Spills: 7 incidents in FY2024.\n\nFines: 3 penalties in FY2024.\n\nWater: 42 ML withdrawn in FY2024.",
)
_COMPANY = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
_AGREE = VerifierOutput(agrees=True, confidence=0.9, notes="ok")


def _field(name: str, high_risk=False) -> FieldDefinition:
    return FieldDefinition(
        field_id=name, name=name, description=name, data_type=FieldDataType.NUMBER, extraction_instructions=name,
        seed_keywords=[name], high_risk=high_risk,
    )


def _draft(value, quote) -> ExtractionDraft:
    return ExtractionDraft(values=[PeriodValue(
        value=value, raw_value_text=str(value), period_text="FY2024",
        citations=[Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=quote)],
    )], confidence=0.9)


_SPILLS, _FINES, _WATER = _draft(7, "Spills: 7 incidents"), _draft(3, "Fines: 3 penalties"), _draft(42, "Water: 42 ML")


async def _run(fake_llm, tmp_path, script, *, size=3, fields=("spills", "fines", "water"), llm_cls=None):
    llm = (llm_cls or fake_llm)(script)
    settings = _settings(tmp_path).model_copy(update={"extraction_group_size": size, "max_concurrent_llm_calls": 1})
    schema = DataPointSchema(name="S", fields=[_field(f) for f in fields])
    result = await _extract_company(
        _COMPANY, schema, registry=DocumentSourceRegistry([_FixedDocSource([_DOC])]), llm=llm, settings=settings,
    )
    return {f.field_id: f for f in result.record.fields}, llm, result


async def test_one_call_extracts_the_group_and_each_field_is_still_verified(fake_llm, tmp_path):
    group = GroupDraft(fields=[FieldDraft(field_id="spills", draft=_SPILLS), FieldDraft(field_id="fines", draft=_FINES),
                               FieldDraft(field_id="water", draft=_WATER)])
    fields, llm, _ = await _run(fake_llm, tmp_path, {"GroupDraft": [group], "VerifierOutput": [_AGREE] * 3})
    assert llm.calls == ["GroupDraft", "VerifierOutput", "VerifierOutput", "VerifierOutput"]
    assert {k: (f.value, f.grounded) for k, f in fields.items()} == {
        "spills": (7.0, True), "fines": (3.0, True), "water": (42.0, True),
    }
    assert "field_id: spills" in llm.prompts[0] and "field_id: water" in llm.prompts[0]


async def test_a_field_the_group_call_left_out_is_extracted_on_its_own(fake_llm, tmp_path):
    group = GroupDraft(fields=[FieldDraft(field_id="spills", draft=_SPILLS), FieldDraft(field_id="nope", draft=_FINES)])
    fields, llm, _ = await _run(
        fake_llm, tmp_path, {"GroupDraft": [group], "ExtractionDraft": [_FINES], "VerifierOutput": [_AGREE] * 2},
        fields=("spills", "fines"),
    )
    assert sorted(llm.calls) == ["ExtractionDraft", "GroupDraft", "VerifierOutput", "VerifierOutput"]
    assert (fields["spills"].value, fields["fines"].value) == (7.0, 3.0)


async def test_a_failed_group_call_falls_back_to_one_call_per_field(fake_llm, tmp_path):
    class Failing(fake_llm):
        async def complete_structured(self, *, output_model, **kw):
            if output_model is GroupDraft:
                raise ValueError("no schema-valid answer")
            return await super().complete_structured(output_model=output_model, **kw)

    fields, llm, _ = await _run(
        fake_llm, tmp_path, {"ExtractionDraft": [_SPILLS, _FINES], "VerifierOutput": [_AGREE] * 2},
        fields=("spills", "fines"), llm_cls=Failing,
    )
    assert (fields["spills"].value, fields["fines"].value) == (7.0, 3.0)


async def test_high_risk_fields_and_grouping_off_keep_one_call_per_field(fake_llm, tmp_path):
    _, llm, _ = await _run(fake_llm, tmp_path, {"ExtractionDraft": [_SPILLS, _FINES], "VerifierOutput": [_AGREE] * 2},
                           size=0, fields=("spills", "fines"))
    assert "GroupDraft" not in llm.calls

    llm = fake_llm({"ExtractionDraft": [_SPILLS, _SPILLS, _FINES, _FINES]})  # high-risk: blind second extraction
    schema = DataPointSchema(name="S", fields=[_field("spills", True), _field("fines", True)])
    settings = _settings(tmp_path).model_copy(update={"extraction_group_size": 3, "max_concurrent_llm_calls": 1})
    await _extract_company(_COMPANY, schema, registry=DocumentSourceRegistry([_FixedDocSource([_DOC])]), llm=llm,
                           settings=settings)
    assert "GroupDraft" not in llm.calls


def _chunk(cid: str) -> DocumentChunk:
    return DocumentChunk(chunk_id=cid, doc_id="d", company_id="c", doc_type=DocType.OTHER, text=cid, char_start=0, char_end=1)


def test_merge_evidence_takes_each_fields_best_first_without_duplicates():
    a, b, c, d = map(_chunk, "abcd")
    assert [x.chunk_id for x in merge_evidence([[a, b, c], [d, a]], 10)] == ["a", "d", "b", "c"]
    assert [x.chunk_id for x in merge_evidence([[a, b, c], [d, a]], 2)] == ["a", "d"]
    assert merge_evidence([[], []], 5) == []


async def test_extract_group_drops_unknown_field_ids(fake_llm):
    group = GroupDraft(fields=[FieldDraft(field_id="spills", draft=_SPILLS), FieldDraft(field_id="other", draft=_FINES)])
    drafts, _ = await extract_group("Acme", [_field("spills")], [_chunk("a")], fake_llm({"GroupDraft": [group]}))
    assert list(drafts) == ["spills"]
