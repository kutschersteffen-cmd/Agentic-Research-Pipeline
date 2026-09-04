from arp.config import Settings
from arp.discovery.site_finder import SearchResult, WebSearchClient
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.rd_exposure.news_scoring import _AssessmentList, _ResultAssessment
from arp.research.rd_exposure.resolver import (
    RDResolverContext,
    resolve_company_activity_rd_exposure,
    resolve_news_mentions,
    resolve_rd_intensity,
)
from arp.schemas.common import CompanyRef, Citation, DocType, SourceDocument
from arp.schemas.thematic import ActivityDefinition, LifecycleStage


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


class _FixedSearchClient(WebSearchClient):
    def __init__(self, results):
        self._results = results

    async def search(self, query, max_results=5):
        return self._results


class _FailingSearchClient(WebSearchClient):
    async def search(self, query, max_results=5):
        raise RuntimeError("search unavailable")


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


def _activity(lifecycle_stage=None, core_isic_codes=None) -> ActivityDefinition:
    return ActivityDefinition(
        name="Solid-state batteries",
        in_scope_description="Development of solid-state battery technology for EVs.",
        out_of_scope_description="",
        seed_keywords=["solid-state battery"],
        lifecycle_stage=lifecycle_stage,
        core_isic_codes=core_isic_codes or [],
    )


# --- resolve_company_activity_rd_exposure: lifecycle-stage gating -----------

async def test_returns_none_when_lifecycle_stage_not_set(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Motors")
    llm = fake_llm({})
    ctx = RDResolverContext(registry=DocumentSourceRegistry([]), settings=_settings(tmp_path))
    result, usage = await resolve_company_activity_rd_exposure(
        company, _activity(lifecycle_stage=None), None, documents=[], ctx=ctx, llm=llm
    )
    assert result is None
    assert usage.input_tokens == 0
    assert llm.calls == []


async def test_returns_none_for_mature_activity(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Motors")
    llm = fake_llm({})
    ctx = RDResolverContext(registry=DocumentSourceRegistry([]), settings=_settings(tmp_path))
    result, _usage = await resolve_company_activity_rd_exposure(
        company, _activity(lifecycle_stage=LifecycleStage.MATURE), None, documents=[], ctx=ctx, llm=llm
    )
    assert result is None
    assert llm.calls == []


async def test_resolves_for_ideation_stage_activity(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Motors")
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])
    llm = fake_llm({})  # no evidence -> no extraction call; no search client -> no news call
    ctx = RDResolverContext(registry=registry, settings=_settings(tmp_path))

    result, _usage = await resolve_company_activity_rd_exposure(
        company, _activity(lifecycle_stage=LifecycleStage.IDEATION), None, documents=[doc], ctx=ctx, llm=llm
    )
    assert result is not None
    assert result.rd_intensity.source == "unresolved"
    assert result.news_mentions.source == "unresolved"
    assert result.sector_relevant is True  # no company_isic/core_isic_codes -> defaults relevant


# --- resolve_company_activity_rd_exposure: sector-relevance gate ------------

async def test_irrelevant_sector_skips_rd_intensity_extraction(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Retail")
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We are investing heavily in solid-state batteries.")
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])
    llm = fake_llm({})  # company_isic="45" (retail) doesn't overlap "27" -- extraction must be skipped
    ctx = RDResolverContext(registry=registry, settings=_settings(tmp_path))

    result, _usage = await resolve_company_activity_rd_exposure(
        company, _activity(lifecycle_stage=LifecycleStage.IDEATION, core_isic_codes=["27"]), "45", documents=[doc], ctx=ctx, llm=llm
    )
    assert result.sector_relevant is False
    assert result.rd_intensity.source == "unresolved"
    assert llm.calls == []


# --- resolve_rd_intensity ----------------------------------------------------

async def test_resolve_rd_intensity_finds_explicit_percentage(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Acme Motors")
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K",
        full_text="We invested 14% of revenue in R&D last year, primarily on our solid-state battery program.",
    )
    quote = "We invested 14% of revenue in R&D last year"
    draft = ExtractionDraft(value=14.0, raw_value_text=quote, citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], confidence=0.8)
    verifier = VerifierOutput(agrees=True, confidence=0.75, notes="Matches evidence.")
    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result, usage = await resolve_rd_intensity(company, _activity(), documents=[doc], registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.source == "extracted"
    assert result.value_pct == 0.14
    assert result.citation is not None and result.citation.grounded is True
    assert usage.input_tokens > 0


async def test_resolve_rd_intensity_no_evidence_is_unresolved(tmp_path, fake_llm):
    company = CompanyRef(company_id="c1", name="Shoe Co")
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    llm = fake_llm({"ExtractionDraft": [ExtractionDraft(value=None, confidence=0.0, citations=[])], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.0, notes="")]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result, _usage = await resolve_rd_intensity(company, _activity(), documents=[doc], registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.source == "unresolved"


# --- resolve_news_mentions ----------------------------------------------------

async def test_resolve_news_mentions_no_search_client_is_unresolved(fake_llm):
    llm = fake_llm({})
    result, usage = await resolve_news_mentions(CompanyRef(company_id="c1", name="Acme Motors"), _activity(), search_client=None, llm=llm)
    assert result.source == "unresolved"
    assert usage.input_tokens == 0
    assert llm.calls == []


async def test_resolve_news_mentions_no_results_found(fake_llm):
    llm = fake_llm({})  # empty result list short-circuits before any LLM call
    result, _usage = await resolve_news_mentions(
        CompanyRef(company_id="c1", name="Acme Motors"), _activity(), search_client=_FixedSearchClient([]), llm=llm
    )
    assert result.source == "news"
    assert result.value_pct == 0.0
    assert llm.calls == []


async def test_resolve_news_mentions_scores_and_cites_relevant_results(fake_llm):
    results = [
        SearchResult(title="Acme Motors solid-state battery breakthrough", url="https://example.com/1", snippet="New breakthrough."),
        SearchResult(title="Acme Motors annual shareholder meeting notice", url="https://example.com/2", snippet="Routine notice."),
    ]
    draft = _AssessmentList(
        assessments=[
            _ResultAssessment(result_index=0, relevant=True, rationale="Breakthrough."),
            _ResultAssessment(result_index=1, relevant=False, rationale="Unrelated."),
        ]
    )
    llm = fake_llm({_AssessmentList.__name__: [draft]})
    result, usage = await resolve_news_mentions(
        CompanyRef(company_id="c1", name="Acme Motors"), _activity(), search_client=_FixedSearchClient(results), llm=llm
    )
    assert result.source == "news"
    assert result.value_pct == 0.5
    assert "https://example.com/1" in result.notes
    assert usage.input_tokens > 0


async def test_resolve_news_mentions_search_failure_is_unresolved(fake_llm):
    llm = fake_llm({})
    result, usage = await resolve_news_mentions(
        CompanyRef(company_id="c1", name="Acme Motors"), _activity(), search_client=_FailingSearchClient(), llm=llm
    )
    assert result.source == "unresolved"
    assert usage.input_tokens == 0
    assert llm.calls == []
