from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _registry, _run_store
from arp.config import get_settings
from arp.extraction.pipeline import _extract_company
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.research.stock_inference import run as infer_run
from arp.research.stock_inference.clusters import cluster_points
from arp.research.stock_inference.profile import discover_missing
from arp.research.stock_inference.schemas import InferRun
from arp.retrieval.embeddings import embed_texts

infer_app = typer.Typer(help="Infer a taxonomy from a set of stocks: start, then show.")


def _themes_table(run: InferRun) -> None:
    typer.echo("rank\tweight_share\tcount_share\tstocks\tname")
    for t in run.themes:
        share = "n/a" if t.weight_share is None else f"{t.weight_share:.4f}"
        typer.echo(f"{t.rank}\t{share}\t{t.count_share:.4f}\t{len(t.supporting)}\t{t.name}")


@infer_app.command("start")
def infer_start(
    stocks: Path = typer.Option(..., "--stocks", help="Holdings CSV, or a universe CSV/JSON."),
    methodology: list[str] = typer.Option([], "--methodology", help="Methodology file or URL; repeatable."),
    segments: Path = typer.Option(None, "--segments", help="Revenue-catalogue CSV."),
    benchmark: Path = typer.Option(None, "--benchmark", help="Universe CSV/JSON used as contrast for clusters."),
    name: str = typer.Option(None, "--name", help="Set name; defaults to the stocks file's stem."),
) -> None:
    settings = get_settings()
    try:
        run = asyncio.run(infer_run.start(
            stocks, methodology=methodology, segments_path=segments, benchmark_path=benchmark, name=name,
            run_store=_run_store(), settings=settings, llm=build_llm_client(settings),
            verifier_llm=build_verifier_llm_client(settings), registry=_registry(), discover=discover_missing,
            extract=_extract_company, cluster=cluster_points, embed=embed_texts,
        ))
    except infer_run.InferFailed as e:
        typer.echo(f"Run {e.run.run_id}")
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    except (ValueError, OSError) as e:  # bad input files: no run was created
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Run {run.run_id}")
    _themes_table(run)
    typer.echo(f"stage: {run.stage}")


@infer_app.command("show")
def infer_show(run_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
    try:
        run = infer_run.load_run(run_id, _run_store())
    except KeyError as e:
        typer.echo(e.args[0], err=True)
        raise typer.Exit(1) from None
    if as_json:
        data = infer_run.dump(run)
        for p in data["profiles"]:
            if p["citation"]:
                p["citation"] = {k: p["citation"][k] for k in ("doc_id", "page", "quote")}
        typer.echo(json.dumps(data, indent=2))
        return
    typer.echo(f"Run {run.run_id}\tname: {run.name}\tstage: {run.stage}")
    described = sum(1 for p in run.profiles if p.description)
    typer.echo(f"profiles: {len(run.profiles)} ({described} described)\tclusters: {len(run.clusters)}")
    _themes_table(run)
    if run.outliers:
        typer.echo(f"outliers: {', '.join(run.outliers)}")
