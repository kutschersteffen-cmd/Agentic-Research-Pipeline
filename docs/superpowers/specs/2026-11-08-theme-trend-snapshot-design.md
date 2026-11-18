# Theme trend snapshot (Engine 7, step 1, first slice)

Spec slug: `theme-trend`. Status: approved by the owner 2026-11-08. Date: 2026-11-08.
Review page: https://claude.ai/artifact/CFjYPf137g6zUN2SNFEsFD.
Starting material: "Theme Engines and Trends", Part 2 (https://claude.ai/artifact/ERoWojiAa3mfyf8b9Kaxov).
Builds on `2026-11-04-taxonomy-from-stocks-design.md` (the mapping a theme's stocks come from) and
`2026-11-07-theme-comovement-design.md` (the co-movement method, reused here).

## Intent

Every theme measure in the pipeline runs once: a co-movement block, a capex trend, an emerging-theme score. A
trend needs the same measures for the same theme, period after period, stored side by side. This slice stores,
per theme and per calendar quarter, three numbers from the market and corporate filings, each with a direction,
and prints them as one table. Later slices add attention, talk vs action and a stage label (emerging, building
out, commercial, mainstream, fading) on top of the stored history.

The five dimensions from the starting material, and what this slice covers:

| Dimension | This slice |
|---|---|
| Direction | `market`, `capex`, `rnd` directions (up / flat / down) per quarter |
| Speed | quarter-on-quarter change, printed by `show` |
| Breadth | diffusion: share of the theme's companies whose capex / R&D rose |
| Conviction (talk vs action) | later (needs emerging-theme clusters matched to a taxonomy) |
| Pricing | basket excess return over ACWI and co-movement |

## Owner decisions (2026-11-08)

Quarterly snapshots · theme = `taxonomy_id`, companies from the stock mapping of the inference run that made the
taxonomy · first slice = market (excess return, co-movement) + diffusion (XBRL capex, R&D) · stage label later ·
one JSON file per theme · backfill over a quarter range in one call · CLI only.

## Goals

1. `arp theme trend snapshot <taxonomy_id>` computes one snapshot per quarter, for one quarter or a range, and
   stores it in the theme's trend file. Re-running a quarter replaces that quarter only.
2. Every number is point-in-time: prices up to the quarter's last Friday, filings filed on or before the quarter's
   last day. No model call.
3. `arp theme trend show <taxonomy_id>` prints the stored quarters side by side, with the change from the
   previous stored quarter.

## Non-goals (later rows or specs)

- Attention (mention velocity, breadth, novelty, persistence from `arp/emerging_themes/scoring.py`) and talk vs
  action share (`ActionType`): both need emerging-theme clusters matched to a taxonomy theme first.
- Corporate action totals (capex / capacity / orders amounts from grounded quotes).
- Diffusion from theme revenue or backlog (revenue catalogue), and from non-US filers (ESEF).
- The divergence matrix (narrative vs action vs market) and the rule-based stage classifier.
- Point-in-time membership: members are today's mapping for every quarter, including backfilled ones
  (survivorship; stored as `membership: "current_mapping"`).
- Monthly snapshots; a scheduler; API endpoints and UI; Postgres storage.
- Themes without a stock mapping (hand-made taxonomies).
- Changing any existing command, the inference run or the taxonomy.

## Anti-goals

- A number that uses a price after the quarter's last Friday or a filing filed after the quarter's last day.
- A failed or refused call that changes the trend file.
- A model call.

## Design

### Commands

```
arp theme trend snapshot <taxonomy_id> --symbols <csv> (--quarter <YYYYQn> | --from <YYYYQn> --to <YYYYQn>)
                         [--prices <wide csv>] [--facts-dir <dir>]
arp theme trend show <taxonomy_id> [--json]
```

- `trend` is a new sub-group of the existing `arp theme` group.
- `--symbols`: the `comove` symbols CSV (`company_id`, `symbol`, `home_index`) plus an optional `cik` column
  (digits, SEC CIK). Same rules and messages as `comove`: rows for non-members are ignored first; a blank
  `symbol` counts as no row; a blank `home_index`, a duplicate `company_id`, a missing column or a control that is
  also a stock refuse with `comove`'s messages.
- `--prices`: a wide weekly CSV read with `CsvPriceSource`; without it, Yahoo (`YFinancePriceSource`).
- `--facts-dir`: a directory of SEC companyfacts JSON files named `CIK<cik, 10 digits>.json`; a CIK with no file
  has no facts. Without it, `XbrlFactSource` (SEC, with its cache).
- Success: one stdout line per quarter, in quarter order: `Saved <taxonomy_id> <quarter>`.
- All quarters of a range are computed before anything is written; a refusal or error writes nothing. Any
  other error (an unreadable facts file, a price source failure) exits non-zero with the file byte-identical.

Refusals (exit 1, stderr exactly, trend file byte-identical or still absent), checked in this order:

| Case | Message |
|---|---|
| Neither or both of `--quarter` and `--from`/`--to`, or only one of `--from`/`--to` | `Give --quarter, or --from and --to.` |
| A quarter not in the form `YYYYQn` (n 1-4) | `Quarter <value> is not in the form YYYYQn.` |
| `--from` later than `--to` | `--from <from> is after --to <to>.` |
| `--quarter`, or `--to`, whose last day is today or later (only that quarter is checked) | `Quarter <quarter> has not ended.` |
| Unknown taxonomy | `Taxonomy <taxonomy_id> not found.` |
| No inference run has this `taxonomy_id` | `Taxonomy <taxonomy_id> has no stock mapping; trend needs a taxonomy made by 'arp taxonomy infer pick'.` |
| Symbols file problems | `comove`'s messages |

### Members

The inference run (RunStore snapshot `infer`) whose `taxonomy_id` equals the argument. Members are the distinct
`company_id`s of its `mapping` with tier `core`, `enabler` or `adopter` (tier `unknown` is left out), sorted.

### Quarter

`2026Q2` runs 2026-04-01 to 2026-06-30 (`quarter_end`). Quarter weeks are the Fridays inside it. `last_friday` is
the last of them; `prior_friday` is the last Friday of the previous quarter.

### Market (per quarter)

- Prices: the weekly returns for every member symbol and `ACWI`, fetched once for the whole range (from 53 weeks
  before the first quarter's `prior_friday` to the last quarter's `last_friday`).
- A symbol's quarter return is `P(last_friday) / P(prior_friday) − 1`, defined only when it has a weekly return
  for every quarter week.
- `ACWI` without a quarter return: `skipped: "short_control"`, numbers `null`.
- `weeks`: the number of quarter weeks (Fridays in the quarter). Members with a quarter return: `stocks` (count). Fewer than 3: `skipped: "too_few_stocks"`, numbers `null`.
- `basket_return`: equal-weighted mean of the members' quarter returns; `acwi_return`; `excess_return` =
  `basket_return − acwi_return`.
- `direction`: `up` if `excess_return > 0.01`, `down` if `< −0.01`, else `flat`; `null` when skipped.

### Co-movement (per quarter)

`comove`'s method on one basket (every member with a symbol), for the 52 weekly returns ending at `last_friday`:
residualise on `[1, ACWI, home_index]`, priced = at least 35 of 52 returns for the stock and its home index,
`mean_resid_corr`, shuffle null (seed 0, 500 draws) `null_mean`, `null_p95`, `p_value`. Reuse the functions in
`arp/research/stock_inference/comove.py`; do not copy them.

- `ACWI` with fewer than 35 returns in the window: `skipped: "short_control"`.
- Fewer than 3 priced members: `skipped: "too_few_stocks"`.
- `window_weeks` 52, `stocks` = priced members.

### Diffusion (per quarter, `capex` and `rnd`)

For each member with a `cik`: the annual rows (10-K or 10-K/A, `fp` `FY`, a full year, as `_annual_row` in
`arp/ingestion/xbrl.py`) of the first tag in `_CAPEX_TAGS` (or `_RND_TAGS`) that has at least two distinct
`end` dates among rows with `filed` on or before `quarter_end`. Of those rows, the latest-filed row for each of the
two latest `end` dates gives `latest` and `prior`. The member is `rising` when `latest.val > prior.val`.

- `companies`: members with such a pair; `rising`: how many are rising; `share` = `rising / companies`.
- Fewer than 3 `companies`: `skipped: "too_few_companies"`, `share` and `direction` `null`.
- `direction`: `up` if `share > 0.55`, `down` if `< 0.45`, else `flat`.

### Trend file

`<portfolios_dir>/theme_trends/<taxonomy_id>.json`, written atomically:

| Key | Content |
|---|---|
| `taxonomy_id` | the argument |
| `snapshots[]` | one per quarter, sorted by quarter |

Each snapshot:

| Key | Content |
|---|---|
| `quarter`, `quarter_end` | `2026Q2`, `2026-06-30` |
| `run_id`, `taxonomy_version` | the inference run; the taxonomy's latest version when computed |
| `membership` | `"current_mapping"` |
| `source` | `csv` or `yfinance` |
| `members[]` | `{company_id, symbol, cik, skipped}`: `symbol`/`cik` `null` when absent; `skipped` `no_symbol` or `null` |
| `market` | `{weeks, stocks, basket_return, acwi_return, excess_return, direction, skipped}` |
| `comovement` | `{window_weeks, stocks, mean_resid_corr, null_mean, null_p95, p_value, skipped}` |
| `diffusion` | `{capex: {companies, rising, share, direction, skipped}, rnd: {…same}}` |

Numbers rounded to 4 decimals. No timestamps, so the same inputs give the same file.

### `show`

- No trend file: exit 1, stderr `No trend stored for <taxonomy_id>.`
- `--json`: the trend file's content, unchanged.
- Otherwise line 1 is the literal header
  `quarter\texcess_return\tmarket\tmean_resid_corr\tcorr_change\tcapex_share\tcapex_change\tcapex\trnd_share\trnd_change\trnd`,
  then one line per stored quarter in order. `*_change` = this quarter's value minus the previous *stored*
  quarter's, only when the previous stored quarter is the calendar quarter just before and both values exist.
  Numbers print with 4 decimals; missing values and `null` directions as `n/a`.

## Constraints

- One PR. No new dependency. No change to `comove`'s output or to the inference run.
- Tests use `--prices` and `--facts-dir`; never the network.

## Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| One JSON file per theme, all quarters | Whole trend in one read; same style as `TaxonomyStore`; no migration | chosen by the owner |
| Postgres table | Queryable from SQL / Superset; schema change and Postgres in every test | rejected for now |
| RunStore snapshot per theme and quarter | Reuses storage; listing a theme's history means scanning runs | rejected |
| Theme = inference run + theme rank | Direct link to `comove`; a new run breaks the trend line | rejected (owner: taxonomy id) |

## Calls made (not decided by the owner)

1. Members exclude tier `unknown`.
2. Excess return over ACWI only, no home-index adjustment; equal weights.
3. Co-movement window 52 weeks ending at the quarter's last Friday (a 13-week quarter is too short for
   correlations); minimum 35 returns (2/3, as `comove`).
4. Direction bands: excess return ±0.01 per quarter; diffusion 0.45 / 0.55. Co-movement gets no direction, only
   its change.
5. Speed (`*_change`) is computed by `show` from the stored quarters, not stored, so re-running one quarter
   never leaves a stale change in the next.
6. Diffusion from XBRL capex and R&D only (US filers), CIK from the symbols file; minimum 3 companies.
7. `--facts-dir` as the offline source for filings, like `--prices` for prices.
8. A range is all-or-nothing.

## Left to the builder

Module layout (suggested `arp/research/theme_trend.py` and `arp/cli/theme.py`), how the inference run is found
for a taxonomy, helper names.

## Acceptance

Conventions:
- **Fixture prices**: 91 weekly prices on every Friday from 2025-01-03 to 2026-09-25. `rng =
  numpy.random.default_rng(0)`, drawing `rng.normal(0.0, sd, 90)` in this order: `m`, `h1` (sd 0.02), `t` (sd
  0.03), then noise `n1`..`n4` (sd 0.02). Returns: `ACWI` = `m`, `HOME1` = `h1`, `A<k>` = `m + h1 + t + n<k>`.
  Prices are `100 × cumprod(1 + r)` with 100 as the first row, written with `repr(float)`. Columns `date`,
  `ACWI`, `HOME1`, `A1`..`A4`.
- **Fixture taxonomy and run**: a taxonomy `tax_t` (version 1) and an `InferRun` at `drafted` with `taxonomy_id`
  `tax_t` and `mapping` rows `a1`..`a4` (tier `core`), `a5` (tier `adopter`) and `z1` (tier `unknown`), saved
  with `RunStore.save_snapshot(run_id, "infer", dump(run))`.
- **Fixture symbols**: `company_id,symbol,home_index,cik`; `a<k>` → `A<k>`, `HOME1`, `<k>` for k 1-4. No row
  for `a5` or `z1`.
- **Fixture facts**: `CIK000000000<k>.json` for k 1-4, companyfacts JSON with
  `facts.us-gaap.PaymentsToAcquirePropertyPlantAndEquipment.units.USD` rows (`form` `10-K`, `fp` `FY`,
  `start` Jan 1 and `end` Dec 31 of the year): `a1` FY2023 120 filed 2024-02-15, FY2024 100 filed 2025-02-15,
  FY2025 150 filed 2026-07-15; `a2`, `a3`, `a4` FY2024 100 filed 2025-02-15 and FY2025 110 / 90 / 120 filed
  2026-02-20. No R&D rows.
- `R(s, q)` = `P_s(last_friday) / P_s(prior_friday) − 1` on the fixture prices; `EX(q)` =
  `round(mean(R(A1..A4, q)) − R(ACWI, q), 4)` (about `0.0167` for 2026Q2 and `−0.0148` for 2026Q3).
- Every row runs `arp theme trend snapshot tax_t --symbols <symbols> --prices <prices> --facts-dir <facts>` with
  the quarter flags it names. "Today" is the real date (`date.today()`). "File" is `<portfolios_dir>/theme_trends/tax_t.json`.

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | Fixtures | `snapshot --quarter 2026Q2` | Exit 0; stdout exactly `Saved tax_t 2026Q2` | holdout |
| AC-2 | Same | same | File `snapshots` has 1 entry: `quarter` `2026Q2`, `quarter_end` `2026-06-30`, `membership` `current_mapping`, `source` `csv`, `taxonomy_version` `1` | holdout |
| AC-3 | Same | same | `members[].company_id` is `["a1","a2","a3","a4","a5"]`; `a5` `skipped` `no_symbol`, `symbol` `null`, `cik` `null`; the others `skipped` `null` | holdout |
| AC-4 | Same | same | `market`: `weeks` 13, `stocks` 4, `excess_return` `EX(2026Q2)`, `direction` `up`, `skipped` `null` | holdout |
| AC-5 | Same | same | `market.acwi_return` equals `round(R(ACWI, 2026Q2), 4)` | holdout |
| AC-6 | Same | same | `comovement`: `window_weeks` 52, `stocks` 4, `mean_resid_corr` > `null_p95`, `p_value` `0.002`, `skipped` `null` | holdout |
| AC-7 | Same | same | `diffusion.capex`: `companies` 4, `rising` 2, `share` 0.5, `direction` `flat` | holdout |
| AC-8 | Same | same | `diffusion.rnd`: `companies` 0, `share` `null`, `direction` `null`, `skipped` `too_few_companies` | holdout |
| AC-9 | Fixtures | `snapshot --quarter 2026Q3` | `market.excess_return` `EX(2026Q3)`, `market.direction` `down` | holdout |
| AC-34 | Fixtures | `snapshot --quarter 2026Q3` | `diffusion.capex`: `companies` 4, `rising` 3, `share` 0.75, `direction` `up` (a1's FY2025 filing, filed 2026-07-15, now counts) | holdout |
| AC-10 | Fixtures | `snapshot --from 2026Q2 --to 2026Q3` | Stdout exactly two lines: `Saved tax_t 2026Q2`, `Saved tax_t 2026Q3` | holdout |
| AC-35 | Fixtures | `snapshot --from 2026Q2 --to 2026Q3` | File `snapshots[].quarter` is `["2026Q2","2026Q3"]` | holdout |
| AC-11 | `2026Q2` stored from fixture prices with `A4`'s 2026-05-15 price blank (`market.stocks` 3), and `2026Q3` stored from the full fixture | `snapshot --quarter 2026Q2` with the full fixture prices | The `2026Q2` entry has `market.stocks` 4; still 2 snapshots; the `2026Q3` entry is unchanged | holdout |
| AC-12 | Fixtures, `--quarter 2026Q3` already stored | `snapshot --quarter 2026Q2` | `snapshots[].quarter` `["2026Q2","2026Q3"]` (sorted) and the `2026Q3` entry is unchanged | holdout |
| AC-13 | Fixture prices with `A4`'s 2026-08-14 price blank | `snapshot --quarter 2026Q3` | `market.stocks` 3 | holdout |
| AC-14 | Fixture prices with `A3` and `A4` blank from 2026-07-03 on | `snapshot --quarter 2026Q3` | `market.skipped` `too_few_stocks`, `market.excess_return` `null`, `market.direction` `null` | holdout |
| AC-15 | Fixtures | `snapshot --quarter 2025Q1` | Exit 0; `market.skipped` `short_control`; `comovement.skipped` `short_control` | holdout |
| AC-16 | Fixture symbols without the `cik` column | `snapshot --quarter 2026Q2` | Exit 0; `diffusion.capex` `companies` 0, `skipped` `too_few_companies` | holdout |
| AC-17 | Fixtures | `snapshot --quarter 2099Q1` | Exit 1; stderr `Quarter 2099Q1 has not ended.`; no file | holdout |
| AC-18 | Fixtures, `2026Q2` stored | `snapshot --from 2026Q3 --to 2099Q1` | Exit 1; stderr `Quarter 2099Q1 has not ended.`; file byte-identical | holdout |
| AC-19 | Fixtures | `snapshot --quarter 2026-3` | Exit 1; stderr `Quarter 2026-3 is not in the form YYYYQn.` | holdout |
| AC-20 | Fixtures | `snapshot` with no quarter flag; with `--quarter 2026Q2 --from 2026Q1 --to 2026Q2`; with `--from 2026Q2` alone | All three exit 1; stderr `Give --quarter, or --from and --to.` | holdout |
| AC-21 | Fixtures | `snapshot --from 2026Q3 --to 2026Q2` | Exit 1; stderr `--from 2026Q3 is after --to 2026Q2.` | holdout |
| AC-22 | No taxonomy `tax_nope` | `snapshot tax_nope ... --quarter 2026Q2` | Exit 1; stderr `Taxonomy tax_nope not found.` | holdout |
| AC-23 | A taxonomy `tax_hand` with no inference run | `snapshot tax_hand ... --quarter 2026Q2` | Exit 1; stderr `Taxonomy tax_hand has no stock mapping; trend needs a taxonomy made by 'arp taxonomy infer pick'.` | holdout |
| AC-24 | Fixture symbols with `a3`'s `home_index` blank, `2026Q2` stored | `snapshot --quarter 2026Q3` | Exit 1; stderr `Stock a3 has no home_index.`; file byte-identical | holdout |
| AC-25 | Fixtures, `--from 2026Q2 --to 2026Q3` stored | `show tax_t` | Line 1 is the literal header from the Design; 3 lines in all; line 3 starts `2026Q3\t` and its `capex_change` column is `0.2500` | holdout |
| AC-26 | Same | `show tax_t` | Line 2 has `n/a` in `corr_change`, `capex_change` and `rnd_change`, and `n/a` in `rnd_share` and `rnd` | holdout |
| AC-27 | Fixtures, `2025Q4` and `2026Q2` stored (no `2026Q1`) | `show tax_t` | The `2026Q2` line has `n/a` in `corr_change` (both quarters have a `mean_resid_corr`; the gap rule alone makes it `n/a`) | holdout |
| AC-28 | Same as AC-25 | `show tax_t --json` | Output parses to the file's content | holdout |
| AC-29 | No trend file | `show tax_t` | Exit 1; stderr `No trend stored for tax_t.` | holdout |
| AC-30 | Fixtures, run twice in two empty data dirs | `snapshot --from 2026Q2 --to 2026Q3` | The two files are byte-identical | holdout |
| AC-31 | Fixtures, `ARP_ANTHROPIC_API_KEY` unset | `snapshot --quarter 2026Q2` | Exit 0; file byte-identical to the one from the same command with `ARP_ANTHROPIC_API_KEY=dummy` | holdout |
| AC-32 | Fixtures | `snapshot --quarter 2026Q2` | The inference run's JSON (`infer show --json`) and the taxonomy file are byte-identical before and after | holdout |
| AC-33 | The fixture run, symbols and prices defined in the Acceptance conventions of `2026-11-07-theme-comovement-design.md` | `arp taxonomy infer comove <run> --symbols <symbols> --prices <fixture> --end 2026-10-30` | The `comovement` block in `infer show --json` is identical to the block `main` produces on the same fixture (recorded from `main` by the test-writer) | holdout |
| AC-36 | `2026Q2` stored; fixture facts with `CIK0000000004.json` replaced by the text `not json` | `snapshot --from 2026Q2 --to 2026Q3` | Exit code not 0; file byte-identical | holdout |

Must not change: the inference run and the taxonomy (AC-32); `comove`'s behaviour (AC-33).

Row IDs are not in numeric order: AC-34 to AC-36 were added after the spec-critic pass, next to the rows they
split from.
