from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.cli._shared import _registry, _run_store
from arp.config import get_settings
from arp.scale.load import live, simulate
from arp.scale.report import RunReport, render_markdown, run_report

scale_app = typer.Typer(help="Load test and cost/time per 1,000 issuers.")

_SIMULATED_NOTE = (
    "Simulated run: each company takes {latency} s, with no network, no API key and no LLM calls. "
    "It measures orchestration overhead only, not real cost or time, and the token and cost figures are synthetic. "
    "`max_concurrent_llm_calls` stays at its default of 8. For real numbers run "
    "`arp scale load --live --universe <universe.csv> --schema <schema.json> --concurrency 4,8,16 --issuers 200`."
)
_LIVE_NOTE = (
    "Live run: real LLM calls against the configured provider; the cost column is real spend. "
    "Trial runs: every row routes to review and is never published."
)


def _write(reports: list[RunReport], note: str, out: Path | None) -> None:
    md = render_markdown(reports, title="Load report", note=note)
    if out is None:
        typer.echo(md)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    typer.echo(f"Wrote {out}")


@scale_app.command("load")
def load(
    issuers: int = typer.Option(200, help="Number of issuers per run."),
    concurrency: str = typer.Option("8", help="Comma-separated concurrency levels, one run each."),
    live_mode: bool = typer.Option(False, "--live", help="Real extraction runs (spends API money)."),
    universe: Path = typer.Option(None, help="Universe file (--live)."),
    schema: Path = typer.Option(None, help="DataPointSchema JSON (--live)."),
    latency: float = typer.Option(0.05, help="Seconds per simulated company."),
    out: Path = typer.Option(None, help="Write the markdown report here."),
) -> None:
    levels = [int(c) for c in concurrency.split(",")]
    store = _run_store()
    if live_mode and (universe is None or schema is None):
        typer.echo("--live needs --universe and --schema.", err=True)
        raise typer.Exit(1)
    run_ids = []
    for c in levels:
        if live_mode:
            run_ids.append(
                asyncio.run(live(universe, schema, c, settings=get_settings(), run_store=store, registry=_registry()))
            )
        else:
            run_ids.append(asyncio.run(simulate(issuers, c, run_store=store, latency_s=latency)))
    reports = [run_report(store.load_manifest(r)) for r in run_ids]
    _write(reports, _LIVE_NOTE if live_mode else _SIMULATED_NOTE.format(latency=latency), out)


@scale_app.command("report")
def report(run_ids: list[str] = typer.Argument(...), out: Path = typer.Option(None)) -> None:
    store = _run_store()
    manifests = [store.load_manifest(r) for r in run_ids]
    if None in manifests:
        typer.echo("Unknown run id.", err=True)
        raise typer.Exit(1)
    _write([run_report(m) for m in manifests], "Report from run manifests.", out)
