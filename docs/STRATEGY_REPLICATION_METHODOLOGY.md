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

Two ways to produce one:

- **`arp replicate extract-spec`** — the grounded extractor/verifier
  pipeline against real paper text. Requires `ARP_ANTHROPIC_API_KEY`.
- **`arp replicate example <name>`** — a bundled, hand-authored worked
  example (currently `jegadeesh_titman_1993`, the 6-month formation /
  6-month holding decile momentum strategy from Jegadeesh & Titman (1993),
  *Journal of Finance* 48(1)). Its methodology parameters (6/6 formation,
  decile sort, no skip month, NYSE/AMEX universe, 1965-1989 sample) are
  well-established facts repeated across the momentum literature; its
  `reported_performance` figures are **approximate, not transcribed from
  the paper's own tables** — see the spec's own `extraction_notes` and
  `reported_performance.notes`, and its `needs_review=True`/lowered
  `confidence`. Use this to exercise the backtest engine end to end, not
  as ground truth for the paper's exact reported numbers.

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

Only momentum-style signals and monthly rebalancing are implemented today
(`SignalType.MOMENTUM` in `signals.py`; `backtest_engine.py` raises
`NotImplementedError` for any other `rebalance_frequency` or a
`weighting` other than equal-weight). The construction is Jegadeesh &
Titman (1993)'s own overlapping-portfolio design: a new decile sort is
formed every month from the trailing J-month return (skipping the most
recent month first, if the spec says so), and a formed portfolio is held
for K months. A given calendar month's long/short return is the
equal-weighted average, across the up to K portfolios currently being
held, of that month's realized return for the stocks in each leg — what
produces a monthly return series even though any one portfolio only
re-ranks every K months.

`run_backtest` takes one `PricePanel` covering both the in-sample and
out-of-sample windows (plus the formation lookback) and a `period_start`/
`period_end` per call — it restricts which months are *emitted* as output
to that window while still using earlier months in the same panel for
formation-window lookback, so two calls (in-sample, out-of-sample) share
one fetch and one formation cache instead of needing separately-windowed
panels.

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

- Only momentum-style signals and monthly rebalancing are implemented;
  value/quality/low-volatility/quarterly-or-annual rebalancing are new
  `SignalType`s and `RebalanceFrequency` branches, not a redesign.
- No transaction-cost or turnover modeling yet
  (`BacktestResult.monthly_turnover_pct` is reserved but unset).
- No point-in-time universe reconstruction or survivorship-bias handling
  (see "Price data" above) — a real quant-research use of this beyond a
  worked example needs a point-in-time vendor behind a new
  `PriceDataSource`.
- Equal weighting only; value-weighting is declared in the schema
  (`WeightingScheme.VALUE`) but not yet implemented in `backtest_engine.py`.
