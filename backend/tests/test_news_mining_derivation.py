import pytest

from arp.discovery.site_finder import SearchResult
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.taxonomy_sources.corpus_synthesis import _SynthesizedActivityDraft, _SynthesizedActivityDraftList
from arp.research.taxonomy_sources.news_mining import (
    build_theme_from_news_and_transcripts,
    gather_corpus_from_news,
    gather_corpus_from_transcripts,
)
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.taxonomy_sources import CorpusSourceType


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


async def test_gather_corpus_from_news_dedupes_across_queries(fake_search):
    result = SearchResult(title="Electrification boom", url="https://news.example.com/a", snippet="Grid demand rising.")
    search = fake_search({"companies news": [result], "market trends": [result]})

    corpus = await gather_corpus_from_news("Electrification", search)
    assert len(corpus) == 1
    assert corpus[0].source_type == CorpusSourceType.NEWS
    assert "Grid demand rising" in corpus[0].text


async def test_gather_corpus_from_transcripts_only_returns_keyword_hits():
    on_topic = SourceDocument(
        company_id="c1", doc_type=DocType.EARNINGS_TRANSCRIPT, title="Q1 call",
        full_text="Analyst: tell us about electrification investments this quarter.",
    )
    off_topic = SourceDocument(
        company_id="c1", doc_type=DocType.EARNINGS_TRANSCRIPT, title="Q2 call", full_text="We had a great quarter for snack sales.",
    )
    registry = DocumentSourceRegistry([_FixedDocSource([on_topic, off_topic])])
    companies = [CompanyRef(company_id="c1", name="Acme Co")]

    corpus = await gather_corpus_from_transcripts(companies, registry, keywords=["electrification"])
    assert len(corpus) == 1
    assert "electrification" in corpus[0].text.lower()
    assert corpus[0].source_type == CorpusSourceType.TRANSCRIPT


async def test_build_theme_requires_at_least_one_source(fake_llm):
    llm = fake_llm({})
    with pytest.raises(ValueError):
        await build_theme_from_news_and_transcripts("Electrification", "desc", llm)


async def test_build_theme_from_news_and_transcripts_combines_both(fake_llm, fake_search):
    result = SearchResult(title="Electrification boom", url="https://news.example.com/a", snippet="Grid demand rising.")
    search = fake_search({"companies news": [result]})

    transcript = SourceDocument(
        company_id="c1", doc_type=DocType.EARNINGS_TRANSCRIPT, title="Q1 call", full_text="We are investing heavily in electrification.",
    )
    registry = DocumentSourceRegistry([_FixedDocSource([transcript])])
    companies = [CompanyRef(company_id="c1", name="Acme Co")]

    draft = _SynthesizedActivityDraftList(
        activities=[_SynthesizedActivityDraft(name="Grid investment", in_scope_description="x", out_of_scope_description="y")],
        corpus_assessment="Combined news + transcript signal.",
    )
    llm = fake_llm({_SynthesizedActivityDraftList.__name__: [draft]})

    theme, notes, _usage = await build_theme_from_news_and_transcripts(
        "Electrification", "desc", llm, search_client=search, companies=companies, registry=registry
    )
    assert theme.activities[0].name == "Grid investment"
    assert "1 news" in notes
    assert "1 transcript" in notes
