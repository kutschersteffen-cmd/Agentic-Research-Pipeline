# Theme co-movement: implementation plan

Spec: `docs/superpowers/specs/2026-11-07-theme-comovement-design.md` (slug `theme-comovement`). One PR, `risk:normal`.

**Goal:** `arp taxonomy infer comove <run_id> --symbols <csv>` adds a `comovement` block to an inference run,
computed in numpy from weekly returns. No model call, no new dependency, no new stage.

## Tasks (TDD: failing test first, then code)

1. **Weekly returns** in `arp/replication/price_data.py`.
   - `PriceDataSource.get_weekly_returns(tickers, start, end)`: a new abstract method next to the monthly one.
   - `CsvPriceSource`: the same price-to-return loop as monthly, rows already week-ends; a symbol with no column
     gets all-`None` returns. The return loop moves into a small shared helper; the monthly method's behaviour
     (including its `ValueError`) is unchanged.
   - `YFinancePriceSource`: daily `auto_adjust` closes, `resample("W-FRI").last()`, then the same return loop.
   - Tests: AC-35, AC-36, AC-37, AC-38 (stubbed `yf.download`).
2. **Method** in a new `arp/research/stock_inference/comove.py`, as pure functions on numpy arrays:
   - residualise on `[1, ACWI, home]`;
   - leave-one-out theme factor and the loading row: OLS slope, R², Newey-West t (Bartlett, 4 lags, the same
     kernel as `signal_lab.stats.newey_west_t`), down/up/lag/lead correlations, null below 52 shared weeks;
   - basket tests: mean pairwise residual correlation, seed-0 shuffle null with 500 draws, eigenvalues against
     the Marchenko-Pastur bound;
   - flags `text_only` and `returns_only`.
   - Tests on small synthetic arrays where the answer is known: a perfect factor gives R² 1, a shuffle keeps
     gaps in place, eigenvalues are null when T < 2N.
3. **Run step** `comove(run_id, symbols_path, prices, end, weeks, run_store)` in the same module.
   - Checks in spec order: run, stage, symbols file, controls, prices. Each refusal raises with the spec's exact
     text and saves nothing.
   - Writes `InferRun.comovement` (a new optional field, a plain dict); `dump()` leaves the key out while it is
     `None`, so runs without it print exactly as today.
   - `default_end(today)` returns the last Friday strictly before today (AC-39).
4. **CLI** `infer comove` in `arp/cli/taxonomy_infer.py`: `--symbols`, `--end`, `--weeks 156`, `--prices`;
   stdout in the spec's two-table format.
   - CLI tests on the spec's fixture (prices built exactly as the Acceptance conventions say) for the
     `holdout` rows: AC-1 to AC-34, AC-40 to AC-42.
   - AC-43 (`pick` keeps the block) as a unit test with the stub LLM.
5. **Checks**: `ruff check .`, the new tests and the existing `test_cli_taxonomy_infer.py` and
   `test_stock_inference_*` tests; `/code-review` and `/ponytail:ponytail-review`; open the PR with
   `Spec: theme-comovement`.

## Reuse

- `price_data.py`: `PricePanel`, `CsvPriceSource` and `YFinancePriceSource` are extended, not copied.
- `signal_lab/stats.py`: the Newey-West Bartlett kernel is reused as a formula. The function itself tests a
  mean, not a slope, as the spec says.
- `index/risk.py`: nothing fits. Its covariance code is Ledoit-Wolf on full panels; this step needs plain
  correlations with gaps.

## Calls I'm making (spec leaves them open)

- A loading row under 52 shared weeks has every number `null`, `n_weeks` included (the spec says "every number").
- Lag and lead correlations align by calendar week, so a gap week is not bridged.
- Newey-West without a small-sample correction, as in `newey_west_t`.
- In stdout, counts (`members`, `factors_above_noise`) print as integers; decimals print with 4 places.

## Not in this PR

Everything under the spec's Non-goals. No API, no UI, no openwiki edit.
