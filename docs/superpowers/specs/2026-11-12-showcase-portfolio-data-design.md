# Showcase portfolio data: simulated ESG for the public holdings, imported into Transition Intelligence

Slug: `showcase-portfolio-data`. Risk: high (portfolio import, load records, a new observation source).

## Decisions for the owner at approval

1. **Where the A-F transition grade comes from.** Recommended: **(a) a column of the simulated dataset**,
   computed by a fixed rule against sector peers (section "Transition grade"). Alternative: **(b) Decision
   Studio**, a six-tier framework run over the simulated indicators. The existing preset in
   `backend/arp/decision/credibility.py` has five tiers (A Credible, B Credible gaps, C Partial, D Not
   credible, E Opaque) and a five-question test that needs indicator columns this dataset does not have;
   (b) means reworking that preset and revising this spec before any build. Rows AC-20 to AC-25 hold for (a).
2. **Where grades show** (any of three; rows retire with the places not picked):
   - **Company page** (rows AC-60 to AC-62): needs the imported companies to open on `#/companies/<ref>`,
     which today knows only registry companies, so PR 3 registers them (about 2,540).
   - **Transition Intelligence dashboards** (rows AC-63, AC-64): the grade and a per-portfolio grade
     breakdown go into `bi_published`. Dashboards are Superset embeds, so they are not visible where no
     Superset runs (the bank JupyterLab has none).
   - **Index Construction as a field** (row AC-65): the dataset names the column `transition_grade`;
     `index-starting-universe` turns the file into index candidates, where it shows as a category.

## Intent

The owner cannot get ESG data (12 Nov): "we can not get esg data. therefore we need to mock them. so the ask
is that you simulate various kinds of esg data and revenue shares to controversial activities such as
tobacco, oil, gas etc. think about reasonable estimate for these exposures. use the sectors as reference. we
also need to include the holdings of the portfolios into transition intelligence workspace." And: "simulate a
transition assessment with a scale applicable within each sector A (Leader), B (Credible), C(Gaps),
D(Emerging), E(not credible), F(Disqualified)". The owner also chose "Fix English labels in the app".

So this spec builds three things:

1. A **simulated dataset**, one row per company in the seven public holdings files, with sector-based
   estimates, labelled simulated wherever a value shows.
2. The seven **public portfolios imported into Transition Intelligence** in a state where the monthly run
   works, run for six months so `bi_published` (what the dashboards read) has a history.
3. One **A-F transition grade** per company against its sector peers, shown where the owner picks.

It takes over the portfolio part of the unapproved draft `2026-11-12-showcase-demo-pack-design.md`
(branch `ccr-ab3f2be4-wt1dcl`): its loader step `portfolios`, row AC-40 and plan decisions 5, 8 and 9. The
rest of that draft (ten companies, documents, Argus and voting runs, run sheet) is not part of this spec.

## Current state (read on `main` d9b65c2)

- `data/holdings/` holds `DAX.xlsx`, `EURO_STOXX_50.xlsx`, `MSCI_EM.xlsx`, `MSCI_Europe.xlsx`, `MSCI_World.xlsx`,
  `SP500.xlsx` (sheet date 2026-11-02, German labels). `AI_Big_Data.xlsx` (sheet date 2026-11-12, fund ISIN
  IE00BGV5VN51, English labels) is on branch `ccr-ab3f2be4-wt1dcl` only; PR 1 brings it to `main` unchanged.
- Rows whose `Type of Security` is `Aktien`, `Equities`, `Depository Receipts` or `Preferred Stock` carry
  about 2,540 distinct ISINs across the seven files. Sectors are GICS-like, in German (`Finanzen`,
  `Versorgungsunternehmen`, ...), English in the AI file (`Technology`, ...), plus a legacy scheme
  (`Finanzdienstleister`, `Verbrauchsgüter`, `Grundstoffe`, ...).
- `arp portfolio import-constituents` (`backend/arp/portfolio/constituent_import.py`) accepts only
  `Constituent_<12 characters>.xlsx`, requires `--notional-eur`, writes one snapshot at the sheet date, writes
  no holdings load record, and translates only German labels: `Equities`, `Preferred Stock`, `Share Class`,
  `Right` become asset class `other`; English countries and sectors and `Grundstoffe`, `unknown` are reported
  as untranslated. Companies are stored as `isin_<ISIN>`.
- `arp portfolio monthly-run` (`backend/arp/portfolio/monthly_run.py`) is blocked unless every portfolio has
  an `ok` holdings load record for the month and the ESG provider has an `ok` ESG load. When it runs it
  publishes `portfolio_climate_metrics`, `alerts`, `triggers` and `company_profile` into `bi_published`
  (Postgres only). `company_profile` already carries every observation field with its `source`.
- The ESG upload (`backend/arp/portfolio/climate/esg_intake.py`) takes seven columns: `company_id`,
  `climate_scope1_tco2e`, `climate_scope2_tco2e`, `climate_scope3_tco2e`, `climate_carbon_intensity`,
  `climate_evic_eur_m`, `climate_revenue_eur_m`, `climate_green_revenue_pct` (percent). It writes
  observations with source `internal_api`. Observation sources are `internal_api`, `extracted`, `catalogue`,
  `estimated_proxy` (priority in that order, `datapoint_mapping._SOURCE_PRIORITY`).
- Index Construction (`backend/arp/index/`) screens on metrics `esg_score`, `ghg_intensity`, `lct_score`,
  `coal_revenue_pct`, `oil_revenue_pct`, `gas_revenue_pct`, `high_intensity_power_revenue_pct`,
  `tobacco_revenue_pct`, `green_revenue_pct` (fractions 0 to 1), flags `norms_violation`,
  `controversial_weapons`, `severe_controversy`, category `lct_category`. Its universe is the hash-seeded
  `demo_universe()`.
- PR #419 (`showcase-portfolio-fixes`) changes `HoldingsIntake` and the ESG upload (defects 6 to 8).

## Goals

1. One simulated row per company in the seven files, with the seven climate columns, further ESG scores,
   revenue shares in eight controversial activities, two exclusion flags and a transition grade.
2. Values are plausible for the company's sector and size: emissions scale with revenue, high-emitting
   sectors are far above low-emitting ones, and controversial revenue appears only where the business does it.
3. Every simulated value says it is simulated wherever it shows: file, observation source, published rows,
   screens.
4. The seven public files import through the app's own import under their own names, without a notional,
   with English labels translated.
5. Each imported portfolio can be run monthly for 2026-05 to 2026-10, and those six runs fill `bi_published`.
6. One A-F grade per company, relative to its sector peers, with a fixed share of each grade per sector.
7. Same input, same output: regenerating the dataset gives the same bytes.

## Non-goals

- Real ESG data, or any claim that a value is real.
- Portfolios other than the seven files and the app's seeded demo portfolios.
- A Decision Studio credibility rework, unless the owner picks decision 1(b).
- Index Construction candidates built from the dataset (that is `index-starting-universe`, which depends on PR 1).
- Superset dashboards or charts; this spec only fills the rows they read.
- Monthly runs for 2026-11 (the month has not ended).

## Anti-goals

- A real company shown as a norms violator or controversial-weapons maker by chance: those two flags come
  only from the hand-written override list, never from a random draw.
- A simulated value that could be read as real on any screen or export.
- Absurd numbers in front of senior management: a software company with tobacco revenue, a bank with
  steel-mill emissions, Apple with a revenue of EUR 2 million.
- Two share lines of one company with different grades when the files give them the same name.

## Constraints

- Simulated history is invented and must say so: load records carry `simulated history` in their detail,
  portfolios get the tag `history:simulated`.
- PR 2 changes the same ESG upload and holdings code as PR #419 and is built after #419 merges.
- The dataset is hash-seeded on the company name (SHA-256, the way `arp/index/mock_data.py` draws), never
  `random` without a seed.
- No identifier is typed from memory: the override list names companies by the ISIN and name the holdings
  files give.

## Approaches

1. **Committed dataset file from a deterministic generator, loaded through the app's own intake (chosen,
   my call).** `arp showcase simulate` writes `data/simulated/esg_simulated.csv`; the file is committed so
   the owner can open it in Excel and reviewers can read the numbers; `arp showcase load` feeds it through
   the ESG upload and the import. Costs one generator, one loader, one 1 MB file.
2. Generate on the fly at load time, nothing committed (as `demo_universe()` does). Smaller repo, but nobody
   can review the numbers before the demo, and `index-starting-universe` would have to call the generator.
3. Extend `arp portfolio seed-demo`. Rejected: seeded demo portfolios are invented companies; these are real
   holdings, and mixing the two hides which is which.

## Simulated dataset (PR 1)

`arp showcase simulate [--holdings-dir data/holdings] [--out data/simulated/esg_simulated.csv]` reads the
seven files and `data/simulated/activity_overrides.csv` and writes the dataset. `data/simulated/README.md`
starts with the line `SIMULATED DATA. Not real ESG data. Generated by arp showcase simulate.` and lists the
sector tables below.

**Rows.** One per distinct ISIN over rows whose `Type of Security` is `Aktien`, `Equities`,
`Depository Receipts` or `Preferred Stock`. Name, country and sector come from the first file in this order:
`MSCI_World`, `MSCI_EM`, `MSCI_Europe`, `SP500`, `EURO_STOXX_50`, `DAX`, `AI_Big_Data`. Rows are sorted by ISIN.

**Seed.** Every draw comes from SHA-256 of the name, upper-cased and stripped, so lines the files give the
same name get identical values (except `isin`, `company_id`, `files`).

**Columns**, in this order:

| Group | Columns |
|---|---|
| Identity | `isin`, `company_id` (`isin_<ISIN>`), `name`, `country` (English), `sector` (peer group, table below), `files` (file stems, `;`-joined), `data_status` (always `simulated`) |
| Climate (the ESG upload's seven) | `climate_scope1_tco2e`, `climate_scope2_tco2e`, `climate_scope3_tco2e`, `climate_carbon_intensity` (tCO2e per EUR M revenue, scope 1+2), `climate_evic_eur_m`, `climate_revenue_eur_m`, `climate_green_revenue_pct` (percent, 0 to 100) |
| ESG scores (0 to 10, 2 decimals) | `esg_e_score`, `esg_s_score`, `esg_g_score`, `esg_score` (mean of the three), `esg_trend` (0.80 to 1.20), `controversy_level` (integer 0 to 5) |
| Revenue shares (fractions 0 to 1, 4 decimals, Index Construction's convention) | `coal_revenue_pct`, `oil_revenue_pct`, `gas_revenue_pct`, `high_intensity_power_revenue_pct`, `tobacco_revenue_pct`, `weapons_revenue_pct`, `alcohol_revenue_pct`, `gambling_revenue_pct` |
| Flags (`true`/`false`) | `controversial_weapons`, `norms_violation`, `severe_controversy` (`controversy_level` = 5) |
| Transition | `ghg_intensity` (= `climate_carbon_intensity`), `green_revenue_pct` (= green share / 100), `lct_score` (0 to 10), `lct_category`, `transition_score` (0 to 1, 4 decimals), `transition_grade` (`A` to `F`), `transition_grade_label` |

**Peer group (`sector`).** Every sector label in the files maps to one of: Energy, Materials, Industrials,
Utilities, Consumer Staples, Consumer Discretionary, Health Care, Financials, Information Technology,
Communication Services, Real Estate, Unknown. German GICS names map to their English name; legacy names:
`Finanzdienstleister` → Financials, `Technologie`/`Technology` → Information Technology,
`Telekommunikation`/`Telecommunications` → Communication Services, `Verbrauchsgüter` → Consumer Discretionary,
`Grundstoffe` → Materials, `unbekannt`/`unknown`/blank → Unknown. An unmapped label fails the run, naming it.

**Size.** Market cap (EUR M) = the company's weight in its first file × that index's assumed market cap
(EUR bn × 1,000): MSCI World 75,000; MSCI EM 8,500; MSCI Europe 14,000; S&P 500 52,000; EURO STOXX 50 4,800;
DAX 1,900. A company found only in `AI_Big_Data` gets its sector's median market cap over the other rows.
`climate_evic_eur_m` = market cap × EV factor; `climate_revenue_eur_m` = EVIC / EV-to-sales. Both from the
sector table.

**Sector table (illustrative, not sourced; builder may tune within reason and must keep it in README.md).**
Ranges are drawn log-uniform for intensity, uniform otherwise.

| Sector | Intensity S1+2 (t/EUR M) | Scope 1 share of S1+2 | Scope 3 × (S1+2) | Green % | EV factor | EV-to-sales |
|---|---|---|---|---|---|---|
| Utilities | 150 to 1,500 | 0.95 | 0.5 to 2 | 10 to 60 | 1.6 | 2.8 |
| Energy | 150 to 600 | 0.85 | 8 to 15 | 0 to 8 | 1.25 | 1.2 |
| Materials | 150 to 1,200 | 0.75 | 1 to 4 | 0 to 15 | 1.2 | 1.6 |
| Industrials | 15 to 120 | 0.50 | 4 to 20 | 3 to 35 | 1.15 | 2.0 |
| Consumer Staples | 15 to 80 | 0.50 | 5 to 15 | 0 to 5 | 1.1 | 2.0 |
| Consumer Discretionary | 8 to 50 | 0.35 | 5 to 20 | 0 to 25 | 1.1 | 1.8 |
| Real Estate | 15 to 80 | 0.30 | 1 to 3 | 0 to 30 | 1.6 | 10 |
| Communication Services | 3 to 25 | 0.15 | 2 to 6 | 0 to 5 | 1.1 | 4 |
| Health Care | 5 to 30 | 0.40 | 4 to 10 | 0 to 5 | 1.1 | 4 |
| Information Technology | 3 to 40 | 0.25 | 4 to 15 | 0 to 15 | 1.05 | 6 |
| Financials | 0.5 to 8 | 0.20 | 3 to 10 | 0 to 5 | 1.0 | 3 |
| Unknown | 10 to 100 | 0.50 | 2 to 8 | 0 to 5 | 1.1 | 2 |

Scope 1 + scope 2 = intensity × revenue; scope 1 = that × the scope 1 share. E score: sector mean
(Utilities, Energy, Materials 4.5; others 6.0) ± 2.5; S and G: 6.0 ± 2.5; clipped to 0 to 10.
`controversy_level`: 0 (60 %), 1 (20 %), 2 (12 %), 3 (5 %), 4 (2 %), 5 (1 %).

**Controversial revenue.** A share is non-zero only where the sector does the activity (draw "present" with
the probability, then the share uniform in the range) or where the override list names the company:

| Activity | Sector: probability, share range when present |
|---|---|
| coal | Utilities 30 %, 0.05 to 0.40; Energy 10 %, 0.05 to 0.60; Materials 10 %, 0.01 to 0.15 |
| oil | Energy 80 %, 0.20 to 0.90; Utilities 5 %, 0.01 to 0.10; Materials 5 %, 0.01 to 0.10 |
| gas | Energy 70 %, 0.10 to 0.60; Utilities 60 %, 0.05 to 0.50 |
| high_intensity_power | Utilities 50 %, 0.10 to 0.70 |
| weapons | Industrials 10 %, 0.05 to 0.60; Information Technology 3 %, 0.01 to 0.10 |
| alcohol | Consumer Staples 8 %, 0.05 to 0.40 |
| gambling | Consumer Discretionary 3 %, 0.20 to 1.00 |
| tobacco | none: overrides only |

`activity_overrides.csv` (`isin,name,activity,share,reason`) sets a share (flags: `1`) for companies whose
business is the activity: tobacco makers, coal miners, defence primes, brewers and distillers, casino and
betting groups, and the companies the owner wants flagged. `isin` and `name` are copied from a holdings file;
`reason` is one line ("cigarette manufacturer"). `controversial_weapons` and `norms_violation` are `true`
only for override rows (anti-goal 1). The builder writes the list; the owner can edit it in the PR.

## Transition grade (PR 1, decision 1(a))

Per peer group (`sector`):

1. **F Disqualified** when `controversial_weapons` or `norms_violation` is `true`, or `coal_revenue_pct` > 0.25.
2. The rest get `transition_score` = 0.5 × (1 − intensity percentile) + 0.3 × green-share percentile +
   0.2 × `esg_e_score` / 10, where a percentile is (rank − 1) / (n − 1) by ascending value among the group's
   non-F rows (0 when n = 1). `lct_score` = 10 × `transition_score`.
3. Sort by `transition_score` descending, ties by ISIN ascending; position r of n:
   r ≤ floor(0.10 n) → **A Leader**; r ≤ floor(0.30 n) → **B Credible**; r ≤ floor(0.60 n) → **C Gaps**;
   r ≤ floor(0.85 n) → **D Emerging**; else **E Not credible**.

`lct_category`: green share ≥ 50 % → `solutions`; else Utilities, Energy, Materials with grade D, E or F →
`asset_stranding`, with A, B or C → `operational_transition`; else Industrials and Consumer Discretionary
with intensity above the group median → `product_transition`; else `neutral`.

## Import fixes and English labels (PR 2, after #419)

`arp portfolio import-constituents <files...> [--notional-eur N] [--fund-isin ISIN]`:

- **Any file name.** `Constituent_<ISIN>.xlsx` behaves as today. Any other name: portfolio id
  `portfolio_<stem>` (lower-cased, non-alphanumerics → `_`), name `<stem with _ as space> (public ETF holdings,
  <sheet date>)`, tag `source:<file name>`. `--fund-isin` (one file only) adds the tag `fund_isin:<ISIN>`.
- **No notional needed.** Default EUR 100,000,000, tag `sizing:assumed-notional-eur-100000000` as today.
- **Holdings load record.** Each import appends `LoadRecord(kind="holdings", source_id=<portfolio id>,
  month=<sheet date YYYY-MM>, status="ok", content_hash=<SHA-256 of the file bytes>, detail="constituent
  import <file name>")`.
- **English labels.** Asset classes `Equities` and `Preferred Stock` → `equity`, `Share Class` → `fund`,
  `Right` → `derivative`. Every English country and sector value in the seven files is a known value (kept as
  given) except `Korea, Republic of` → `South Korea` (the German files' name), and `Grundstoffe` → `Basic Materials`,
  `unknown` → `Unknown`. Importing the seven files reports no
  untranslated value and no other asset class.

## Loader and monthly runs (PR 2)

`arp showcase load [--holdings-dir data/holdings] [--dataset data/simulated/esg_simulated.csv]`, Postgres
store, prints one line per step and exits 1 on any `FAIL`:

1. `import`: the seven files through the import above (AI with `--fund-isin IE00BGV5VN51`).
2. `history`: for each imported portfolio, a snapshot at each month end 2026-05-31 to 2026-10-31 with the
   same securities and weights as the file snapshot, a holdings load record for that month with detail
   `simulated history from <file name>`, and the tag `history:simulated`.
3. `esg`: one ESG load per month 2026-05 to 2026-10 through the ESG intake with provider `simulated`, from the
   dataset's seven climate columns. Observations from provider `simulated` get source `simulated`, a new
   observation source ranked below `estimated_proxy`, so any real value wins. 2026-10 equals the file;
   earlier month m: scope 1, scope 2 and carbon intensity = file value × (1 + g × months before 2026-10), g by
   grade A 0.010, B 0.006, C 0.003, D 0, E −0.002, F −0.004 (leaders were higher before, so they fall).
4. `scores`: the non-climate columns (ESG scores, revenue shares, flags, grade, label, peer group) as
   observations with source `simulated`, period 2026-10, under a built-in schema "Simulated ESG".
5. `runs`: `run_month` for 2026-05 to 2026-10 over the seven imported portfolios with provider `simulated`,
   printing `ok run <month>: <a> alerts, <t> triggers`.

Running it twice changes nothing: the ESG intake answers `unchanged`, snapshots and load records for a month
are not written twice, re-runs add no alerts.

## Grades on screens (PR 3, per decision 2)

Wherever a simulated value or grade shows, the word `Simulated` shows next to it (a badge or a column).
The grade shows as `<letter> <label>`, e.g. `B Credible`, with its peer group.

## PRs

| PR | Contents | Risk | Waits for |
|---|---|---|---|
| 1 | `AI_Big_Data.xlsx` to `main`, `arp showcase simulate`, `data/simulated/` (dataset, overrides, README), grades | normal | nothing |
| 2 | Import fixes, English labels, `simulated` source, `arp showcase load`, monthly runs | high | #419 merged |
| 3 | Grades and the `Simulated` label on the screens the owner picks | normal | PR 2 |

My call against the intake plan: the loader moves from PR 1 to PR 2, because it needs the import fixes;
PR 1 stays independent so `index-starting-universe` can start on the file.

## Left to the builder

- Where `simulated` priority is wired and which screens list observation sources today.
- The override list's contents, within the rules above.
- How the grade breakdown is shaped in `bi_published` (decision 2), within row AC-64.

## Acceptance

`<N>` below is the number of distinct ISINs over rows of the seven files whose `Type of Security` is
`Aktien`, `Equities`, `Depository Receipts` or `Preferred Stock`; tests compute it from the files.
"The loader ran" means `arp showcase load` on an empty Postgres test database with the committed dataset.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The seven files in `data/holdings/` | `arp showcase simulate --out <tmp>` runs | exit 0; `<tmp>` has `<N>` data rows, one per ISIN, sorted by ISIN, with the columns of "Columns" in that order | holdout |
| AC-2 | Same | it runs twice | both outputs are byte-identical to each other and to the committed `data/simulated/esg_simulated.csv` | holdout |
| AC-3 | The committed dataset | every row is read | `data_status` is `simulated` and `company_id` is `isin_<isin>` on every row | holdout |
| AC-4 | `data/simulated/README.md` | line 1 is read | it is `SIMULATED DATA. Not real ESG data. Generated by arp showcase simulate.` | holdout |
| AC-5 | The dataset | every row is read | `sector` is one of the 12 peer groups; no row is blank in any climate, score, share, flag or transition column | holdout |
| AC-6 | A copy of `DAX.xlsx` with one sector cell set to `Raumfahrt` | `arp showcase simulate` reads it | exit 1, stderr names `Raumfahrt` | holdout |
| AC-7 | The dataset | each row's carbon intensity is recomputed | `(scope1 + scope2) / revenue` equals `climate_carbon_intensity` within 0.5 % on every row with revenue > 0 | holdout |
| AC-8 | The dataset | medians of `climate_carbon_intensity` per sector are taken | each of Utilities, Energy, Materials is more than 5 × each of Information Technology, Financials, Health Care | holdout |
| AC-9 | The dataset | `climate_green_revenue_pct` is read | every value is between 0 and 100; the Utilities median is above the Energy median | holdout |
| AC-10 | The dataset and `MSCI_World.xlsx` | the 10 rows with the largest MSCI World weight are read | each has `climate_revenue_eur_m` ≥ 10,000 | holdout |
| AC-11 | The dataset | rows with `tobacco_revenue_pct` > 0 are listed | every one has a `tobacco` row in `activity_overrides.csv` with the same ISIN | holdout |
| AC-12 | The dataset | rows with `coal_revenue_pct`, `oil_revenue_pct` or `gas_revenue_pct` > 0 are listed | every one has sector Energy, Utilities or Materials, or an override row for that activity | holdout |
| AC-13 | The dataset | rows with `weapons_revenue_pct` > 0 are listed | every one has sector Industrials or Information Technology, or a `weapons` override row | holdout |
| AC-14 | The dataset | rows with `controversial_weapons` or `norms_violation` `true` are listed | every one has an override row for that flag | holdout |
| AC-15 | `activity_overrides.csv` | each row is checked against the seven files | its `isin` appears in a file with exactly its `name`; `activity` is one of the eight activities, `controversial_weapons` or `norms_violation`; `reason` is not blank; `share` is between 0 and 1 | holdout |
| AC-16 | `activity_overrides.csv` | it is read | it has at least one `tobacco`, one `coal`, one `weapons` and one `alcohol` row | holdout |
| AC-17 | The dataset | every revenue-share column is read | every value is between 0 and 1 | holdout |
| AC-18 | The dataset | rows are grouped by `name` | rows with the same `name` have equal values in every column except `isin`, `company_id`, `files` | holdout |
| AC-19 | The dataset | `esg_score` is recomputed | it equals the mean of `esg_e_score`, `esg_s_score`, `esg_g_score` within 0.01 | holdout |
| AC-20 | The dataset | `transition_grade` and `transition_grade_label` are read | the pairs are exactly `A`/`Leader`, `B`/`Credible`, `C`/`Gaps`, `D`/`Emerging`, `E`/`Not credible`, `F`/`Disqualified` | holdout |
| AC-21 | The dataset | rows with grade `F` are compared with the rule | a row is `F` exactly when `controversial_weapons` or `norms_violation` is `true` or `coal_revenue_pct` > 0.25 | holdout |
| AC-22 | The dataset | per sector, the n non-F rows are counted by grade | A = floor(0.10 n), B = floor(0.30 n) − floor(0.10 n), C = floor(0.60 n) − floor(0.30 n), D = floor(0.85 n) − floor(0.60 n), E = the rest | holdout |
| AC-23 | The dataset | per sector, non-F rows are sorted by `transition_score` descending, ties by ISIN | grades never go back up along that order (no A after a B, ...) | holdout |
| AC-24 | The dataset | `transition_score` is recomputed from the rule in "Transition grade" | it equals the file's value within 0.0001 on every non-F row | holdout |
| AC-25 | The dataset | `lct_score` and `lct_category` are read | `lct_score` = 10 × `transition_score` within 0.01; `lct_category` follows the rule in "Transition grade" on every row | holdout |
| AC-26 | The dataset | its header is compared with Index Construction's field names | `esg_score`, `ghg_intensity`, `lct_score`, `coal_revenue_pct`, `oil_revenue_pct`, `gas_revenue_pct`, `high_intensity_power_revenue_pct`, `tobacco_revenue_pct`, `green_revenue_pct`, `norms_violation`, `controversial_weapons`, `severe_controversy`, `lct_category` are all present | holdout |
| AC-27 | `AI_Big_Data.xlsx` on `main` after PR 1 | its bytes are compared with the file on `ccr-ab3f2be4-wt1dcl` | identical | holdout |
| AC-30 | An empty store | `arp portfolio import-constituents data/holdings/DAX.xlsx` runs (no `--notional-eur`) | exit 0; portfolio `portfolio_dax` exists, named `DAX (public ETF holdings, 2026-11-02)`, with tags `source:DAX.xlsx` and `sizing:assumed-notional-eur-100000000` | holdout |
| AC-31 | Same | the snapshot of `portfolio_dax` at 2026-11-02 is read | 43 holdings, weights summing to the file's `Weighting` sum × 100 within 0.0001 | holdout |
| AC-32 | Same | `GET /api/portfolio/monthly-run/status?month=2026-11` for `portfolio_dax` | holdings status `ok` | holdout |
| AC-33 | An empty store | `import-constituents AI_Big_Data.xlsx --fund-isin IE00BGV5VN51` runs | portfolio `portfolio_ai_big_data`, named `AI Big Data (public ETF holdings, 2026-11-12)`, tags include `fund_isin:IE00BGV5VN51` and `source:AI_Big_Data.xlsx` | holdout |
| AC-34 | Same | the 100 `Equities` rows' securities are read | every one has asset class `equity` | holdout |
| AC-35 | An empty store | the seven files are imported in one call | the JSON output has `"untranslated": []` and `"other_asset_classes": []` | holdout |
| AC-36 | Same | the companies of `AI_Big_Data.xlsx` rows with country `United States` and `Korea, Republic of` are read | their countries are `United States` and `South Korea` | holdout |
| AC-37 | `--fund-isin` with two files | the import runs | exit 1, message names `--fund-isin` and says one file only; nothing written | holdout |
| AC-38 | Must not change: an empty store, a copy of `DAX.xlsx` named `Constituent_DE000A0H0744.xlsx` | it is imported with `--notional-eur 50000000` | portfolio `portfolio_de000a0h0744` named `Portfolio DE000A0H0744`, tags `source:constituents`, `sizing:assumed-notional-eur-50000000`, `fund_isin:DE000A0H0744`, 43 holdings | holdout |
| AC-40 | The loader ran | portfolios are listed | 7 imported portfolios (`portfolio_dax`, `portfolio_euro_stoxx_50`, `portfolio_msci_em`, `portfolio_msci_europe`, `portfolio_msci_world`, `portfolio_sp500`, `portfolio_ai_big_data`), each tagged `history:simulated` | holdout |
| AC-41 | Same | snapshot dates of `portfolio_dax` are listed | 2026-05-31, 2026-06-30, 2026-07-31, 2026-08-31, 2026-09-30, 2026-10-31, 2026-11-02 | holdout |
| AC-42 | Same | the 2026-07-31 and 2026-11-02 snapshots of `portfolio_msci_world` are compared | same security ids, same `weight_pct` per security | holdout |
| AC-43 | Same | holdings load records of `portfolio_sp500` for 2026-05 to 2026-10 are read | each is `ok` with a detail starting `simulated history from SP500.xlsx` | holdout |
| AC-44 | Same | ESG load records for provider `simulated` are read | one `ok` record for each month 2026-05 to 2026-10 | holdout |
| AC-45 | Same | the resolved `climate_scope1_tco2e` of any dataset company for period 2026-10 is read | value equals the dataset's, source `simulated` | holdout |
| AC-46 | Same, a grade-A company with dataset scope 1 = S | its 2026-05 scope 1 observation is read | value = S × 1.05 within 0.1 % (5 months × 0.010) | holdout |
| AC-47 | Same, a grade-D company | its 2026-05 and 2026-10 scope 1 observations are read | equal | holdout |
| AC-48 | The loader ran, then an `internal_api` scope 1 observation for one company in 2026-10 is added | that company's scope 1 for 2026-10 is resolved | the `internal_api` value, not the simulated one | holdout |
| AC-49 | The loader ran | `transition_grade` observations are read | one per dataset company, value `A` to `F` equal to the dataset, source `simulated` | holdout |
| AC-50 | Same | the loader's output is read | it has six lines `ok run 2026-05: ...` to `ok run 2026-10: ...`; exit 0 | holdout |
| AC-51 | Same | `bi_published` rows with dataset `portfolio_climate_metrics` are counted per month | each month 2026-05 to 2026-10 has at least one row for each of the 7 imported portfolios | holdout |
| AC-52 | Same | `bi_published` rows with dataset `company_profile` for 2026-10 are read | rows with `field_id` `climate_scope1_tco2e` and `transition_grade` exist, every one with source `simulated` | holdout |
| AC-53 | The loader ran once | it runs again | exit 0; portfolio count, snapshot count, load-record count and observation count are the same as after the first run | holdout |
| AC-54 | Must not change: an ESG file uploaded with provider `default` | its observations are read | source `internal_api` | holdout |
| AC-55 | Must not change: a portfolio with no holdings load record for 2026-10 | `arp portfolio monthly-run --month 2026-10 --portfolio <it>` | status `blocked`, a reason naming the portfolio, exit 1 | holdout |
| AC-56 | Must not change: Index Construction with no universe file | `demo_universe()` is called | its output is identical to `main` before this spec | holdout |
| AC-60 | Decision 2 includes the company page; the e2e stack after the loader | a user opens the company with the largest weight in `DAX.xlsx` | the page shows `Transition grade`, the grade as `<letter> <label>`, its peer group, and the word `Simulated` | evaluator |
| AC-61 | Same | the user looks at any climate value or revenue share on that page | the word `Simulated` shows next to it | evaluator |
| AC-62 | Same | a user searches for that company's name | it is found and opens the page of AC-60 | evaluator |
| AC-63 | Decision 2 includes the dashboards; the loader ran | `bi_published` `company_profile` rows for 2026-10 are read | every dataset company has a `transition_grade` row | holdout |
| AC-64 | Same | `bi_published` `portfolio_climate_metrics` rows for 2026-10 of `portfolio_dax` are read | they include the weight share of each grade A to F, the six summing to 100 % within 0.1 | holdout |
| AC-65 | Decision 2 includes Index Construction | `index-starting-universe` builds candidates from the dataset | the field catalogue lists `transition_grade` as a category (row owned by that spec) | evaluator |

Rows owned by later PRs: PR 1 AC-1 to AC-27; PR 2 AC-30 to AC-56; PR 3 AC-60 to AC-65 for the places picked.
