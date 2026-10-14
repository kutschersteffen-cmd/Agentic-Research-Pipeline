# Signals workbench, plan 1: evidence core and experiment registry

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a score panel and a price panel, produce honest evidence (rank-IC, in-window versus post-cutoff split, costs, deflated Sharpe, overlap with baseline signals), register the experiment with its trial count, and gate graduation, from the CLI.

**Architecture:** A new package `backend/arp/signal_lab/` holds pure functions (cutoffs, statistics, evidence, comparison) and one `Registry` class that stores experiments as rows of a single long-lived run in the existing run store. The replication backtest engine gains cost and turnover. No new tables, no UI, no new signal methods.

**Tech Stack:** Python 3.11, numpy only (the repo has no scipy or pandas), pydantic v2, typer, the existing `RunStore` (Postgres).

**Spec:** `docs/superpowers/specs/2026-10-14-signals-workbench-design.md` (approved 2026-10-14). Lab context: `docs/superpowers/specs/2026-10-14-rd-lab-overview-design.md`.

## Roadmap (this is plan 1 of 5)

1. **This plan:** evidence core and registry.
2. Point-in-time text store, vendor adapters (CSV first), full-text Thomson Reuters ingestion.
3. Methods interface and methods (embeddings head, topics, learned lexicon, search variant, transforms).
4. Notebook library.
5. App screens and API.

Not in this plan: value-weighted backtest (needs market caps), rerun stability and leakage report (need the LLM methods of plan 3), neutralisation, any UI.

## Global Constraints

- Python `>=3.11`; every module starts with `from __future__ import annotations`.
- numpy only for statistics. Do not add scipy, pandas, statsmodels or scikit-learn in this plan.
- Dates are ISO strings (`YYYY-MM-DD`); panel period-ends are compared as strings.
- Training-cutoff rule: a period counts as evidence only if `period_end > cutoff` (strictly). A period exactly on the cutoff is `in_window`. A model with no recorded cutoff is `in_window` for every period (contaminated). `model=None` means no model is involved and every period is `post_cutoff`.
- A graduated experiment must have a `post_cutoff` window with at least 12 monthly IC observations. Otherwise `decide(..., "graduate")` raises `ValueError`.
- "insufficient_data" is a valid result. Never force an order.
- Default `cost_bps` is 10.0 per side on traded weight (a default the owner has not confirmed; keep it a parameter).
- Backend checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`. Tests that touch `RunStore` need `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test` (Postgres is running in the cloud container; the `pg` fixture is in `tests/conftest.py`).
- Never delete or weaken an existing test. List every test change in the PR description (this plan changes none).
- Comments only for the why. Do not touch adjacent code.

## Review Focus

Failure modes the spec implies but a task's happy path would not exercise, most likely first. Each has a test in the task that owns the code.

1. Cutoff file missing, or model not in it: every period is `in_window` and graduation is refused. (Task 1, Task 6)
2. A month with fewer than 10 scored names, or with constant scores: skipped, never reported as IC 0. (Task 2)
3. A period exactly on the cutoff date is `in_window`. (Task 1)
4. Registering the same experiment twice must not add a trial. (Task 6)
5. `cost_bps=0` must make net equal gross, and a held-constant portfolio must show zero turnover after the first month. (Task 4)

## File structure

| File | Responsibility |
|---|---|
| `backend/arp/signal_lab/__init__.py` | empty |
| `backend/arp/signal_lab/cutoffs.py` | training-cutoff table and the window label |
| `backend/arp/signal_lab/stats.py` | rank-IC, Newey-West t, IC summary, cross-correlation, paired comparison |
| `backend/arp/signal_lab/evidence.py` | `evaluate_signal` and the evidence models |
| `backend/arp/signal_lab/baselines.py` | price-momentum panel for overlap checks |
| `backend/arp/signal_lab/registry.py` | `Recipe`, `ExperimentRecord`, `Registry` |
| `backend/arp/cli/signal_lab.py` | `arp signals evaluate | list | decide` |
| `backend/arp/replication/backtest_engine.py` | modify: `cost_bps`, turnover, net series |
| `backend/arp/schemas/strategy_replication.py` | modify: `BacktestResult.net_long_short` |
| `backend/arp/config.py` | modify: `training_cutoffs_path` |
| `backend/arp/cli/__init__.py` | modify: register the `signals` typer |
| `backend/tests/test_signal_lab_*.py`, `backend/tests/test_replication_costs.py` | new tests |

---

### Task 1: Training-cutoff table

**Files:**
- Create: `backend/arp/signal_lab/__init__.py`, `backend/arp/signal_lab/cutoffs.py`
- Modify: `backend/arp/config.py` (add `training_cutoffs_path: Path = Field(default=REPO_ROOT / "data" / "training_cutoffs.json")` next to the other `data/` paths, around line 74)
- Test: `backend/tests/test_signal_lab_cutoffs.py`

**Interfaces:**
- Produces:
  - `class CutoffTable` with `entries: dict[str, ModelCutoff]`, `cutoff_for(model: str) -> str | None`
  - `class ModelCutoff(BaseModel)`: `cutoff: str`, `source: str`
  - `load_cutoff_table(path: Path) -> CutoffTable` (a missing file returns an empty table)
  - `period_window(model: str | None, period_end: str, table: CutoffTable) -> Literal["in_window", "post_cutoff"]`

- [ ] **Step 1: Write the failing tests** in `test_signal_lab_cutoffs.py`:
  - `test_post_cutoff_is_strictly_after`: table `{"m": ModelCutoff(cutoff="2024-06-30", source="x")}`; `period_window("m", "2024-07-01", t) == "post_cutoff"`; `period_window("m", "2024-06-30", t) == "in_window"` (Review Focus 3).
  - `test_unknown_model_is_contaminated`: `period_window("other", "2030-01-01", empty) == "in_window"` (Review Focus 1).
  - `test_no_model_is_post_cutoff`: `period_window(None, "1999-01-01", empty) == "post_cutoff"`.
  - `test_load_missing_file_is_empty`: `load_cutoff_table(tmp_path / "nope.json").entries == {}`.
  - `test_load_reads_entries`: write `{"m": {"cutoff": "2024-06-30", "source": "doc"}}`; `cutoff_for("m") == "2024-06-30"`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_signal_lab_cutoffs.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the signatures above in `cutoffs.py`. The JSON file maps model name to `{"cutoff", "source"}`. Add the `Settings` field. Do not create `data/training_cutoffs.json`: the owner supplies the dates.
- [ ] **Step 4: Run the tests and `ruff check .`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): training-cutoff table and window label`.

### Task 2: Rank-IC and robust significance

**Files:**
- Create: `backend/arp/signal_lab/stats.py`
- Test: `backend/tests/test_signal_lab_stats.py`

**Interfaces:**
- Consumes: `CharacteristicPanel`, `PricePanel` from `arp.replication` (`period_ends`, `values` or `returns`, as in `characteristics_data.py` and `price_data.py`).
- Produces:
  - `spearman(x: list[float], y: list[float]) -> float | None` (average ranks for ties; `None` if either side is constant or fewer than 3 points)
  - `rank_ic_series(scores: CharacteristicPanel, prices: PricePanel, *, forward_months: int = 1, min_names: int = 10) -> list[tuple[str, float]]` (pairs `(score period_end, IC)`; the score at index `i` is paired with the return at index `i + forward_months`; months with fewer than `min_names` names that have both values, or with undefined IC, are skipped)
  - `newey_west_t(values: list[float], lags: int | None = None) -> float | None` (t-statistic of the mean with a Bartlett-kernel HAC variance; default `lags = int(4 * (n / 100) ** (2 / 9))`; `None` if `n < 3` or variance is not positive)
  - `class IcSummary(BaseModel)`: `n: int`, `mean: float | None`, `t_nw: float | None`, `hit_rate: float | None`
  - `summarize_ic(series: list[tuple[str, float]]) -> IcSummary`

- [ ] **Step 1: Write the failing tests:**
  - `test_spearman_perfect_and_inverse`: `spearman([1,2,3,4],[10,20,30,40]) == 1.0` and `[-1.0]` for reversed; ties handled: `spearman([1,1,2,3],[1,2,3,4])` is between 0 and 1.
  - `test_spearman_constant_is_none`.
  - `test_rank_ic_skips_thin_and_constant_months` (Review Focus 2): 12 tickers, 4 months, month 2 has only 5 scored names, month 3 has all-equal scores; expect those two months absent from the result.
  - `test_rank_ic_uses_forward_return`: scores equal to next month's return rank give IC 1.0 for every scored month.
  - `test_newey_west_matches_plain_t_for_iid`: with `numpy.random.default_rng(0).normal(0.1, 1, 400)`, `abs(newey_west_t(x) - plain_t) < 0.3` where `plain_t = mean / (std(ddof=1) / sqrt(n))`.
  - `test_newey_west_lower_for_autocorrelated`: an AR(1) series (`phi=0.7`, seed 0, n=400) has `abs(t_nw) < abs(plain_t)`.
  - `test_summarize_ic_hit_rate`: `[("a",0.1),("b",-0.05),("c",0.2)]` gives `n=3`, `hit_rate == 2/3`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_signal_lab_stats.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the signatures above. Ranks via `numpy.argsort` with average ranks for ties (no scipy).
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): rank-IC and Newey-West significance`.

### Task 3: Overlap and paired comparison

**Files:**
- Modify: `backend/arp/signal_lab/stats.py`
- Create: `backend/arp/signal_lab/baselines.py`
- Test: `backend/tests/test_signal_lab_stats.py` (append), `backend/tests/test_signal_lab_baselines.py`

**Interfaces:**
- Consumes: `momentum_scores(panel: PricePanel, formation_idx: int, formation_period_months: int, skip_month: bool) -> dict[str, float]` from `arp.replication.signals`.
- Produces:
  - `mean_cross_correlation(a: CharacteristicPanel, b: CharacteristicPanel, *, min_names: int = 10) -> float | None` (mean over months of the cross-sectional Spearman; `None` if no month qualifies; panels must share `period_ends`, else `ValueError`)
  - `compare_signals(a: list[float], b: list[float], *, n_comparisons: int, confidence: float = 0.95, n_boot: int = 2000, seed: int = 0, min_periods: int = 12) -> Literal["a_higher", "b_higher", "insufficient_data"]` (`a` and `b` are aligned monthly long-short returns; `ValueError` if lengths differ; paired bootstrap of the mean difference; two-sided level `alpha = (1 - confidence) / max(1, n_comparisons)`; ordered only if the interval excludes zero)
  - `momentum_panel(prices: PricePanel, *, formation_period_months: int = 12, skip_month: bool = True) -> CharacteristicPanel` (`source="price_momentum"`; months with no score get `None`)

- [ ] **Step 1: Write the failing tests:**
  - `test_cross_correlation_identical_panels_is_one` and `test_cross_correlation_mismatched_grids_raises`.
  - `test_compare_clear_difference`: `a = [1.0 + noise]*60`, `b = [0.0 + noise]*60` with seed-0 noise of sd 0.5: `"a_higher"`.
  - `test_compare_indistinguishable_is_insufficient`: two seed-0 noise series with equal mean: `"insufficient_data"`.
  - `test_compare_too_few_periods`: 6 periods gives `"insufficient_data"` regardless of values.
  - `test_compare_more_comparisons_is_harder`: a modest difference that is `"a_higher"` with `n_comparisons=1` becomes `"insufficient_data"` with `n_comparisons=50` (pick the series so this holds with seed 0; adjust the effect size, not the rule).
  - `test_momentum_panel_matches_signals`: on a 24-month synthetic `PricePanel`, `momentum_panel(...).values[t][i] == momentum_scores(panel, i, 12, True)[t]` where defined.
- [ ] **Step 2: Run** the two test files. Expected: FAIL.
- [ ] **Step 3: Implement.** Bootstrap with `numpy.random.default_rng(seed)`, resampling pair indices.
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): overlap, momentum baseline, paired comparison`.

### Task 4: Costs and turnover in the backtest engine

**Files:**
- Modify: `backend/arp/replication/backtest_engine.py` (`run_backtest`), `backend/arp/schemas/strategy_replication.py` (`BacktestResult`)
- Test: `backend/tests/test_replication_costs.py`

**Interfaces:**
- Consumes: the existing `run_backtest(spec, panel, *, period_label, period_start, period_end, benchmark_returns=None, characteristics=None, allowed_period_ends=None) -> BacktestResult`.
- Produces: `run_backtest(..., cost_bps: float = 0.0)`; `BacktestResult.net_long_short: LegPerformance | None = None`; `BacktestResult.monthly_turnover_pct` now filled.

Definitions to implement: each month, a leg's weight on a ticker is the mean, across the formation portfolios active that month, of `1 / len(bucket)` if the ticker is in that portfolio's leg, else 0. Traded weight for the month is the sum over both legs of `|w_t - w_{t-1}|`, with `w_{t-1}` of the previous emitted month (the first emitted month trades the full weight, 2.0). Net long-short return for the month is `long_short - cost_bps / 10000 * traded_weight` (in return units, then converted to percent like the rest). `monthly_turnover_pct` is the mean traded weight divided by 2, times 100. When `cost_bps == 0.0`, `net_long_short` is left `None` (gross only) and the existing results are unchanged.

- [ ] **Step 1: Write the failing tests** (build the synthetic panel the way `tests/test_replication_pipeline.py::_write_prices_csv` does, or construct `PricePanel` directly):
  - `test_zero_cost_leaves_results_unchanged`: result with `cost_bps=0.0` equals the result of today's call field for field, and `net_long_short is None`.
  - `test_net_equals_gross_minus_cost`: with `cost_bps=10`, for each period `net_ls_return_pct == gross_ls_return_pct - 10/10000 * traded_weight * 100` (expose per-period traded weight on `PortfolioPeriodReturn.traded_weight: float | None = None`).
  - `test_constant_portfolio_has_zero_turnover_after_first_month` (Review Focus 5): with deterministic winners and losers, a 1-month hold and `CUSTOM` rebalance every month, traded weight after the first emitted month is 0.0 and `monthly_turnover_pct` is small and positive (first month included).
  - `test_cost_reduces_net_return`: `net_long_short.monthly_mean_return_pct < long_short.monthly_mean_return_pct`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_replication_costs.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the weights, traded weight and net series inside `run_backtest`; add the two schema fields (`net_long_short`, `PortfolioPeriodReturn.traded_weight`).
- [ ] **Step 4: Run** the new tests and the whole replication suite: `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python3 -m pytest tests -q -k "replication"` and `ruff check .`. Expected: PASS, no existing test changed.
- [ ] **Step 5: Commit** `feat(replication): transaction costs and turnover in the backtest`.

### Task 5: Window evidence

**Files:**
- Create: `backend/arp/signal_lab/evidence.py`
- Test: `backend/tests/test_signal_lab_evidence.py`

**Interfaces:**
- Consumes: `period_window`, `CutoffTable` (Task 1); `rank_ic_series`, `summarize_ic`, `IcSummary`, `mean_cross_correlation` (Tasks 2, 3); `run_backtest(..., cost_bps, allowed_period_ends)` (Task 4); `deflated_sharpe_ratio(monthly_returns_pct, *, n_trials) -> DeflatedSharpeAssessment`.
- Produces:
  - `class WindowEvidence(BaseModel)`: `window: Literal["in_window", "post_cutoff"]`, `periods: int`, `ic: IcSummary`, `long_short: LegPerformance | None`, `net_long_short: LegPerformance | None`, `monthly_turnover_pct: float | None`, `deflated_sharpe: DeflatedSharpeAssessment | None`
  - `class EvidenceReport(BaseModel)`: `windows: list[WindowEvidence]`, `contamination_gap_ic: float | None` (mean IC in-window minus post-cutoff, `None` unless both exist), `overlap: dict[str, float | None]`, `n_trials: int`
  - `evaluate_signal(scores: CharacteristicPanel, prices: PricePanel, spec: StrategySpec, *, model: str | None, cutoffs: CutoffTable, cost_bps: float = 10.0, n_trials: int = 1, baselines: dict[str, CharacteristicPanel] | None = None, forward_months: int = 1) -> EvidenceReport`
  - `sentiment_spec(characteristic_name: str, *, start: str, end: str, num_portfolios: int = 5) -> StrategySpec` (a `TEXT_SENTIMENT` spec with `holding_period_months=1`, `characteristic_lag_months=0`, `long_leg_portfolio=1`, `short_leg_portfolio=num_portfolios`, and placeholder paper fields saying "lab experiment")

Rules: split `scores.period_ends` within `[spec.sample_period_start, spec.sample_period_end]` by `period_window`; a window with no periods is omitted. For each window run `run_backtest(..., allowed_period_ends=<that window's periods>, cost_bps=cost_bps)` and `rank_ic_series` restricted to those periods. `deflated_sharpe` uses the net series when `net_long_short` exists, else the gross one, with `n_trials`.

- [ ] **Step 1: Write the failing tests** with a synthetic 60-month, 20-ticker panel where the score equals the next month's return plus noise (so IC is clearly positive):
  - `test_unknown_model_has_only_in_window_evidence` (Review Focus 1).
  - `test_split_at_cutoff`: model cutoff in the middle of the panel gives both windows, and the periods in each window are disjoint and union to the sample.
  - `test_no_model_is_all_post_cutoff`.
  - `test_contamination_gap`: scores that are strong only before the cutoff give `contamination_gap_ic > 0`.
  - `test_overlap_reported`: passing `baselines={"momentum": momentum_panel(prices)}` yields a float for `"momentum"`.
  - `test_trials_flow_into_deflated_sharpe`: `n_trials=50` gives a lower `deflated_sharpe.deflated_sharpe_ratio` than `n_trials=1` on the same data.
- [ ] **Step 2: Run** and confirm FAIL.
- [ ] **Step 3: Implement** the models and `evaluate_signal` / `sentiment_spec` as specified.
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): window-split evidence report`.

### Task 6: Experiment registry

**Files:**
- Create: `backend/arp/signal_lab/registry.py`
- Test: `backend/tests/test_signal_lab_registry.py` (uses the `pg` fixture)

**Interfaces:**
- Consumes: `RunStore.load_manifest/save_manifest/append_result/read_results`; `RunManifest(run_id, run_type, status)`; `JobStatus.RUNNING`; `EvidenceReport` (Task 5).
- Produces:
  - `SIGNAL_REGISTRY_RUN_ID = "signal_registry"`
  - `class Recipe(BaseModel)`: `category: Literal["sentiment_narrative", "earnings_call_tone", "fundamental", "price_momentum", "analyst_revisions"]`, `method: str`, `text_source: str | None`, `params: dict`, `universe: str`, `window_start: str`, `window_end: str`, `forward_months: int = 1`, `cost_bps: float = 10.0`
  - `class ExperimentRecord(BaseModel)`: `experiment_id: str`, `recipe: Recipe`, `data_version: str`, `model: str | None`, `evidence: EvidenceReport`, `created_at: str`, `decision: Literal["none", "graduate", "shelve"] = "none"`, `decided_by: str | None`, `decided_at: str | None`
  - `class Registry`: `__init__(self, store: RunStore)`; `register(recipe, evidence, *, data_version: str, model: str | None) -> ExperimentRecord`; `list_experiments() -> list[ExperimentRecord]` (decisions applied, latest wins); `trial_count(recipe: Recipe) -> int` (registered experiments with the same category, universe, window_start and window_end); `decide(experiment_id: str, decision: Literal["graduate", "shelve"], *, approver: str) -> ExperimentRecord`
  - `experiment_id` is the first 16 hex characters of the SHA-256 of the canonical JSON of `(recipe, data_version, model)`.

Rules: `register` creates the registry run on first use (`save_manifest` of a `RunManifest` with `run_type="signal_registry"` and status `RUNNING`), appends a row with `_key = f"experiment:{experiment_id}"` (re-registering is a no-op, so no extra trial), and writes the experiment row as `{"type": "experiment", ...}`. `decide` appends a row `{"type": "decision", "_key": f"decision:{experiment_id}:{n}", ...}` and never edits earlier rows; `graduate` raises `ValueError` unless some window has `window == "post_cutoff"` and `ic.n >= 12`; an unknown `experiment_id` raises `ValueError`.

- [ ] **Step 1: Write the failing tests:**
  - `test_register_is_idempotent` (Review Focus 4): registering the same inputs twice leaves `len(list_experiments()) == 1` and `trial_count == 1`.
  - `test_trial_count_scoped`: two recipes differing only in `method` count as 2 under the same scope; a recipe with a different `universe` does not add to it.
  - `test_graduate_requires_post_cutoff_evidence` (Review Focus 1): an experiment whose only window is `in_window` raises on `graduate`; with a `post_cutoff` window of `ic.n=12` it succeeds and records approver and time.
  - `test_decisions_append_only_latest_wins`: graduate then shelve gives `decision == "shelve"`, and `read_results` still contains both decision rows.
  - `test_decide_unknown_id_raises`.
- [ ] **Step 2: Run** with `ARP_TEST_POSTGRES_DSN=... python3 -m pytest tests/test_signal_lab_registry.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the models and `Registry`.
- [ ] **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): experiment registry with trial counting and graduation gate`.

### Task 7: CLI and end-to-end test

**Files:**
- Create: `backend/arp/cli/signal_lab.py` (a `signals_app = typer.Typer(...)`)
- Modify: `backend/arp/cli/__init__.py` (import and `app.add_typer(signals_app, name="signals")`, next to `replicate_app`)
- Test: `backend/tests/test_signal_lab_cli.py` (uses `pg`)

**Interfaces:**
- Consumes: everything above; `CsvPriceSource`, `CsvCharacteristicSource` (existing, same wide-CSV format `arp replicate backtest` reads); `_run_store()` from `arp.cli._shared`.
- Produces three commands:
  - `arp signals evaluate --scores scores.csv --prices prices.csv --category <category> --method <str> --universe <str> --start <ISO> --end <ISO> [--model <str>] [--cost-bps 10] [--data-version <str>] [--baseline-momentum] [--out report.json]`: reads both CSVs onto one monthly grid, builds `sentiment_spec`, loads the cutoff table from `Settings.training_cutoffs_path`, sets `n_trials = registry.trial_count(recipe) + 1`, calls `evaluate_signal`, registers, prints a table (window, periods, mean IC, t_nw, net Sharpe) and `experiment_id`, and writes the report JSON if `--out`.
  - `arp signals list`: prints experiments with category, method, decision and trial count.
  - `arp signals decide <experiment_id> --decision graduate|shelve --approver <name>`: prints the result or the `ValueError` message and exits 1.

- [ ] **Step 1: Write the failing test** `test_evaluate_registers_and_graduation_is_gated`: build a 40-month, 15-ticker prices CSV and scores CSV (score equals next month's return plus noise) in `tmp_path`, write a cutoff file marking model `"m"` cutoff in the middle of the window, point `ARP_TRAINING_CUTOFFS_PATH` at it, run `typer.testing.CliRunner().invoke(app, ["signals","evaluate",...,"--model","m"])`. Assert exit code 0, the output contains an `experiment_id`, and `arp signals decide <id> --decision graduate` exits 1 (post-cutoff window under 12 months). Then run evaluate on a longer panel (60 months, cutoff at month 20) and assert graduate exits 0.
- [ ] **Step 2: Run** and confirm FAIL.
- [ ] **Step 3: Implement** the three commands and register the typer.
- [ ] **Step 4: Run** the full new test set plus the replication suite and `ruff check .`, then `python3 -c "import arp.cli"`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): arp signals evaluate, list, decide`.

---

## Self-review

- **Spec coverage:** cutoff map and window label (Task 1); rank-IC with robust t (Task 2); overlap with baselines and the insufficient-data comparison (Task 3); costs and turnover, gross and net (Task 4); post-cutoff split, contamination gap, deflated Sharpe with trial count (Task 5); registry, trial counting, append-only decisions, graduation gate (Task 6); usable from the CLI (Task 7). Not covered here, by design, and listed in the roadmap: leakage report, rerun stability, value-weighting, point-in-time text store, methods, notebook library, screens.
- **Step scan:** every step names a signature, test name or command.
- **Type consistency:** `period_window`, `CutoffTable`, `IcSummary`, `WindowEvidence`, `EvidenceReport`, `Recipe`, `Registry.trial_count` are defined once and used with the same names.
- **Proportion:** the plan is about the length of the spec it implements and holds no function bodies.
- **Open item for the owner:** the default `cost_bps=10.0` and the 12-month graduation minimum are my defaults, not owner decisions.
