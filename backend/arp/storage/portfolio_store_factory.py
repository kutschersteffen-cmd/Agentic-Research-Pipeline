from __future__ import annotations

"""Single choke point for choosing PortfolioStore (file, default) vs.
PostgresPortfolioStore (opt-in, Settings.portfolio_backend == "postgres")
-- both the CLI and the API call this rather than duplicating the branch.
"""

from typing import TYPE_CHECKING

from arp.config import Settings
from arp.storage.portfolio_store import PortfolioStore

if TYPE_CHECKING:
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore


def build_portfolio_store(settings: Settings) -> "PortfolioStore | PostgresPortfolioStore":
    file_store = PortfolioStore(settings.portfolios_dir)
    if settings.portfolio_backend != "postgres":
        return file_store
    if not settings.postgres_dsn:
        raise RuntimeError(
            "portfolio_backend is 'postgres' but postgres_dsn is not set. Set ARP_POSTGRES_DSN, or set "
            "ARP_PORTFOLIO_BACKEND=file to use the default file-based store."
        )
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    return PostgresPortfolioStore(settings.postgres_dsn, file_store)
