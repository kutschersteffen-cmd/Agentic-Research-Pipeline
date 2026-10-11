"""Single choke point for building the portfolio store (both the CLI and the API call this): the
Postgres store, which keeps observations/news/flags/rules in the wrapped file-based PortfolioStore."""

from __future__ import annotations

from arp.config import Settings
from arp.db.session import require_dsn
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.postgres_portfolio_store import PostgresPortfolioStore


def build_portfolio_store(settings: Settings) -> PostgresPortfolioStore:
    return PostgresPortfolioStore(require_dsn(settings), PortfolioStore(settings.portfolios_dir))
