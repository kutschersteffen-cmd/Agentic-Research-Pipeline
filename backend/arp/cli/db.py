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


reindex_app = typer.Typer(
    help="Backfill/resync the opt-in OpenSearch and object-store projections for documents registered before "
    "those stores were enabled (or whose live indexing/upload hook previously failed). Runs regardless of "
    "ARP_SEARCH_LIVE_INDEXING_ENABLED/ARP_OBJECT_STORE_LIVE_UPLOAD_ENABLED -- those flags only gate the "
    "per-ingestion live hook, not this one-off backfill."
)
db_app.add_typer(reindex_app, name="reindex")


@reindex_app.command("opensearch")
def reindex_opensearch(batch_size: int = typer.Option(200, help="Rows read from the parsed-content cache per batch.")) -> None:
    """Re-chunks and bulk-indexes every already-registered document's
    cached parsed text into arp-documents/arp-chunks. Safe to re-run --
    every index write is an upsert keyed by doc_id/chunk_id."""
    settings = get_settings()
    if not settings.opensearch_url:
        typer.echo("ARP_OPENSEARCH_URL is not set -- nothing to index.", err=True)
        raise typer.Exit(1)
    from arp.ingestion.indexing_config import IndexingConfig
    from arp.retrieval.search_indexer import index_document
    from arp.schemas.common import DocType
    from arp.storage.document_store import DocumentContentStore

    content_store = DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)
    config = IndexingConfig(opensearch_url=settings.opensearch_url, search_live_indexing_enabled=True)

    indexed = failed = skipped = 0
    offset = 0
    while True:
        rows, _total = content_store.list_cached_content(offset, batch_size)
        if not rows:
            break
        doc_refs = content_store.list_documents_by_content_keys([row["content_key"] for row in rows])
        for row in rows:
            doc_ref = doc_refs.get(row["content_key"])
            if doc_ref is None:
                skipped += 1  # parsed content with no registered document (e.g. content_cache_enabled but not registered)
                continue
            parsed = content_store.get_cached_text(row["id"])
            if parsed is None:
                skipped += 1
                continue
            try:
                index_document(
                    config,
                    doc_id=doc_ref.doc_id,
                    company_id=doc_ref.company_id,
                    doc_type=DocType(doc_ref.doc_type),
                    title=doc_ref.title,
                    full_text=parsed.full_text,
                )
                indexed += 1
            except Exception as exc:  # noqa: BLE001 - isolate one bad document from the whole backfill
                failed += 1
                typer.echo(f"Failed to index {doc_ref.doc_id}: {exc}", err=True)
        offset += len(rows)
    typer.echo(f"OpenSearch backfill complete: indexed={indexed} skipped={skipped} failed={failed}.")


@reindex_app.command("object-store")
def reindex_object_store() -> None:
    """Uploads every already-registered document's original bytes to
    object storage -- read from local_path when the file still exists
    locally, otherwise re-fetched from source_url (e.g. an EDGAR filing
    with no local copy). Skips documents that already have a storage_uri
    recorded. Safe to re-run."""
    settings = get_settings()
    if not settings.object_store_endpoint_url:
        typer.echo("ARP_OBJECT_STORE_ENDPOINT_URL is not set -- nothing to upload.", err=True)
        raise typer.Exit(1)
    from pathlib import Path

    import httpx

    from arp.ingestion.indexing_config import IndexingConfig
    from arp.storage.document_blob_store import upload_document
    from arp.storage.document_store import DocumentContentStore

    content_store = DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)
    config = IndexingConfig(
        object_store_endpoint_url=settings.object_store_endpoint_url,
        object_store_access_key=settings.object_store_access_key,
        object_store_secret_key=settings.object_store_secret_key,
        object_store_bucket=settings.object_store_bucket,
        object_store_live_upload_enabled=True,
    )

    uploaded = failed = skipped = 0
    for doc_ref in content_store.list_all_documents():
        if doc_ref.storage_uri:
            skipped += 1
            continue
        try:
            if doc_ref.local_path and Path(doc_ref.local_path).exists():
                data = Path(doc_ref.local_path).read_bytes()
            elif doc_ref.source_url:
                resp = httpx.get(doc_ref.source_url, headers={"User-Agent": settings.edgar_user_agent}, timeout=30.0, follow_redirects=True)
                resp.raise_for_status()
                data = resp.content
            else:
                skipped += 1
                continue
            storage_uri = upload_document(config, doc_ref.content_key, data)
            content_store.set_storage_uri(doc_ref.doc_id, storage_uri)
            uploaded += 1
        except Exception as exc:  # noqa: BLE001 - isolate one bad document from the whole backfill
            failed += 1
            typer.echo(f"Failed to archive {doc_ref.doc_id}: {exc}", err=True)
    typer.echo(f"Object-store backfill complete: uploaded={uploaded} skipped={skipped} failed={failed}.")
