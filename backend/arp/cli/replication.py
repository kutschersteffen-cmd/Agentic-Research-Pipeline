from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

import typer

from arp.cli._shared import _run_store
from arp.config import Settings, get_settings
from arp.discovery.academic_search import ArxivSearchClient, CompositeSearchClient, SemanticScholarSearchClient
from arp.discovery.site_finder import DuckDuckGoSearchClient, WebSearchClient
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.replication.characteristics_data import CsvCharacteristicSource
from arp.replication.cpcv import run_pbo_analysis
from arp.replication.examples import list_examples, load_example_spec
from arp.replication.golden_set import load_bundled_cases, run_golden_set
from arp.replication.paper_discovery import discover_candidate_papers, rank_candidate_papers
from arp.replication.pipeline import run_replication
from arp.replication.price_data import CsvPriceSource, PriceDataSource
from arp.replication.regime_analysis import regime_stratified_report
from arp.replication.sanity_check import sanity_check_report
from arp.replication.sentiment_scoring import build_sentiment_panel
from arp.replication.spec_graph import extract_strategy_spec
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.strategy_replication import BacktestResult, ReplicationComparisonReport, StrategySpec
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


def _build_search_client(source: str, settings: Settings) -> WebSearchClient:
    if source == "duckduckgo":
        return DuckDuckGoSearchClient(settings.discovery_user_agent)
    if source == "arxiv":
        return ArxivSearchClient()
    if source == "semanticscholar":
        return SemanticScholarSearchClient()
    if source == "all":
        return CompositeSearchClient(
            [ArxivSearchClient(), SemanticScholarSearchClient(), DuckDuckGoSearchClient(settings.discovery_user_agent)]
        )
    raise typer.BadParameter(f"--source must be one of duckduckgo, arxiv, semanticscholar, all -- got {source!r}")


@replicate_app.command("discover-papers")
def replicate_discover_papers(
    topic: str = typer.Argument(..., help="e.g. 'momentum', 'quality investing', 'low volatility anomaly'."),
    out: Path = typer.Option(..., help="Write ranked candidates (JSON list of PaperCandidate) here."),
    max_candidates: int = typer.Option(10, help="Cap on the number of candidates returned."),
    source: str = typer.Option(
        "all",
        help="'arxiv' (arXiv's own API, restricted to q-fin categories), 'semanticscholar' (broad academic search "
        "incl. SSRN/NBER-hosted papers via the Semantic Scholar Graph API -- SSRN itself has no public search API "
        "and scraping it would violate its terms of service, so this is the legitimate stand-in), 'duckduckgo' "
        "(generic web search, the original fallback), or 'all' (all three, merged/deduped).",
    ),
) -> None:
    """Searches for candidate 'outperformance' papers on `topic` and ranks them by replication-worthiness (a
    testable claim, plausibly replicable with price/one-fundamental-ratio/text data, a real academic/practitioner
    source) -- proposes candidates for you to review and pick from, never fetches or extracts a spec
    automatically. Requires ARP_ANTHROPIC_API_KEY for the ranking step."""
    settings = get_settings()
    search_client = _build_search_client(source, settings)
    llm = build_llm_client(settings)

    async def _run() -> list:
        candidates = await discover_candidate_papers(topic, search_client, max_candidates=max_candidates)
        if not candidates:
            return []
        ranked, _usage = await rank_candidate_papers(topic, candidates, llm)
        return ranked

    ranked = asyncio.run(_run())
    out.write_text(json.dumps([c.model_dump(mode="json") for c in ranked], indent=2))
    typer.echo(f"Wrote {len(ranked)} candidate(s) to {out}")
    for c in ranked[:5]:
        score = f"{c.replication_worthiness_score:.2f}" if c.replication_worthiness_score is not None else "?"
        typer.echo(f"  [{score}] {c.title} -- {c.url}")


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


def _parse_characteristics_sources(entries: list[str]) -> dict[str, CsvCharacteristicSource]:
    sources: dict[str, CsvCharacteristicSource] = {}
    for entry in entries:
        if "=" not in entry:
            raise typer.BadParameter(f"--characteristics must be 'name=path.csv', got {entry!r}")
        name, path_str = entry.split("=", 1)
        sources[name.strip()] = CsvCharacteristicSource(Path(path_str.strip()))
    return sources


@replicate_app.command("backtest")
def replicate_backtest(
    spec: Path = typer.Option(..., help="StrategySpec JSON (see 'arp replicate example' / 'extract-spec')."),
    prices: Path = typer.Option(..., help="Wide CSV: a date column + one column per ticker."),
    price_kind: str = typer.Option("price", help="'price' (returns are derived) or 'return' (CSV already holds periodic returns)."),
    tickers: str = typer.Option(..., help="Comma-separated tickers, or a path to a file with one ticker per line."),
    characteristics: list[str] = typer.Option(
        [],
        help="'characteristic_name=path.csv', repeatable. Same date grid as --prices. Required for every "
        "characteristic_name the spec's signal_type (value/text_sentiment) or COMPOSITE components need -- see "
        "'arp replicate backtest' error output for exactly which name(s) are missing.",
    ),
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
    characteristics_sources = _parse_characteristics_sources(characteristics)

    try:
        run_id, report = run_replication(
            strategy_spec,
            universe,
            source,
            run_store=_run_store(),
            characteristics_sources=characteristics_sources,
            benchmark_ticker=benchmark,
            out_of_sample_start=out_of_sample_start,
            out_of_sample_end=out_of_sample_end,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")
    typer.echo(f"Verdict: {report.verdict.value}")
    typer.echo(report.verdict_notes)


@replicate_app.command("score-sentiment")
def replicate_score_sentiment(
    manifest: Path = typer.Option(
        ...,
        help="JSON list of {ticker, period_end, text, doc_id?} objects -- one dated news/transcript excerpt per "
        "cell. period_end values across the whole manifest define the panel's monthly grid.",
    ),
    out: Path = typer.Option(..., help="Write the resulting characteristics CSV here (feed it to 'backtest --characteristics <name>=<out>')."),
    records_out: Path = typer.Option(None, help="Optionally also write the full per-cell audit trail (grounded quote, confidence) here as JSON."),
) -> None:
    """Scores each manifest entry's sentiment via a grounded LLM pass (see arp/replication/sentiment_scoring.py --
    the model is explicitly told never to use hindsight about what happened after a document's own date) and
    writes the result as a characteristics CSV for SignalType.TEXT_SENTIMENT. Requires ARP_ANTHROPIC_API_KEY."""
    entries = json.loads(manifest.read_text())
    period_ends = sorted({e["period_end"] for e in entries})
    documents_by_ticker_period: dict[str, dict[str, SourceDocument]] = {}
    for e in entries:
        doc = SourceDocument(
            doc_id=e.get("doc_id") or f"{e['ticker']}_{e['period_end']}",
            company_id=e["ticker"],
            doc_type=DocType(e["doc_type"]) if e.get("doc_type") else DocType.OTHER,
            title=f"{e['ticker']} {e['period_end']}",
            full_text=e["text"],
            fiscal_period=e["period_end"],
        )
        documents_by_ticker_period.setdefault(e["ticker"], {})[e["period_end"]] = doc

    settings = get_settings()
    llm = build_llm_client(settings)
    panel, records, usages = asyncio.run(
        build_sentiment_panel(documents_by_ticker_period, period_ends, llm, fuzzy_threshold=settings.grounding_fuzzy_threshold)
    )

    tickers = sorted(panel.values.keys())
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *tickers])
        for i, period_end in enumerate(period_ends):
            writer.writerow([period_end, *(panel.values[t][i] if panel.values[t][i] is not None else "" for t in tickers)])
    typer.echo(f"Wrote {out} ({len(tickers)} ticker(s) x {len(period_ends)} period(s), {len(usages)} document(s) scored)")

    ungrounded = [r for r in records if not r.grounded]
    if ungrounded:
        typer.echo(f"NOTE: {len(ungrounded)} of {len(records)} scored document(s) failed grounding and were excluded from the panel.")
    if records_out:
        records_out.write_text(json.dumps([r.model_dump(mode="json") for r in records], indent=2))
        typer.echo(f"Wrote per-cell audit trail to {records_out}")


@replicate_app.command("golden-set")
def replicate_golden_set() -> None:
    """Runs the bundled backtest-engine golden set (deterministic, no LLM/API key needed) -- run this before a
    signals.py/backtest_engine.py/rebalance.py/metrics.py change ships, the same discipline 'arp golden-set run'
    applies to the extraction pipeline."""
    report = run_golden_set(load_bundled_cases())
    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        typer.echo(f"[{status}] {r.case_id}: {r.description}")
        if not r.passed:
            typer.echo(f"         {r.detail}")
    typer.echo(f"\n{report.passed}/{report.total} passed.")
    if not report.all_passed:
        raise typer.Exit(1)


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


@replicate_app.command("sanity-check")
def replicate_sanity_check(run_id: str) -> None:
    """Runs a qualitative LLM 'sanity check' pass over a completed run's comparison report -- flags implausible
    Sharpe/return figures, a too-thin universe, or an overfitting signature, as a second opinion layered on top
    of (never replacing) the deterministic numbers. Requires ARP_ANTHROPIC_API_KEY. Appends the assessment to
    the run's results.jsonl."""
    store = RunStore(get_settings().runs_dir)
    rows = store.read_jsonl(store.results_path(run_id))
    spec_row = next((r for r in rows if r.get("type") == "spec"), None)
    comparison_row = next((r for r in rows if r.get("type") == "comparison"), None)
    if spec_row is None or comparison_row is None:
        typer.echo(f"No spec/comparison report found for run {run_id}.", err=True)
        raise typer.Exit(1)

    spec = StrategySpec.model_validate({k: v for k, v in spec_row.items() if k != "type"})
    report = ReplicationComparisonReport.model_validate({k: v for k, v in comparison_row.items() if k != "type"})

    settings = get_settings()
    llm = build_llm_client(settings)
    assessment, _usage = asyncio.run(sanity_check_report(spec, report, llm))

    typer.echo(f"Plausible: {assessment.plausible}")
    typer.echo(assessment.summary)
    for f in assessment.findings:
        typer.echo(f"  - [{f.concern}] {f.explanation}")
    store.append_jsonl(store.results_path(run_id), {"type": "sanity_check", **assessment.model_dump(mode="json")})


@replicate_app.command("regime-report")
def replicate_regime_report(
    run_id: str,
    trailing_window_months: int = typer.Option(12, help="Trailing window (in months) used to classify each period's volatility regime from the benchmark series."),
) -> None:
    """Breaks a completed run's in-sample long-short performance out by low/mid/high trailing-volatility regime
    (arp/replication/regime_analysis.py) -- surfaces regime-dependent decay a single full-sample Sharpe ratio can
    hide (see arXiv 2512.12924). Requires the run to have been backtested with --benchmark set (regime
    classification uses the benchmark's own volatility, never the strategy's, to avoid circularity). Appends the
    report to the run's results.jsonl."""
    store = RunStore(get_settings().runs_dir)
    rows = store.read_jsonl(store.results_path(run_id))
    in_sample_row = next((r for r in rows if r.get("type") == "in_sample"), None)
    if in_sample_row is None:
        typer.echo(f"No in-sample result found for run {run_id}.", err=True)
        raise typer.Exit(1)

    in_sample = BacktestResult.model_validate({k: v for k, v in in_sample_row.items() if k != "type"})
    report = regime_stratified_report(in_sample, trailing_window_months=trailing_window_months)
    if not report.buckets:
        typer.echo(report.notes)
        raise typer.Exit(1)
    for bucket in report.buckets:
        typer.echo(
            f"{bucket.regime:>14}: {bucket.num_periods:3d} period(s), annualized_return="
            f"{bucket.long_short.annualized_return_pct}, sharpe={bucket.long_short.sharpe_ratio}"
        )
    typer.echo(report.notes)
    store.append_jsonl(store.results_path(run_id), {"type": "regime_report", **report.model_dump(mode="json")})


@replicate_app.command("pbo")
def replicate_pbo(
    candidate_specs: list[Path] = typer.Option(..., "--candidate-spec", help="StrategySpec JSON for one candidate variant -- repeat for each variant considered (2+ required)."),
    prices: Path = typer.Option(..., help="Wide CSV: a date column + one column per ticker, shared by every candidate."),
    price_kind: str = typer.Option("price", help="'price' (returns are derived) or 'return'."),
    tickers: str = typer.Option(..., help="Comma-separated tickers, or a path to a file with one ticker per line."),
    characteristics: list[str] = typer.Option([], help="'characteristic_name=path.csv', repeatable -- required if any candidate needs one."),
    period_start: str = typer.Option(..., help="ISO date: start of the window split into blocks for cross-validation."),
    period_end: str = typer.Option(..., help="ISO date: end of that window."),
    num_blocks: int = typer.Option(8, help="Number of contiguous blocks the window is split into (must be even; C(num_blocks, num_blocks/2) splits are evaluated)."),
    purge_months: int = typer.Option(None, help="Periods immediately before each test block dropped from training. Defaults to the largest holding_period_months across candidates."),
    embargo_months: int = typer.Option(1, help="Periods immediately after each test block dropped from training."),
    out: Path = typer.Option(None, help="Optionally write the full PBOReport JSON here."),
) -> None:
    """Estimates the Probability of Backtest Overfitting (Bailey, Borwein, Lopez de Prado & Zhu) across 2+
    candidate StrategySpec variants via purged, embargoed Combinatorially Symmetric Cross-Validation
    (arp/replication/cpcv.py) -- a high PBO is a warning about the SELECTION process (picking the best-looking
    variant), not proof any one candidate is broken. Zero LLM calls, deterministic."""
    if len(candidate_specs) < 2:
        typer.echo("--candidate-spec must be given at least twice (2+ variants to compare).", err=True)
        raise typer.Exit(1)

    specs = [_load_spec(p) for p in candidate_specs]
    universe = _load_tickers(tickers)
    source = _price_source(prices, price_kind)
    panel = source.get_monthly_returns(universe, period_start, period_end)
    characteristics_sources = _parse_characteristics_sources(characteristics)
    characteristic_panels = {
        name: src.get_values(universe, period_start, period_end) for name, src in characteristics_sources.items()
    } or None

    try:
        report = run_pbo_analysis(
            specs, panel, period_start=period_start, period_end=period_end,
            num_blocks=num_blocks, purge_months=purge_months, embargo_months=embargo_months,
            characteristics=characteristic_panels,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"PBO = {report.probability_of_backtest_overfitting:.2f} across {report.num_splits} split(s)")
    for spec_id, count in report.per_candidate_selection_count.items():
        typer.echo(f"  {spec_id}: selected as in-sample-best on {count}/{report.num_splits} split(s)")
    typer.echo(report.notes)
    if out:
        out.write_text(report.model_dump_json(indent=2))
        typer.echo(f"Wrote {out}")
