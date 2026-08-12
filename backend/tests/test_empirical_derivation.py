import pytest

from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.taxonomy_sources.corpus_synthesis import _SynthesizedActivityDraft, _SynthesizedActivityDraftList
from arp.research.taxonomy_sources.empirical import build_theme_empirical, gather_corpus_from_extraction
from arp.schemas.common import CompanyRef, DocType, SourceDocument


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs_by_company):
        self._docs_by_company = docs_by_company

    async def fetch(self, company, doc_types=None):
        return self._docs_by_company.get(company.company_id, [])


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


async def test_gather_corpus_from_extraction_skips_companies_with_no_value(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We make EV batteries for the electrification of transport.")
    registry = DocumentSourceRegistry([_FixedDocSource({"c1": [doc], "c2": []})])
    companies = [
        CompanyRef(company_id="c1", name="Acme Batteries"),
        CompanyRef(company_id="c2", name="Acme Nothing"),
    ]

    draft = ExtractionDraft(value="Manufactures EV battery packs.", citations=[], confidence=0.8)
    verifier = VerifierOutput(agrees=True, confidence=0.8, notes="matches evidence")
    llm = fake_llm({ExtractionDraft.__name__: [draft], VerifierOutput.__name__: [verifier]})

    corpus, usage = await gather_corpus_from_extraction("Electrification", "desc", companies, registry, llm, _settings(tmp_path))
    assert len(corpus) == 1
    assert corpus[0].source_ref == "c1"
    assert "battery" in corpus[0].text.lower()


async def test_build_theme_empirical_end_to_end(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We make EV batteries for the electrification of transport.")
    registry = DocumentSourceRegistry([_FixedDocSource({"c1": [doc]})])
    companies = [CompanyRef(company_id="c1", name="Acme Batteries")]

    extraction_draft = ExtractionDraft(value="Manufactures EV battery packs.", citations=[], confidence=0.8)
    verifier = VerifierOutput(agrees=True, confidence=0.8, notes="ok")
    synthesis_draft = _SynthesizedActivityDraftList(
        activities=[_SynthesizedActivityDraft(name="EV battery manufacturing", in_scope_description="x", out_of_scope_description="y")],
        corpus_assessment="One company, thin but usable.",
    )
    llm = fake_llm(
        {
            ExtractionDraft.__name__: [extraction_draft],
            VerifierOutput.__name__: [verifier],
            _SynthesizedActivityDraftList.__name__: [synthesis_draft],
        }
    )

    theme, notes, usage = await build_theme_empirical("Electrification", "desc", companies, registry, llm, _settings(tmp_path))
    assert theme.activities[0].name == "EV battery manufacturing"
    assert "1/1" in notes
    assert usage.input_tokens > 0


async def test_build_theme_empirical_raises_when_corpus_is_empty(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    registry = DocumentSourceRegistry([_FixedDocSource({"c1": [doc]})])
    companies = [CompanyRef(company_id="c1", name="Shoe Co")]

    # extraction with no keyword hits for the schema's seed keyword ("Electrification") -> no evidence -> null value
    llm = fake_llm({})
    with pytest.raises(ValueError):
        await build_theme_empirical("Electrification", "desc", companies, registry, llm, _settings(tmp_path))
