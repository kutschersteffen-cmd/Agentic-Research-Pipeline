from __future__ import annotations

import hashlib
from pathlib import Path
from typing import get_args

import typer

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.replication._wide_csv import read_wide_csv
from arp.replication.characteristics_data import CsvCharacteristicSource
from arp.replication.price_data import CsvPriceSource
from arp.signal_lab.baselines import momentum_panel
from arp.signal_lab.cutoffs import load_cutoff_table
from arp.signal_lab.evidence import evaluate_signal, sentiment_spec
from arp.signal_lab.registry import Recipe, Registry, experiment_id_for

signals_app = typer.Typer(
    help="Signals workbench: evaluate a signal's out-of-sample evidence, register it, and gate graduation."
)

_CATEGORIES = get_args(Recipe.model_fields["category"].annotation)


def _fail(exc: ValueError) -> typer.Exit:
    typer.echo(str(exc), err=True)
    return typer.Exit(1)


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


@signals_app.command("evaluate")
def signals_evaluate(
    scores: Path = typer.Option(..., help="Wide CSV of signal scores: a date column + one column per ticker."),
    prices: Path = typer.Option(..., help="Wide CSV of prices on the same dates as --scores."),
    category: str = typer.Option(..., help=f"One of {', '.join(_CATEGORIES)}."),
    method: str = typer.Option(..., help="Free-text name of how the scores were made."),
    universe: str = typer.Option(..., help="Free-text name of the ticker universe."),
    start: str = typer.Option(..., help="ISO date: first score month in the sample."),
    end: str = typer.Option(..., help="ISO date: last score month in the sample."),
    model: str = typer.Option(None, help="Model that made the scores; omit if none (every month counts as post-cutoff)."),
    cost_bps: float = typer.Option(10.0, help="One-way trading cost in basis points."),
    data_version: str = typer.Option(None, help="Defaults to a hash of both CSV files, so changed data is a new experiment."),
    baseline_momentum: bool = typer.Option(False, "--baseline-momentum", help="Also report overlap with 12-1 momentum."),
    out: Path = typer.Option(None, help="Optionally write the evidence report JSON here."),
) -> None:
    """Scores the signal against next-month returns, splits the evidence at the model's training cutoff,
    registers the experiment (once per recipe, data, model and cutoff), and prints the windows."""
    if category not in _CATEGORIES:
        typer.echo(f"--category must be one of {', '.join(_CATEGORIES)}, got {category!r}", err=True)
        raise typer.Exit(1)
    if data_version is None:
        data_version = hashlib.sha256(scores.read_bytes() + prices.read_bytes()).hexdigest()[:12]

    try:
        cutoffs_path = get_settings().training_cutoffs_path
        cutoffs = load_cutoff_table(cutoffs_path)
        cutoff = cutoffs.cutoff_for(model) if model else None
        # Say which split applies: an unlisted model or a dropped --model otherwise changes the evidence silently.
        if model is None:
            typer.echo(
                "no --model given: every period counts as post_cutoff; "
                "use this only for a signal that involves no trained model",
                err=True,
            )
        elif cutoff is None:
            typer.echo(
                f"model '{model}' has no recorded cutoff in {cutoffs_path}: every period is in_window and cannot graduate",
                err=True,
            )
        else:
            typer.echo(f"model '{model}': cutoff {cutoff} ({cutoffs.entries[model].source})", err=True)
            if cutoff > end:
                typer.echo(f"all periods are in_window: cutoff {cutoff} is after --end {end}", err=True)
        tickers = list(read_wide_csv(scores)[1])
        score_panel = CsvCharacteristicSource(scores).get_values(tickers, start, end)
        price_panel = CsvPriceSource(prices).get_monthly_returns(tickers, start, end)
        recipe = Recipe(
            category=category, method=method, text_source=None, params={}, universe=universe,
            window_start=start, window_end=end, cost_bps=cost_bps,
        )
        registry = Registry(_run_store())
        experiment_id = experiment_id_for(recipe, data_version=data_version, model=model, cutoff=cutoff)
        # A re-run of a registered experiment is not a new trial, so it must not inflate the deflation.
        n_trials = registry.trial_count(recipe) + (0 if registry.has(experiment_id) else 1)
        report = evaluate_signal(
            score_panel,
            price_panel,
            sentiment_spec("signal", start=start, end=end),
            model=model,
            cutoffs=cutoffs,
            cost_bps=cost_bps,
            n_trials=n_trials,
            baselines={"momentum": momentum_panel(price_panel)} if baseline_momentum else None,
        )
        registry.register(recipe, report, data_version=data_version, model=model, cutoff=cutoff)
    except ValueError as exc:
        raise _fail(exc) from exc

    typer.echo(f"experiment_id: {experiment_id}")
    typer.echo(f"{'window':<12} {'periods':>7} {'IC obs':>6} {'mean IC':>8} {'NW t':>7} {'net Sharpe':>10}")
    for w in report.windows:
        sharpe = w.net_long_short.sharpe_ratio if w.net_long_short else None
        typer.echo(
            f"{w.window:<12} {w.periods:>7} {w.ic.n:>6} {_fmt(w.ic.mean):>8} {_fmt(w.ic.t_nw, 2):>7} {_fmt(sharpe, 2):>10}"
        )
    if report.contamination_gap_ic is not None:
        typer.echo(f"contamination gap (in_window IC - post_cutoff IC): {report.contamination_gap_ic:.3f}")
    for name, value in report.overlap.items():
        typer.echo(f"overlap with {name}: {_fmt(value)}")
    if out:
        out.write_text(report.model_dump_json(indent=2))
        typer.echo(f"Wrote {out}")


@signals_app.command("list")
def signals_list() -> None:
    """Lists registered experiments with category, method, decision and trial count."""
    for r in Registry(_run_store()).list_experiments():
        typer.echo(
            f"{r.experiment_id}  {r.recipe.category}  {r.recipe.method}  decision={r.decision}  "
            f"trials={r.evidence.n_trials}"
        )


@signals_app.command("decide")
def signals_decide(
    experiment_id: str = typer.Argument(...),
    decision: str = typer.Option(..., help="graduate or shelve. Graduating needs 12+ post-cutoff IC months."),
    approver: str = typer.Option(..., help="Who approves; recorded with the decision."),
) -> None:
    """Records a graduate/shelve decision; graduation is refused without post-cutoff evidence."""
    try:
        cutoffs = load_cutoff_table(get_settings().training_cutoffs_path)
        record = Registry(_run_store()).decide(experiment_id, decision, approver=approver, cutoffs=cutoffs)  # type: ignore[arg-type]
    except ValueError as exc:
        raise _fail(exc) from exc
    typer.echo(f"{record.experiment_id}: {record.decision} by {record.decided_by}")
