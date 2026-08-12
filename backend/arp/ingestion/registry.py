from __future__ import annotations

import logging

from arp.ingestion.base import DocumentSource
from arp.schemas.common import CompanyRef, DocType, SourceDocument

logger = logging.getLogger(__name__)


class DocumentSourceRegistry:
    """Fans a fetch out across multiple DocumentSources and de-dupes by content hash."""

    def __init__(self, sources: list[DocumentSource]) -> None:
        self.sources = sources

    async def fetch_all(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        seen_hashes: set[str] = set()
        results: list[SourceDocument] = []
        for source in self.sources:
            try:
                docs = await source.fetch(company, doc_types)
            except Exception as exc:  # noqa: BLE001 - one source failing shouldn't block the others
                logger.warning("Document source %s failed for %s: %s", source.name, company.company_id, exc)
                continue
            for doc in docs:
                if doc.sha256 and doc.sha256 in seen_hashes:
                    continue
                if doc.sha256:
                    seen_hashes.add(doc.sha256)
                results.append(doc)
        return results
