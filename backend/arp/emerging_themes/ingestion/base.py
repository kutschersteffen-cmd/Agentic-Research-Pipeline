from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from arp.schemas.emerging_themes import RawMention


class MentionSource(ABC):
    """A universe-wide, keyword/firehose-driven source of raw mentions.

    Deliberately not shaped like `portfolio/news/mock_source.py`'s
    `fetch(company, since)`, which assumes the caller already knows which
    company to ask about. These sources are the opposite -- EDGAR
    full-text search, GDELT, and regulatory RSS all return whatever
    matches a query or feed across the whole market, with company
    identity resolved *after* ingestion (see
    `emerging_themes/entity_resolution.py`), not supplied up front.
    """

    name: str = "base"

    @abstractmethod
    async def fetch(self, since: datetime) -> list[RawMention]:
        raise NotImplementedError
