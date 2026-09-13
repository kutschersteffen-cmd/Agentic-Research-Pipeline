# Investment Strategy Replication: methodology

Reviews an academic "outperformance" strategy paper, reduces it to an
executable specification, and backtests it deterministically both
in-sample (against the paper's own reported window) and out-of-sample
(against any later window, run under identical rules) to see whether the
effect holds up or decays. Code lives in `backend/arp/replication/`,
schemas in `backend/arp/schemas/strategy_replication.py`, CLI in
`backend/arp/cli/replication.py` (`arp replicate ...`).

## Why this shape

The rest of this codebase's precision controls (grounded citations,
independent extractor/verifier pairs, a hard programmatic check before any
LLM claim is trusted) exist because LLM output about a source document
can't be trusted unless it's checked against that document. A quant
strategy paper's *methodology* (formation period, holding period,
portfolio construction, reported performance) is exactly this kind of
claim, so **spec extraction reuses the same discipline**: `spec_graph.py`
runs the same gather-evidence → extract → independent-verify → ground →
aggregate flow as every extraction pipeline in `arp/extraction/`, via the
same shared graph shape (`arp/extraction/graph_shape.py`). Every field on
the resulting `StrategySpec` is either grounded in a verbatim quote from
the paper or explicitly flagged `needs_review`.

Once a `StrategySpec` exists, though, **replaying its rules is a pure,
deterministic computation** — deciding which stocks rank into which
decile and what a long-short portfolio returned is arithmetic on price
data, not a judgment call an LLM should ever touch. So the entire backtest
engine (`signals.py`, `backtest_engine.py`, `metrics.py`, `compare.py`) is
zero-LLM, mirroring this codebase's existing "compute deterministically,
gate on human review only where it isn't" pattern (e.g. the input-output
exposure tier, the holdings-overlap engine).

## Pipeline

```
paper text ──▶ spec_graph.py (extract/verify/ground) ──▶ StrategySpec
                                                              │
                                              tickers ──▶ PriceDataSource ──▶ PricePanel
                                                              │                    │
                                                              ▼                    ▼
                                                       backtest_engine.py (in-sample window)
                                                       backtest_engine.py (out-of-sample window)
                                                              │
                                                              ▼
                                                        compare.py ──▶ ReplicationComparisonReport
```

`pipeline.py::run_replication` ties this together and persists every stage
under `runs/<run_id>/results.jsonl` (rows tagged `spec` / `in_sample` /
`out_of_sample` / `comparison`) plus a `manifest.json`, the same file-based
convention every other run type in this codebase uses (`RunStore`) — so
`arp runs list` / `arp runs show` see strategy-replication runs too.

## StrategySpec: what gets extracted

`arp/schemas/strategy_replication.py::StrategySpec` captures: the signal
type, formation/holding periods (in months) and an optional skip month,
number of cross-sectional buckets (deciles/quintiles/...) and which bucket
is long vs. short, weighting scheme, the paper's own sample period, and
its reported long/short/long-short performance (`ReportedPerformance`) —
each figure left `null` rather than guessed if the paper doesn't report it.

A signal is either computed from price history alone (`SignalType.MOMENTUM`:
`formation_period_months`, `skip_month`) or from a fundamental
characteristic (`SignalType.VALUE`: `characteristic_name`,
`characteristic_lag_months`) — see "Two signal families" below for what
each field means and ignores.

Two ways to produce a StrategySpec:

- **`arp replicate extract-spec`** — the grounded extractor/verifier
  pipeline against real paper text. Requires `ARP_ANTHROPIC_API_KEY`. Works
  for either signal family; the extractor's system prompt (`arp/
  replication/spec_extractor_agent.py`) tells it which fields matter for
  which.
- **`arp replicate example <name>`** — a bundled, hand-authored worked
  example:
  - `jegadeesh_titman_1993`: the 6-month formation / 6-month holding
    decile momentum strategy from Jegadeesh & Titman (1993), *Journal of
    Finance* 48(1). Its methodology parameters (6/6 formation, decile
    sort, no skip month, NYSE/AMEX universe, 1965-1989 sample) are
    well-established facts repeated across the momentum literature.
  - `book_to_market_value_premium`: a decile sort on book-to-market,
    long the highest decile (cheap/value) and short the lowest (expensive/
    growth). Unlike the momentum example, there is no single canonical
    "the value paper" to cite the way Jegadeesh & Titman is for momentum —
    this spec is a stylized composite of the classic book-to-market
    literature (Rosenberg, Reid & Lanstein 1985; Fama & French 1992), and
    its `extraction_notes` spells out two specific simplifications: (1)
    this engine only implements monthly rebalancing, so its
    `holding_period_months=12` is approximated as 12 overlapping
    monthly-formed cohorts averaged together rather than the literature's
    typical once-a-year, non-overlapping rebalance; (2)
    `characteristic_lag_months=6` is a reasonable point-in-time-disclosure
    lag, not a value transcribed from either paper.

  Both examples' `reported_performance` figures are **approximate, not
  transcribed from any paper's own tables** — see each spec's own
  `extraction_notes`/`reported_performance.notes`, and its
  `needs_review=True`/lowered `confidence`. Use these to exercise the
  backtest engine end to end, not as ground truth for a paper's exact
  reported numbers.

## Four signal families

`arp/replication/signals.py::compute_signal_scores` dispatches on
`spec.signal_type`:

- **MOMENTUM** (`momentum_scores`): the compounded return over the
  trailing `formation_period_months`, read straight from the same
  `PricePanel` the backtest already needs for realized returns. No extra
  data source required.
- **VALUE** (`value_scores`): the characteristic's own level, looked up
  `characteristic_lag_months` months behind the ranking month from a
  *separate* `CharacteristicPanel` (see "Characteristic data" below) —
  not derived from price history at all. Higher characteristic = higher
  score, so `long_leg_portfolio=1`/`short_leg_portfolio=N` reproduces the
  standard long-value/short-growth construction for something like
  book-to-market.
- **TEXT_SENTIMENT**: mechanically identical to VALUE (same
  `characteristic_name`/`characteristic_lag_months` fields, same
  `CharacteristicPanel` plumbing) — the only difference is *how the panel
  gets built*: `arp/replication/sentiment_scoring.py` scores dated news/
  transcript text via a grounded LLM pass instead of reading a vendor's
  fundamentals feed. Kept as its own `SignalType` (rather than reusing
  VALUE) purely so a spec/report is self-describing about where the
  signal came from — see "LLM-scored sentiment as a characteristic" below
  for the specific precision control this needs that VALUE doesn't.
- **COMPOSITE** (`composite_scores`): combines two or more other signals
  (each a `CompositeSignalComponent` — the same per-signal parameters a
  standalone spec would carry, minus portfolio construction, which is
  decided once at the composite level) via **weighted rank-averaging**:
  each component's raw scores are first converted to a `[0, 1]`
  percentile rank (`_percentile_ranks`) before weighting, since a momentum
  return, a book-to-market ratio, and a bounded sentiment score live on
  incomparable scales and only their relative ordering is meaningful. A
  ticker missing one component (e.g. no sentiment data that period) is
  still scored on the components it does have, using only the weight of
  those — never diluted by an assumed-zero contribution from a component
  it was never eligible for. A component's own `signal_type` may not
  itself be COMPOSITE (no nesting).

All four feed the same `assign_portfolios` (rank into buckets, bucket 1 =
highest score) and the same rebalance-scheduled backtest loop in
`backtest_engine.py` — adding a fifth signal family (quality, low-
volatility, ...) means one new scoring function and one new `SignalType`
branch, not a new engine.

## Characteristic data: the value/sentiment-signal counterpart to price data

`arp/replication/characteristics_data.py::CharacteristicDataSource` is
`PriceDataSource`'s counterpart for VALUE/TEXT_SENTIMENT/COMPOSITE: the
same pluggable-adapter shape, so `signals.py`/`backtest_engine.py` never
talk to a fundamentals (or sentiment) vendor directly.

- **`CsvCharacteristicSource`** (the only implementation so far): a wide
  CSV, one `date` column plus one column per ticker, holding the raw
  characteristic level (e.g. book-to-market ratio, or a sentiment score)
  directly — no return derivation, no index-0-is-always-None convention
  (a characteristic doesn't need a prior period to be defined, unlike a
  return).
- `run_backtest`/`run_replication` take characteristics as a **dict keyed
  by `characteristic_name`** (`arp replicate backtest --characteristics
  book_to_market=bm.csv --characteristics news_sentiment=sent.csv`, one
  entry per name), since a COMPOSITE spec's components may each need a
  different one. `required_characteristic_names(spec)` (in
  `backtest_engine.py`) resolves exactly which names a given spec needs,
  and raises immediately (not a deferred, confusing failure) if a
  VALUE/TEXT_SENTIMENT spec or component has no `characteristic_name` set
  at all.
- Every characteristics panel's `period_ends` must *exactly match* the
  price panel's — a characteristic reported less often than monthly (the
  normal case: book equity is typically an annual figure) is expected to
  already be forward-filled onto the same monthly grid by whoever
  prepares the CSV, rather than this engine trying to reconcile two
  different date grids itself. A mismatch raises a clear `ValueError`
  rather than silently misaligning indices.
- **What this doesn't correct for**: restatements. The CSV's characteristic
  values are trusted as point-in-time exactly as supplied — a real
  point-in-time fundamentals vendor (Compustat, Sharadar) is a
  straightforward second `CharacteristicDataSource` implementation when
  that matters (same "Restated/point-in-time fundamentals" caveat as the
  Price data section below).

## LLM-scored sentiment as a characteristic

`arp/replication/sentiment_scoring.py::build_sentiment_panel` scores one
document per (ticker, period) cell — via `score_document_sentiment`, a
single grounded LLM call bounded to `[-1.0, 1.0]` with a verbatim
supporting quote — and assembles the results into a `CharacteristicPanel`
exactly like a `CsvCharacteristicSource` would produce, so everything
downstream (backtest engine, COMPOSITE) is unaware the data came from an
LLM rather than a vendor feed. Two things distinguish it from a vendor
characteristic:

- **Grounding, not trust**: an ungrounded citation (the model's quote
  doesn't actually appear in the source text) sets that cell to `None`
  rather than keeping an unverifiable score — the same programmatic check
  used everywhere else in this codebase, applied here to an LLM *opinion*
  about a document rather than a fact extracted from one.
- **Temporal contamination / hindsight risk** (the risk Glasserman & Lin
  (2024) describe for pretrained models incorporating information from
  future periods into a historical backtest): the scoring prompt is
  explicitly instructed to score text *only* as a contemporary reader
  would have, using nothing it might separately know about what happened
  to the company afterward. This is a prompt-level mitigation, not a
  provable guarantee — `SentimentScoreRecord.model` records exactly which
  model scored each cell (persist it alongside the panel, `arp replicate
  score-sentiment --records-out ...` writes it out), so a reviewer can at
  least reason explicitly about how much of that model's training window
  overlaps the scored period, instead of the risk being invisible.

`arp replicate score-sentiment --manifest manifest.json --out sentiment.csv`
takes a JSON manifest (`[{ticker, period_end, text, doc_type?}, ...]`) and
writes a characteristics CSV ready for `backtest --characteristics
<name>=sentiment.csv`. Wiring this to ARP's own document-discovery/news
ingestion (`arp/discovery/`, `arp/portfolio/news/`) instead of a
hand-built manifest is a natural next step, not yet done.

## Price data: a pluggable adapter

`arp/replication/price_data.py::PriceDataSource` is the only interface the
signal/backtest code talks to — swapping data vendors never touches
`signals.py`, `backtest_engine.py`, or `metrics.py`.

- **`CsvPriceSource`** (default): a wide CSV, one `date` column plus one
  column per ticker, either raw prices (returns derived period-over-period)
  or already-computed periodic returns. Free, no network, no API key — the
  only source this project's no-network unit tests exercise.
- **`YFinancePriceSource`** (opt-in extra: `pip install -e ".[replication]"`):
  free real-market monthly adjusted-close data via Yahoo Finance.

**What neither of these correct for**, and what a paid point-in-time
vendor (CRSP, Compustat, Sharadar, Bloomberg — a straightforward third
`PriceDataSource` implementation) would:

- **Survivorship bias**: today's ticker list, backtested over history,
  silently excludes delisted/failed/acquired names — biasing results
  upward versus what an investor could have actually traded at the time.
- **Point-in-time universe membership**: a paper's universe ("NYSE
  ordinary common shares") is a historical fact that changes every month;
  this version backtests one fixed `tickers` list the caller supplies
  (`run_replication`'s `tickers` argument), not a reconstruction of the
  paper's exact historical universe at each formation date.
- **Restated/point-in-time fundamentals**: irrelevant to the momentum
  example (pure price signal) but binding for any future value/quality
  signal that reads accounting data — as-reported figures at the time,
  not today's restated numbers, are what a real backtest needs.

## Backtest construction

Only equal weighting is implemented (`backtest_engine.py` raises
`NotImplementedError` for a `weighting` other than equal-weight) — this
applies identically across all four signal families. Rebalance frequency, though, is
fully user-defined: a new decile sort is formed at every valid *rebalance
date*, and each formed portfolio is held for K (`holding_period_months`)
months; a given calendar month's long/short return is the equal-weighted
average, across however many of those portfolios are still within their
holding window, of that month's realized return for the stocks in each
leg.

### Rebalance frequency: fixed presets or a fully custom schedule

`StrategySpec.rebalance_frequency` (`arp/replication/rebalance.py`
resolves it, `backtest_engine.py` consumes the result) is not limited to
three hardcoded choices:

- **MONTHLY / QUARTERLY / ANNUAL** imply a fixed interval of 1/3/12
  months.
- **CUSTOM** reads `rebalance_interval_months` directly — any positive
  integer, so a paper with an oddball cadence (every 2 months, every 18
  months) is a spec field, not a new enum member or a code change.
- **`rebalance_anchor_month`** (optional, 1=Jan..12=Dec, any frequency)
  anchors rebalances to a specific calendar month instead of simply every
  `interval` months counted from the start of the fetched panel —
  `rebalance_frequency=ANNUAL, rebalance_anchor_month=6` reproduces the
  classic Fama & French June-aligned annual rebalance exactly;
  `rebalance_anchor_month=2` with `QUARTERLY` rebalances every
  February/May/August/November instead of whatever quarter boundary the
  panel happens to start on. If the anchor month never occurs in the
  fetched panel (e.g. a window shorter than a year), `run_backtest` warns
  and simply produces no periods, rather than silently rebalancing on the
  wrong months.

The interval-and-rebalance-date resolution is a small, independently
tested pure function (`resolve_rebalance_interval_months`,
`resolve_rebalance_months` in `arp/replication/rebalance.py`) that
`run_backtest` calls once per invocation; the main backtest loop itself
doesn't know or care whether it's looking at a monthly, quarterly, annual,
or custom schedule — it only asks "was `f` a valid rebalance date, and is
it still within its holding window at month `m`?" This is what lets one
`rebalance_interval_months`/`holding_period_months` pair reproduce either
end of the spectrum with the exact same code path:

- **interval = 1** (with K > 1): Jegadeesh & Titman (1993)'s own
  overlapping-portfolio construction — up to K portfolios active at once,
  averaged together, which is what lets a monthly return series exist even
  though any one portfolio only re-ranks every K months.
- **interval = K**: a standard **non-overlapping** rebalance — exactly one
  portfolio active at a time. This is what the `book_to_market_value_premium`
  worked example now uses (`rebalance_frequency=ANNUAL,
  rebalance_anchor_month=6, holding_period_months=12`) to reproduce the
  classic annual, June-aligned value-factor rebalance genuinely, rather
  than the monthly-overlapping approximation of it this example used
  before `rebalance_anchor_month`/interval-based scheduling existed.
- **1 < interval < K**: a mix — fewer than K overlapping cohorts active at
  once.

`run_backtest` takes one `PricePanel` (and, for a characteristic-based
signal, a dict of `CharacteristicPanel`s keyed by name) covering both the
in-sample and out-of-sample windows (plus the lookback) and a
`period_start`/`period_end` per call —
it restricts which months are *emitted* as output to that window while
still using earlier months in the same panel for lookback, so two calls
(in-sample, out-of-sample) share one fetch and one formation cache instead
of needing separately-windowed panels.

## Metrics

`metrics.py::compute_leg_performance` reports, per leg (long/short/
long-short): geometric (CAGR-style) annualized return, annualized
volatility, Sharpe ratio, a t-statistic on the mean monthly return,
max drawdown from the compounded path, and (given a benchmark series)
CAPM-style alpha/beta via a simple OLS fit. A near-zero-but-not-exactly-
zero volatility (float64 noise on a genuinely constant series, ~1e-17)
is treated as zero rather than producing an absurd Sharpe ratio or beta —
see `_ZERO_VOLATILITY_EPSILON`.

## In-sample vs. out-of-sample, and the verdict

`compare.py::build_comparison_report` compares the in-sample backtest
against `StrategySpec.reported_performance`, then (if an out-of-sample
result is supplied) checks whether the effect persists:

| Verdict | Meaning |
|---|---|
| `replicated` | In-sample long-short return is statistically significant, positive, and within a documented magnitude tolerance of the paper's own reported figure (or the paper reported no figure to compare against). |
| `partially_replicated` | Same sign as the paper, but a material magnitude gap. |
| `not_replicated` | Wrong sign, or not statistically distinguishable from zero in-sample. |
| `decayed_out_of_sample` | Replicated in-sample, but the out-of-sample window is insignificant, non-positive, or a material downgrade — usually the finding of most interest for an "outperformance" claim. |
| `insufficient_data` | Fewer than `MIN_PERIODS_FOR_A_VERDICT` (12) monthly observations. |

The thresholds (`MIN_SIGNIFICANT_T_STAT=2.0`, `MIN_PERIODS_FOR_A_VERDICT=12`,
`FULL_REPLICATION_MAGNITUDE_RATIO=0.5`) are reasonable, disclosed starting
points — not empirically tuned against a labeled set of replication
outcomes, the same caveat this codebase states for its other threshold
constants (e.g. `Settings.arbitration_*`).

## Provenance

`StrategySpec.provenance` (a `ProvenanceInfo`, the same type
`ExtractedField` carries elsewhere in this codebase) records which
extractor/verifier model and system-prompt hash produced a spec from
`arp replicate extract-spec` — left at its all-`None` default for a
hand-authored spec (the bundled examples, or one you write by hand). A
later prompt or model change is then detectable against a previously
persisted spec instead of silently mixing pipeline versions, the same
reasoning the rest of this codebase already applies to every extraction.

## Golden set: behavioural equivalence tests for the backtest engine

Everything in `signals.py`/`backtest_engine.py`/`rebalance.py`/
`metrics.py` is deterministic, which cuts both ways: there's no
inherent randomness to worry about, but also no test-time signal that a
refactor silently changed *what a given input computes to*.
`arp/replication/golden_set.py` (`arp replicate golden-set`) is this
codebase's existing golden-set pattern (`arp golden_set/`, used for LLM
extraction) applied to that risk: a small set of fixed
`(StrategySpec, PricePanel, CharacteristicPanel*)` inputs with a captured,
reviewed expected `long_short.annualized_return_pct`/period count, run
before a change to any of those four modules ships. Unlike the
extraction golden set (compared against a human-verified real answer),
"known-correct" here means "captured from a reviewed run and guarded
against silent drift" — the same spirit as a snapshot test, appropriate
for code with no LLM variance to average out. The two bundled cases cover
the two structurally distinct rebalance code paths this module has (a
1-month-interval overlapping construction, and an interval-equals-K
non-overlapping one) — add a case here whenever a change touches either
path, or introduces a new signal family.

## Sanity-check pass: a qualitative second opinion

`arp/replication/sanity_check.py` (`arp replicate sanity-check <run_id>`)
sends a completed `ReplicationComparisonReport`'s key figures (universe
size, period counts, in/out-of-sample Sharpe/return/t-stat, the verdict)
to an LLM instructed to flag anything a seasoned quant would find
suspicious: an implausible Sharpe or annualized return, a too-thin
universe or leg, a classic overfitting signature (dramatic in-sample vs.
out-of-sample gap combined with many free parameters), or reported
performance that suspiciously exactly matches the replication. This is
the AFI ("augment, never replace") pattern applied to this module's own
output — the assessment is advisory only, appended to the run's
`results.jsonl` as its own row (`type=sanity_check`), and never mutates
or overrides the deterministic numbers it reviews. There is no grounding
check here (unlike every other LLM call in this codebase): a sanity check
is an opinion about whether a set of numbers looks plausible, not a fact
extracted from a source document, so there's nothing to check a quote
against — `SanityCheckAssessment`'s own docstring says this explicitly.

## Literature discovery: proposing candidate papers

`arp/replication/paper_discovery.py` (`arp replicate discover-papers
"<topic>"`) closes the loop back toward this module's original purpose —
*finding* papers to replicate, not just replicating ones already in hand.
It mirrors the Taxonomy Researcher's shape exactly
(`arp/agents/taxonomy_researcher.py`): `discover_candidate_papers`
searches a `WebSearchClient` (the same interface/DuckDuckGo fallback
`arp/discovery/site_finder.py` already provides) with a handful of varied
query templates and dedupes by URL; `rank_candidate_papers` sends the
results (title/URL/snippet only — never the paper itself) to an LLM that
scores each for replication-worthiness (a specific, testable claim;
plausibly replicable with price/one-fundamental-ratio/text data; a real
academic/practitioner source) and guesses a `suggested_signal_type` as a
starting hint. Nothing is fetched, read, or turned into a `StrategySpec`
automatically — candidates are written to a JSON file for a human to
review and pick from, the same "propose, never auto-apply" discipline as
every other discovery/research agent in this codebase. Feeding a chosen
candidate's actual full text into `arp replicate extract-spec` is a
separate, deliberate next step. A persistent background scheduler (like
`TaxonomyResearcherScheduler`) would be a natural extension but doesn't
exist yet — this is on-demand only today.

## Known limitations / next steps

- MOMENTUM, VALUE, TEXT_SENTIMENT, and COMPOSITE are implemented; quality/
  low-volatility/size are new `SignalType`s and scoring functions in
  `signals.py`, not a redesign (they'd likely reuse `CharacteristicDataSource`
  exactly as VALUE/TEXT_SENTIMENT do, and could be combined into a
  COMPOSITE spec immediately once they exist).
- Rebalance frequency is fully flexible (see "Backtest construction"
  above) but every rebalance date still shares one fixed `holding_period_
  months`/`num_portfolios`/leg-selection for the whole sample — a paper
  that changes its own methodology partway through its sample (rare, but
  not unheard of) would need two specs and two backtests stitched
  together, not a single run.
- No transaction-cost or turnover modeling yet
  (`BacktestResult.monthly_turnover_pct` is reserved but unset).
- No point-in-time universe reconstruction, survivorship-bias handling, or
  restatement-aware fundamentals (see "Price data" and "Characteristic
  data" above) — a real quant-research use of this beyond a worked example
  needs point-in-time vendors behind new `PriceDataSource`/
  `CharacteristicDataSource` implementations.
- Equal weighting only; value-weighting is declared in the schema
  (`WeightingScheme.VALUE` — market-cap weighting in the standard finance
  sense, unrelated to `SignalType.VALUE`) but not yet implemented in
  `backtest_engine.py`.
- `score-sentiment` takes a hand-built JSON manifest, not a live feed from
  ARP's own document-discovery/news infrastructure (`arp/discovery/`,
  `arp/portfolio/news/`) — wiring those together is a natural next step.
- `discover-papers` is on-demand only; a persistent background scheduler
  (mirroring `TaxonomyResearcherScheduler`) that periodically re-scans
  topics and accumulates candidates over time doesn't exist yet.
- `StrategySpecDraft`/the extractor prompt don't cover COMPOSITE specs --
  a composite spec is assembled by hand today (or by combining two
  already-extracted specs' components), not extracted from one paper in
  one pass.
