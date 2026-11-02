"""Single choke point for building the portfolio store (both the CLI and the API call this): the
Postgres store, which keeps observations/news/flags/rules in the wrapped file-based PortfolioStore."""

from __future__ import annotations

from arp.config import Settings
from arp.db.session import require_dsn
from arp.storage.issuer_sectors import IssuerSectorStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.postgres_portfolio_store import PostgresPortfolioStore


def build_portfolio_store(settings: Settings, *, merge_master: bool = True) -> PostgresPortfolioStore:
    """`merge_master=False` reads companies as stored (the DB import must not write master values back)."""
    sectors = IssuerSectorStore(settings.identifier_map_path.with_name("issuer_sectors.json")) if merge_master else None
    return PostgresPortfolioStore(require_dsn(settings), PortfolioStore(settings.portfolios_dir, sectors), sectors)
