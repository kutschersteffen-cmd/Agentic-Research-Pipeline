from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import get_args

import typer
from pydantic import ValidationError

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.db.session import require_dsn
from arp.llm.factory import build_llm_client
from arp.portfolio.news.text_pull import pull_news_text
from arp.replication._wide_csv import read_wide_csv
from arp.replication.characteristics_data import CsvCharacteristicSource
from arp.replication.price_data import CsvPriceSource
from arp.signal_lab.adapters.fundamentals import CsvFundamentalSource
from arp.signal_lab.adapters.revisions import CsvRevisionSource
from arp.signal_lab.adapters.transcripts import CsvTranscriptSource
from arp.signal_lab.baselines import momentum_panel
from arp.signal_lab.compare import compare_experiments
from arp.signal_lab.cutoffs import load_cutoff_table
from arp.signal_lab.evidence import EvidenceReport, evaluate_signal, sentiment_spec
from arp.signal_lab.methods import base as methods_base
from arp.signal_lab.methods.embedding import default_embedder
from arp.signal_lab.methods.finbert import default_finbert
from arp.signal_lab.methods.llm_scoring import estimate_llm_calls
from arp.signal_lab.methods.topics import default_topic_model
from arp.signal_lab.registry import Recipe, Registry, experiment_id_for
from arp.signal_lab.text_panel import manifest_from_text_items
from arp.signal_lab.text_store import TextStore
from arp.storage.identifier_map import IdentifierMapStore

signals_app = typer.Typer(
    help="Signals workbench: evaluate a signal's out-of-sample evidence, register it, and gate graduation."
)

_CATEGORIES = get_args(Recipe.model_fields["category"].annotation)


def _fail(exc: ValueError) -> typer.Exit:
    typer.echo(str(exc), err=True)
    return typer.Exit(1)


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _echo_report(report: EvidenceReport) -> None:
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
    _echo_report(report)
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


@signals_app.command("compare")
def signals_compare(
    a: str = typer.Argument(..., help="First experiment id."),
    b: str = typer.Argument(..., help="Second experiment id."),
    confidence: float = typer.Option(0.95, help="Confidence before the correction for the number of comparisons."),
) -> None:
    """Ranks two registered experiments on their common post-cutoff months, or says the data cannot separate them."""
    try:
        result = compare_experiments(a, b, Registry(_run_store()), confidence=confidence)
    except ValueError as exc:
        raise _fail(exc) from exc
    typer.echo(
        f"{result.verdict} ({result.months} common post-cutoff months, corrected for {result.n_comparisons} comparisons)"
    )
    if result.reason:
        typer.echo(result.reason)


def _text_store() -> TextStore:
    return TextStore(require_dsn(get_settings()))


@signals_app.command("pull-news-text")
def signals_pull_news_text(since: str = typer.Option(None, help="ISO date; default: all stories the feed returns")) -> None:
    """Pulls Refinitiv headlines plus full story text into the point-in-time text store."""
    settings = get_settings()
    try:
        result = pull_news_text(_text_store(), settings, IdentifierMapStore(settings.identifier_map_path), since=since)
    except ValueError as exc:
        raise _fail(exc) from exc
    except Exception as exc:  # fetch failure or unexpected response; no traceback, it could show credentials
        typer.echo(f"News text pull failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{result['stories']} stories, {result['records']} new records, {result['unmatched']} not matched to an issuer")


@signals_app.command("text-manifest")
def signals_text_manifest(
    out: Path = typer.Option(..., help="Write the score-sentiment manifest JSON here."),
    event_from: str = typer.Option(None, help="ISO time: earliest event time; a date-only bound means the end of that day; naive times are refused."),
    event_to: str = typer.Option(None, help="ISO time: latest event time."),
    known_by: str = typer.Option(None, help="ISO time: only text stored by then (meaningful for live-ingested items only)."),
) -> None:
    """Builds a score-sentiment manifest from the text store, one entry per linked item in its event month."""
    try:
        items = _text_store().items(event_from=event_from, event_to=event_to, known_by=known_by)
    except ValueError as exc:
        raise _fail(exc) from exc
    entries = manifest_from_text_items(items)
    out.write_text(json.dumps(entries, indent=2))
    typer.echo(f"Wrote {out} ({len(entries)} entries)")


@signals_app.command("ingest-transcripts")
def signals_ingest_transcripts(csv_path: Path = typer.Option(..., "--csv", help="Transcript CSV: issuer_key, event_time, title, text.")) -> None:
    """Adds transcripts to the text store, stamped with the ingestion time unless the file gives knowledge_time."""
    try:
        records = CsvTranscriptSource(csv_path).records()
        store = _text_store()
        new = sum(store.add(r) for r in records)
    except ValueError as exc:
        raise _fail(exc) from exc
    typer.echo(f"{len(records)} records, {new} new")


@signals_app.command("build-panel")
def signals_build_panel(
    kind: str = typer.Option(..., help="fundamentals or revisions."),
    csv_path: Path = typer.Option(..., "--csv", help="Vendor CSV for the chosen kind."),
    prices: Path = typer.Option(..., help="Price CSV: its dates and columns set the panel's grid and issuers."),
    out: Path = typer.Option(..., help="Write the wide scores CSV here (feed it to 'evaluate --scores')."),
    metric: str = typer.Option(None, help="Required for fundamentals."),
    window_months: int = typer.Option(3, help="Revisions only: trailing months of revisions per period."),
) -> None:
    """Builds a point-in-time characteristic panel from a vendor CSV on the price CSV's grid."""
    try:
        if kind not in ("fundamentals", "revisions"):
            raise ValueError(f"--kind must be fundamentals or revisions, got {kind!r}")
        if kind == "fundamentals" and not metric:
            raise ValueError("--metric is required for --kind fundamentals")
        dates, columns = read_wide_csv(prices)
        issuers = list(columns)
        if kind == "fundamentals":
            panel = CsvFundamentalSource(csv_path).get_panel(metric, issuers, dates)
        else:
            panel = CsvRevisionSource(csv_path).get_panel(issuers, dates, window_months=window_months)
    except ValueError as exc:
        raise _fail(exc) from exc
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *issuers])
        for i, d in enumerate(dates):
            writer.writerow([d, *("" if (v := panel.values[t][i]) is None else v for t in issuers)])
    typer.echo(f"Wrote {out} ({len(dates)} periods x {len(issuers)} issuers)")


_TEXTLESS = {"panel", "price_momentum", "transform", "composite"}


def _spec_nodes(spec: dict) -> Iterator[dict]:
    """The spec and every spec nested under a transform's `base` or a composite's `components`."""
    yield spec
    params = spec.get("params")
    if not isinstance(params, dict):
        return
    children = [params.get("base"), *(params["components"] if isinstance(params.get("components"), list) else [])]
    for child in children:
        if isinstance(child, dict):
            yield from _spec_nodes(child)


def _load_recipe(path: Path) -> Recipe:
    try:
        return Recipe.model_validate(json.loads(path.read_text()))
    except OSError as exc:
        raise ValueError(f"cannot read recipe {path}: {exc.strerror}") from exc
    except ValidationError as exc:
        detail = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'recipe'}: {e['msg']}" for e in exc.errors())
        raise ValueError(f"invalid recipe {path}: {detail}") from exc
    except ValueError as exc:  # malformed JSON
        raise ValueError(f"invalid recipe {path}: {exc}") from exc


def _resources(names: set[str]) -> dict:
    # Only what the chosen methods need: loading an embedding or FinBERT model is slow, an LLM client needs a key.
    # issuer_first gets no search tool: the method refuses with its documented message.
    res: dict = {}
    if "grounded_llm" in names:
        res["llm"] = build_llm_client(get_settings())
    if names & {"embedding_ridge", "topic_attention"}:
        res["embedder"] = default_embedder()
    if "topic_attention" in names:
        res["topic_model"] = default_topic_model(res["embedder"])
    if "finbert" in names:
        res["finbert"] = default_finbert()
    return res


@signals_app.command("run")
def signals_run(
    recipe_path: Path = typer.Option(..., "--recipe", help="JSON file with the Recipe fields; 'method' is a registered method name."),
    prices: Path = typer.Option(..., help="Price CSV on calendar month-end dates; its columns are the issuers."),
    panel: list[str] = typer.Option([], "--panel", help="NAME=PATH.csv, repeatable: a 'build-panel' output for the 'panel' method and as a baseline."),
    known_by: str = typer.Option(None, help="ISO time: only text stored by then (meaningful for live-ingested items only)."),
    confirm_above: int = typer.Option(200, help="Refuse to run a recipe estimated to make more LLM calls than this unless --yes."),
    yes: bool = typer.Option(False, "--yes", help="Run even when the LLM call estimate exceeds --confirm-above."),
    out: Path = typer.Option(None, help="Optionally write the evidence report JSON here."),
) -> None:
    """Runs a method recipe on the text store and prices, registers the experiment (once per recipe and data) and prints the windows."""
    try:
        recipe = _load_recipe(recipe_path)
        spec = {"method": recipe.method, "params": recipe.params}
        nodes = list(_spec_nodes(spec))
        for node in nodes:
            methods_base.get_method(node.get("method"))  # unknown names fail before any slow work
        names = {node["method"] for node in nodes}
        panel_files: dict[str, Path] = {}
        for item in panel:
            name, sep, path = item.partition("=")
            if not sep or not name or not path:
                raise ValueError(f"--panel must be NAME=PATH, got {item!r}")
            panel_files[name] = Path(path)

        dates, columns = read_wide_csv(prices)
        if recipe.window_start < dates[0] or recipe.window_end > dates[-1]:
            raise ValueError(
                f"recipe window {recipe.window_start}..{recipe.window_end} is outside the price file {dates[0]}..{dates[-1]}"
            )
        issuers = list(columns)
        price_panel = CsvPriceSource(prices).get_monthly_returns(issuers, recipe.window_start, recipe.window_end)
        panels = {
            name: CsvCharacteristicSource(path).get_values(issuers, recipe.window_start, recipe.window_end)
            for name, path in panel_files.items()
        }
        texts = [] if names <= _TEXTLESS else _text_store().items(known_by=known_by)

        digest = hashlib.sha256("\n".join(sorted(t.item_id for t in texts)).encode())
        digest.update(prices.read_bytes())
        for name in sorted(panel_files):
            digest.update(panel_files[name].read_bytes())
        data_version = digest.hexdigest()[:12]

        inp = methods_base.MethodInput(texts=texts, prices=price_panel, panels=panels)
        llm_nodes = [n for n in nodes if n["method"] == "grounded_llm"]
        if llm_nodes:
            est = estimate_llm_calls(inp)
            passes = 0
            for node in llm_nodes:
                k = (node.get("params") or {}).get("stability_runs", 0)
                if isinstance(k, bool) or not isinstance(k, int) or k < 0:
                    raise ValueError(f"grounded_llm 'stability_runs' must be 0 or an integer >= 2, got {k!r}")
                passes += 1 + k
            calls, tokens = est["calls"] * passes, est["approx_input_tokens"] * passes
            typer.echo(f"LLM calls (estimate): {calls}, approx input tokens: {tokens}")
            if calls > confirm_above and not yes:
                raise ValueError(f"{calls} LLM calls exceed --confirm-above {confirm_above}; rerun with --yes to proceed")
        inp.resources = _resources(names)

        cutoffs = load_cutoff_table(get_settings().training_cutoffs_path)
        record = methods_base.run_recipe(
            recipe, inp, registry=Registry(_run_store()), cutoffs=cutoffs, data_version=data_version
        )
    except ValueError as exc:
        raise _fail(exc) from exc
    except Exception as exc:  # may carry LLM or network detail: print type and message only, never a traceback
        typer.echo(f"Run failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"experiment_id: {record.experiment_id}")
    _echo_report(record.evidence)
    if record.notes:
        typer.echo(f"notes: {json.dumps(record.notes, sort_keys=True, default=str)}")
    if out:
        out.write_text(record.evidence.model_dump_json(indent=2))
        typer.echo(f"Wrote {out}")
