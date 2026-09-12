from __future__ import annotations

import typer

from arp.config import get_settings

db_app = typer.Typer(
    help="Opt-in store setup: Postgres/pgvector (arp/storage/postgres*.py, requires ARP_POSTGRES_DSN + the "
    "`postgres` extra), OpenSearch (opensearch_client.py, requires ARP_OPENSEARCH_URL + the `opensearch` extra), "
    "and object storage (object_store_client.py, requires ARP_OBJECT_STORE_ENDPOINT_URL + the `object_storage` extra)."
)


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


@db_app.command("init-opensearch")
def db_init_opensearch() -> None:
    """Creates the arp-companies/arp-documents/arp-chunks/arp-taxonomy
    indices (behind their stable aliases), idempotently. Run once against a
    fresh OpenSearch cluster before setting ARP_SEARCH_LIVE_INDEXING_ENABLED
    and/or ARP_RETRIEVAL_BACKEND=opensearch."""
    settings = get_settings()
    if not settings.opensearch_url:
        typer.echo("ARP_OPENSEARCH_URL is not set -- nothing to initialize.", err=True)
        raise typer.Exit(1)
    from arp.storage.opensearch_client import ensure_indices

    ensure_indices(settings.opensearch_url)
    typer.echo(f"OpenSearch indices ready at {settings.opensearch_url}.")


@db_app.command("init-object-store")
def db_init_object_store() -> None:
    """Creates the object-storage bucket for immutable source-document
    copies, idempotently. Run once against a fresh MinIO/S3-compatible
    endpoint before setting ARP_OBJECT_STORE_LIVE_UPLOAD_ENABLED."""
    settings = get_settings()
    if not settings.object_store_endpoint_url:
        typer.echo("ARP_OBJECT_STORE_ENDPOINT_URL is not set -- nothing to initialize.", err=True)
        raise typer.Exit(1)
    from arp.storage.object_store_client import ensure_bucket, get_client

    client = get_client(settings.object_store_endpoint_url, settings.object_store_access_key, settings.object_store_secret_key)
    ensure_bucket(client, settings.object_store_bucket)
    typer.echo(f"Object store bucket '{settings.object_store_bucket}' ready at {settings.object_store_endpoint_url}.")
