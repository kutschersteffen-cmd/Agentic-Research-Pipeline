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
   before any build. Rows AC-22 to AC-26 and AC-52 hold for (a).
2. **Where grades show** (any of three; rows retire with the places not picked):
   - **Transition Intelligence, recommended** (AC-73 to AC-75): a native "Simulated ESG" card in Risk
     Monitoring → Company Profiles (beside the existing `ProfileActionStrip`, so it works without Superset),
     plus a per-portfolio grade breakdown in `bi_published` and grade text in the `bi.company_profile` view
     for later dashboards (charts stay with PR #424).
   - **Index Construction as a field, recommended** (no row here): the dataset carries `transition_grade`
     with the type in "Fields for Index Construction"; `index-starting-universe` shows it as a category.
   - **Company page, not recommended** (AC-70 to AC-72): `#/companies/<ref>` shows authoritative facts from
     the company registry, a different id space; PR 3 would have to register about 2,540 companies there and
     mix simulated values into a page of real facts.

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
import's file-name rule. This spec adds an import path without that rule, so the six files keep their own
names and get ids `portfolio_dax`, ... with no made-up ISIN anywhere. Only `AI_Big_Data.xlsx` carries a fund
ISIN (IE00BGV5VN51).

## Current state (read on `main` d9b65c2 and f0b7ae0)

- `data/holdings/` holds `DAX.xlsx`, `EURO_STOXX_50.xlsx`, `MSCI_EM.xlsx`, `MSCI_Europe.xlsx`, `MSCI_World.xlsx`,
  `SP500.xlsx` (sheet date 2026-11-02, German labels). `AI_Big_Data.xlsx` (sheet date 2026-11-12, English
  labels, SHA-256 `f7df310918dd8243af970b33e3dcd757f255b0b16edc19b226f74d08ad2eb5bd`) is on branch
  `ccr-ab3f2be4-wt1dcl` only; **PR 1 brings it to `main` unchanged**.
- Rows whose `Type of Security` is `Aktien`, `Equities`, `Depository Receipts` or `Preferred Stock` carry
  2,538 distinct ISINs (2,530 name + country keys). 14 of them have `Weighting` `N/A` in every file (12 in
  MSCI_EM, 2 in MSCI_World). Sectors: MSCI World, EM, Europe and S&P 500 use German GICS labels; DAX and
  EURO STOXX 50 use an older scheme that files BMW, Mercedes, VW, Continental, Ferrari and AB InBev under
  `Basiskonsumgüter` (Consumer Staples); the AI file uses English labels.
- `import_constituent_files` (`backend/arp/portfolio/constituent_import.py`, CLI `arp portfolio
  import-constituents`) accepts only `Constituent_<12 characters>.xlsx` (pinned by
  `tests/test_constituent_import.py::test_bad_file_name`), requires a notional, writes one snapshot at the
  sheet date and no holdings load record, skips rows without a numeric weight before registering their
  company, and knows only German labels: `Equities`, `Preferred Stock`, `Share Class`, `Right` become asset
  class `other`; English countries and sectors, `Grundstoffe`, `unknown` and 20 German countries of the
  MSCI EM file are reported untranslated. Cash and fund lines are imported as positions (asset class `cash`,
  `fund`); that stays. Companies are stored as `isin_<ISIN>`; `CompanyRef.sector` is whatever the last
  imported file said.
- `arp portfolio monthly-run` and `POST /api/portfolio/monthly-run` (`backend/arp/portfolio/monthly_run.py`)
  are blocked unless every portfolio has an `ok` holdings load record for the month and the ESG provider an
  `ok` ESG load; the API and the UI's "Run now" use provider `default`. A run resolves observations as of
  max(month end, `at` of the latest ESG load), picking the latest `observed_at` on or before that date, and
  publishes `portfolio_climate_metrics`, `alerts`, `triggers` and `company_profile` into `bi_published`
  (Postgres only). The `bi.company_profile` view keeps numeric values only, so text values read as NULL.
- Observation sources are `internal_api`, `extracted`, `catalogue`, `estimated_proxy`
  (`DataPointObservationSource`, ranked in `datapoint_mapping._SOURCE_PRIORITY`). The ESG upload writes
  `internal_api` and a provider row per company.
- Risk Monitoring → Company Profiles embeds Superset; only `ProfileActionStrip` is native. Ask the Portfolio
  (`qa_agent.py`) uses observations without saying their source.
- Index Construction (`backend/arp/index/`) screens on the names in "Fields for Index Construction"; its
  universe today is the hash-seeded `demo_universe()`.
- PR #419 (`showcase-portfolio-fixes`) changes `HoldingsIntake` and the ESG upload (defects 6 to 8), and lists
  portfolios without a holder record on Holdings Intake.

## Goals

1. One simulated row per company in the seven files, with the seven climate columns, further ESG scores,
   revenue shares in eight controversial activities, two exclusion flags and a transition grade.
2. Values are plausible for sector and size: emissions scale with revenue, every company's intensity sits in
   its sector's range, controversial revenue appears only where the business does it.
3. Every simulated value says it is simulated wherever it shows: file, observation source, published rows,
   screens.
4. The seven public files import through the app's own import under their own names, without a notional,
   with English labels and the missing German countries translated.
5. Each imported portfolio runs monthly for 2026-06 to 2026-11, from the CLI and from "Run now", and the six
   runs fill `bi_published` with month-specific values.
6. One A-F grade per company, relative to its sector peers, with a fixed share of each grade per sector.
7. Same input, same output: regenerating the dataset gives the same bytes.

## Non-goals

- Real ESG data, or any claim that a value is real.
- Portfolios other than the seven files and the app's seeded demo portfolios.
- A Decision Studio credibility rework, unless the owner picks open decision 1(b).
- Index Construction candidates built from the dataset (`index-starting-universe`, which depends on PR 1).
- Superset dashboards and charts (PR #424); this spec fills only the rows they read.
- Removing cash and fund lines from imported portfolios; the project import (`arp/projects/service.py`),
  which keeps its notional.
- Holder records for imported portfolios (PR #419 lists portfolios without one).

## Anti-goals

- A real company shown as a norms violator or controversial-weapons maker by chance: those two flags come
  only from the override list, never from a random draw.
- A simulated value that could be read as real on any screen or in `bi_published`.
- Absurd numbers in front of senior management: a software company with tobacco revenue, a bank with
  steel-mill emissions, a mega-cap with a revenue of EUR 2 million.
- Two lines of one company (same name and country) with different values or grades.

## Constraints

- Simulated history is invented and says so: load records carry `simulated` in their detail, portfolios get
  the tag `history:simulated`.
- PR 2 touches the same holdings and ESG code as PR #419 and is built after #419 merges.
- Every draw is seeded from SHA-256 (the way `arp/index/mock_data.py` draws), never unseeded `random`.
- No identifier typed from memory: overrides copy ISIN and name from the holdings files.
- Paths given to the new commands resolve against the repo root, so they work from `backend/` too.
- `mock_esg_source._SECTOR_BASELINES` stays as is (the seeded demo dataset depends on it).

## Approaches

1. **Committed dataset file from a deterministic generator, loaded by one command (chosen, my call).**
   `arp showcase simulate` writes `data/simulated/esg_simulated.csv`; it is committed so the owner can open it
   in Excel and reviewers can read the numbers; `arp showcase load` imports the holdings and writes the
   values. Costs one generator, one loader, a file of about 1 MB.
2. Generate at load time, nothing committed (as `demo_universe()` does). Smaller repo, but nobody can review
   the numbers before the demo, and `index-starting-universe` would have to call the generator.
3. Extend `arp portfolio seed-demo`. Rejected: the seeded portfolios are invented companies; these are real
   holdings, and mixing the two hides which is which.

## Simulated dataset (PR 1)

`arp showcase simulate [--holdings-dir data/holdings] [--overrides data/simulated/activity_overrides.csv]
[--out data/simulated/esg_simulated.csv]`. `data/simulated/README.md` starts with the line
`SIMULATED DATA. Not real ESG data. Generated by arp showcase simulate.` and copies the tables below.

**Rows.** One per distinct ISIN over rows whose `Type of Security` is `Aktien`, `Equities`,
`Depository Receipts` or `Preferred Stock`, sorted by ISIN. Rows with weight `N/A` are kept.

**Key.** A company is a key: `Name` (upper-cased, stripped) + `Country` of its line. Lines with the same key
(share classes, dual listings) are one company: `EQT` in the US and `EQT` in Sweden are two keys. Draws come
from SHA-256 of the key. Every ISIN of a key gets identical values in every column except `isin`,
`company_id`, `files`. Name, country and sector are the key's, taken from its first line in the file order
`MSCI_World`, `SP500`, `MSCI_Europe`, `MSCI_EM`, `AI_Big_Data`, `EURO_STOXX_50`, `DAX`.

**Columns**, in this order. Decimals: tCO2e and EUR M values 2; `climate_carbon_intensity`, `ghg_intensity`,
revenue shares, `green_revenue_pct` and `transition_score` 4; `climate_green_revenue_pct`, the E, S, G
scores, `esg_score`, `esg_trend` and `lct_score` 2.

| Group | Columns |
|---|---|
| Identity | `isin`, `company_id` (`isin_<ISIN>`), `name`, `country` (English), `sector` (peer group), `files` (file stems, `;`-joined), `data_status` (always `simulated`) |
| Climate (the ESG upload's seven) | `climate_scope1_tco2e`, `climate_scope2_tco2e`, `climate_scope3_tco2e`, `climate_carbon_intensity` (tCO2e per EUR M revenue, scope 1+2), `climate_evic_eur_m`, `climate_revenue_eur_m`, `climate_green_revenue_pct` (percent 0 to 100) |
| ESG scores (0 to 10) | `esg_e_score`, `esg_s_score`, `esg_g_score`, `esg_score` (mean of the three), `esg_trend` (0.80 to 1.20), `controversy_level` (integer 0 to 5) |
| Revenue shares (fractions 0 to 1, Index Construction's convention) | `coal_revenue_pct`, `oil_revenue_pct`, `gas_revenue_pct`, `high_intensity_power_revenue_pct`, `tobacco_revenue_pct`, `weapons_revenue_pct`, `alcohol_revenue_pct`, `gambling_revenue_pct` |
| Flags (`true`/`false`) | `controversial_weapons`, `norms_violation`, `severe_controversy` (`controversy_level` = 5) |
| Transition | `ghg_intensity` (= `climate_carbon_intensity`), `green_revenue_pct` (= green percent / 100), `transition_score` (0 to 1), `lct_score` (0 to 10), `lct_category`, `transition_grade` (`A` to `F`), `transition_grade_label` |

**Peer group (`sector`).** The key's GICS label from the first of `MSCI_World`, `SP500`, `MSCI_Europe`,
`MSCI_EM` that holds one of its ISINs with a label other than `unbekannt`; else its `AI_Big_Data` label;
else Unknown (the DAX and EURO STOXX 50 labels are never used). Labels map to: Energy (`Energie`), Materials
(`Material`), Industrials (`Industrieunternehmen`, `Industrials`), Utilities (`Versorgungsunternehmen`),
Consumer Staples (`Basiskonsumgüter`), Consumer Discretionary (`Nicht-Basiskonsumgüter`, `Consumer
Discretionary`), Health Care (`Gesundheitswesen`), Financials (`Finanzen`, `Financials`), Information
Technology (`Informationstechnologie`, `Technology`), Communication Services (`Kommunikationsdienste`,
`Telecommunications`), Real Estate (`Immobilien`), Unknown (`unbekannt`, `unknown`, blank). A label in those
five files outside this list fails the run, naming it.

**Size.** Weight = the sum of the key's `Weighting` values in the first of `MSCI_World`, `MSCI_EM`,
`MSCI_Europe`, `SP500`, `EURO_STOXX_50`, `DAX` holding the key with a numeric weight, as a fraction (each file
sums to about 1.0). Market cap (EUR M) = weight × that index's assumed market cap: MSCI World 75,000,000;
MSCI EM 8,500,000; MSCI Europe 14,000,000; S&P 500 52,000,000; EURO STOXX 50 4,800,000; DAX 1,900,000.
A key with no numeric weight there (AI-only, or `N/A`) gets the median market cap of its peer group's other
keys. `climate_evic_eur_m` = market cap × EV factor; `climate_revenue_eur_m` = EVIC / EV-to-sales.

**Sector table** (illustrative, not sourced; README.md copies it unchanged). Intensity drawn log-uniform in
the range, the others uniform.

| Sector | Intensity S1+2 (t/EUR M) | Scope 1 share of S1+2 | Scope 3 × (S1+2) | Green % | EV factor | EV-to-sales |
|---|---|---|---|---|---|---|
| Utilities | 150 to 1500 | 0.95 | 0.5 to 2 | 10 to 60 | 1.6 | 2.8 |
| Energy | 150 to 600 | 0.85 | 8 to 15 | 0 to 8 | 1.25 | 1.2 |
| Materials | 150 to 1200 | 0.75 | 1 to 4 | 0 to 15 | 1.2 | 1.6 |
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

**Controversial revenue (owner decision 1).** A share is non-zero only where the peer group does the
activity (draw "present" with the probability, then the share uniform in the range) or an override names
the key:

| Activity | Sector: probability, share range when present | Override range |
|---|---|---|
| coal | Utilities 30 %, 0.05 to 0.40; Energy 10 %, 0.05 to 0.60; Materials 10 %, 0.01 to 0.15 | 0.10 to 1.00 |
| oil | Energy 80 %, 0.20 to 0.90; Utilities 5 %, 0.01 to 0.10; Materials 5 %, 0.01 to 0.10 | 0.30 to 0.90 |
| gas | Energy 70 %, 0.10 to 0.60; Utilities 60 %, 0.05 to 0.50 | 0.10 to 0.50 |
| high_intensity_power | Utilities 50 %, 0.10 to 0.70 | 0.10 to 1.00 |
| weapons | Industrials 10 %, 0.05 to 0.60; Information Technology 3 %, 0.01 to 0.10 | 0.10 to 1.00 |
| alcohol | Consumer Staples 8 %, 0.05 to 0.40 | 0.30 to 1.00 |
| gambling | Consumer Discretionary 3 %, 0.20 to 1.00 | 0.30 to 1.00 |
| tobacco | none | 0.50 to 1.00 |

`data/simulated/activity_overrides.csv` (`isin,name,activity,share,reason`) names companies whose business is
the activity. `isin` and `name` are copied from a holdings file; `reason` is one line ("cigarette
manufacturer"); flags `controversial_weapons` and `norms_violation` take `share` `1`. An override applies to
every ISIN of its key. It holds at least these ISINs, all checked present in the files (the builder adds
brewers, distillers, casino and betting groups and may add more):

- tobacco: US7181721090, US02209S1033, GB0002875804, GB0004544929, JP3726800000, KR7033780008, INE154A01025
- coal: INE522F01014, CNE1000002R0, CNE100000767, CNE1000004Q8, CNE000000WV6, INE733E01010, DE0007037129,
  ZAE000006896, JE00B4T3BW64
- weapons: DE0007030009, US5398301094, US6668071029, US3695501086, GB0002634946, US75513E1010, IT0003856405,
  FR0000121329, SE0021921269, DE000HAG0005, NO0013536151, US5024311095, US4464131063, IL0010811243,
  INE263A01024, INE066F01020, NL0000235190, FR0000073272, US0970231058, US4385162056
- oil and gas (one `oil` and one `gas` row each): GB00BP6MXD84, FR0000120271, US30233Q1085, US1667641005,
  GB0007980591, IT0003132476, NO0010096985, US20825C1045, AU0000224040, SA14TG012N13, CNE1000003W8,
  CNE1000007Q1, INE002A01018, RU0007661625

## Transition grade (PR 1, open decision 1(a), owner decision 2)

Per peer group, over its n keys, with values as written in the file:

1. `transition_score` = 0.5 × (1 − intensity percentile) + 0.3 × green-share percentile + 0.2 × `esg_e_score`
   / 10. A percentile is (rank − 1) / (n − 1), rank by ascending value, ties take the lowest rank, 0 when
   n = 1. `lct_score` = 10 × `transition_score`.
2. Sort keys by `transition_score` descending, ties by the key's smallest ISIN ascending; position r of n:
   r ≤ floor(0.10 n) → **A Leader**; ≤ floor(0.30 n) → **B Credible**; ≤ floor(0.60 n) → **C Gaps**;
   ≤ floor(0.85 n) → **D Emerging**; ≤ floor(0.95 n) → **E Not credible**; else **F Disqualified**.
   Every ISIN gets its key's grade.

`lct_category`: green percent ≥ 50 → `solutions`; else Utilities, Energy, Materials with grade D, E or F →
`asset_stranding`, with A, B or C → `operational_transition`; else Industrials and Consumer Discretionary
with `climate_carbon_intensity` above the median over the peer group's keys → `product_transition`; else
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
| Every column | `data/simulated/esg_simulated.csv`, `data_status` = `simulated` | File; README line 1 `SIMULATED DATA. ...` |
| Seven climate columns | Observations, source `simulated`, one set per month 2026-06 to 2026-11 | `bi_published` rows with `source` `simulated`; Ask the Portfolio answers and monitoring alerts built on them show `Simulated`; the TI card if picked |
| The 25 `simulated_esg` fields (below) | Observations, source `simulated`, period 2026-11 | `bi_published` `company_profile` rows with `source` `simulated`; the TI card if picked |
| Grade breakdown per portfolio | `bi_published` `portfolio_climate_metrics` keys, if TI picked | Superset later (PR #424) |
| Holdings history | Snapshots 2026-06-30 to 2026-10-31, tag `history:simulated`, load-record detail `simulated history from <file>` | Portfolio tags |

The screen label is the word `Simulated`. Schema `simulated_esg` ("Simulated ESG") has exactly these 25 field
ids, units as in "Columns": `esg_e_score`, `esg_s_score`, `esg_g_score`, `esg_score`, `esg_trend`,
`controversy_level`, the eight revenue shares, `controversial_weapons`, `norms_violation`,
`severe_controversy`, `ghg_intensity`, `green_revenue_pct`, `transition_score`, `lct_score`, `lct_category`,
`transition_grade`, `transition_grade_label`, `peer_group` (the `sector` column). It is served at
`GET /api/climate/simulated-schema`, next to `GET /api/climate/schema`.

## Import fixes and English labels (PR 2, after #419)

- **`import_constituent_files` stays as it is** (still rejects other names; `test_bad_file_name` unchanged).
- **New `import_holdings_file(store, path, portfolio_id, name, notional_eur=100_000_000, fund_isin=None,
  project_id=None)`** in the same module, sharing the row parsing. `arp portfolio import-constituents
  <files...> [--notional-eur N] [--fund-isin ISIN] [--project P]` sends `Constituent_<ISIN>.xlsx` files the
  old way and any other file here with id `portfolio_<stem>` (lower-cased, non-alphanumerics → `_`), with
  `--project P` `P-portfolio-<stem>` and tag `project:P`; name `<stem with _ as space> (public ETF
  holdings, <sheet date>)`; tags `source:<file name>`, `sizing:assumed-notional-eur-100000000` (or the given
  notional), and with `--fund-isin` (one file only) `fund_isin:<ISIN>`. `--notional-eur` becomes optional
  for both paths, default 100,000,000.
- **Holdings load record** (both paths): `LoadRecord(kind="holdings", source_id=<portfolio id>, month=<sheet
  date YYYY-MM>, status="ok", content_hash=<SHA-256 of the file bytes>, detail="constituent import <file
  name>")`, unless the latest record for that portfolio and month has the same `content_hash`.
- **Rows without a numeric weight** (both paths) still register their company and security; they get no
  holding and are listed under `skipped_no_weight` as today.
- **English labels.** Asset classes `Equities` and `Preferred Stock` → `equity`, `Share Class` → `fund`,
  `Right` → `derivative`. English values in the files are identity entries (countries Australia, Canada,
  China, Germany, Hong Kong, Ireland, Israel, Japan, Sweden, Taiwan, United Kingdom, United States; sectors
  Consumer Discretionary, Financials, Industrials, Technology, Telecommunications); `Korea, Republic of` →
  `South Korea`, `Grundstoffe` → `Basic Materials`, `unknown` → `Unknown`.
- **German countries missing today:** Ägypten → Egypt, Griechenland → Greece, Indien → India, Indonesien →
  Indonesia, Kasachstan → Kazakhstan, Kolumbien → Colombia, Kuwait → Kuwait, Malaysia → Malaysia, Mexiko →
  Mexico, Peru → Peru, Philippinen → Philippines, Polen → Poland, Qatar → Qatar, Rumänien → Romania, Russland →
  Russia, Saudi Arabien → Saudi Arabia, Südafrika → South Africa, Tschechische Republik → Czech Republic,
  Türkei → Turkey, Ungarn → Hungary.

## Loader and monthly runs (PR 2)

`arp showcase load [--holdings-dir data/holdings] [--dataset data/simulated/esg_simulated.csv]`, Postgres
store, prints one line per step `ok|FAIL <step>: <reason>`, exits 1 on any `FAIL`:

1. `import`: the seven files through `import_holdings_file`, `AI_Big_Data` with fund ISIN IE00BGV5VN51.
2. `history` (owner decision 3): for each imported portfolio, a snapshot at each month end 2026-06-30 to
   2026-10-31 with the same securities as the file snapshot and weights `w × (1 + u)`, `u` uniform in
   −0.05 to +0.05 seeded by SHA-256 of portfolio id + ISIN + month, then scaled so the month's weights sum to
   the file snapshot's sum; market values follow the weights. A holdings load record per month, detail
   `simulated history from <file name>` (not written twice), and the tag `history:simulated`.
3. `esg`: for each month 2026-06 to 2026-11, the seven climate values per dataset company appended directly
   as observations with source `simulated` (new `DataPointObservationSource`, ranked below
   `estimated_proxy`, so any real value wins) and `observed_at` = that month end (2026-11: 2026-11-02), then
   `LoadRecord(kind="esg", source_id="simulated", month, status="ok", at=<same date>, detail="simulated ESG
   from esg_simulated.csv")`. No ESG upload, no provider rows. 2026-11 equals the file; month m before it:
   scope 1, scope 2 and carbon intensity = file value × (1 + g × k), k = months before 2026-11 (June = 5),
   g by grade A 0.010, B 0.008, C 0.006, D 0.004, E 0.002, F 0 (emissions fall over time).
4. `scores`: the 25 `simulated_esg` fields as observations with source `simulated`, period 2026-11,
   `observed_at` 2026-11-02.
5. `runs`: `run_month` for 2026-06 to 2026-11 over the seven imported portfolios with provider `simulated`,
   printing `ok run <month>: <a> alerts, <t> triggers`.

Steps 3 and 4 write no observation that already exists with the same company, field, source, period and
value, so a second run changes nothing.

**Provider when none is given.** `GET /api/portfolio/monthly-run/status` and `POST /api/portfolio/monthly-run`
without `esg_provider` use `default` when that month has a `default` ESG load, else `simulated`; the CLI's
`--esg-provider` does the same when left out. So "Run now" works on the simulated months.

## Grades on screens (PR 3, per open decision 2)

Wherever a simulated value or grade shows, the word `Simulated` shows next to it. The grade shows as
`<letter> <label>`, e.g. `B Credible`, with its peer group.

## PRs

| PR | Contents | Risk | Waits for |
|---|---|---|---|
| 1 | `AI_Big_Data.xlsx` to `main`, `arp showcase simulate`, `data/simulated/` (dataset, overrides, README), grades | normal | nothing |
| 2 | `import_holdings_file`, English labels, `simulated` source and schema, provider fallback, `arp showcase load`, monthly runs, `Simulated` on Ask the Portfolio and alerts | high | #419 merged |
| 3 | Grades and labels where the owner picks | normal | PR 2 |

My call against the intake plan: the loader moves from PR 1 to PR 2, because it needs the import fixes;
PR 1 stays independent so `index-starting-universe` can start on the file.

## Left to the builder

- Where `Simulated` is rendered on Ask the Portfolio and alerts, within AC-58 and AC-59.
- The override list beyond the ISINs above, within the rules.

## Acceptance

`<N>` is the number of distinct ISINs over equity rows (`Aktien`, `Equities`, `Depository Receipts`,
`Preferred Stock`) of the seven files, tests compute it (2,538 today); a key is name + country as defined in
"Key". "The e2e stack" is `backend/scripts/e2e_stack.sh up` (seed-demo data only). "The loader ran" means
`arp showcase load` on the e2e stack with the committed dataset.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The seven files in `data/holdings/` | `arp showcase simulate --out <tmp>` runs from `backend/` | exit 0; `<tmp>` has `<N>` data rows, one per ISIN, sorted by ISIN, with the columns of "Columns" in that order | holdout |
| AC-2 | Same | it runs twice | both outputs are byte-identical to each other and to the committed `data/simulated/esg_simulated.csv` | holdout |
| AC-3 | The committed dataset | every row is read | `data_status` is `simulated` and `company_id` is `isin_<isin>` on every row | holdout |
| AC-4 | `data/simulated/README.md` | line 1 is read | it is `SIMULATED DATA. Not real ESG data. Generated by arp showcase simulate.` | holdout |
| AC-5 | The dataset | every row is read | `sector` is one of the 12 peer groups; no cell is blank | holdout |
| AC-6 | A copy of the seven files where the `Industry Classification` of the first equity row of `MSCI_World.xlsx` is `Raumfahrt` | `arp showcase simulate --holdings-dir <copy>` runs | exit 1, stderr names `Raumfahrt` | holdout |
| AC-7 | The dataset | carbon intensity is recomputed on rows with scope 1 + scope 2 ≥ 100 | `(scope1 + scope2) / revenue` equals `climate_carbon_intensity` within 0.5 % | holdout |
| AC-8 | The dataset | every row's `climate_carbon_intensity` is checked against the spec's sector table | it lies within its sector's intensity range | holdout |
| AC-9 | The dataset | medians of `climate_carbon_intensity` per sector are taken | each of Utilities, Energy, Materials is more than 5 × each of Information Technology, Financials, Health Care | holdout |
| AC-10 | The dataset | `climate_green_revenue_pct` is read | every value is between 0 and 100 | holdout |
| AC-11 | The dataset and `MSCI_World.xlsx` | the key with the largest summed MSCI World `Weighting` w (fraction) is read | `climate_evic_eur_m` = w × 75,000,000 × its sector's EV factor, within 1 % | holdout |
| AC-12 | The dataset | rows with `tobacco_revenue_pct` > 0 are listed | every one's key has a `tobacco` override | holdout |
| AC-13 | The dataset | rows with `coal_revenue_pct`, `oil_revenue_pct` or `gas_revenue_pct` > 0 are listed | every one has sector Energy, Utilities or Materials, or its key has an override for that activity | holdout |
| AC-14 | The dataset | rows with `weapons_revenue_pct` > 0 are listed | every one has sector Industrials or Information Technology, or a `weapons` override for its key | holdout |
| AC-15 | The dataset | rows with `controversial_weapons` or `norms_violation` `true` are listed | every one's key has an override for that flag | holdout |
| AC-16 | `activity_overrides.csv` and the seven files | each override row is checked | its `isin` appears in a file with exactly its `name`; `activity` is one of the eight activities, `controversial_weapons` or `norms_violation`; `reason` is not blank; `share` lies in its activity's override range (flags: 1) | holdout |
| AC-17 | `activity_overrides.csv` | it is read | every ISIN listed in "Controversial revenue" has a row with that activity (oil and gas: one `oil` and one `gas` row) | holdout |
| AC-18 | The dataset | rows whose key has an override for an activity are read | the share equals the override's `share` | holdout |
| AC-19 | The dataset | every revenue-share column is read | every value is between 0 and 1 | holdout |
| AC-20 | The dataset | rows are grouped by key | rows of one key have equal values in every column except `isin`, `company_id`, `files` | holdout |
| AC-21 | The dataset | `esg_score` is recomputed | it equals the mean of `esg_e_score`, `esg_s_score`, `esg_g_score` within 0.01 | holdout |
| AC-22 | The dataset | `transition_grade` and `transition_grade_label` are read | the pairs are exactly `A`/`Leader`, `B`/`Credible`, `C`/`Gaps`, `D`/`Emerging`, `E`/`Not credible`, `F`/`Disqualified` | holdout |
| AC-23 | The dataset | per sector, the n distinct keys are counted by grade | A = floor(0.10 n), B = floor(0.30 n) − floor(0.10 n), C = floor(0.60 n) − floor(0.30 n), D = floor(0.85 n) − floor(0.60 n), E = floor(0.95 n) − floor(0.85 n), F = n − floor(0.95 n) | holdout |
| AC-24 | The dataset | per sector, keys are sorted by `transition_score` descending, ties by smallest ISIN | grades never go back up along that order | holdout |
| AC-25 | The dataset | `transition_score` is recomputed per key from the file's values by the rule in "Transition grade" | it equals the file's value within 0.0001 | holdout |
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
| AC-38 | Same | the companies of the 14 equity ISINs with `Weighting` `N/A` are looked up | all 14 exist as `isin_<ISIN>`; none is a holding | holdout |
| AC-39 | The e2e stack | `import-constituents` with two files and `--fund-isin X` | exit 1, the message names `--fund-isin` and says one file only; no portfolio written | holdout |
| AC-40 | The e2e stack | `import-constituents data/holdings/DAX.xlsx --project p1` | portfolio `p1-portfolio-dax` with tag `project:p1` | holdout |
| AC-41 | Must not change: the e2e stack, a copy of `DAX.xlsx` named `Constituent_DE000A0H0744.xlsx` | it is imported with `--notional-eur 50000000` | portfolio `portfolio_de000a0h0744` named `Portfolio DE000A0H0744`, tags `source:constituents`, `sizing:assumed-notional-eur-50000000`, `fund_isin:DE000A0H0744`; 43 holdings | holdout |
| AC-42 | Must not change: a file named `holdings.xlsx` | `import_constituent_files` is called on it | it raises `ValueError` naming `Constituent_` | unit |
| AC-43 | The loader ran | portfolios tagged `history:simulated` are listed | exactly `portfolio_dax`, `portfolio_euro_stoxx_50`, `portfolio_msci_em`, `portfolio_msci_europe`, `portfolio_msci_world`, `portfolio_sp500`, `portfolio_ai_big_data` | holdout |
| AC-44 | Same | snapshot dates of `portfolio_dax` are listed | 2026-06-30, 2026-07-31, 2026-08-31, 2026-09-30, 2026-10-31, 2026-11-02 | holdout |
| AC-45 | Same | the 2026-07-31 and 2026-11-02 snapshots of `portfolio_msci_world` are compared | same security ids; every ratio `w_0731 / w_1102` between 0.90 and 1.11; the two weight sums equal within 0.0001 | holdout |
| AC-46 | Same | the 2026-07-31 and 2026-08-31 snapshots of `portfolio_msci_world` are compared | at least one weight differs | holdout |
| AC-47 | Same | holdings load records of `portfolio_sp500` for 2026-06 to 2026-10 are read | one per month, `ok`, detail starting `simulated history from SP500.xlsx` | holdout |
| AC-48 | Same | ESG load records for provider `simulated` are read | one `ok` record per month 2026-06 to 2026-11 | holdout |
| AC-49 | Same | `bi_published` `company_profile` rows for 2026-11 with `field_id` `climate_scope1_tco2e` are read | each dataset company's value equals the dataset's, source `simulated` | holdout |
| AC-50 | Same, a grade-A company with dataset scope 1 = S | its `company_profile` `climate_scope1_tco2e` row for 2026-06 is read | value = S × 1.05 within 0.1 % | holdout |
| AC-51 | Same, a grade-F company with dataset scope 1 = S | its rows for 2026-06 and 2026-11 are read | both equal S | holdout |
| AC-52 | Same | `bi_published` `company_profile` rows for 2026-11 with `field_id` `transition_grade` are read | one per dataset company, value equal to the dataset's grade, source `simulated` | holdout |
| AC-53 | Same | `bi_published` `portfolio_climate_metrics` rows are counted per month | each month 2026-06 to 2026-11 has at least one row for each of the 7 portfolios of AC-43 | holdout |
| AC-54 | Same | `GET /api/climate/simulated-schema` is called | schema id `simulated_esg` with exactly the 25 field ids of "Where each field is stored and shown" | holdout |
| AC-55 | The loader ran once | it runs again | exit 0; counts of portfolios, snapshots, load records and observations equal those after the first run | holdout |
| AC-56 | The loader ran, then an `internal_api` scope 1 observation for one dataset company with `observed_at` 2026-11-02 | `arp portfolio monthly-run --month 2026-11 --portfolio portfolio_dax` runs and that company's `company_profile` scope 1 row for 2026-11 is read | the `internal_api` value | holdout |
| AC-57 | The loader ran | `POST /api/portfolio/monthly-run` with `{"month": "2026-10", "portfolio_ids": ["portfolio_dax"]}` (no provider) | status `ran` | holdout |
| AC-58 | The loader ran | a user asks Ask the Portfolio for the carbon intensity of `DAX (public ETF holdings, 2026-11-02)` | the answer shows the word `Simulated` | evaluator |
| AC-59 | The loader ran and a threshold rule on carbon intensity raised an alert for an imported portfolio | a user opens Risk Monitoring, Monitoring | that alert shows the word `Simulated` | evaluator |
| AC-60 | Must not change: an ESG file uploaded with provider `default` for 2026-10 | the run status for 2026-10 is read without a provider, and the file's observations are read | provider `default` is used; observations have source `internal_api` | holdout |
| AC-61 | Must not change: a portfolio with no holdings load record for 2026-10 | `arp portfolio monthly-run --month 2026-10 --portfolio <it>` | status `blocked`, a reason naming the portfolio, exit 1 | holdout |
| AC-70 | Open decision 2 includes the company page; the loader ran | a user opens the company with the largest weight in `DAX.xlsx` | the page shows `Transition grade`, the grade as `<letter> <label>`, its peer group and the word `Simulated` | evaluator |
| AC-71 | Same | the user looks at any climate value or revenue share on that page | the word `Simulated` shows next to it | evaluator |
| AC-72 | Same | a user searches for that company's name | it is found and opens the page of AC-70 | evaluator |
| AC-73 | Open decision 2 includes Transition Intelligence; the loader ran | a user opens Risk Monitoring → Company Profiles and picks the company with the largest weight in `DAX.xlsx` | a card titled `Simulated ESG` shows the grade as `<letter> <label>`, the peer group, scope 1, carbon intensity and the eight revenue shares | evaluator |
| AC-74 | Same | `bi_published` `portfolio_climate_metrics` rows for 2026-11 of `portfolio_dax` are read | keys `grade_a_weight_pct` to `grade_f_weight_pct`, each a share of the weight of graded holdings, summing to 100 within 0.1 percentage points | holdout |
| AC-75 | Same | the `bi.company_profile` view is queried for `transition_grade` in 2026-11 | a text column holds the grade letter for every dataset company | holdout |

Rows by PR: PR 1 AC-1 to AC-28; PR 2 AC-30 to AC-61; PR 3 AC-70 to AC-75 for the places picked.
