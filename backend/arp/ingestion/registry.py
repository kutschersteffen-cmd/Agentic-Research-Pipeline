from __future__ import annotations

import asyncio
import logging

from arp.ingestion.base import DocumentSource
from arp.schemas.common import CompanyRef, DocType, SourceDocument

logger = logging.getLogger(__name__)


class DocumentSourceRegistry:
    """Fans a fetch out across multiple DocumentSources and de-dupes by content hash."""

    def __init__(self, sources: list[DocumentSource]) -> None:
        self.sources = sources

    async def fetch_all(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        """The sources are independent network fetches, so they run concurrently:
        this is the first await of both _extract_company and _match_company, so
        every company used to pay the sum of source latencies rather than the max.
        Results are still walked in source order, keeping the dedup deterministic,
        and return_exceptions preserves the per-source failure isolation below.
        """
        fetched = await asyncio.gather(
            *(source.fetch(company, doc_types) for source in self.sources),
            return_exceptions=True,
        )
        seen_hashes: set[str] = set()
        results: list[SourceDocument] = []
        for source, docs in zip(self.sources, fetched, strict=True):
            if isinstance(docs, BaseException):  # one source failing shouldn't block the others
                logger.warning("Document source %s failed for %s: %s", source.name, company.company_id, docs)
                continue
            for doc in docs:
                if doc.sha256 and doc.sha256 in seen_hashes:
                    continue
                if doc.sha256:
                    seen_hashes.add(doc.sha256)
                results.append(doc)
        return results
