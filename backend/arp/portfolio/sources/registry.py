from __future__ import annotations

import logging

from arp.portfolio.sources.base import PortfolioSource
from arp.schemas.portfolio import Holding

logger = logging.getLogger(__name__)


class PortfolioSourceRegistry:
    """Fans a fetch out across multiple PortfolioSources for one snapshot,
    mirroring `ingestion.registry.DocumentSourceRegistry`: the first source
    to return a non-empty snapshot wins, and one source failing (e.g. the
    primary custodian API is briefly down) never blocks a fallback source
    from still producing a snapshot.
    """

    def __init__(self, sources: list[PortfolioSource]) -> None:
        self.sources = sources

    async def fetch(self, portfolio_id: str, as_of_date: str) -> list[Holding]:
        for source in self.sources:
            try:
                holdings = await source.fetch(portfolio_id, as_of_date)
            except Exception as exc:  # noqa: BLE001 - one source failing shouldn't block a fallback
                logger.warning("Portfolio source %s failed for %s/%s: %s", source.name, portfolio_id, as_of_date, exc)
                continue
            if holdings:
                return holdings
        return []
