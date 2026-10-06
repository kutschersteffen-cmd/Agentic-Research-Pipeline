from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import httpx
import typer

from arp.cli._shared import cli_principal
from arp.config import Settings, get_settings
from arp.holdings.api_source import pull_due, pull_holder
from arp.holdings.file_source import file_ref, load_mapping, read_rows, template
from arp.holdings.intake import IntakeError, ingest, previous_month_end
from arp.holdings.validate import validate
from arp.snapshots.client import SnapshotClient, SnapshotHashMismatch
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store_factory import build_portfolio_store

holdings_app = typer.Typer(help="Holdings intake: file import, monthly API pull and templates (E77).")


def _stores(settings: Settings):
    return build_portfolio_store(settings), IdentifierMapStore(settings.identifier_map_path)


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(1)


@holdings_app.command("import")
def import_cmd(
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False),
    holder: str = typer.Option(..., "--holder"),
    as_of: str = typer.Option(..., "--as-of"),
    kind: str = typer.Option("portfolio", "--kind"),
    provider: str = typer.Option("default", "--provider"),
    override_reason: str | None = typer.Option(None, "--override-reason"),
) -> None:
    """Imports a CSV or Excel holdings file; a rejected file prints one line per error."""
    settings = get_settings()
    principal = cli_principal(settings)
    store, idmap = _stores(settings)
    if kind not in ("index", "portfolio"):
        _fail(f"--kind must be index or portfolio, not {kind!r}")
    data = file.read_bytes()
    try:
        mapping = load_mapping(provider)
        validated = validate(read_rows(data, file.name, mapping), kind=kind, as_of=as_of, decimal=mapping.decimal,
                             weight_unit=mapping.weight_unit)
        result = ingest(store, validated, kind=kind, holder_id=holder, as_of=as_of, source="file",
                        source_ref=file_ref(data), principal=principal, override_reason=override_reason, idmap=idmap)
    except IntakeError as e:
        for err in e.errors:
            typer.echo(f"row {err.row if err.row is not None else '-'}, {err.column or '-'}: {err.message}", err=True)
        _fail(e.message)
    except (ValueError, FileExistsError) as e:
        _fail(str(e))
    typer.echo(json.dumps(asdict(result), indent=2))


@holdings_app.command("pull")
def pull_cmd(
    holder: str | None = typer.Option(None, "--holder"),
    kind: str = typer.Option("portfolio", "--kind"),
    as_of: str | None = typer.Option(None, "--as-of"),
) -> None:
    """Pulls one holder, or every API holder whose last month is missing, from ARP_HOLDINGS_API_URL."""
    settings = get_settings()
    if not settings.holdings_api_url:
        _fail("holdings_api_url is not set (ARP_HOLDINGS_API_URL).")
    store, idmap = _stores(settings)
    client = SnapshotClient(settings.holdings_api_url, settings.holdings_api_token)
    try:
        if holder is None:
            out = pull_due(store, settings=settings, client=client, today=date.today(), idmap=idmap)
        else:
            cfg = store.get_holder(kind, holder)
            if cfg is None:
                _fail(f"unknown holder {kind}/{holder}")
            r = pull_holder(cfg, as_of or previous_month_end(date.today()), client=client,
                            base_url=settings.holdings_api_url, store=store, idmap=idmap)
            out = [{"holder_id": holder, "kind": kind, **asdict(r)}]
    except (ValueError, FileExistsError, httpx.HTTPError, SnapshotHashMismatch) as e:
        _fail(str(e))
    finally:
        client.close()
    typer.echo(json.dumps(out, indent=2))
    if any(o["status"] == "failed" for o in out):
        raise typer.Exit(1)


@holdings_app.command("template")
def template_cmd(
    kind: str = typer.Option(..., "--kind"),
    fmt: str = typer.Option("csv", "--format"),
    out: Path = typer.Option(..., "--out"),
) -> None:
    if kind not in ("index", "portfolio") or fmt not in ("csv", "xlsx"):
        _fail("--kind is index or portfolio; --format is csv or xlsx")
    out.write_bytes(template(kind, fmt))
    typer.echo(str(out))
