from __future__ import annotations

from pathlib import Path

import typer

from arp.config import REPO_ROOT

showcase_app = typer.Typer(help="Showcase data: the simulated ESG dataset for the public holdings files (not real ESG data).")


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
