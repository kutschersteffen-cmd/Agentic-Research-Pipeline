from __future__ import annotations

from arp.config import Settings
from arp.extraction.pipeline import _extract_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.cost_tracker import combine_usage
from arp.research.taxonomy_sources.corpus_synthesis import synthesize_activities_from_corpus
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.taxonomy_sources import CorpusSnippet, CorpusSourceType
from arp.schemas.thematic import ThemeDefinition


def _activity_description_schema(theme_name: str, theme_description: str) -> DataPointSchema:
    field = FieldDefinition(
        name="primary_business_activities",
        description=f"A description of the company's primary business activities, especially anything related to: {theme_name} ({theme_description})",
        data_type=FieldDataType.STRING,
        extraction_instructions=(
            "Summarize the company's stated primary business segments or activities in 2-4 sentences, based on "
            "its own disclosures. Give particular weight to anything plausibly related to the theme described "
            "above, but describe the business as actually stated -- don't editorialize about theme relevance."
        ),
        seed_keywords=[theme_name],
    )
    return DataPointSchema(name="Business activity description", fields=[field])


async def gather_corpus_from_extraction(
    theme_name: str,
    theme_description: str,
    companies: list[CompanyRef],
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
    sample_size: int = 25,
) -> tuple[list[CorpusSnippet], LLMUsage]:
    """Runs the Extraction Engine's own per-company extractor/verifier
    pipeline over a sample of the universe to pull a real, cited
    description of what each company actually does, then hands those
    descriptions to corpus_synthesis as the empirical bottom-up material.
    """
    schema = _activity_description_schema(theme_name, theme_description)
    sample = companies[:sample_size]
    corpus: list[CorpusSnippet] = []
    total_usage = LLMUsage()
    for company in sample:
        result = await _extract_company(company, schema, registry=registry, llm=llm, settings=settings)
        total_usage = combine_usage(total_usage, result.usage)
        field = result.record.fields[0] if result.record.fields else None
        if field and field.value:
            corpus.append(
                CorpusSnippet(text=str(field.value), source_type=CorpusSourceType.EXTRACTION_ENGINE, source_ref=company.company_id)
            )
    return corpus, total_usage


async def build_theme_empirical(
    theme_name: str,
    theme_description: str,
    companies: list[CompanyRef],
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    settings: Settings,
    sample_size: int = 25,
) -> tuple[ThemeDefinition, str, LLMUsage]:
    corpus, extract_usage = await gather_corpus_from_extraction(
        theme_name, theme_description, companies, registry, llm, settings, sample_size
    )
    if not corpus:
        raise ValueError("No usable business-activity descriptions were extracted from the sample universe.")

    activities, assessment, synth_usage = await synthesize_activities_from_corpus(theme_name, theme_description, corpus, llm)
    theme = ThemeDefinition(name=theme_name, description=theme_description, activities=activities)
    sampled = min(sample_size, len(companies))
    notes = f"Empirically derived from {len(corpus)}/{sampled} sampled companies' extracted business-activity descriptions. {assessment}"
    return theme, notes, combine_usage(extract_usage, synth_usage)
