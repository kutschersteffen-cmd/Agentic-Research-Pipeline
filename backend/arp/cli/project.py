from __future__ import annotations

import json
import math
from pathlib import Path

import typer

from arp.config import get_settings
from arp.projects.store import Project, ProjectError, ProjectStore

project_app = typer.Typer(help="Projects: a folder of data files plus saved dashboards (arp/projects/).")


def _store() -> ProjectStore:
    return ProjectStore(get_settings().projects_dir)


def _portfolio_store():
    from arp.cli._shared import _portfolio_store as build

    return build()


def _superset_client():
    from arp.bi.superset_client import SupersetClient

    s = get_settings()
    return SupersetClient(s.superset_url, s.superset_user, s.superset_password)


def _summary(p: Project) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at,
        "data_files": sum(len(s.files) for s in p.data), "dashboards": len(p.dashboards),
    }  # fmt: skip


def _fail(message: str, code: int = 1) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code)


@project_app.command("create")
def project_create(
    id: str = typer.Argument(..., help="Project id: lowercase letters, digits and dashes."),
    name: str = typer.Option(..., "--name", help="Display name."),
    description: str = typer.Option("", "--description", help="Optional description."),
) -> None:
    """Creates an empty project and prints its summary as JSON."""
    try:
        p = _store().create(id, name.strip(), description.strip())
    except ProjectError as e:
        raise _fail(str(e)) from e
    typer.echo(json.dumps(_summary(p)))


@project_app.command("add-data")
def project_add_data(
    id: str = typer.Argument(..., help="Project id."),
    files: list[Path] = typer.Argument(..., help="DWS Constituent_<ISIN>.xlsx files."),
    notional_eur: float = typer.Option(..., "--notional-eur", help="Assumed fund size in EUR; the files carry weights only."),
) -> None:
    """Copies each file into the project's data folder and prints the updated summary as JSON."""
    if not math.isfinite(notional_eur) or notional_eur <= 0:
        raise _fail("--notional-eur must be a finite number greater than 0")
    store = _store()
    try:
        store.get(id)
        contents = [(f.name, f.read_bytes()) for f in files]
        for name, content in contents:
            p = store.add_data_file(id, name, content, {"notional_eur": notional_eur})
    except OSError as e:
        raise _fail(f"Cannot read {e.filename}: {e.strerror}") from e
    except ProjectError as e:
        raise _fail(str(e)) from e
    typer.echo(json.dumps(_summary(p)))


@project_app.command("list")
def project_list() -> None:
    """One project per line: id, name, data files, dashboards (tab-separated)."""
    for p in _store().list():
        s = _summary(p)
        typer.echo(f"{s['id']}\t{s['name']}\t{s['data_files']}\t{s['dashboards']}")


@project_app.command("open")
def project_open(id: str = typer.Argument(..., help="Project id.")) -> None:
    """Imports the project's data and provisions its dashboards in Superset; prints the result as JSON.

    Needs ARP_PORTFOLIO_BACKEND=postgres and ARP_SUPERSET_PASSWORD."""
    import httpx

    from arp.bi.service import BIError
    from arp.bi.superset_client import SupersetError
    from arp.projects.service import OpenError, open_project

    s = get_settings()
    if s.portfolio_backend != "postgres":
        raise _fail("Projects need Postgres: set ARP_PORTFOLIO_BACKEND=postgres.", 2)
    if s.superset_password is None:
        raise _fail("Superset is not configured: set ARP_SUPERSET_PASSWORD.", 2)
    try:
        result = open_project(_store(), _portfolio_store(), _superset_client(), id)
    except OpenError as e:
        raise _fail(f"Opening the project failed at {e.step}: {e}") from e
    except ProjectError as e:
        raise _fail(str(e)) from e
    except (BIError, SupersetError, httpx.HTTPError) as e:
        raise _fail(f"Superset at {s.superset_url}: {e}") from e  # str(e) omits the response body
    typer.echo(json.dumps(result.model_dump()))
