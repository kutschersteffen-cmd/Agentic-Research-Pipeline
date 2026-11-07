# Theme co-movement from weekly returns (Engine A, layer 3, first slice)

Spec slug: `theme-comovement`. Status: approved by the owner 2026-11-07. Date: 2026-11-07.
Review page: https://claude.ai/artifact/6FETE3paKBhbJsK5D3NY7S.
Builds on `2026-11-04-taxonomy-from-stocks-design.md` (the `arp taxonomy infer` run, layers 1 and 2).

## Intent

Layers 1 and 2 say what a stock set is *about*, from text. They cannot say whether the market *trades* the
stocks as one theme. A stock can be described as a hydrogen company and move like an industrial (Air Products,
Cummins), and a fund's largest holding can be only loosely tied to the rest (Bloom: 16 % of HYDR, partial R²
0.11). This step measures, from weekly returns, how strongly each stock moves with the others once market and
home-market moves are removed, per stock and per basket, and flags where text and returns disagree.

A prototype on HYDR (24 holdings, 156 weeks) already showed the method works: mean residual correlation 0.095
against a shuffle null of 0.009, two factors above noise (hydrogen; Korea vs West), partial R² from 0.35
(Ballard) to 0.01 (Air Products, Cummins). This spec turns that prototype into a repeatable run step. It reuses
the prototype's method, cut to the owner's choices below.

## Where it sits

```
arp taxonomy infer start ──► profiles, clusters, ranked themes            [stage themes_ready]
arp taxonomy infer comove <run_id> --symbols <csv> ──► run JSON `comovement` block   (stage unchanged)
arp taxonomy infer pick ──► draft taxonomy                                [stage drafted]
```

`comove` runs at `themes_ready` or `drafted`, as often as wanted; each run replaces the block.

## Goals

1. One command adds a `comovement` block to an inference run: per-stock loadings on a leave-one-out theme
   factor and per-basket tests, for the basket of all priced stocks and one basket per ranked theme.
2. Every number is computed in code from weekly local-currency returns; no model call.
3. Text-vs-return disagreements are flagged per theme: `text_only` (a supporting stock that does not move with the
   theme) and `returns_only` (a non-supporting stock that does).
4. Same inputs give the same block, whatever the row order of the symbols file.

## Non-goals (later slices, each its own spec or row)

- Style factors (momentum, growth/value, quality) and theme-driver factors (EUA, TTF gas, platinum).
- IWM small-cap and US10Y yield-change controls from the prototype (owner: ACWI + home index only for now).
- Thin-trading corrections: Dimson / Scholes-Williams betas, Huber or winsorised regression.
- Thematic-ETF flow factor (shares outstanding) as the false-co-movement control.
- Hierarchical partial-pooling betas for short histories (this slice skips short histories instead).
- Rolling or Kalman time-varying beta, absorption ratio (for the later trend engine).
- Matched random baskets from a wider price universe; out-of-sample check; AUC against golden `core` vs `not`.
- Disagreement flags on `mapping[].tier` (owner: theme membership only).
- Automatic symbol or home-index resolution from tickers or ISINs (owner: always a symbols file).
- Using the result to change themes, mapping, tiers or the taxonomy; UI and API endpoints.
- Daily returns.

## Anti-goals

- A control that holds the basket's own stocks (owner rule).
- A guessed Yahoo symbol or home index.
- A failed or refused `comove` that changes the run record.
- A result that changes when the symbols file's rows are reordered.

## Owner decisions (2026-11-07)

Baskets: all priced stocks + one per ranked theme · symbols and home indices always from a `--symbols` CSV ·
controls ACWI + home index only · flags on theme membership · result stored as a block on the inference run,
replaced on re-run, no new stage · from the owner's earlier review: weekly returns, the correct home index per
listing (KOSDAQ for KOSDAQ listings, which the symbols file carries), never a control holding the theme's stocks.

## Design

### Command

```
arp taxonomy infer comove <run_id> --symbols <csv> [--end <YYYY-MM-DD>] [--weeks 156] [--prices <wide csv>]
```

- `--symbols`: CSV with header columns `company_id`, `symbol`, `home_index` (others ignored). `symbol` and
  `home_index` are price-source symbols (Yahoo: `NEL.OL`, `^OSEAX`, `288620.KQ`, `^KQ11`). Rows whose
  `company_id` is not a described stock of the run are ignored before any other check. Among the remaining rows:
  a blank `symbol` counts as no row (`no_symbol`); a blank `home_index` exits 1 with
  `Stock <company_id> has no home_index.`; a `company_id` on two rows exits 1 with
  `<path>: company_id <company_id> appears twice.`
- `--end`: last week-end date of the window; default the most recent Friday strictly before today.
- `--weeks`: number of weekly returns in the window, default 156.
- `--prices`: a wide CSV (`date` + one column per symbol, weekly prices, one row per week-end) read with
  `CsvPriceSource`; without it, Yahoo. Used for offline runs and tests.
- Checks run in this order: run lookup, stage, symbols file, controls, prices.
- Stage check: at any stage other than `themes_ready` or `drafted`, exit 1 with
  `Run <run_id> is at stage '<stage>'; 'comove' needs 'themes_ready' or 'drafted'.` (this exact text; `WrongStage` need
  not be reused).
- Unknown run: exit 1 with `Run <run_id> not found.` (as `infer show`).
- Symbols file without the three columns: exit 1 with `<path>: needs columns company_id, symbol, home_index.`
  `<path>` is printed exactly as passed to `--symbols`.
- A `home_index` that equals a `symbol` in the (kept) rows, or `ACWI` appearing as a `symbol`: exit 1 with
  `Control <symbol> is also a stock in the run.`
- Success: stdout line 1 `Run <run_id>`, then the basket and flag lines (format below).
- Every refusal and failure leaves the stored run byte-identical.

### Prices

- `PriceDataSource` gets `get_weekly_returns(tickers, start, end) -> PricePanel` alongside the monthly method,
  implemented by both `CsvPriceSource` (rows are already week-ends; a symbol with no column gets all-`None`
  returns instead of the monthly method's `ValueError`) and `YFinancePriceSource` (daily
  auto-adjusted closes, last close of each week ending Friday, `W-FRI`). Returns are in the listing's own
  currency; no FX conversion. The monthly method is unchanged.
- The window is the `--weeks` weekly returns ending at `--end`, fetched for every stock symbol, every distinct
  `home_index` and `ACWI`.
- A stock is **priced** when it has a symbol, at least `ceil(2/3 × weeks)` (104 of 156) non-missing returns,
  and its `home_index` has at least `ceil(2/3 × weeks)` non-missing returns in the window. Otherwise it is skipped with `no_symbol` (no row or blank symbol),
  `short_history` (fewer returns, including none or no price column), or `short_control` (its home index is
  short), checked in that order.
- `ACWI` with fewer than `ceil(2/3 × weeks)` returns: exit 1 with
  `Control ACWI has prices for only <k> of <weeks> weeks.`
- Fewer than 3 priced stocks: exit 1 with `Only <k> stocks have prices for at least <min> of <weeks> weeks;
  comove needs 3.`

### Method (from the prototype)

1. **Residualise.** Per priced stock `i`: OLS of `r_i` on `[1, ACWI, home_index_i]` over the weeks where all three
   have a return. The residual `e_i,t` exists on those weeks, is missing on others.
2. **Baskets.** `all`: every priced stock. `theme:<rank>`: for each theme in `themes`, its `supporting` stocks that
   are priced. A basket with fewer than 3 priced members gets `skipped: "too_few_stocks"` and no numbers.
3. **Theme factor.** For stock `i` and basket `B`: `f_t` = mean of `e_j,t` over members `j ≠ i` with a residual at
   `t`; missing when fewer than 2 such `j`. For a member this is leave-one-out; for a non-member it is the mean
   over all members.
4. **Loadings,** for every priced stock against every non-skipped basket: OLS of `e_i` on `[1, f]` over weeks
   where both exist (`n_weeks`).
   - `beta`: the slope. `partial_r2`: the R² of that regression (the theme factor's partial R² given the
     controls, by Frisch-Waugh-Lovell).
   - `nw_t`: slope / Newey-West standard error, Bartlett kernel, 4 lags.
   - `down_corr` / `up_corr`: Pearson correlation of `e_i` and `f` on weeks with `f < 0` / `f > 0`.
   - `lag_corr`: corr(`e_i,t`, `f_t-1`) (the stock follows the theme a week later); `lead_corr`:
     corr(`e_i,t`, `f_t+1`).
   - Fewer than 52 shared weeks: every number in the row is `null`.
5. **Basket tests.**
   - `mean_resid_corr`: mean Pearson correlation over all member pairs, each pair on its shared weeks.
   - Shuffle null: a fresh `numpy.random.default_rng(0)` per basket; 500 draws; each draw permutes each member's
     observed residual values among that member's observed weeks (gaps stay where they are), members in
     `company_id` order, and recomputes the mean correlation.
     `null_mean`, `null_p95` (`numpy.percentile(..., 95)`), `p_value` = (1 + draws ≥ observed) / 501.
   - Eigenvalues of the members' residual correlation matrix on the weeks where every member has a residual
     (`complete_weeks` = T, members = N): `eigenvalues` (descending, at most 5), `mp_lambda_plus` =
     (1 + √(N/T))², `factors_above_noise` = count of eigenvalues > `mp_lambda_plus`. When T < 2N these three are
     `null`.
6. **Flags,** theme baskets only: a member with `nw_t < 2` → `text_only`; a non-member with `nw_t ≥ 2` →
   `returns_only`; otherwise `null`. A row with `nw_t` `null` gets no flag.

### Run JSON (`infer show --json`)

`comovement` is absent until `comove` has run (so runs without it print exactly as today), then:

| Key | Content |
|---|---|
| `end`, `weeks`, `source` | window end date, weeks, `yfinance` or `csv` |
| `controls` | `["ACWI", "home_index"]` |
| `stocks[]` | `{company_id, symbol, home_index, n_returns, skipped}`: one per described stock; `skipped` `null`, `no_symbol`, `short_history` or `short_control` |
| `baskets[]` | `{basket, members[], skipped, mean_resid_corr, null_mean, null_p95, p_value, complete_weeks, eigenvalues[], mp_lambda_plus, factors_above_noise}` |
| `loadings[]` | `{basket, company_id, member, n_weeks, beta, partial_r2, nw_t, down_corr, up_corr, lag_corr, lead_corr, flag}` |

Numbers rounded to 4 decimals as in the rest of the run JSON. Sorting: `stocks` and `members` by `company_id`;
`baskets` `all` first, then by theme rank; `loadings` in basket order, then by `company_id`.

### Stdout after `Run <run_id>`

Line 2 is the literal header `basket\tmembers\tmean_resid_corr\tnull_p95\tp_value\tfactors_above_noise`, then one
line per basket (`members` is the member count; a skipped basket prints its `skipped` value in each number
column). Then the literal header `flag\tbasket\tcompany_id\tnw_t`, then one line per non-null flag, in JSON order.
Numbers print with 4 decimals; missing values as `n/a`.

## Constraints

- Yahoo through `yfinance` (the `replication` extra); tests use `--prices` and never the network.
- One PR. No new dependency: numpy is enough for OLS, Newey-West, correlations and eigenvalues.
  (`signal_lab/stats.newey_west_t` is the HAC t of a mean, not of a slope; reuse its kernel, not the function.)

## Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| `comovement` block on the inference run | One record to read; `infer show` already prints it; re-run replaces it | chosen by the owner |
| Separate comove run in `RunStore` | Several windows side by side; more code for history nobody asked for | rejected |
| Report file only | Simplest; nothing for the later trend engine or UI to read | rejected |

## Calls made (not decided by the owner)

1. Minimum history 2/3 of the window (104 of 156 weeks); minimum 3 priced stocks per basket; 52 shared weeks per loading.
2. Week end Friday (`W-FRI`), last daily close of the week; ACWI fixed as the global control symbol.
3. `text_only` / `returns_only` threshold `nw_t` 2, one-sided.
4. Shuffle null permutes each member's residuals in time independently, seed 0.
5. Eigenvalue test only when complete weeks ≥ 2 × members.
6. Description-less (not described) stocks are not priced and not listed.
7. Symbols-file edge cases: blank symbol → `no_symbol`; blank home index and duplicate ids refuse.
8. A short home index skips only the stocks that use it (`short_control`); only a short ACWI stops the run.
9. One fresh seed-0 generator per basket; shuffles keep each member's gaps in place.
10. Stdout `members` is a count; two literal header lines.

## Left to the builder

Module layout (suggested `arp/research/stock_inference/comove.py`), helper names, how Yahoo symbols are batched.

## Acceptance

Conventions:
- **Fixture prices** (the "fixture"): 160 weekly prices, dates every Friday ending 2026-10-30, built as
  `rng = numpy.random.default_rng(0)`, drawing in this order with `rng.normal(0.0, sd, 159)` (`sd` is the
  standard deviation): `m`, `h1`, `h2` (sd 0.02), `t_theme` (sd 0.03), then noise for `a1`, `a2`, `a3`, `a4`
  (sd 0.02) and `b1`, `b2` (sd 0.03). Returns: `ACWI` = `m`, `HOME1` = `h1`, `HOME2` = `h2`;
  `a*` = `m + h1 + t_theme + noise`; `b*` = `m + h2 + noise`. Prices are `100 × cumprod(1 + r)` with 100 as the
  first row, written with `repr(float)` (full precision). Columns `date`, `ACWI`, `HOME1`, `HOME2`, `A1`..`A4`,
  `B1`, `B2`. The expected values in AC-4 to AC-9 were checked on this fixture with the prototype method on
  2026-11-07 (theme stocks `nw_t` 11.7 to 14.7, `b1` 0.08, `a4` 15.7, `b2` −0.82; no shuffle draw reached the
  observed correlation; second eigenvalue of `theme:1` 1.001).
- **Fixture run**: an `InferRun` at `themes_ready` with described stocks `a1`..`a4`, `b1`, `b2` (each with a
  `description`) and one theme, rank 1, supporting `a1`, `a2`, `a3`, `b1`, written with
  `RunStore.save_snapshot(run_id, "infer", dump(run))`. "Moved to stage X" = the same run re-saved with that
  stage; a "copy" = the same run under a second `run_id`. No row makes a model call.
- **Fixture symbols**: `company_id,symbol,home_index`; `a*` → `A*`, `HOME1`; `b*` → `B*`, `HOME2`.
- Every row runs `arp taxonomy infer comove <run> --symbols <symbols> --prices <fixture> --end 2026-10-30` unless
  it says otherwise. "Run JSON" is `infer show <run> --json`.

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | Fixture run, symbols, prices | `comove` | Exit 0; stdout line 1 `Run <run_id>` | holdout |
| AC-2 | Same | `comove` | Run JSON `stage` still `themes_ready` | holdout |
| AC-3 | Same | `comove` | `comovement.baskets[].basket` is `["all", "theme:1"]` | holdout |
| AC-4 | Same | `comove` | Basket `theme:1` `members` `["a1","a2","a3","b1"]` | holdout |
| AC-5 | Same | `comove` | `loadings` has 12 rows; in `theme:1`, `member` is `true` for `a1`,`a2`,`a3`,`b1` and `false` for `a4`,`b2` | holdout |
| AC-6 | Same | `comove` | `theme:1` loadings `a1`,`a2`,`a3`: `nw_t` > 5, `partial_r2` > 0.3, `flag` `null` | holdout |
| AC-7 | Same | `comove` | `theme:1` loading `b1`: `flag` `text_only` | holdout |
| AC-8 | Same | `comove` | `theme:1` loading `a4`: `flag` `returns_only` | holdout |
| AC-9 | Same | `comove` | `theme:1` loading `b2`: `flag` `null` | holdout |
| AC-10 | Same | `comove` | Every `all` loading has `flag` `null` | holdout |
| AC-11 | Same | `comove` | Basket `all`: `mean_resid_corr` > `null_p95` and `p_value` `0.002` | holdout |
| AC-12 | Same | `comove` | Basket `theme:1`: `complete_weeks` `156`, `mp_lambda_plus` `1.3459`, `factors_above_noise` `1`, `eigenvalues` 4 entries in descending order | holdout |
| AC-13 | Same | `comove` | `comovement.end` `2026-10-30`, `weeks` `156`, `source` `csv`, `controls` `["ACWI","home_index"]` | holdout |
| AC-14 | Fixture symbols, and a copy with the rows in reverse order | `comove` on the fixture run and on its copy, one file each | The two `comovement` blocks are identical | holdout |
| AC-15 | Fixture symbols without the `b2` row | `comove` | `stocks` entry `b2`: `skipped` `no_symbol` | holdout |
| AC-16 | Same | `comove` | No `loadings` row has `company_id` `b2` | holdout |
| AC-17 | Fixture prices with `A4`'s first 60 prices blank | `comove` | `stocks` entry `a4`: `skipped` `short_history`, `n_returns` `99` | holdout |
| AC-18 | Fixture prices without the `B2` column | `comove` | Exit 0; `stocks` entry `b2`: `skipped` `short_history`, `n_returns` `0` | holdout |
| AC-19 | Fixture prices with every `HOME2` price blank | `comove` | Exit 0; `stocks` entries `b1` and `b2`: `skipped` `short_control` | holdout |
| AC-19a | Fixture prices with `HOME2`'s first 50 prices blank | `comove` | `stocks` entries `b1` and `b2`: `skipped` `null` | holdout |
| AC-20 | Fixture run with a second theme, rank 2, supporting `b1`, `b2` | `comove` | Basket `theme:2`: `skipped` `too_few_stocks`, `mean_resid_corr` `null` | holdout |
| AC-21 | Same | `comove` | No `loadings` row has basket `theme:2` | holdout |
| AC-22 | Fixture symbols with `b1`'s `home_index` set to `A1` | `comove` | Exit 1; stderr `Control A1 is also a stock in the run.`; run JSON byte-identical to before | holdout |
| AC-23 | Fixture symbols with `a1`'s `symbol` set to `ACWI` | `comove` | Exit 1; stderr `Control ACWI is also a stock in the run.`; run JSON byte-identical | holdout |
| AC-24 | Fixture prices with every `ACWI` price blank | `comove` | Exit 1; stderr `Control ACWI has prices for only 0 of 156 weeks.`; run JSON byte-identical | holdout |
| AC-25 | Fixture symbols with only the `a1` and `a2` rows | `comove` | Exit 1; stderr `Only 2 stocks have prices for at least 104 of 156 weeks; comove needs 3.`; run JSON byte-identical | holdout |
| AC-26 | Symbols file `bad.csv` with header `company_id,ticker` | `comove <run> --symbols bad.csv ...` | Exit 1; stderr `bad.csv: needs columns company_id, symbol, home_index.` | holdout |
| AC-27 | Fixture symbols with `a3`'s `home_index` blank | `comove` | Exit 1; stderr `Stock a3 has no home_index.`; run JSON byte-identical | holdout |
| AC-28 | Fixture symbols `sym.csv` with the `a3` row twice | `comove <run> --symbols sym.csv ...` | Exit 1; stderr `sym.csv: company_id a3 appears twice.` | holdout |
| AC-29 | Fixture run re-saved at stage `failed` | `comove` | Exit 1; stderr `Run <run_id> is at stage 'failed'; 'comove' needs 'themes_ready' or 'drafted'.` | holdout |
| AC-30 | No run `nope` | `comove nope --symbols <fixture symbols> --prices <fixture> --end 2026-10-30` | Exit 1; stderr `Run nope not found.` | holdout |
| AC-31 | Fixture run after `comove` | `comove` again with `--weeks 120` | Exit 0; `comovement.weeks` `120` | holdout |
| AC-32 | Fixture run, never `comove`d | `infer show --json` | Output has no `comovement` key and equals `dump(run)` of the saved fixture run | holdout |
| AC-33 | Fixture run | `comove` | Every run JSON key other than `comovement` is identical before and after | holdout |
| AC-34 | Fixture run re-saved at stage `drafted` | `comove` | Exit 0; `stage` still `drafted` | holdout |
| AC-35 | Fixture prices CSV | `CsvPriceSource(path).get_weekly_returns(["ACWI"], "2023-01-01", "2026-10-30")` | 160 `period_ends`, last `2026-10-30`; `returns["ACWI"][0]` `None`; `returns["ACWI"][1]` equals `m[0]` within 1e-9 | holdout |
| AC-36 | Same CSV | `CsvPriceSource(path).get_monthly_returns(["ACWI"], "2023-01-01", "2026-10-30")` | Same three results as AC-35 (the monthly method is unchanged) | holdout |
| AC-37 | Same CSV | `CsvPriceSource(path).get_monthly_returns(["NOPE"], "2023-01-01", "2026-10-30")` | Raises `ValueError` (as on `main`) | holdout |
| AC-38 | `yf.download` stubbed to return daily closes Mon 2026-10-19 to Fri 2026-10-30, Fridays 100 and 110 | `YFinancePriceSource().get_weekly_returns(["X"], "2026-10-19", "2026-10-30")` | `period_ends` `["2026-10-23","2026-10-30"]`; `returns["X"][1]` `0.1` within 1e-9 | unit |
| AC-39 | Today 2026-11-06 (a Friday), then today 2026-11-07 | `comove` without `--end` | `comovement.end` `2026-10-30`, then `2026-11-06` | unit |
| AC-40 | Stdout of AC-1 | | Line 2 `basket\tmembers\tmean_resid_corr\tnull_p95\tp_value\tfactors_above_noise`; line 3 starts `all\t6\t` | holdout |
| AC-41 | Stdout of AC-1 | | Line 5 `flag\tbasket\tcompany_id\tnw_t`; then exactly two lines, starting `returns_only\ttheme:1\ta4\t` and `text_only\ttheme:1\tb1\t` | holdout |
| AC-42 | Fixture run, no LLM key set (`ARP_ANTHROPIC_API_KEY` unset) | `comove` | Exit 0; `comovement` equals AC-1's | holdout |
| AC-43 | Fixture run after `comove` (stub LLM for `pick`) | `infer pick <run> --theme 1` | Exit 0; `stage` `drafted`; `comovement` unchanged | unit |

Must not change: `infer show --json` for runs without `comove` (AC-32); every other run key (AC-33); the stage
(AC-2, AC-34); monthly returns (AC-36, AC-37); `pick` on a run with the block (AC-43).
