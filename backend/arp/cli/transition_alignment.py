from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from arp.transition_alignment import benchmarks
from arp.transition_alignment.benchmarks import STALE, BenchmarksError, count_redlines, read_and_validate, sign_benchmarks
from arp.transition_barrier import dataset
from arp.transition_barrier.rule_book import RuleBookError, RuleBookNotFound

transition_alignment_app = typer.Typer(help="Transition plan alignment: capex benchmarks, R&D tests and redlines per sector.")

benchmarks_app = typer.Typer(help="The benchmarks file: validate it, sign a new version.")
transition_alignment_app.add_typer(benchmarks_app, name="benchmarks")

_DATA_DIR_HELP = "Directory with benchmarks.json."


def _fail(lines: list[str]) -> typer.Exit:
    for line in lines:
        typer.echo(line)
    return typer.Exit(code=1)


def _load_raw(directory: Path | None) -> tuple[Path, dict, list[str]]:
    """Raw benchmarks and their errors against the active barrier data directory."""
    directory = directory or benchmarks.data_dir()
    try:
        return (directory, *read_and_validate(directory, dataset.data_dir()))
    except (BenchmarksError, RuleBookNotFound, RuleBookError) as exc:
        raise _fail([str(exc)]) from None


@benchmarks_app.command("validate")
def benchmarks_validate(data_dir_opt: Path = typer.Option(None, "--data-dir", help=_DATA_DIR_HELP)) -> None:
    """Check the benchmarks file against the capex preset and the barrier data; print every error, one per line."""
    _, raw, errors = _load_raw(data_dir_opt)
    if errors:
        raise _fail(errors)
    typer.echo(f"Benchmarks v{raw['version']}: OK, {len(raw['sectors'])} sectors, {count_redlines(raw)} redlines")


@benchmarks_app.command("sign")
def benchmarks_sign(
    approved_by: str = typer.Option(..., "--approved-by", help="Who approved this version."),
    data_dir_opt: Path = typer.Option(None, "--data-dir", help=_DATA_DIR_HELP),
) -> None:
    """Bump the version, re-fingerprint and log the approval. A stale fingerprint is what this fixes."""
    directory, _, errors = _load_raw(data_dir_opt)
    blocking = [e for e in errors if not e.startswith(STALE)]
    if blocking:
        raise _fail(blocking)
    typer.echo(f"Signed benchmarks v{sign_benchmarks(directory, approved_by, date.today())}")
