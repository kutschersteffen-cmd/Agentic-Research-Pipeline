from __future__ import annotations

from abc import ABC, abstractmethod

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import NewsItem


class NewsSource(ABC):
    """A source that can produce company-specific news articles. Mirrors
    `ingestion.base.DocumentSource` deliberately -- same
    fetch-one-company-at-a-time shape -- rather than inventing a new
    ingestion pattern for decision 4's news-feed requirement.

    Implementations: a real news API/vendor connector, or (for now)
    `mock_source.MockNewsSource`.
    """

    name: str = "base"

    @abstractmethod
    async def fetch(self, company: CompanyRef, since: str | None = None) -> list[NewsItem]:
        raise NotImplementedError
