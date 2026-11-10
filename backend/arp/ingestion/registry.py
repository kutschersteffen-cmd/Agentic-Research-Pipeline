from __future__ import annotations

import asyncio
import json
import logging
import re
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


class KeptFileMissing(Exception):
    """A kept file no source returned because a source failed as a whole: the company fails, not as a document problem."""


class KeptDocuments:
    """A document registry that hands a listed company only its kept documents (by content key); every other
    company, and everything but `fetch_all`, is the wrapped registry's. `names`: content key -> file name, for the
    error that names a kept file the run could not read."""

    def __init__(self, inner, only: dict[str, set[str]], names: dict[str, str] | None = None) -> None:
        self.inner, self.only, self.names = inner, only, names or {}

    async def fetch_all(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        keep = self.only.get(company.company_id)
        if keep is None:
            return await self.inner.fetch_all(company, doc_types)
        docs, failed = await self._fetch(company, doc_types)
        # the kept files first, then the dedup among them: the registry dedups on the text's hash, the kept list holds
        # the files' byte hashes, so its dedup could drop a kept file for another with the same text
        kept, seen = [], set()
        for d in docs:
            if d.content_key in keep and not (d.sha256 and d.sha256 in seen):
                seen.add(d.sha256)
                kept.append(d)
        for d in kept:
            if not _IMAGE.sub("", d.full_text).strip():
                raise UnreadableDocument(f"No text could be read from {Path(d.local_path).name if d.local_path else d.title}")
        # a kept file that failed to parse, or had no text, is left out of the fetch (logged, not raised);
        # a doc-type fetch leaves some out on purpose
        missing = sorted(keep - {d.content_key for d in docs}) if doc_types is None else []
        if missing:
            name = self.names.get(missing[0], "a kept file")
            if failed:  # a whole source failed: the file may be fine, so no Replace file
                raise KeptFileMissing(f"Kept file not found: {name}")
            raise UnreadableDocument(f"No text could be read from {name}")
        settings = getattr(self.inner, "settings", None)
        if kept and isinstance(settings, Settings) and isinstance(getattr(self.inner, "sources", None), list) and (
                settings.doc_tree_enabled or settings.tree_context_enabled):
            await self.inner._build_trees(kept)  # the registry's own fetch_all would have, had it been called
        return kept

    async def _fetch(self, company: CompanyRef, doc_types: list[DocType] | None) -> tuple[list[SourceDocument], list[str]]:
        """Every source's documents, undeduplicated, and the names of the sources that failed as a whole."""
        sources = getattr(self.inner, "sources", None)
        if not isinstance(sources, list):  # a registry without sources (tests): its own fetch
            return await self.inner.fetch_all(company, doc_types), []
        fetched = await asyncio.gather(*(s.fetch(company, doc_types) for s in sources), return_exceptions=True)
        docs, failed = [], []
        for source, got in zip(sources, fetched, strict=True):
            if isinstance(got, BaseException):
                logger.warning("Document source %s failed for %s: %s", source.name, company.company_id, got)
                failed.append(source.name)
            else:
                docs.extend(got)
        return docs, failed

    def __getattr__(self, name):
        return getattr(self.inner, name)


_IMAGE = re.compile(r"<!--\s*image\s*-->")  # Docling's markdown for a picture: no text the run could read
KEPT_NAMES = "kept_names.json"  # in a run's folder: content key -> file name of the kept files


def read_only_documents(run_dir: Path) -> dict[str, set[str]] | None:
    path = run_dir / ONLY_DOCUMENTS
    return {k: set(v) for k, v in json.loads(path.read_text()).items()} if path.is_file() else None


def read_kept_names(run_dir: Path) -> dict[str, str]:
    path = run_dir / KEPT_NAMES
    return json.loads(path.read_text()) if path.is_file() else {}


def for_run(registry, run_dir: Path):
    """The registry a run reads through: limited to its kept documents when it was started from Argus."""
    only = read_only_documents(run_dir)
    return registry if only is None else KeptDocuments(registry, only, read_kept_names(run_dir))
