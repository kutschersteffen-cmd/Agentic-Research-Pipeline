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

## Two signal families

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

Both feed the same `assign_portfolios` (rank into buckets, bucket 1 =
highest score) and the same overlapping-portfolio backtest loop in
`backtest_engine.py` — adding a third signal family (quality, low-
volatility, ...) means one new scoring function and one new
`SignalType` branch, not a new engine.

## Characteristic data: the value-signal counterpart to price data

`arp/replication/characteristics_data.py::CharacteristicDataSource` is
`PriceDataSource`'s counterpart for VALUE (and any future
characteristic-based signal): the same pluggable-adapter shape, so
`signals.py`/`backtest_engine.py` never talk to a fundamentals vendor
directly.

- **`CsvCharacteristicSource`** (the only implementation so far): a wide
  CSV, one `date` column plus one column per ticker, holding the raw
  characteristic level (e.g. book-to-market ratio) directly — no return
  derivation, no index-0-is-always-None convention (a characteristic
  doesn't need a prior period to be defined, unlike a return).
- `run_backtest` and `run_replication` both require the characteristics
  panel's `period_ends` to *exactly match* the price panel's — a
  characteristic reported less often than monthly (the normal case: book
  equity is typically an annual figure) is expected to already be
  forward-filled onto the same monthly grid by whoever prepares the CSV,
  rather than this engine trying to reconcile two different date grids
  itself. A mismatch raises a clear `ValueError` rather than silently
  misaligning indices.
- **What this doesn't correct for**: restatements. The CSV's characteristic
  values are trusted as point-in-time exactly as supplied — a real
  point-in-time fundamentals vendor (Compustat, Sharadar) is a
  straightforward second `CharacteristicDataSource` implementation when
  that matters (same "Restated/point-in-time fundamentals" caveat as the
  Price data section below).

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

Only monthly rebalancing and equal weighting are implemented today
(`backtest_engine.py` raises `NotImplementedError` for any other
`rebalance_frequency` or a `weighting` other than equal-weight) — this
applies identically to MOMENTUM and VALUE. The construction is Jegadeesh &
Titman (1993)'s own overlapping-portfolio design: a new decile sort is
formed every month from that month's signal score (whatever
`compute_signal_scores` returns for the spec's `signal_type`), and a
formed portfolio is held for K months. A given calendar month's long/short
return is the equal-weighted average, across the up to K portfolios
currently being held, of that month's realized return for the stocks in
each leg — what produces a monthly return series even though any one
portfolio only re-ranks every K months.

Applying this same monthly-overlapping construction to a VALUE spec is a
**deliberate simplification**: the classic value-factor literature
typically re-ranks once a year (often June-aligned, to respect fiscal
reporting lags), not every month. `holding_period_months=12` under this
engine's monthly-rebalance convention approximates that as 12 overlapping
monthly-formed cohorts rather than one static annual portfolio — see the
`book_to_market_value_premium` example's `extraction_notes` for this
spelled out against a real, if composite, strategy. A true annual
(non-overlapping) `RebalanceFrequency.ANNUAL` path is a natural next
extension (see "Known limitations" below).

`run_backtest` takes one `PricePanel` (and, for VALUE, one
`CharacteristicPanel`) covering both the in-sample and out-of-sample
windows (plus the lookback) and a `period_start`/`period_end` per call —
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

## Known limitations / next steps

- MOMENTUM and VALUE are implemented; quality/low-volatility/size are new
  `SignalType`s and scoring functions in `signals.py`, not a redesign
  (quality/size would likely reuse `CharacteristicDataSource` exactly as
  VALUE does).
- Only monthly rebalancing is implemented; a true annual, non-overlapping
  `RebalanceFrequency.ANNUAL` path (needed to faithfully replicate the
  value-factor literature's typical June-aligned rebalance, rather than
  this engine's monthly-overlapping approximation of it) is a new
  `backtest_engine.py` code path, not a new signal.
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
