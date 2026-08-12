from __future__ import annotations

from abc import ABC, abstractmethod

from arp.schemas.common import CompanyRef, DocType, SourceDocument


class DocumentSource(ABC):
    """A source that can produce SourceDocuments for a company.

    Implementations: SEC EDGAR (US filings), local file drop (anything the
    discovery crawler or the user placed under data/documents/), and any
    future paid connector (transcripts, AlphaSense, etc).
    """

    name: str = "base"

    @abstractmethod
    async def fetch(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        raise NotImplementedError
