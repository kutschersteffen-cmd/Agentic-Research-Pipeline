import pytest
from pydantic import BaseModel, ValidationError

from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.pipeline import _extract_company
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.llm.factory import build_llm_client
from arp.llm.langchain_client import LangChainAnthropicClient
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from tests.test_extraction_pipeline import _FixedDocSource, _schema, _settings


class _Out(BaseModel):
    x: int = 1


async def assert_llm_contract(client: LLMClient) -> None:
    """Any LLMClient must pass this: a validated output_model instance plus an LLMUsage naming its provider."""
    out, usage = await client.complete_structured(system="s", prompt="p", output_model=_Out)
    assert isinstance(out, _Out)
    assert isinstance(usage, LLMUsage)
    assert usage.provider


async def test_fake_client_passes_contract(fake_llm):
    await assert_llm_contract(fake_llm({"_Out": [_Out()]}))


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        Settings(llm_provider="vertex")


def test_factory_builds_anthropic(tmp_path):
    client = build_llm_client(Settings(anthropic_api_key="dummy", cache_dir=tmp_path))
    assert isinstance(client, LangChainAnthropicClient)


async def test_provenance_records_provider(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
        full_text="In fiscal 2025, we invested $120 million in green capex across our facilities.",
    )
    draft = ExtractionDraft(
        value=120.0, raw_value_text="$120 million in green capex",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="invested $120 million in green capex")],
        confidence=0.9,
    )
    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")]})
    result = await _extract_company(
        CompanyRef(company_id="c1", name="Acme", ticker="A"), _schema(),
        registry=DocumentSourceRegistry([_FixedDocSource([doc])]), llm=llm, settings=_settings(tmp_path),
    )
    assert result.record.fields[0].provenance.provider == "fake"
