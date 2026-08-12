from __future__ import annotations

from arp.discovery.site_finder import WebSearchClient
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.research.taxonomy_sources.corpus_synthesis import synthesize_activities_from_corpus
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.taxonomy_sources import CorpusSnippet, CorpusSourceType
from arp.schemas.thematic import ThemeDefinition

_NEWS_QUERY_TEMPLATES = [
    "{theme} companies news",
    "{theme} market trends",
    "{theme} industry outlook",
]


async def gather_corpus_from_news(
    theme_name: str, search_client: WebSearchClient, max_results: int = 15
) -> list[CorpusSnippet]:
    """News search gives current, real-world vocabulary for a theme --
    the same instinct as the academic keyword-discovery methods this
    system already leans on (see docs/METHODOLOGY.md), applied to recent
    news instead of transcripts."""
    corpus: list[CorpusSnippet] = []
    seen_urls: set[str] = set()
    for template in _NEWS_QUERY_TEMPLATES:
        results = await search_client.search(template.format(theme=theme_name), max_results=6)
        for r in results:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            text = f"{r.title}\n{r.snippet}" if r.snippet else r.title
            corpus.append(CorpusSnippet(text=text, source_type=CorpusSourceType.NEWS, source_ref=r.url))
    return corpus[:max_results]


async def gather_corpus_from_transcripts(
    companies: list[CompanyRef],
    registry: DocumentSourceRegistry,
    keywords: list[str],
    max_chunks_per_company: int = 5,
) -> list[CorpusSnippet]:
    """Keyword-in-context mining of any earnings-call transcripts already
    available for the supplied companies (Sautner et al.-style), reusing
    the same chunking/keyword-hit machinery the thematic pipeline uses for
    evidence retrieval."""
    corpus: list[CorpusSnippet] = []
    for company in companies:
        docs = await registry.fetch_all(company, doc_types=[DocType.EARNINGS_TRANSCRIPT])
        for doc in docs:
            chunks = chunk_document(doc, keywords=keywords)
            hits = [c for c in chunks if c.keyword_hits][:max_chunks_per_company]
            for chunk in hits:
                corpus.append(
                    CorpusSnippet(text=chunk.text, source_type=CorpusSourceType.TRANSCRIPT, source_ref=f"{company.company_id}:{doc.doc_id}")
                )
    return corpus


async def build_theme_from_news_and_transcripts(
    theme_name: str,
    theme_description: str,
    llm: LLMClient,
    *,
    search_client: WebSearchClient | None = None,
    companies: list[CompanyRef] | None = None,
    registry: DocumentSourceRegistry | None = None,
) -> tuple[ThemeDefinition, str, LLMUsage]:
    corpus: list[CorpusSnippet] = []
    if search_client is not None:
        corpus.extend(await gather_corpus_from_news(theme_name, search_client))
    if companies and registry is not None:
        corpus.extend(await gather_corpus_from_transcripts(companies, registry, keywords=[theme_name]))

    if not corpus:
        raise ValueError("No news or transcript corpus could be gathered -- pass a search client and/or companies with available transcripts.")

    activities, assessment, usage = await synthesize_activities_from_corpus(theme_name, theme_description, corpus, llm)
    theme = ThemeDefinition(name=theme_name, description=theme_description, activities=activities)
    news_count = sum(1 for s in corpus if s.source_type == CorpusSourceType.NEWS)
    transcript_count = sum(1 for s in corpus if s.source_type == CorpusSourceType.TRANSCRIPT)
    notes = f"Derived from {news_count} news snippet(s) and {transcript_count} transcript passage(s). {assessment}"
    return theme, notes, usage
