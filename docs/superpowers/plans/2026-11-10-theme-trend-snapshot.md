# Theme trend snapshot: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp theme trend snapshot|show <taxonomy_id>` stores and prints per-quarter market, co-movement and diffusion numbers for a taxonomy's stocks.

**Architecture:** One new module `backend/arp/research/theme_trend.py` (pure functions plus one orchestrator that computes every quarter before writing) and a `trend` sub-group in `backend/arp/cli/theme.py`. Co-movement maths is imported from `stock_inference/comove.py`, not copied. One JSON file per theme, written atomically. No model call.

**Tech Stack:** Python, numpy, typer, pytest (`CliRunner`, `pg` fixture as in `tests/test_theme_comovement.py`).

**Spec:** `docs/superpowers/specs/2026-11-08-theme-trend-snapshot-design.md` (slug `theme-trend`). One PR, `Spec: theme-trend`, `risk:normal`.

## Global Constraints

- One PR. No new dependency. No change to `comove`'s output or to the inference run.
- No model call; tests never touch the network (`--prices`, `--facts-dir`).
- Numbers rounded to 4 decimals (reuse `arp.research.stock_inference.run._round`). No timestamps: same inputs, same bytes.
- A refusal or error writes nothing; all quarters of a range are computed before the file is written.
- Trend file: `<settings.portfolios_dir>/theme_trends/<taxonomy_id>.json`, via `arp.storage.atomic_io.atomic_write_text`.

## Which acceptance rows are checked how

All 36 rows are `holdout`, written by the test-writer in the private repo; none is `unit` or `evaluator`. The implementing session writes its own unit tests (below) and never sees the hidden ones. Rows by owning task:

| Task | Rows |
|---|---|
| 1 | AC-33 |
| 2 | AC-4, 5, 6, 13, 14, 15 |
| 3 | AC-7, 8, 16, 34 |
| 4 | AC-2, 3, 9, 11, 12, 24, 30, 31, 32, 35 |
| 5 | AC-1, 10, 17 to 23, 25 to 29, 36 |

## Owner answers (2026-11-10)

1. A skipped block keeps its counts (`weeks`, `stocks`, `window_weeks`); only returns, excess return, direction and correlation numbers are `null`.
2. `members[].cik` is the trimmed CSV value as typed; zero-padding happens only when looking up the facts file or calling SEC.
3. An existing trend file that is unreadable (bad JSON, or `taxonomy_id` not equal to the file name) makes `snapshot` exit 1 with `Trend file for <taxonomy_id> is unreadable: <reason>.`, file untouched.

## Review Focus

Inputs the spec implies but no acceptance row pins. Each gets a test in the task named.

- A member whose `prior_friday` price is blank: its quarter return is undefined, so it drops from `stocks` (task 2).
- A mapping where every member is tier `unknown`, or no member has a symbol: the snapshot is still saved with every block `skipped`, no crash (task 4).
- A filing amended later: a `10-K/A` filed after `quarter_end` must not replace the value a quarter saw; a row whose `val` equals the prior's is not rising (task 3).
- `--from 0001Q1`: `OverflowError` from date arithmetic must exit non-zero with the file untouched (task 5).
- Unreadable existing trend file (owner answer 3) (task 4).

## Calls I'm making (spec leaves them open)

- The inference run is found by scanning `runs_dir/*/snapshots/infer.json` for `taxonomy_id`, not `RunStore.list_runs`: the spec's fixture saves only a snapshot, and `list_runs` needs a `manifest.json`. First match in sorted run-id order wins.
- Unknown taxonomy: check `safe_id` and that `taxonomies_dir/<id>` exists before `TaxonomyStore.get`, because `get` creates an empty directory for an unknown id.
- A quarter return is the product of the 13 weekly returns (defined only when all 13 exist). It equals `P(last)/P(prior) − 1` when no price is blank.
- Direction uses the unrounded excess return and share.
- When several `--quarter`/`--from`/`--to` values are malformed, the first in that order is reported.
- `YYYYQn` is strict: four digits, capital `Q`, n 1 to 4.
- Diffusion reads rows from the first unit under `us-gaap.<tag>.units`, as `XbrlFactSource._annual_candidates` does. It does not rely on the `fy` key.
- No lock around the read-modify-write of the trend file (shortcut: last writer wins; add a `KeyedLock` when a scheduler runs two snapshots at once).
- CLI tests monkeypatch `arp.cli.theme._run_store` and `_taxonomy_store` and set `portfolios_dir` via settings; hidden tests will do the same, so use exactly those names.

## File structure

- Modify `backend/arp/research/stock_inference/comove.py`: split `_window` into fetch plus `_slice` (task 1).
- Create `backend/arp/research/theme_trend.py` (tasks 2 to 4).
- Modify `backend/arp/cli/theme.py`: `trend_app` with `snapshot` and `show` (task 5).
- Create `backend/tests/test_theme_trend.py` (all tasks; one fixture helper block at the top, built exactly as the spec's Acceptance conventions say).

## Task 1: Slice a prefetched panel in `comove.py`

**Files:** Modify `backend/arp/research/stock_inference/comove.py:176-183`. Test: existing `backend/tests/test_theme_comovement.py`.

**Interfaces:**
- Produces: `_slice(panel: PricePanel, tickers: list[str], end: str, weeks: int) -> dict[str, np.ndarray]`: the body of today's `_window` after the fetch. `_window` becomes fetch then `_slice`, returning the same `(dict, panel.source)`.

- [ ] **Step 1:** Run `cd backend && python3 -m pytest tests/test_theme_comovement.py` and note it passes (baseline for AC-33).
- [ ] **Step 2:** Extract `_slice`; `_window` calls it. No other change.
- [ ] **Step 3:** Re-run the same file; expect the same passes.
- [ ] **Step 4:** Commit `refactor: split comove window fetch from slice`.

## Task 2: Quarters, market and co-movement

**Files:** Create `backend/arp/research/theme_trend.py`. Test: `backend/tests/test_theme_trend.py`.

**Interfaces:**
- Produces: `class TrendRefused(Exception)` (`args[0]` is the message).
- Produces: `parse_quarter(text: str) -> tuple[int, int]` (raises `TrendRefused("Quarter <text> is not in the form YYYYQn.")`), `quarter_end(q: str) -> date`, `quarter_label(year: int, n: int) -> str`, `quarters(first: str, last: str) -> list[str]`, `fridays(q: str) -> list[date]` (Fridays inside the quarter), `prior_friday(q: str) -> date`, `previous_quarter(q: str) -> str`.
- Produces: `market_block(panel: PricePanel, symbols: list[str], q: str) -> dict` with keys `weeks, stocks, basket_return, acwi_return, excess_return, direction, skipped`.
- Produces: `comovement_block(panel: PricePanel, members: dict[str, tuple[str, str]], q: str) -> dict` with keys `window_weeks, stocks, mean_resid_corr, null_mean, null_p95, p_value, skipped`. `members` maps company_id to `(symbol, home_index)`.

- [ ] **Step 1: Tests** (names and assertions, spec values):
  - `test_quarter_calendar`: `quarter_end("2026Q2") == date(2026, 6, 30)`; `len(fridays("2026Q2")) == 13`; `prior_friday("2026Q2") == date(2026, 3, 27)`; `previous_quarter("2026Q1") == "2025Q4"`; `quarters("2025Q4", "2026Q2") == ["2025Q4", "2026Q1", "2026Q2"]`.
  - `test_parse_quarter_rejects`: `"2026-3"`, `"2026q2"`, `"2026Q5"`, `"2026Q0"` raise with the spec's text.
  - `test_market_block_fixture`: on the fixture panel (spec conventions), 2026Q2 gives `weeks == 13`, `stocks == 4`, `excess_return == EX(2026Q2)`, `direction == "up"`, `acwi_return == round(R(ACWI, 2026Q2), 4)`. (AC-4, 5)
  - `test_market_block_blank_week_drops_stock`: blank `A4` at 2026-08-14, 2026Q3, `stocks == 3` (AC-13). Blank `A3` and `A4` from 2026-07-03 on: `skipped == "too_few_stocks"`, `excess_return is None`, `direction is None`, `stocks == 2` (AC-14, owner answer 1). Blank `A1` at `prior_friday`: `A1` leaves `stocks` (Review Focus).
  - `test_market_short_control`: 2025Q1 has no `prior_friday` price, so `skipped == "short_control"`, numbers `None`, `weeks == 13` (AC-15).
  - `test_comovement_block_fixture`: 2026Q2 gives `window_weeks == 52`, `stocks == 4`, `mean_resid_corr > null_p95`, `p_value == 0.002`, `skipped is None` (AC-6). 2025Q1: `skipped == "short_control"` (AC-15). Only 2 priced members: `too_few_stocks`, `stocks == 2`.
- [ ] **Step 2:** Run `python3 -m pytest tests/test_theme_trend.py`; expect FAIL (module missing).
- [ ] **Step 3:** Implement the calendar helpers (stdlib `datetime`).
- [ ] **Step 4:** Implement `market_block`. A symbol's quarter return is the product of `1 + r` over the quarter's Fridays in `panel.period_ends`, `None` unless all 13 returns are present. ACWI without one: `short_control`. Fewer than 3 stocks: `too_few_stocks`. Bands ±0.01 on the unrounded value.
- [ ] **Step 5:** Implement `comovement_block` with `comove._slice`, `_residualise` and `_basket_tests` (take only the four spec keys), seed 0 and 500 draws as `comove` does. Need `math.ceil(2 * 52 / 3) = 35` returns for ACWI, and for a stock and its home index to count as priced.
- [ ] **Step 6:** Run the test file; expect PASS. Commit `feat: theme trend quarter, market and co-movement blocks`.

## Task 3: Diffusion

**Files:** Modify `backend/arp/research/theme_trend.py`. Test: `backend/tests/test_theme_trend.py`.

**Interfaces:**
- Produces: `diffusion_block(facts: dict[str, dict | None], members: dict[str, str | None], quarter_end_day: date) -> dict` returning `{"capex": {...}, "rnd": {...}}`, each `{companies, rising, share, direction, skipped}`. `facts` maps cik to companyfacts JSON or `None`; `members` maps company_id to cik or `None`.
- Consumes: `arp.ingestion.xbrl._CAPEX_TAGS`, `_RND_TAGS`, `_annual_row`.

- [ ] **Step 1: Tests** with companyfacts built per the spec's Acceptance conventions:
  - 2026Q2 (`quarter_end` 2026-06-30): `capex == {companies: 4, rising: 2, share: 0.5, direction: "flat", skipped: None}`; `rnd` has `companies 0`, `share None`, `direction None`, `skipped "too_few_companies"` (AC-7, 8).
  - 2026Q3 (2026-09-30): `rising 3`, `share 0.75`, `direction "up"` (AC-34).
  - No cik for any member: `capex.companies == 0`, `skipped "too_few_companies"` (AC-16).
  - A `10-K/A` for FY2024 filed after `quarter_end` is ignored; a re-filed FY2024 row filed before it wins by latest `filed`; equal values are not rising (Review Focus).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement per spec: rows passing `_annual_row` with `filed <= quarter_end`; first tag with two distinct `end` dates; latest-filed row per end; `latest`/`prior` from the two latest ends; `rising` when `latest.val > prior.val`. Skipped under 3 companies; bands 0.45 / 0.55 on the unrounded share.
- [ ] **Step 4:** Run; expect PASS. Commit `feat: theme trend diffusion block`.

## Task 4: Members, snapshots and the trend file

**Files:** Modify `backend/arp/research/theme_trend.py`. Test: `backend/tests/test_theme_trend.py`.

**Interfaces:**
- Consumes: tasks 2 and 3; `arp.research.stock_inference.comove._read_symbols`; `InferRun`; `Taxonomy`.
- Produces: `find_members(taxonomy_id: str, run_store, taxonomy_store) -> tuple[str, int, list[str]]` returning `(run_id, taxonomy_version, sorted company_ids)`; raises `TrendRefused` with the two taxonomy messages from the spec.
- Produces: `snapshot_theme(taxonomy_id: str, symbols_path: str | Path, quarter_list: list[str], prices: PriceDataSource, facts_for: Callable[[str], dict | None], run_store, taxonomy_store, trends_dir: Path) -> list[str]`. Computes all quarters, then writes; returns the saved quarters.
- Produces: `load_trend(path: Path) -> dict | None` (`None` when absent; `TrendRefused` when unreadable, owner answer 3).

- [ ] **Step 1: Tests** (CLI-free, fixture run saved with `RunStore.save_snapshot(run_id, "infer", dump(run))`):
  - `find_members` returns `["a1".."a5"]` (tier `unknown` `z1` excluded); no run raises the `has no stock mapping` message (AC-23, AC-3); an unknown id raises `Taxonomy tax_nope not found.` and creates no `taxonomies/tax_nope` directory (AC-22).
  - Snapshot for 2026Q2: `quarter`, `quarter_end "2026-06-30"`, `membership "current_mapping"`, `source "csv"`, `taxonomy_version 1`, `a5` has `skipped "no_symbol"`, `symbol` and `cik` `None`, the others `skipped None` (AC-2, AC-3). `members[].cik == "1"` as typed.
  - Re-running 2026Q2 replaces that entry only, keeps 2026Q3 unchanged and the list sorted (AC-11, 12, 35). Two empty dirs, same range: byte-identical files (AC-30).
  - A bad `home_index` for `a3` raises `Stock a3 has no home_index.` and leaves an existing file byte-identical (AC-24). A facts loader that raises leaves the file byte-identical (the engine of AC-36).
  - The inference run JSON and the taxonomy file are byte-identical before and after (AC-32).
  - Every member tier `unknown` or no symbols: saved, `market.skipped == "too_few_stocks"`, `diffusion.*.skipped == "too_few_companies"` (Review Focus). A trend file containing `not json`: `TrendRefused`, bytes unchanged.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `find_members` (scan `run_store.runs_dir`, as in Calls).
- [ ] **Step 4:** Implement `snapshot_theme`: `_read_symbols(path, set(members))` for symbols and home indexes; a second small CSV pass for `cik` by company_id, kept only for members that survived `_read_symbols`; one `prices.get_weekly_returns(tickers, start, end)` for the whole range with `start = prior_friday(first) − 53 weeks` and `end = last quarter's last Friday`; `facts_for(cik)` once per cik for the range; build each snapshot with the keys in the spec's Trend file table; run the result through `_round`; merge by quarter, sort; `json.dumps(..., indent=2)` plus newline; `mkdir` the `theme_trends` directory and `atomic_write_text` only after everything is computed.
- [ ] **Step 5:** Run; expect PASS. Commit `feat: theme trend snapshot storage`.

## Task 5: CLI, `show`, checks and PR

**Files:** Modify `backend/arp/cli/theme.py` (new `trend_app`, mounted with `theme_app.add_typer(trend_app, name="trend")`). Test: `backend/tests/test_theme_trend.py`.

**Interfaces:**
- Produces: `arp theme trend snapshot <taxonomy_id> --symbols <csv> (--quarter | --from --to) [--prices] [--facts-dir]` and `arp theme trend show <taxonomy_id> [--json]`.
- Produces in `theme_trend.py`: `format_show(trend: dict) -> str` building the header and rows per the spec.
- Consumes: `get_settings().portfolios_dir`, `_run_store`, `_taxonomy_store`, `_xbrl_source`.

- [ ] **Step 1: Tests** with `CliRunner` on `theme_app`, one per spec behaviour:
  - stdout exactly `Saved tax_t 2026Q2\n` (AC-1); the range prints two lines (AC-10).
  - Refusals, exit 1 and stderr exact, in the spec's order: AC-17 (`2099Q1`, no file), AC-18 (`--from 2026Q3 --to 2099Q1`, stored file byte-identical), AC-19, AC-20 (all three variants), AC-21, AC-22, AC-23. `--from 0001Q1 --to 2026Q2` exits non-zero and the file is untouched (Review Focus).
  - `show`: header literal; line 3 starts `2026Q3\t` and `capex_change` is `0.2500`; line 2 has `n/a` in `corr_change`, `capex_change`, `rnd_change`, `rnd_share`, `rnd` (AC-25, 26). With `2025Q4` and `2026Q2` stored, `corr_change` is `n/a` (AC-27). `--json` parses to the file's content (AC-28). No file: exit 1, `No trend stored for tax_t.` (AC-29).
  - `ARP_ANTHROPIC_API_KEY` unset gives a file byte-identical to one made with `dummy` (AC-31). `CIK0000000004.json` containing `not json` exits non-zero, file byte-identical (AC-36).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `snapshot`. Check order: quarter flags given, form of each value, `from <= to`, `--quarter`/`--to` ended (`quarter_end < date.today()`), then the taxonomy checks inside `snapshot_theme`. Source: `CsvPriceSource(prices)` or `YFinancePriceSource()`. Facts: with `--facts-dir`, read `CIK<cik.zfill(10)>.json` (missing file is `None`, bad JSON propagates); otherwise `asyncio.run(_xbrl_source().fetch_company_facts(cik))`, built only if a member has a cik. Catch `TrendRefused` and `ComoveRefused`, echo `args[0]` to stderr, exit 1; catch `ImportError, OSError, ValueError, OverflowError` and exit 1 with the message. Print `Saved <id> <quarter>` lines only after the write.
- [ ] **Step 4:** Implement `show` and `format_show`. `*_change` is this value minus the previous stored quarter's, only when `previous_quarter(this) ==` that quarter and both values exist. Four decimals; `None` prints `n/a`.
- [ ] **Step 5:** Run `cd backend && ruff check . && python3 -m pytest tests/test_theme_trend.py tests/test_theme_comovement.py tests/test_cli_taxonomy_infer.py`; expect PASS (needs `bash .claude/hooks/ensure-deps.sh postgres`).
- [ ] **Step 6:** `/ponytail:ponytail-review` and `/code-review`. Open the PR against `main` with `Spec: theme-trend`, label `risk:normal`. Say in the PR whether `openwiki/` needs an update (it does: new command; the weekly `/context-refresh` regenerates it, do not edit by hand). List any test changes (none expected).

## Not in this PR

Everything under the spec's Non-goals: attention, talk vs action, stage label, point-in-time membership, API, UI, Postgres.
