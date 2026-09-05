from __future__ import annotations

import typer

from arp.config import get_settings

db_app = typer.Typer(help="Opt-in Postgres/pgvector store setup (arp/storage/postgres*.py). Requires ARP_POSTGRES_DSN and the `postgres` extra.")


@db_app.command("init-postgres")
def db_init_postgres() -> None:
    """Creates the pgvector extension and every table the opt-in Postgres
    store defines (portfolios/securities/companies/holdings/security
    resolutions/chunk_embeddings), idempotently. Run once against a fresh
    database before setting ARP_PORTFOLIO_BACKEND=postgres and/or
    ARP_EMBEDDINGS_BACKEND=postgres."""
    settings = get_settings()
    if not settings.postgres_dsn:
        typer.echo("ARP_POSTGRES_DSN is not set -- nothing to initialize.", err=True)
        raise typer.Exit(1)
    from arp.storage.postgres import ensure_schema

    ensure_schema(settings.postgres_dsn)
    typer.echo(f"Postgres schema ready at {settings.postgres_dsn}.")
