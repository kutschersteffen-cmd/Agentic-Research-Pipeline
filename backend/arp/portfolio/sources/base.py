from __future__ import annotations

from abc import ABC, abstractmethod

from arp.schemas.portfolio import Holding


class PortfolioSource(ABC):
    """A source that can produce a dated holdings snapshot for one
    portfolio. Mirrors `ingestion.base.DocumentSource`'s shape rather than
    inventing a new connector pattern.

    Implementations: a real custodian/PMS API connector (decision 1), a
    CSV/XLSX fallback for manual overrides/backfills, or (for now)
    `mock_custodian.MockCustodianSource`.
    """

    name: str = "base"

    @abstractmethod
    async def fetch(self, portfolio_id: str, as_of_date: str) -> list[Holding]:
        raise NotImplementedError
