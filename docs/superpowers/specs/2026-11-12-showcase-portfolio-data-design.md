# Showcase portfolio data: simulated ESG for the public holdings, imported into Transition Intelligence

Slug: `showcase-portfolio-data`. Risk: high (portfolio import and weights, load records, a new observation source).

## Decided by the owner (12 Nov, buttons in the dispatcher session; confirm at approval)

1. **Controversial revenue: sector plus known names.** Companies whose business is the activity are named
   in an override list and get a high share from a plausible range; everyone else gets zero, or a small share
   where the sector makes it plausible.
2. **Grade F (Disqualified) is the bottom 5 % of each sector** on the simulated transition score. No exclusion
   rule behind it. Split per sector: A 10 %, B 20 %, C 30 %, D 25 %, E 10 %, F 5 % (my split of the proposed
   A to E so the six sum to 100 %).
3. **History: six months, June to November 2026.** Earlier months reuse the same holdings with small seeded
   weight changes; emissions drift slightly downward over time.
4. "Fix English labels in the app".

## Open for the owner at approval

1. **Where the A-F grade comes from.** Recommended: **(a) a column of the simulated dataset**, computed by
   the rule in "Transition grade". Alternative: **(b) Decision Studio**, a six-tier framework run over the
   simulated indicators. The existing preset in `backend/arp/decision/credibility.py` has five tiers
   (A Credible, B Credible gaps, C Partial, D Not credible, E Opaque) and a five-question test that needs
   indicator columns this dataset does not have; (b) means reworking that preset and revising this spec
   before any build. Rows AC-20 to AC-25 hold for (a).
2. **Where grades show** (any of three; rows retire with the places not picked):
   - **Company page** (AC-70 to AC-72): needs the imported companies to open on `#/companies/<ref>`, which
     today knows only registry companies, so PR 3 registers them (about 2,540).
   - **Transition Intelligence dashboards** (AC-73): a per-portfolio grade breakdown in `bi_published`.
     The grade per company reaches `bi_published` anyway (AC-52). Dashboards are Superset embeds and stay out
     of this spec (PR #424 holds the chart command); they are not visible where no Superset runs.
   - **Index Construction as a field** (no row here): the dataset carries `transition_grade` with the type
     in "Fields for Index Construction"; `index-starting-universe` shows it as a category.

## Intent

The owner cannot get ESG data (12 Nov): "we can not get esg data. therefore we need to mock them. so the ask
is that you simulate various kinds of esg data and revenue shares to controversial activities such as
tobacco, oil, gas etc. think about reasonable estimate for these exposures. use the sectors as reference. we
also need to include the holdings of the portfolios into transition intelligence workspace." And: "simulate a
transition assessment with a scale applicable within each sector A (Leader), B (Credible), C(Gaps),
D(Emerging), E(not credible), F(Disqualified)".

This spec builds three things:

1. A **simulated dataset**, one row per company in the seven public holdings files, with sector-based
   estimates, labelled simulated wherever a value shows.
2. The seven **public portfolios imported into Transition Intelligence** so the monthly run works, run for
   June to November 2026 so `bi_published` (what the dashboards read) has six months of history.
3. One **A-F transition grade** per company against its sector peers.

It takes over the portfolio part of the unapproved draft `2026-11-12-showcase-demo-pack-design.md` (branch
`ccr-ab3f2be4-wt1dcl`): its loader step `portfolios`, row AC-40 and plan decisions 5, 8 and 9. The draft's
ten companies, documents, Argus and voting runs and run sheet stay in that draft. The demo pack, when
approved, loads the portfolio data by calling `arp showcase load` (one command, below).

The owner chose placeholder ids (`DAX000000000`, ...) for the six index files on 12 Nov, as a way round the
import's file-name rule. This spec removes that rule, so the six files keep their own names and get ids
`portfolio_dax`, ... with no made-up ISIN anywhere. Only `AI_Big_Data.xlsx` carries a fund ISIN (IE00BGV5VN51).

## Current state (read on `main` d9b65c2)

- `data/holdings/` holds `DAX.xlsx`, `EURO_STOXX_50.xlsx`, `MSCI_EM.xlsx`, `MSCI_Europe.xlsx`, `MSCI_World.xlsx`,
  `SP500.xlsx` (sheet date 2026-11-02, German labels). `AI_Big_Data.xlsx` (sheet date 2026-11-12, English
  labels, SHA-256 `f7df310918dd8243af970b33e3dcd757f255b0b16edc19b226f74d08ad2eb5bd`) is on branch
  `ccr-ab3f2be4-wt1dcl` only; **PR 1 brings it to `main` unchanged**.
- Rows whose `Type of Security` is `Aktien`, `Equities`, `Depository Receipts` or `Preferred Stock` carry
  about 2,540 distinct ISINs. Sectors come in two German schemes (GICS-like `Finanzen`, ...; and a legacy one
  that, among others, puts BMW, Mercedes and VW under `Basiskonsumgüter`) and English in the AI file.
- `arp portfolio import-constituents` (`backend/arp/portfolio/constituent_import.py`) accepts only
  `Constituent_<12 characters>.xlsx`, requires `--notional-eur`, writes one snapshot at the sheet date, writes
  no holdings load record, and knows only German labels: `Equities`, `Preferred Stock`, `Share Class`, `Right`
  become asset class `other`; English countries and sectors, `Grundstoffe`, `unknown` and 20 German
  countries of the MSCI EM file are reported untranslated. Cash and fund lines are imported as positions
  (asset class `cash`, `fund`); that stays. Companies are stored as `isin_<ISIN>`.
- `arp portfolio monthly-run` (`backend/arp/portfolio/monthly_run.py`) is blocked unless every portfolio has
  an `ok` holdings load record for the month and the ESG provider an `ok` ESG load. It resolves observations
  as of max(month end, date of the latest ESG load), picking the latest `observed_at` on or before that date
  (`datapoint_mapping.resolve_field_value`), and publishes `portfolio_climate_metrics`, `alerts`, `triggers`
  and `company_profile` into `bi_published` (Postgres only). `company_profile` carries every observation field
  with its `source`.
- The ESG intake (`backend/arp/portfolio/climate/esg_intake.py`) reads columns through
  `mappings/<provider>.json` (only `default.json` exists), takes `company_id` plus seven climate fields and
  writes observations with source `internal_api`. Sources rank `internal_api`, `extracted`, `catalogue`,
  `estimated_proxy` (`datapoint_mapping._SOURCE_PRIORITY`).
- Index Construction (`backend/arp/index/`) screens on metric, flag and category names listed in
  "Fields for Index Construction"; its universe today is the hash-seeded `demo_universe()`.
- PR #419 (`showcase-portfolio-fixes`) changes `HoldingsIntake` and the ESG upload (defects 6 to 8).

## Goals

1. One simulated row per company in the seven files, with the seven climate columns, further ESG scores,
   revenue shares in eight controversial activities, two exclusion flags and a transition grade.
2. Values are plausible for sector and size: emissions scale with revenue, every company's intensity sits in
   its sector's range, controversial revenue appears only where the business does it.
3. Every simulated value says it is simulated wherever it shows: file, observation source, published rows,
   screens.
4. The seven public files import through the app's own import under their own names, without a notional,
   with English labels and the missing German countries translated.
5. Each imported portfolio runs monthly for 2026-06 to 2026-11, and the six runs fill `bi_published` with
   month-specific values.
6. One A-F grade per company, relative to its sector peers, with a fixed share of each grade per sector.
7. Same input, same output: regenerating the dataset gives the same bytes.

## Non-goals

- Real ESG data, or any claim that a value is real.
- Portfolios other than the seven files and the app's seeded demo portfolios.
- A Decision Studio credibility rework, unless the owner picks open decision 1(b).
- Index Construction candidates built from the dataset (`index-starting-universe`, which depends on PR 1).
- Superset dashboards and charts (PR #424); this spec fills only the rows they read.
- Removing cash and fund lines from imported portfolios.

## Anti-goals

- A real company shown as a norms violator or controversial-weapons maker by chance: those two flags come
  only from the override list, never from a random draw.
- A simulated value that could be read as real on any screen or in `bi_published`.
- Absurd numbers in front of senior management: a software company with tobacco revenue, a bank with
  steel-mill emissions, a mega-cap with a revenue of EUR 2 million.
- Two lines of one company (same name and country) with different values.

## Constraints

- Simulated history is invented and says so: load records carry `simulated history` in their detail,
  portfolios get the tag `history:simulated`.
- PR 2 changes the same ESG intake and holdings code as PR #419 and is built after #419 merges.
- Every draw is seeded from SHA-256 (the way `arp/index/mock_data.py` draws), never unseeded `random`.
- No identifier typed from memory: the override list copies ISIN and name from the holdings files.
- Paths given to the new commands resolve against the repo root, so they work from `backend/` too.

## Approaches

1. **Committed dataset file from a deterministic generator, loaded through the app's own intake (chosen,
   my call).** `arp showcase simulate` writes `data/simulated/esg_simulated.csv`; it is committed so the
   owner can open it in Excel and reviewers can read the numbers; `arp showcase load` feeds it through the
   import and the ESG intake. Costs one generator, one loader, a file of about 1 MB.
2. Generate at load time, nothing committed (as `demo_universe()` does). Smaller repo, but nobody can review
   the numbers before the demo, and `index-starting-universe` would have to call the generator.
3. Extend `arp portfolio seed-demo`. Rejected: the seeded portfolios are invented companies; these are real
   holdings, and mixing the two hides which is which.

## Simulated dataset (PR 1)

`arp showcase simulate [--holdings-dir data/holdings] [--overrides data/simulated/activity_overrides.csv]
[--out data/simulated/esg_simulated.csv]`. `data/simulated/README.md` starts with the line
`SIMULATED DATA. Not real ESG data. Generated by arp showcase simulate.` and holds the sector tables below.

**Rows.** One per distinct ISIN over rows whose `Type of Security` is `Aktien`, `Equities`,
`Depository Receipts` or `Preferred Stock`, sorted by ISIN. Name, country and sector come from the first
file holding that ISIN in this order: `MSCI_World`, `MSCI_EM`, `MSCI_Europe`, `SP500`, `EURO_STOXX_50`, `DAX`,
`AI_Big_Data` (so the MSCI and S&P scheme wins over the legacy one).

**Key and seed.** The key is name (upper-cased, stripped) + country. Draws come from SHA-256 of the key.
Lines with the same key (share classes, dual listings) get the summed weight of the key in the first file
and identical values in every column except `isin`, `company_id`, `files`. `EQT` in the US and `EQT` in
Sweden are two keys.

**Columns**, in this order. Decimals: tCO2e and EUR M values 2, intensity 4, percent 2, fractions 4,
scores 2.

| Group | Columns |
|---|---|
| Identity | `isin`, `company_id` (`isin_<ISIN>`), `name`, `country` (English), `sector` (peer group), `files` (file stems, `;`-joined), `data_status` (always `simulated`) |
| Climate (the ESG intake's seven) | `climate_scope1_tco2e`, `climate_scope2_tco2e`, `climate_scope3_tco2e`, `climate_carbon_intensity` (tCO2e per EUR M revenue, scope 1+2), `climate_evic_eur_m`, `climate_revenue_eur_m`, `climate_green_revenue_pct` (percent 0 to 100) |
| ESG scores (0 to 10) | `esg_e_score`, `esg_s_score`, `esg_g_score`, `esg_score` (mean of the three), `esg_trend` (0.80 to 1.20), `controversy_level` (integer 0 to 5) |
| Revenue shares (fractions 0 to 1, Index Construction's convention) | `coal_revenue_pct`, `oil_revenue_pct`, `gas_revenue_pct`, `high_intensity_power_revenue_pct`, `tobacco_revenue_pct`, `weapons_revenue_pct`, `alcohol_revenue_pct`, `gambling_revenue_pct` |
| Flags (`true`/`false`) | `controversial_weapons`, `norms_violation`, `severe_controversy` (`controversy_level` = 5) |
| Transition | `ghg_intensity` (= `climate_carbon_intensity`), `green_revenue_pct` (= green percent / 100), `transition_score` (0 to 1), `lct_score` (0 to 10), `lct_category`, `transition_grade` (`A` to `F`), `transition_grade_label` |

**Peer group (`sector`).** Every `Industry Classification` value on every equity row of every file maps to
one of: Energy, Materials, Industrials, Utilities, Consumer Staples, Consumer Discretionary, Health Care,
Financials, Information Technology, Communication Services, Real Estate, Unknown; an unmapped value fails
the run, naming it, whether or not the row is the one used. German GICS names map to their English name;
legacy names: `Finanzdienstleister` → Financials, `Technologie`/`Technology` → Information Technology,
`Telekommunikation`/`Telecommunications` → Communication Services, `Verbrauchsgüter` → Consumer
Discretionary, `Grundstoffe` → Materials, `unbekannt`/`unknown`/blank → Unknown.

**Size.** Market cap (EUR M) = the key's weight in its first file × that index's assumed market cap (EUR bn
× 1,000): MSCI World 75,000; MSCI EM 8,500; MSCI Europe 14,000; S&P 500 52,000; EURO STOXX 50 4,800;
DAX 1,900. A key found only in `AI_Big_Data` gets its sector's median market cap over the other keys.
`climate_evic_eur_m` = market cap × EV factor; `climate_revenue_eur_m` = EVIC / EV-to-sales.

**Sector table** (illustrative, not sourced; the builder may tune it, and README.md holds the version used).
Intensity drawn log-uniform in the range, the others uniform.

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

**Controversial revenue (owner decision 1).** A share is non-zero only where the sector does the activity
(draw "present" with the probability, then the share uniform in the range) or the override list names the
company:

| Activity | Sector: probability, share range when present |
|---|---|
| coal | Utilities 30 %, 0.05 to 0.40; Energy 10 %, 0.05 to 0.60; Materials 10 %, 0.01 to 0.15 |
| oil | Energy 80 %, 0.20 to 0.90; Utilities 5 %, 0.01 to 0.10; Materials 5 %, 0.01 to 0.10 |
| gas | Energy 70 %, 0.10 to 0.60; Utilities 60 %, 0.05 to 0.50 |
| high_intensity_power | Utilities 50 %, 0.10 to 0.70 |
| weapons | Industrials 10 %, 0.05 to 0.60; Information Technology 3 %, 0.01 to 0.10 |
| alcohol | Consumer Staples 8 %, 0.05 to 0.40 |
| gambling | Consumer Discretionary 3 %, 0.20 to 1.00 |
| tobacco | overrides only |

`data/simulated/activity_overrides.csv` (`isin,name,activity,share,reason`) sets the share for companies whose
business is the activity (tobacco makers, coal miners, oil and gas majors, defence primes, brewers and
distillers, casino and betting groups); `share` is from the plausible range (tobacco 0.50 to 1.00, coal,
weapons, alcohol, gambling 0.30 to 1.00, oil and gas 0.30 to 0.90). Flags `controversial_weapons` and
`norms_violation` take `share` `1`. `isin` and `name` are copied from a holdings file; `reason` is one line
("cigarette manufacturer"). An override applies to every line of its key. The builder writes the list; the
owner can edit it in the PR.

## Transition grade (PR 1, open decision 1(a), owner decision 2)

Per peer group (`sector`), over all its rows, with values as written in the file:

1. `transition_score` = 0.5 × (1 − intensity percentile) + 0.3 × green-share percentile + 0.2 × `esg_e_score`
   / 10. A percentile is (rank − 1) / (n − 1), rank by ascending value, ties take the lowest rank, 0 when
   n = 1. `lct_score` = 10 × `transition_score`.
2. Sort by `transition_score` descending, ties by ISIN ascending; position r of n:
   r ≤ floor(0.10 n) → **A Leader**; ≤ floor(0.30 n) → **B Credible**; ≤ floor(0.60 n) → **C Gaps**;
   ≤ floor(0.85 n) → **D Emerging**; ≤ floor(0.95 n) → **E Not credible**; else **F Disqualified**.

`lct_category`: green percent ≥ 50 → `solutions`; else Utilities, Energy, Materials with grade D, E or F →
`asset_stranding`, with A, B or C → `operational_transition`; else Industrials and Consumer Discretionary
with `climate_carbon_intensity` above the median of all rows of that sector → `product_transition`; else
`neutral`.

## Fields for Index Construction (what `index-starting-universe` reads)

| Column | Index Construction kind | Type |
|---|---|---|
| `esg_score`, `esg_trend`, `ghg_intensity`, `lct_score`, `coal_revenue_pct`, `oil_revenue_pct`, `gas_revenue_pct`, `high_intensity_power_revenue_pct`, `tobacco_revenue_pct`, `green_revenue_pct` | metric (existing names) | float |
| `weapons_revenue_pct`, `alcohol_revenue_pct`, `gambling_revenue_pct`, `esg_e_score`, `esg_s_score`, `esg_g_score`, `controversy_level`, `transition_score` | metric (new names) | float |
| `norms_violation`, `controversial_weapons`, `severe_controversy` | flag (existing names) | bool |
| `lct_category` | category (existing name) | str |
| `transition_grade` | category (new name) | str, `A` to `F` |
| `sector`, `country` | the candidate's own fields | str |

## Where each field is stored and shown

| Field | Stored as | Shown, with label |
|---|---|---|
| Every column | `data/simulated/esg_simulated.csv`, column `data_status` = `simulated` | File and README line 1 `SIMULATED DATA. ...` |
| Seven climate columns | Observations, source `simulated`, one per month 2026-06 to 2026-11 | `bi_published` rows `source` = `simulated`; Ask the Portfolio and monitoring alerts built on them show `Simulated`; company page if picked |
| ESG scores, shares, flags, grade, label, peer group | Observations, source `simulated`, period 2026-11, schema `simulated_esg` | `bi_published` `company_profile` rows `source` = `simulated`; company page if picked |
| Grade breakdown per portfolio | `bi_published` `portfolio_climate_metrics`, if dashboards picked | Superset (PR #424) |
| Holdings history | Snapshots 2026-06-30 to 2026-10-31, tag `history:simulated`, load-record detail `simulated history from <file>` | Portfolio tags |

The screen label is the word `Simulated`.

## Import fixes and English labels (PR 2, after #419)

`arp portfolio import-constituents <files...> [--notional-eur N] [--fund-isin ISIN] [--project P]`:

- **Any file name.** `Constituent_<ISIN>.xlsx` behaves as today. Any other name: portfolio id
  `portfolio_<stem>` (lower-cased, non-alphanumerics → `_`), with `--project P` `P-portfolio-<stem>` and tag
  `project:P`; name `<stem with _ as space> (public ETF holdings, <sheet date>)`; tag `source:<file name>`.
  `--fund-isin` (one file only) adds the tag `fund_isin:<ISIN>`.
- **No notional needed.** Default EUR 100,000,000, tag `sizing:assumed-notional-eur-100000000` as today.
- **Holdings load record.** An import appends `LoadRecord(kind="holdings", source_id=<portfolio id>,
  month=<sheet date YYYY-MM>, status="ok", content_hash=<SHA-256 of the file bytes>, detail="constituent
  import <file name>")`, unless the latest record for that portfolio and month has the same `content_hash`.
- **English labels.** Asset classes `Equities` and `Preferred Stock` → `equity`, `Share Class` → `fund`,
  `Right` → `derivative`. English values in the files are added as identity entries (countries Australia,
  Canada, China, Germany, Hong Kong, Ireland, Israel, Japan, Sweden, Taiwan, United Kingdom, United States;
  sectors Consumer Discretionary, Financials, Industrials, Technology, Telecommunications), `Korea, Republic
  of` → `South Korea`, `Grundstoffe` → `Basic Materials`, `unknown` → `Unknown`.
- **German countries missing today:** Ägypten → Egypt, Griechenland → Greece, Indien → India, Indonesien →
  Indonesia, Kasachstan → Kazakhstan, Kolumbien → Colombia, Kuwait → Kuwait, Malaysia → Malaysia, Mexiko →
  Mexico, Peru → Peru, Philippinen → Philippines, Polen → Poland, Qatar → Qatar, Rumänien → Romania, Russland →
  Russia, Saudi Arabien → Saudi Arabia, Südafrika → South Africa, Tschechische Republik → Czech Republic,
  Türkei → Turkey, Ungarn → Hungary.

## Loader and monthly runs (PR 2)

`arp showcase load [--holdings-dir data/holdings] [--dataset data/simulated/esg_simulated.csv]`, Postgres
store, prints one line per step `ok|FAIL <step>: <reason>`, exits 1 on any `FAIL`:

1. `import`: the seven files in the order `AI_Big_Data`, `DAX`, `EURO_STOXX_50`, `SP500`, `MSCI_Europe`,
   `MSCI_EM`, `MSCI_World` (so a company's stored sector ends as the dataset's), `AI_Big_Data` with
   `--fund-isin IE00BGV5VN51`.
2. `history` (owner decision 3): for each imported portfolio, a snapshot at each month end 2026-06-30 to
   2026-10-31 with the same securities as the file snapshot and weights `w × (1 + u)`, `u` uniform in
   −0.05 to +0.05 seeded by SHA-256 of portfolio id + ISIN + month, then scaled so the month's weights sum to
   the file snapshot's sum; market values follow the weights. A holdings load record per month with detail
   `simulated history from <file name>` (once per month, as above), and the tag `history:simulated`.
3. `esg`: one ESG load per month 2026-06 to 2026-11 through the ESG intake with provider `simulated`
   (new `arp/portfolio/climate/mappings/simulated.json`, mapping `company_id` and the seven climate columns
   by name; other dataset columns are ignored). The intake writes source `simulated` for provider
   `simulated` (else `internal_api` as today). `simulated` ranks below `estimated_proxy`, so any real value
   wins. Each month's observations have `observed_at` and the load record `at` = that month end (2026-11:
   2026-11-02), so a run of that month resolves that month's values. 2026-11 equals the file; month m
   before it: scope 1, scope 2 and carbon intensity = file value × (1 + g × k), k = months before 2026-11
   (June = 5), g by grade A 0.010, B 0.008, C 0.006, D 0.004, E 0.002, F 0 (emissions fall over time).
4. `scores`: the non-climate columns as observations with source `simulated`, period 2026-11, observed_at
   2026-11-02, under a built-in schema `simulated_esg` ("Simulated ESG", field ids = column names, units as in
   "Columns", served at `GET /api/climate/simulated-schema` next to `GET /api/climate/schema`); no observation is written when an identical `simulated` one
   exists for that company, field and period.
5. `runs`: `run_month` for 2026-06 to 2026-11 over the seven imported portfolios with provider `simulated`,
   printing `ok run <month>: <a> alerts, <t> triggers`.

## Grades on screens (PR 3, per open decision 2)

Wherever a simulated value or grade shows, the word `Simulated` shows next to it. The grade shows as
`<letter> <label>`, e.g. `B Credible`, with its peer group.

## PRs

| PR | Contents | Risk | Waits for |
|---|---|---|---|
| 1 | `AI_Big_Data.xlsx` to `main`, `arp showcase simulate`, `data/simulated/` (dataset, overrides, README), grades | normal | nothing |
| 2 | Import fixes, English labels, `simulated` source and schema, `arp showcase load`, monthly runs, `Simulated` on Ask the Portfolio and alerts | high | #419 merged |
| 3 | Grades and labels on the screens the owner picks | normal | PR 2 |

My call against the intake plan: the loader moves from PR 1 to PR 2, because it needs the import fixes;
PR 1 stays independent so `index-starting-universe` can start on the file.

## Left to the builder

- How `simulated` is ranked in `_SOURCE_PRIORITY` and where `Simulated` is rendered on Ask the Portfolio and
  alerts, within AC-58 and AC-59.
- The override list's contents, within the rules above.

## Acceptance

`<N>` is the number of distinct ISINs over equity rows (`Aktien`, `Equities`, `Depository Receipts`,
`Preferred Stock`) of the seven files; tests compute it. "The e2e stack" is `backend/scripts/e2e_stack.sh up`
(seed-demo data only). "The loader ran" means `arp showcase load` on the e2e stack with the committed dataset.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The seven files in `data/holdings/` | `arp showcase simulate --out <tmp>` runs from `backend/` | exit 0; `<tmp>` has `<N>` data rows, one per ISIN, sorted by ISIN, with the columns of "Columns" in that order | holdout |
| AC-2 | Same | it runs twice | both outputs are byte-identical to each other and to the committed `data/simulated/esg_simulated.csv` | holdout |
| AC-3 | The committed dataset | every row is read | `data_status` is `simulated` and `company_id` is `isin_<isin>` on every row | holdout |
| AC-4 | `data/simulated/README.md` | line 1 is read | it is `SIMULATED DATA. Not real ESG data. Generated by arp showcase simulate.` | holdout |
| AC-5 | The dataset | every row is read | `sector` is one of the 12 peer groups; no cell is blank | holdout |
| AC-6 | A copy of the seven files where the `Industry Classification` of the first equity row of `DAX.xlsx` is `Raumfahrt` | `arp showcase simulate --holdings-dir <copy>` runs | exit 1, stderr names `Raumfahrt` | holdout |
| AC-7 | The dataset | carbon intensity is recomputed on rows with scope 1 + scope 2 ≥ 100 | `(scope1 + scope2) / revenue` equals `climate_carbon_intensity` within 0.5 % | holdout |
| AC-8 | The dataset and the sector table in README.md | every row's `climate_carbon_intensity` is checked | it lies within its sector's intensity range | holdout |
| AC-9 | The dataset | medians of `climate_carbon_intensity` per sector are taken | each of Utilities, Energy, Materials is more than 5 × each of Information Technology, Financials, Health Care | holdout |
| AC-10 | The dataset | `climate_green_revenue_pct` is read | every value is between 0 and 100 | holdout |
| AC-11 | The dataset and `MSCI_World.xlsx` | the 10 ISINs with the largest MSCI World weight are read | each has `climate_revenue_eur_m` ≥ 10,000 | holdout |
| AC-12 | The dataset | rows with `tobacco_revenue_pct` > 0 are listed | every one's key has a `tobacco` override row | holdout |
| AC-13 | The dataset | rows with `coal_revenue_pct`, `oil_revenue_pct` or `gas_revenue_pct` > 0 are listed | every one has sector Energy, Utilities or Materials, or its key has an override row for that activity | holdout |
| AC-14 | The dataset | rows with `weapons_revenue_pct` > 0 are listed | every one has sector Industrials or Information Technology, or a `weapons` override for its key | holdout |
| AC-15 | The dataset | rows with `controversial_weapons` or `norms_violation` `true` are listed | every one's key has an override row for that flag | holdout |
| AC-16 | `activity_overrides.csv` and the seven files | each override row is checked | its `isin` appears in a file with exactly its `name`; `activity` is one of the eight activities, `controversial_weapons` or `norms_violation`; `reason` is not blank; `share` lies in the range for its activity in "Controversial revenue" (flags: 1) | holdout |
| AC-17 | `activity_overrides.csv` | it is read | it has at least one row each for `tobacco`, `coal`, `oil`, `weapons` and `alcohol` | holdout |
| AC-18 | The dataset | rows with an override for an activity are read | the share equals the override's `share` | holdout |
| AC-19 | The dataset | every revenue-share column is read | every value is between 0 and 1 | holdout |
| AC-20 | The dataset | rows are grouped by `name` + `country` | rows of one group have equal values in every column except `isin`, `company_id`, `files` | holdout |
| AC-21 | The dataset | `esg_score` is recomputed | it equals the mean of `esg_e_score`, `esg_s_score`, `esg_g_score` within 0.01 | holdout |
| AC-22 | The dataset | `transition_grade` and `transition_grade_label` are read | the pairs are exactly `A`/`Leader`, `B`/`Credible`, `C`/`Gaps`, `D`/`Emerging`, `E`/`Not credible`, `F`/`Disqualified` | holdout |
| AC-23 | The dataset | per sector, the n rows are counted by grade | A = floor(0.10 n), B = floor(0.30 n) − floor(0.10 n), C = floor(0.60 n) − floor(0.30 n), D = floor(0.85 n) − floor(0.60 n), E = floor(0.95 n) − floor(0.85 n), F = n − floor(0.95 n) | holdout |
| AC-24 | The dataset | per sector, rows are sorted by `transition_score` descending, ties by ISIN | grades never go back up along that order | holdout |
| AC-25 | The dataset | `transition_score` is recomputed from the file's values by the rule in "Transition grade" | it equals the file's value within 0.0001 on every row | holdout |
| AC-26 | The dataset | `lct_score` and `lct_category` are read | `lct_score` = 10 × `transition_score` within 0.01; `lct_category` follows the rule in "Transition grade" on every row | holdout |
| AC-27 | The dataset | its header is compared with "Fields for Index Construction" | every column named there is present | holdout |
| AC-28 | `main` after PR 1 | SHA-256 of `data/holdings/AI_Big_Data.xlsx` is taken | `f7df310918dd8243af970b33e3dcd757f255b0b16edc19b226f74d08ad2eb5bd` | holdout |
| AC-30 | The e2e stack | `arp portfolio import-constituents data/holdings/DAX.xlsx` runs (no `--notional-eur`) | exit 0; portfolio `portfolio_dax` exists, named `DAX (public ETF holdings, 2026-11-02)`, tags `source:DAX.xlsx` and `sizing:assumed-notional-eur-100000000` | holdout |
| AC-31 | Same | the 2026-11-02 snapshot of `portfolio_dax` is read | 43 holdings; weights sum to the file's `Weighting` sum × 100 within 0.0001 | holdout |
| AC-32 | Same | `GET /api/portfolio/monthly-run/status?month=2026-11&portfolio_ids=portfolio_dax` | `holdings.portfolio_dax` is `ok` | holdout |
| AC-33 | Same | the same import runs again | holdings load records for `portfolio_dax` and 2026-11 number 1 | holdout |
| AC-34 | The e2e stack | `import-constituents AI_Big_Data.xlsx --fund-isin IE00BGV5VN51` | portfolio `portfolio_ai_big_data`, named `AI Big Data (public ETF holdings, 2026-11-12)`, tags include `fund_isin:IE00BGV5VN51` and `source:AI_Big_Data.xlsx` | holdout |
| AC-35 | Same | the securities of the 100 `Equities` rows are read | every one has asset class `equity` | holdout |
| AC-36 | The e2e stack | the seven files are imported in one call | the JSON output has `"untranslated": []` and `"other_asset_classes": []` | holdout |
| AC-37 | Same | companies of `AI_Big_Data.xlsx` rows with country `United States` and `Korea, Republic of`, and of an `MSCI_EM.xlsx` row with `Südafrika`, are read | countries `United States`, `South Korea`, `South Africa` | holdout |
| AC-38 | The e2e stack | `import-constituents` with two files and `--fund-isin X` | exit 1, the message names `--fund-isin` and says one file only; no portfolio written | holdout |
| AC-39 | The e2e stack | `import-constituents data/holdings/DAX.xlsx --project p1` | portfolio `p1-portfolio-dax` with tag `project:p1` | holdout |
| AC-40 | Must not change: the e2e stack, a copy of `DAX.xlsx` named `Constituent_DE000A0H0744.xlsx` | it is imported with `--notional-eur 50000000` | portfolio `portfolio_de000a0h0744` named `Portfolio DE000A0H0744`, tags `source:constituents`, `sizing:assumed-notional-eur-50000000`, `fund_isin:DE000A0H0744`; 43 holdings | holdout |
| AC-41 | The loader ran | portfolios tagged `history:simulated` are listed | exactly `portfolio_dax`, `portfolio_euro_stoxx_50`, `portfolio_msci_em`, `portfolio_msci_europe`, `portfolio_msci_world`, `portfolio_sp500`, `portfolio_ai_big_data` | holdout |
| AC-42 | Same | snapshot dates of `portfolio_dax` are listed | 2026-06-30, 2026-07-31, 2026-08-31, 2026-09-30, 2026-10-31, 2026-11-02 | holdout |
| AC-43 | Same | the 2026-07-31 and 2026-11-02 snapshots of `portfolio_msci_world` are compared | same security ids; every 2026-07-31 weight within ±5.5 % (relative) of its 2026-11-02 weight; the two weight sums equal within 0.0001 | holdout |
| AC-44 | Same | the 2026-07-31 and 2026-08-31 snapshots of `portfolio_msci_world` are compared | at least one weight differs | holdout |
| AC-45 | Same | holdings load records of `portfolio_sp500` for 2026-06 to 2026-10 are read | one per month, `ok`, detail starting `simulated history from SP500.xlsx` | holdout |
| AC-46 | Same | ESG load records for provider `simulated` are read | one `ok` record per month 2026-06 to 2026-11 | holdout |
| AC-47 | Same | `bi_published` `company_profile` rows for 2026-11 with `field_id` `climate_scope1_tco2e` are read | each dataset company's value equals the dataset's, source `simulated` | holdout |
| AC-48 | Same, a grade-A company with dataset scope 1 = S | its `company_profile` `climate_scope1_tco2e` row for 2026-06 is read | value = S × 1.05 within 0.1 % | holdout |
| AC-49 | Same, a grade-F company with dataset scope 1 = S | its rows for 2026-06 and 2026-11 are read | both equal S | holdout |
| AC-50 | The loader ran, then an `internal_api` scope 1 observation for one company with `observed_at` 2026-11-02 | `arp portfolio monthly-run --month 2026-11 --esg-provider simulated --portfolio portfolio_dax` and its `company_profile` scope 1 row is read | the `internal_api` value | holdout |
| AC-51 | The loader ran | the loader's output is read | six lines `ok run 2026-06: ...` to `ok run 2026-11: ...`; exit 0 | holdout |
| AC-52 | Same | `bi_published` `company_profile` rows for 2026-11 with `field_id` `transition_grade` are read | one per dataset company, value equal to the dataset's grade, source `simulated` | holdout |
| AC-53 | Same | `bi_published` `portfolio_climate_metrics` rows are counted per month | each month 2026-06 to 2026-11 has at least one row for each of the 7 portfolios of AC-41 | holdout |
| AC-54 | Same | `GET /api/climate/simulated-schema` is called | schema id `simulated_esg`, one field per non-identity, non-climate column | holdout |
| AC-55 | The loader ran once | it runs again | exit 0; counts of portfolios, snapshots, load records and observations equal those after the first run | holdout |
| AC-56 | Must not change: an ESG file uploaded with provider `default` | its observations are read | source `internal_api` | holdout |
| AC-57 | Must not change: a portfolio with no holdings load record for 2026-10 | `arp portfolio monthly-run --month 2026-10 --portfolio <it>` | status `blocked`, a reason naming the portfolio, exit 1 | holdout |
| AC-58 | The loader ran | a user asks Ask the Portfolio for the carbon intensity of `DAX (public ETF holdings, 2026-11-02)` | the answer shows the word `Simulated` | evaluator |
| AC-59 | The loader ran and a threshold rule on carbon intensity raised an alert for an imported portfolio | a user opens Risk Monitoring, Monitoring | that alert shows the word `Simulated` | evaluator |
| AC-60 | Must not change: no universe file | `arp index` builds on `demo_universe()` | the candidates equal those on `main` d9b65c2 | unit |
| AC-70 | Open decision 2 includes the company page; the loader ran | a user opens the company with the largest weight in `DAX.xlsx` | the page shows `Transition grade`, the grade as `<letter> <label>`, its peer group and the word `Simulated` | evaluator |
| AC-71 | Same | the user looks at any climate value or revenue share on that page | the word `Simulated` shows next to it | evaluator |
| AC-72 | Same | a user searches for that company's name | it is found and opens the page of AC-70 | evaluator |
| AC-73 | Open decision 2 includes the dashboards; the loader ran | `bi_published` `portfolio_climate_metrics` rows for 2026-11 of `portfolio_dax` are read | keys `grade_a_weight_pct` to `grade_f_weight_pct`, each a share of the weight of graded holdings, summing to 100 within 0.1 percentage points | holdout |

Rows by PR: PR 1 AC-1 to AC-28; PR 2 AC-30 to AC-60; PR 3 AC-70 to AC-73 for the places picked.
