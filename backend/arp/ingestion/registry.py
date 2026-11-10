from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from arp.config import Settings
from arp.ingestion.base import DocumentSource
from arp.schemas.common import CompanyRef, DocType, SourceDocument

logger = logging.getLogger(__name__)


class DocumentSourceRegistry:
    """Fans a fetch out across multiple DocumentSources and de-dupes by content hash."""

    def __init__(self, sources: list[DocumentSource], settings: Settings | None = None) -> None:
        """`settings` with `doc_tree_enabled` or `tree_context_enabled`: every fetched document's tree is built (or read) once fetched."""
        self.sources = sources
        self.settings = settings

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
        if self.settings is not None and (self.settings.doc_tree_enabled or self.settings.tree_context_enabled):
            await self._build_trees(results)
        return results

    async def _build_trees(self, docs: list[SourceDocument]) -> None:
        from arp.ingestion.doc_tree import build_doc_tree

        for doc in docs:
            try:
                await asyncio.to_thread(build_doc_tree, doc, self.settings)
            except Exception:  # noqa: BLE001 - the tree is optional; the fetch still succeeds
                logger.warning("Document tree failed for %s", doc.doc_id, exc_info=True)


ONLY_DOCUMENTS = "only_documents.json"  # in a run's folder: company id -> the content keys it may read (Argus step 2)


class UnreadableDocument(Exception):
    """A kept document with no text: the company fails, and the error row marks it as a document problem."""

    document_problem = True


class KeptDocuments:
    """A document registry that hands a listed company only its kept documents (by content key); every other
    company, and everything but `fetch_all`, is the wrapped registry's."""

    def __init__(self, inner, only: dict[str, set[str]]) -> None:
        self.inner, self.only = inner, only

    async def fetch_all(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        docs = await self.inner.fetch_all(company, doc_types)
        keep = self.only.get(company.company_id)
        if keep is None:
            return docs
        kept = [d for d in docs if d.content_key in keep]
        for d in kept:
            if not d.full_text.strip():
                raise UnreadableDocument(f"No text could be read from {Path(d.local_path).name if d.local_path else d.title}")
        return kept

    def __getattr__(self, name):
        return getattr(self.inner, name)


def read_only_documents(run_dir: Path) -> dict[str, set[str]] | None:
    path = run_dir / ONLY_DOCUMENTS
    return {k: set(v) for k, v in json.loads(path.read_text()).items()} if path.is_file() else None


def for_run(registry, run_dir: Path):
    """The registry a run reads through: limited to its kept documents when it was started from Argus."""
    only = read_only_documents(run_dir)
    return registry if only is None else KeptDocuments(registry, only)
