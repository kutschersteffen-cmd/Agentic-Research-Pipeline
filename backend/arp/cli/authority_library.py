from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import typer

from arp.config import get_settings
from arp.discovery.site_finder import build_web_search_client
from arp.llm.factory import build_llm_client
from arp.research.authority_taxonomy.discovery import propose
from arp.research.authority_taxonomy.library import THEME_KEYS, approve, reject

authority_library_app = typer.Typer(help="Curated authority source library for theme taxonomies.")


def _theme(value: str) -> str:
    if value not in THEME_KEYS:
        typer.echo(f"unknown theme {value!r}; expected one of: {', '.join(THEME_KEYS)}", err=True)
        raise typer.Exit(1)
    return value


_THEME = typer.Option(..., "--theme", callback=_theme, help="Theme key.")
_ROOT = typer.Option(None, "--root", hidden=True, help="Library directory (tests).")


def _edit(action, theme: str, url: str, *args) -> None:
    try:
        action(theme, url, *args)
    except KeyError:
        typer.echo(f"{url} is not in the {theme} library", err=True)
        raise typer.Exit(1) from None


@authority_library_app.command("propose")
def propose_cmd(theme: str = _THEME, root: Path | None = _ROOT) -> None:
    """Search for sources and add new ones as `proposed` (review, then approve)."""
    settings = get_settings()
    n = asyncio.run(
        propose(
            theme,
            search_client=build_web_search_client(settings.discovery_user_agent),
            llm=build_llm_client(settings),
            user_agent=settings.discovery_user_agent,
            root=root,
        )
    )
    typer.echo(f"added {n} proposed source(s) to {theme}")


@authority_library_app.command("approve")
def approve_cmd(theme: str = _THEME, url: str = typer.Option(..., "--url"), root: Path | None = _ROOT) -> None:
    _edit(approve, theme, url, date.today(), root)


@authority_library_app.command("reject")
def reject_cmd(theme: str = _THEME, url: str = typer.Option(..., "--url"), root: Path | None = _ROOT) -> None:
    _edit(reject, theme, url, root)
