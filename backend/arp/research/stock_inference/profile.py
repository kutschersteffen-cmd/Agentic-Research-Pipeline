"""Step 2: profile each selected stock -- stored data, documents (with discovery) and one cited description."""

from __future__ import annotations

import asyncio
import logging
import re

from arp.config import Settings
from arp.db.session import require_dsn, transaction
from arp.extraction.pipeline import _extract_company
from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.stock_inference.schemas import InferStock, StockProfile
from arp.research.stock_inference.stored import match_company, stored_data
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import CompanyRef, DocumentChunk, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition

logger = logging.getLogger(__name__)

_KEYWORDS = ["segments", "products", "principal activities", "business overview", "services"]
DESCRIPTION_SCHEMA = DataPointSchema(
    name="Business description",
    fields=[FieldDefinition(
        name="business_description",
        description="The company's main business segments, products and services, as the company states them.",
        data_type=FieldDataType.STRING, seed_keywords=_KEYWORDS,
        extraction_instructions="Summarize the business as the company itself describes it, in 2-4 sentences.",
    )],
)


def _ref(stock: InferStock) -> CompanyRef:
    # sources reject ids failing safe_id ("NEL NO"); the run JSON keeps the original id
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stock.company_id).strip("._-")[:128]
    return CompanyRef(company_id=safe, name=stock.name, ticker=stock.ticker, isin=stock.isin,
                      lei=stock.lei, cik=stock.cik)


def description_chunks(documents: list[SourceDocument]) -> list[DocumentChunk]:
    """The 8 chunks of these documents that best match the description query."""
    chunks = [c for d in documents for c in chunk_document(d, keywords=_KEYWORDS)]
    return select_relevant_chunks(chunks, _KEYWORDS, max_chunks=8, require_hit=False, fallback_to_all=True)


async def discover_missing(stocks: list[InferStock], settings: Settings) -> None:
    from arp.discovery.pipeline import run_discovery
    from arp.storage.run_store import RunStore

    run_store = RunStore(require_dsn(settings), settings.runs_dir)
    await run_discovery([_ref(s) for s in stocks], settings=settings, run_store=run_store)


async def profile_stock(
    stock: InferStock, *, documents: list[SourceDocument], registry: DocumentSourceRegistry, llm, verifier_llm,
    settings: Settings, field_limit: asyncio.Semaphore, extract=_extract_company,
) -> tuple[StockProfile, list[DocumentChunk]]:
    profile = StockProfile(company_id=stock.company_id, name=stock.name, weight=stock.weight, isin=stock.isin,
                           sedol=stock.sedol)
    if not documents:
        return profile.model_copy(update={"error": "no_document"}), []
    try:
        chunks = description_chunks(documents)
        result = await extract(_ref(stock), DESCRIPTION_SCHEMA, registry=registry, llm=llm, verifier_llm=verifier_llm,
                               settings=settings, documents=documents, field_limit=field_limit)
        field = result.record.fields[0]
        if field.value is None or not str(field.value).strip():
            return profile.model_copy(update={"error": "not_found"}), chunks
        grounded = ground_citations(field.citations, {d.doc_id: d for d in documents},
                                    settings.grounding_fuzzy_threshold)
        citation = next((c for c in grounded if c.grounded), None)
        if citation is None:
            return profile.model_copy(update={"error": "ungrounded_quote"}), chunks
        return profile.model_copy(update={"description": str(field.value), "citation": citation}), chunks
    except Exception as e:
        return profile.model_copy(update={"error": f"{type(e).__name__}: {e}"}), []


async def profile_all(
    stocks: list[InferStock], *, registry: DocumentSourceRegistry, llm, verifier_llm, settings: Settings,
    discover=discover_missing, extract=_extract_company, session_factory=None, segments: dict,
) -> tuple[list[StockProfile], dict[str, list[DocumentChunk]]]:
    with (session_factory or (lambda: transaction(settings.postgres_dsn)))() as session:
        stored = {}
        for s in stocks:
            cid = match_company(session, s)
            stored[s.company_id] = {**stored_data(session, s, cid, segments), "db_match": str(cid) if cid else "none"}
    docs = dict(zip([s.company_id for s in stocks],
                    await asyncio.gather(*(registry.fetch_all(_ref(s)) for s in stocks)), strict=True))
    missing = [s for s in stocks if not docs[s.company_id]]
    if missing:
        try:
            await discover(missing, settings)
        except Exception as e:  # one failing discovery never ends the run: these stocks become no_document
            logger.warning("Discovery failed for %d stocks: %s", len(missing), e)
        for s, found in zip(missing, await asyncio.gather(*(registry.fetch_all(_ref(s)) for s in missing)), strict=True):
            docs[s.company_id] = found
    field_limit = asyncio.Semaphore(settings.max_concurrent_llm_calls)
    results = await asyncio.gather(*(
        profile_stock(s, documents=docs[s.company_id], registry=registry, llm=llm, verifier_llm=verifier_llm,
                      settings=settings, field_limit=field_limit, extract=extract)
        for s in stocks
    ))
    profiles = [p.model_copy(update=stored[p.company_id]) for p, _ in results]
    return profiles, {p.company_id: c for p, c in results}
