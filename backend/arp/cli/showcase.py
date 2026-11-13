from __future__ import annotations

from pathlib import Path

import typer

from arp.config import REPO_ROOT

showcase_app = typer.Typer(help="Showcase data: the simulated ESG dataset for the public holdings files (not real ESG data), and its loader.")


@showcase_app.callback()
def _showcase() -> None:
    """Showcase data: the simulated ESG dataset for the public holdings files (not real ESG data)."""


def _from_repo_root(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


@showcase_app.command("simulate")
def simulate_cmd(
    holdings_dir: Path = typer.Option(Path("data/holdings"), help="Folder with the seven holdings files."),
    overrides: Path = typer.Option(Path("data/simulated/activity_overrides.csv"), help="Companies whose business is a controversial activity."),
    out: Path = typer.Option(Path("data/simulated/esg_simulated.csv"), help="Where the simulated dataset is written."),
) -> None:
    """Write the SIMULATED ESG dataset, one row per company line of the holdings files. Relative paths
    resolve against the repo root. Reads files only; needs no database."""
    from arp.showcase.simulate import read_holdings, read_overrides, simulate, write_dataset

    try:
        rows = simulate(read_holdings(_from_repo_root(holdings_dir)), read_overrides(_from_repo_root(overrides)))
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    write_dataset(rows, _from_repo_root(out))
    typer.echo(f"wrote {len(rows)} simulated rows to {_from_repo_root(out)}")


@showcase_app.command("load")
def load_cmd(
    holdings_dir: Path = typer.Option(Path("data/holdings"), help="Folder with the seven holdings files."),
    dataset: Path = typer.Option(Path("data/simulated/esg_simulated.csv"), help="The simulated dataset to load."),
) -> None:
    """Import the seven public holdings files, give them SIMULATED history and ESG values for 2026-06 to
    2026-11, and run those six months. Relative paths resolve against the repo root. Safe to re-run."""
    from arp.cli._shared import _portfolio_store
    from arp.config import get_settings
    from arp.showcase.load import load

    if not load(_portfolio_store(), get_settings(), _from_repo_root(holdings_dir), _from_repo_root(dataset), typer.echo):
        raise typer.Exit(1)
