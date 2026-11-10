# Theme trend snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp theme trend snapshot` stores one point-in-time snapshot (market, co-movement, capex and R&D diffusion) per theme and quarter in a JSON file, and `arp theme trend show` prints the stored quarters with their changes.

**Architecture:** One new module `arp/research/theme_trend.py` holds all logic as functions on plain data (a `PricePanel`, companyfacts dicts). It reuses `comove.py`'s numpy functions and the XBRL tag lists and `_annual_row`. `arp/cli/theme.py` gets a thin `trend` sub-group. A range is computed fully in memory, then written once.

**Tech Stack:** Python 3.13, numpy, Typer, pytest. No new dependency, no model call, no network in tests.

**Spec:** `docs/superpowers/specs/2026-11-08-theme-trend-snapshot-design.md` (slug `theme-trend`). One PR, `risk:normal`.

## Global Constraints

- No model call; every number is point-in-time: prices up to the quarter's last Friday, filings with `filed` on or before the quarter's last day.
- Numbers rounded to 4 decimals; no timestamps, so identical inputs give a byte-identical file.
- A refusal or any error writes nothing: the trend file stays byte-identical, or absent.
- Refusal order and exact messages: the spec's table. Exit 1 and the message on stderr.
- `comove`'s output and the inference run and taxonomy files are unchanged.
- Tests use `--prices` and `--facts-dir`, never the network. No new dependency.
- Trend file: `<portfolios_dir>/theme_trends/<taxonomy_id>.json`, written atomically.

## Review Focus

1. A 14-Friday quarter (2027Q4) and a quarter ending on a Friday: `weeks` 14, `last_friday` = `quarter_end`. Task 1.
2. A symbols-file symbol with no price column: no crash, the stock is just not counted. Task 2.
3. Restated filing (same `end` filed twice): the latest-filed row counts; equal `latest` and `prior` is not rising. Task 2.
4. A `cik` written without leading zeros reads `CIK<10 digits>.json`. Task 4.
5. An existing trend file that is not valid JSON: error, file untouched, not overwritten. Task 3.

---

### Task 1: Split `comove._window` into fetch and slice

**Files:**
- Modify: `backend/arp/research/stock_inference/comove.py:176-183`
- Test: `backend/tests/test_theme_comovement.py` (existing, unchanged; it is the guard, AC-33)

**Interfaces:**
- Produces: `comove._slice(panel: PricePanel, tickers: list[str], end: str, weeks: int) -> dict[str, np.ndarray]` — the last `weeks` returns up to `end` per ticker, NaN for None, index 0 dropped. `_window` calls it and returns `(slice, panel.source)` as before.

- [ ] **Step 1: Extract `_slice` from `_window`.** Move the `keep = ...` lines and the dict comprehension into `_slice`; `_window` keeps the date arithmetic and the fetch. No behaviour change.
- [ ] **Step 2: Run** `cd backend && ruff check . && python3 -m pytest tests/test_theme_comovement.py`. Expected: all pass, unchanged.
- [ ] **Step 3: Commit** `refactor: split comove window into fetch and slice`.

### Task 2: Quarter, market, co-movement and diffusion measures

**Files:**
- Create: `backend/arp/research/theme_trend.py`
- Test: `backend/tests/test_theme_trend.py` (create)

**Interfaces:**
- Produces, in `theme_trend.py`:
  - `class TrendRefused(Exception)`: `args[0]` is the message.
  - `@dataclass(frozen=True) class Quarter`: `label: str`, `end: date`, `weeks: list[date]` (Fridays inside it), `prior_friday: date`, `last_friday: date`.
  - `quarter(label: str) -> Quarter`; raises `TrendRefused("Quarter <label> is not in the form YYYYQn.")`.
  - `quarter_range(first: str, last: str) -> list[Quarter]`.
  - `market_block(panel: PricePanel, q: Quarter, symbols: list[str]) -> dict` with the spec's `market` keys.
  - `comovement_block(panel: PricePanel, q: Quarter, members: dict[str, tuple[str, str]]) -> dict` (`company_id -> (symbol, home_index)`), the spec's `comovement` keys.
  - `diffusion_block(facts: dict[str, dict], q: Quarter, tags: list[str]) -> dict` (`cik -> companyfacts JSON`), the spec's `{companies, rising, share, direction, skipped}`.

- [ ] **Step 1: Write failing tests**, with the Acceptance fixture builders (`_prices`, `_facts`) in the test file:
  - `test_quarter_dates`: `quarter("2026Q2")` has `end` 2026-06-30, `last_friday` 2026-06-26, `prior_friday` 2026-03-27, 13 weeks. `quarter("2027Q4")` has 14 weeks and `last_friday == end`. `quarter("2026-3")` raises with the AC-19 message.
  - `test_market_ac4_ac5_ac9`: on the fixture panel, 2026Q2 gives `weeks` 13, `stocks` 4, `excess_return` `EX(2026Q2)`, `direction` `up`, `acwi_return` `round(R(ACWI), 4)`; 2026Q3 gives `down`.
  - `test_market_stocks_drop_gap_ac13_ac14`: a blank price inside the quarter drops that stock (`stocks` 3); two stocks blank gives `skipped` `too_few_stocks` and `null` numbers; a symbol with no column is not counted and does not raise.
  - `test_market_short_control_ac15`: 2025Q1 gives `skipped` `short_control`; the same for `comovement_block`.
  - `test_comovement_ac6`: 2026Q2 gives `window_weeks` 52, `stocks` 4, `mean_resid_corr` > `null_p95`, `p_value` 0.002.
  - `test_diffusion_ac7_ac8_ac34`: 2026Q2 capex `companies` 4, `rising` 2, `share` 0.5, `flat`; 2026Q3 `rising` 3, `up`; R&D with no rows gives `companies` 0, `skipped` `too_few_companies`.
  - `test_diffusion_restated_and_equal`: a second row for the same `end` filed later replaces the earlier one; `latest.val == prior.val` is not rising.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_theme_trend.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the interfaces above in `theme_trend.py`:
  - `market_block`: compound the weekly returns of the quarter's Fridays (equals `P(last)/P(prior) − 1`); a stock counts only when every quarter week has a return. Bands ±0.01.
  - `comovement_block`: `comove._slice` for 52 weeks ending `last_friday`; `comove._residualise` per priced member; `comove._basket_tests` for the four numbers; need 35 returns for the stock and its home index, ACWI ≥ 35 else `short_control`, < 3 priced else `too_few_stocks`.
  - `diffusion_block`: rows pass `arp.ingestion.xbrl._annual_row` and `filed <= q.end`; first tag in `tags` with ≥ 2 distinct `end`; latest-filed row per `end`; take the first unit in `units` as `_annual_candidates` does. Bands 0.45 / 0.55, minimum 3 companies.
- [ ] **Step 4: Run the tests.** Expected: PASS. `ruff check .` clean.
- [ ] **Step 5: Commit** `feat(theme-trend): quarter, market, co-movement and diffusion measures`.

### Task 3: Members, snapshot and the trend file

**Files:**
- Modify: `backend/arp/research/theme_trend.py`
- Test: `backend/tests/test_theme_trend.py`

**Interfaces:**
- Consumes: Task 2's functions.
- Produces:
  - `snapshot(taxonomy_id: str, quarters: list[Quarter], symbols_path: str | Path, prices: PriceDataSource, facts_for: Callable[[str], dict | None], *, taxonomy_store: TaxonomyStore, run_store: LegacyRunStore, portfolios_dir: Path, today: date) -> list[str]` — the saved quarter labels; raises `TrendRefused` for the spec's refusals from "has not ended" on, in order.
  - `trend_path(portfolios_dir: Path, taxonomy_id: str) -> Path`.

- [ ] **Step 1: Write failing tests** on the fixture taxonomy `tax_t` and run (saved with `run_store.save_snapshot(run_id, "infer", dump(run))` into a tmp `runs` dir; `LegacyRunStore(tmp/"runs")`, so no Postgres):
  - `test_snapshot_ac2_ac3`: one 2026Q2 entry with `quarter_end`, `membership`, `source` `csv`, `taxonomy_version` 1, `members` `a1..a5` with `a5` `no_symbol`; `z1` (tier `unknown`) absent.
  - `test_snapshot_replaces_one_quarter_ac11_ac12`: re-running 2026Q2 leaves 2026Q3 unchanged; adding 2026Q2 after 2026Q3 sorts them.
  - `test_snapshot_range_ac35`: `["2026Q2","2026Q3"]`.
  - `test_refusals_write_nothing_ac17_ac18_ac21_ac22_ac23_ac24`: each refusal text exactly, trend file absent or byte-identical; a `home_index`-blank symbols row raises `comove`'s `Stock a3 has no home_index.` (reuse `comove._read_symbols`).
  - `test_error_leaves_file_ac36_and_corrupt_file`: `facts_for` raising `ValueError` for one CIK in the second quarter of a range leaves the file byte-identical; an existing trend file containing `not json` raises and is not replaced.
  - `test_deterministic_ac30_ac32`: two runs in two dirs give identical bytes; the run snapshot and taxonomy file are unchanged.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `snapshot` and `trend_path`:**
  - Check order: "has not ended" (the last quarter only), taxonomy (`taxonomy_store.get`), run (scan `run_store.runs_dir` directories, `read_snapshot(d.name, "infer")`, `taxonomy_id` equal; take the highest `run_id` if several), then symbols via `comove._read_symbols(path, set(members))` (rows for non-members ignored first).
  - `cik` per member: a second small read of the symbols CSV (`cik` column optional; blank is `null`); `members[]` entries as the spec's table.
  - One `prices.get_weekly_returns` call from 53 weeks before the first quarter's `prior_friday` to the last quarter's `last_friday`; `facts_for` is called once per CIK and cached for the range.
  - Round every float to 4 decimals; write with `json.dumps(indent=2)` plus newline to a temp file in the same directory and `os.replace`. Merge by `quarter`, sorted.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(theme-trend): snapshot and trend file`.

### Task 4: `show` and the CLI

**Files:**
- Modify: `backend/arp/research/theme_trend.py`, `backend/arp/cli/theme.py` (add after the `edges_app` lines near the top and the commands at the end)
- Test: `backend/tests/test_theme_trend.py`

**Interfaces:**
- Consumes: Task 3's `snapshot`, `trend_path`.
- Produces: `show(taxonomy_id: str, portfolios_dir: Path, as_json: bool) -> str`; raises `TrendRefused("No trend stored for <id>.")`. CLI: `trend_app = typer.Typer()` added as `theme_app.add_typer(trend_app, name="trend")`, commands `snapshot` and `show` with the spec's options.

- [ ] **Step 1: Write failing tests** with `CliRunner` on `theme_app`, `ARP_RUNS_DIR`, `ARP_TAXONOMIES_DIR`, `ARP_PORTFOLIOS_DIR` set to tmp dirs and `get_settings.cache_clear()`:
  - `test_cli_ac1_ac10`: stdout exactly `Saved tax_t 2026Q2`; a range prints two lines.
  - `test_cli_flag_refusals_ac19_ac20`: the three bad flag combinations give the exact stderr, exit 1.
  - `test_show_ac25_ac26_ac27`: header literal; `capex_change` `0.2500` on line 3; `n/a` in `corr_change`, `capex_change`, `rnd_change`, `rnd_share`, `rnd` on line 2; with `2025Q4` and `2026Q2` stored, `corr_change` is `n/a` (the gap rule).
  - `test_show_json_and_absent_ac28_ac29`: `--json` parses to the file; absent file gives `No trend stored for tax_t.`
  - `test_cli_cik_padding_and_no_key_ac16_ac31`: a `cik` of `1` reads `CIK0000000001.json`; symbols without a `cik` column give capex `too_few_companies`; the file is identical with `ARP_ANTHROPIC_API_KEY` unset and set to `dummy`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** In `theme.py`: flag checks first, in the spec's order (neither or both of `--quarter` and `--from/--to`, then the `YYYYQn` form, then from-after-to), calling `theme_trend.quarter`. `facts_for` reads `<facts-dir>/CIK<cik zero-padded to 10>.json` (missing file → `None`; unreadable → the error propagates, exit non-zero); without `--facts-dir`, `asyncio.run(_xbrl_source().fetch_company_facts(cik))`. Prices: `CsvPriceSource(prices)` or `YFinancePriceSource()`. Stores: `TaxonomyStore(settings.taxonomies_dir)` and `LegacyRunStore(settings.runs_dir)`, no DSN. `TrendRefused` and `ComoveRefused` print `args[0]` to stderr and exit 1; `OSError`/`ValueError` print and exit 1. `show` builds each `*_change` from the previous stored quarter only when it is the calendar quarter just before and both values exist; 4 decimals; missing and `null` as `n/a`.
- [ ] **Step 4: Run** `python3 -m pytest tests/test_theme_trend.py tests/test_theme_comovement.py -v`. Expected: PASS. Then `ruff check .`.
- [ ] **Step 5: Commit** `feat(theme-trend): arp theme trend snapshot and show`.

### Task 5: Checks and PR

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest tests/test_theme_trend.py tests/test_theme_comovement.py tests/test_cli_taxonomy_infer.py`. Expected: pass.
- [ ] **Step 2:** `/code-review` and `/ponytail:ponytail-review` on the diff; fix what they find.
- [ ] **Step 3:** Open the PR against `main`, `risk:normal`, body line `Spec: theme-trend`, listing test changes (none changed or removed) and that `openwiki/` needs the weekly refresh (new command).

## Not in this PR

The spec's Non-goals: attention, talk vs action, stage label, API, UI, Postgres, scheduler, point-in-time membership.

## Self-review notes

- Spec coverage: every goal and Design section maps to Task 2 to 4; AC-1 to AC-36 map to the named tests (AC-12/13/14 in Task 2 and 3, AC-33 is guarded by Task 1's unchanged `test_theme_comovement.py`).
- Call I made: runs are found by scanning `runs_dir/*/infer.json`, because the spec's fixture saves a snapshot with no manifest, so `list_runs` would miss it. If two runs share a `taxonomy_id`, the highest `run_id` wins.
- Call I made: the run and taxonomy are read with the file `LegacyRunStore`, so the command needs no Postgres DSN.
