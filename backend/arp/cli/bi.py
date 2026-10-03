from __future__ import annotations

import json

import typer

from arp.bi.views import PLACEHOLDER_SECRETS
from arp.config import get_settings

bi_app = typer.Typer(help="Apache Superset BI integration (arp/bi/): provision the `bi` views and Superset datasets.")


@bi_app.command("bootstrap")
def bi_bootstrap(
    db_host: str = typer.Option(
        "postgres:5432",
        envvar="ARP_BI_SUPERSET_DB_HOST",
        help="host:port at which Superset (not this CLI) reaches the ARP Postgres. The default is the compose "
        "service; database name comes from ARP_POSTGRES_DSN.",
    ),
) -> None:
    """Applies the `bi` views and the `bi_reader` role to ARP_POSTGRES_DSN,
    then registers that database in Superset (as `arp_bi`, connecting as
    bi_reader), one dataset per view and the catalog metrics. Idempotent;
    run it again after upgrading, since it is also how edited view
    definitions reach an existing database.

    It logs in as ARP_SUPERSET_USER (default arp_designer), which the
    compose `superset` container creates at boot (superset/entrypoint.sh).
    Against any other Superset, create that account once first:
    `superset fab create-admin --username arp_designer --password ... --firstname ARP --lastname Designer
    --email arp_designer@localhost`.

    Then provisions each dashboard template (arp/bi/templates/*.json):
    created when absent, rebuilt when it has fewer charts than the template,
    otherwise left as it is.

    Prints {"database_id", "datasets": {table: id}, "reader_role", "templates": {slug: status}} as JSON."""
    settings = get_settings()
    required = {
        "ARP_POSTGRES_DSN": settings.postgres_dsn,
        "ARP_SUPERSET_PASSWORD": settings.superset_password,
        "ARP_BI_READER_PASSWORD": settings.bi_reader_password,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        typer.echo(f"Not set: {', '.join(missing)} -- see backend/.env.example.", err=True)
        raise typer.Exit(1)

    if settings.bi_reader_password in PLACEHOLDER_SECRETS:
        typer.echo("ARP_BI_READER_PASSWORD is a placeholder -- set it to e.g. the output of `openssl rand -base64 42`.", err=True)
        raise typer.Exit(1)

    import httpx
    from sqlalchemy.engine import make_url

    from arp.bi import templates
    from arp.bi.catalog import BI_DATABASE, VIEW_DATASETS
    from arp.bi.service import BIError
    from arp.bi.superset_client import SupersetClient, SupersetError
    from arp.bi.views import ROLE, create_bi_views, ensure_reader_role
    from arp.storage.postgres import get_engine

    with get_engine(settings.postgres_dsn).begin() as conn:
        create_bi_views(conn)
        ensure_reader_role(conn, settings.bi_reader_password)

    host, _, port = db_host.partition(":")
    reader_uri = (
        make_url(settings.postgres_dsn)
        .set(
            drivername="postgresql",
            username=ROLE,
            password=settings.bi_reader_password,
            host=host,
            port=int(port) if port else None,
            query={},
        )
        .render_as_string(hide_password=False)
    )
    client = SupersetClient(settings.superset_url, settings.superset_user, settings.superset_password)
    try:
        database_id = client.ensure_database(BI_DATABASE, reader_uri)
        datasets = {}
        for table, dataset in VIEW_DATASETS.items():
            dataset_id = client.ensure_dataset(database_id, "bi", dataset.table)
            client.refresh_dataset(dataset_id)  # pick up view column changes
            client.sync_metrics(dataset_id, dataset.metrics)
            client.sync_descriptions(dataset_id, dataset.description, dataset.columns)
            datasets[table] = dataset_id
        statuses = {t.slug: templates.provision(client, t) for t in templates.load_templates()}
    except BIError as e:  # a template that does not fit, or Superset failing mid-provision
        typer.echo(f"Dashboard templates: {e}", err=True)
        if isinstance(e.__cause__, SupersetError) and e.__cause__.body:
            typer.echo(f"Response body: {e.__cause__.body}", err=True)
        raise typer.Exit(1) from e
    except (SupersetError, httpx.HTTPError) as e:
        typer.echo(f"Superset at {settings.superset_url}: {e}", err=True)
        if isinstance(e, SupersetError) and e.body:
            typer.echo(f"Response body: {e.body}", err=True)  # operator-only; str(e) omits it
        raise typer.Exit(1) from e
    typer.echo(json.dumps({"database_id": database_id, "datasets": datasets, "reader_role": ROLE, "templates": statuses}))
