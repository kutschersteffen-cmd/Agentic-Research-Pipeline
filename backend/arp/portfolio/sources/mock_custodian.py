from __future__ import annotations

from arp.portfolio.sources.base import PortfolioSource
from arp.schemas.portfolio import Holding


class MockCustodianSource(PortfolioSource):
    """Stands in for a real custodian/PMS API connector (decision 1): the
    same `fetch(portfolio_id, as_of_date) -> Holding[]` shape a real
    connector would implement, backed by an in-memory dataset instead of
    an HTTP call.
    """

    name = "mock_custodian"

    def __init__(self, holdings_by_key: dict[tuple[str, str], list[Holding]]) -> None:
        self._holdings_by_key = holdings_by_key

    async def fetch(self, portfolio_id: str, as_of_date: str) -> list[Holding]:
        return list(self._holdings_by_key.get((portfolio_id, as_of_date), []))
