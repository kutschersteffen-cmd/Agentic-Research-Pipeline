from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.replication.examples import list_examples, load_example_spec
from arp.replication.pipeline import run_replication
from arp.replication.price_data import CsvPriceSource, PriceDataSource
from arp.replication.spec_graph import extract_strategy_spec
from arp.schemas.strategy_replication import StrategySpec
from arp.storage.run_store import RunStore

replicate_app = typer.Typer(
    help="Investment Strategy Replication: extract an academic 'outperformance' paper's methodology into an "
    "executable spec, then backtest it in-sample and out-of-sample against a pluggable price data source."
)


def _load_tickers(spec_arg: str) -> list[str]:
    path = Path(spec_arg)
    if path.exists():
        rows = [r.strip() for r in path.read_text().splitlines()]
        return [r for r in rows if r and r.lower() not in ("ticker", "company_id")]
    return [t.strip() for t in spec_arg.split(",") if t.strip()]


def _load_spec(path: Path) -> StrategySpec:
    return StrategySpec.model_validate_json(path.read_text())


def _price_source(prices: Path, price_kind: str) -> PriceDataSource:
    return CsvPriceSource(prices, kind=price_kind)


@replicate_app.command("examples")
def replicate_examples() -> None:
    """Lists the bundled worked-example strategy specs (data/*.json)."""
    for name in list_examples():
        typer.echo(name)


@replicate_app.command("example")
def replicate_example(
    name: str = typer.Argument(..., help="Bundled example name, see 'arp replicate examples'."),
    out: Path = typer.Option(..., help="Write the StrategySpec JSON here."),
) -> None:
    """Dumps a bundled worked-example StrategySpec, e.g. the Jegadeesh & Titman (1993) momentum strategy."""
    spec = load_example_spec(name)
    out.write_text(spec.model_dump_json(indent=2))
    typer.echo(f"Wrote {out}")
    if spec.needs_review:
        typer.echo("NOTE: this example is flagged needs_review -- see its extraction_notes before treating it as ground truth.")


@replicate_app.command("extract-spec")
def replicate_extract_spec(
    paper_citation: str = typer.Option(..., help="Full citation, e.g. 'Author (Year), Journal Vol(Issue).'"),
    paper_text: Path = typer.Option(..., help="Path to the paper's raw text (methodology + results sections at minimum)."),
    out: Path = typer.Option(..., help="Write the extracted StrategySpec JSON here."),
) -> None:
    """Extracts a StrategySpec from a paper's raw text via the extractor/independent-verifier pipeline, with every
    field grounded against the source text -- the same precision discipline as every other extraction in this
    codebase. Requires ARP_ANTHROPIC_API_KEY."""
    settings = get_settings()
    llm = build_llm_client(settings)
    verifier_llm = build_verifier_llm_client(settings)
    spec, needs_review, usages = asyncio.run(
        extract_strategy_spec(
            paper_citation,
            paper_text.read_text(),
            llm=llm,
            verifier_llm=verifier_llm,
            settings=settings,
            fuzzy_threshold=settings.grounding_fuzzy_threshold,
            confidence_review_threshold=settings.confidence_review_threshold,
        )
    )
    out.write_text(spec.model_dump_json(indent=2))
    typer.echo(f"Wrote {out} (needs_review={needs_review}, confidence={spec.confidence:.2f})")


@replicate_app.command("backtest")
def replicate_backtest(
    spec: Path = typer.Option(..., help="StrategySpec JSON (see 'arp replicate example' / 'extract-spec')."),
    prices: Path = typer.Option(..., help="Wide CSV: a date column + one column per ticker."),
    price_kind: str = typer.Option("price", help="'price' (returns are derived) or 'return' (CSV already holds periodic returns)."),
    tickers: str = typer.Option(..., help="Comma-separated tickers, or a path to a file with one ticker per line."),
    benchmark: str = typer.Option(None, help="Optional benchmark ticker (must be a column in the prices CSV) for alpha/beta."),
    out_of_sample_start: str = typer.Option(None, help="ISO date. Omit to run in-sample only."),
    out_of_sample_end: str = typer.Option(None, help="ISO date. Required if out_of_sample_start is set."),
) -> None:
    """Backtests a StrategySpec deterministically (zero LLM calls) against a CSV price panel: in-sample over the
    spec's own sample period, and out-of-sample over a separate window with identical rules, if given."""
    if bool(out_of_sample_start) != bool(out_of_sample_end):
        typer.echo("--out-of-sample-start and --out-of-sample-end must be given together.", err=True)
        raise typer.Exit(1)

    strategy_spec = _load_spec(spec)
    universe = _load_tickers(tickers)
    source = _price_source(prices, price_kind)

    run_id, report = run_replication(
        strategy_spec,
        universe,
        source,
        run_store=_run_store(),
        benchmark_ticker=benchmark,
        out_of_sample_start=out_of_sample_start,
        out_of_sample_end=out_of_sample_end,
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")
    typer.echo(f"Verdict: {report.verdict.value}")
    typer.echo(report.verdict_notes)


@replicate_app.command("report")
def replicate_report(run_id: str) -> None:
    """Prints the comparison report for a completed replication run."""
    store = RunStore(get_settings().runs_dir)
    rows = store.read_jsonl(store.results_path(run_id))
    comparison = next((r for r in rows if r.get("type") == "comparison"), None)
    if comparison is None:
        typer.echo(f"No comparison report found for run {run_id}.", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(comparison, indent=2))
