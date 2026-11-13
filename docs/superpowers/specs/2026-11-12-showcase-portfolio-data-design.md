# Showcase portfolio data: simulated ESG for the public holdings, imported into Transition Intelligence

Slug: `showcase-portfolio-data`. Risk: high (portfolio import and weights, load records, a new observation source).

Status: **approved by the owner on 12 Nov 2026** (buttons in the spec session), with the picks below.
Amendment A (13 Nov 2026, written-off positions and revenue shares): **approved by the owner on 13 Nov 2026** (buttons in the amendment session).

## Decided by the owner (12 Nov)

1. **Controversial revenue: sector plus known names.** Companies whose business is the activity are named
   in an override list and get a high share from a plausible range; everyone else gets zero, or a small share
   where the sector makes it plausible.
2. **Grade F (Disqualified) is the bottom 5 % of each sector** on the simulated transition score. No exclusion
   rule behind it. Split per sector: A 10 %, B 20 %, C 30 %, D 25 %, E 10 %, F 5 %.
3. **History: six months, June to November 2026.** Earlier months reuse the same holdings with small seeded
   weight changes; emissions drift slightly downward over time.
4. "Fix English labels in the app".
5. **The A-F grade is a column of the simulated dataset**, computed by the rule in "Transition grade". No
   Decision Studio rework (the five-tier preset in `backend/arp/decision/credibility.py` stays as it is).
6. **Grades show in all three places:**
   - **Transition Intelligence** (AC-73 to AC-75): a native "Simulated ESG" card in Risk Monitoring → Company
     Profiles (beside `ProfileActionStrip`, so it works without Superset), a per-portfolio grade breakdown in
     `bi_published` and grade text in the `bi.company_profile` view for later dashboards (charts stay with
     PR #424).
   - **Index Construction as a field** (no row here): the dataset carries `transition_grade` with the type in
     "Fields for Index Construction"; `index-starting-universe` shows it as a category.
   - **Company page** (AC-70 to AC-72): PR 3 makes the imported companies open on `#/companies/<ref>` and
     shows the grade and simulated values there, each marked `Simulated`, apart from the page's real facts.

## Amendment A (13 Nov 2026): written-off positions, revenue shares capped at 1

Two owner decisions of 13 Nov, after PR 1 (#432) merged and while PR 2 (#434) was open. They change the
dataset, the loader and the index loader; the sections below are edited to match, and every edited place
says `(Amendment A)`.

**A1. Written-off positions are deleted.** 15 equity ISINs sit in the files with an index weight below
0.0001 % (fraction 0.000001): Gazprom, Sberbank, Norilsk Nickel, Surgutneftegas (ordinary and preference),
Tatneft, Novolipetsk Steel, Alrosa, Rusal, Moscow Exchange, Inter RAO, Ozon (MSCI EM, 12 lines), Kangmei
Pharmaceutical (MSCI EM, so 13 MSCI EM lines in all), NMC Health (MSCI Europe, plus an `N/A` line in MSCI
World) and the Hologic contingent right (MSCI World and S&P 500): 17 lines. The dataset gives them nonsense sizes today (7 have EVIC 0.00,
Gazprom revenue 0.01 and scope 1 of 1.91). They are:

- **listed in one shared file, `data/holdings/written_off.csv`** (`isin,name,reason`, one row per ISIN,
  `name` copied from a holdings file, `reason` `index weight below 0.0001 % (written off)`). The list is
  data, not a rule in code: an equity ISIN (`Type of Security` `Aktien`, `Equities`, `Depository Receipts` or
  `Preferred Stock`) is on it when it has at least one numeric `Weighting` in the seven files
  and every numeric `Weighting` it has is below 0.000001 (AC-80 checks the list against that rule). The
  file sits next to the holdings files because all three readers already take the holdings directory:
  `arp showcase simulate` and `arp showcase load` read `<--holdings-dir>/written_off.csv`, the index loader
  reads `<holdings_dir>/written_off.csv` (setting `holdings_dir`, `backend/arp/config.py`). No new option or
  setting. A missing file means nothing is written off. `index_universe.py` belongs to
  `index-starting-universe`; this amendment owns only the reading of the list there (AC-95 to AC-99, AC-103), and
  none of that spec's rows changes;
- **removed from the dataset**: no row for a listed ISIN, and its lines take no part in keys, companies,
  peer groups, sizes or percentiles (`<N>` becomes 2,523 rows, 2,515 companies; grades in the affected peer
  groups are recomputed by the unchanged rule). An override row naming a listed ISIN fails `arp showcase
  simulate` with `overrides row <n>: ISIN <isin> is written off (written_off.csv)`; the Gazprom `oil` and
  `gas` rows leave `activity_overrides.csv` and RU0007661625 leaves the list in "Controversial revenue";
- **not imported by `arp showcase load`**: `import_holdings_file` gains a parameter
  `skip_isins: frozenset[str] = frozenset()` (lines with those ISINs are ignored before anything is written);
  only `arp showcase load` passes the list. Its `import` step therefore skips listed lines,
  so no company, security, holding or snapshot line comes from them, also in the history snapshots. When a
  file was imported before with `import-constituents`, the loader's snapshot at the file date replaces that
  one, so it too holds no listed ISIN. Remaining weights are not rescaled (the deleted weight is at most
  0.0000107 percentage points per file, in MSCI EM). `arp portfolio import-constituents` does not read the list: it
  still imports every line (AC-30 to AC-42 unchanged; the 14 all-`N/A` ISINs of AC-38 are not on the list);
- **not offered by the index loader**: in a `file:` universe a line whose ISIN is listed, and in a
  `portfolio:` universe a holding whose company id is `isin_<listed ISIN>`, is checked before every
  other test, `without a weight` included, and is never a candidate (so NMC Health's `N/A` line in MSCI
  World counts as written off: 2 lines there, 13 in MSCI EM). It is not counted in `Dropped <k> lines: ...`; instead, when
  at least one such line was skipped, the universe's notes end with one more line:
  `Written-off lines not offered (index weight below 0.0001 %): <count>.` (after the `Simulated ESG data`
  line). With no listed line skipped the notes are as today, so `file:DAX` keeps its four lines.

**A2. Revenue shares add up to at most 1.** 31 companies have eight `*_revenue_pct` shares summing above 1
(up to 1.512). One of them, Surgutneftegas preference, is written off by A1, so 30 remain. Per company, after the draws and
overrides of "Controversial revenue", with every share rounded to 4 decimals as written:

1. O = the sum of the company's override shares among the eight activities. **O above 1 fails** `arp showcase
   simulate`, exit 1, stderr `overrides: the activity shares of <isin> (<name>) add up to <O>, more than 1`, `<O>` with 4 decimals
   (`<isin>` = the override rows' ISIN; the overrides file is hand-written, so it is fixed there, not
   scaled). Today the largest O is 0.95.
2. D = the sum of the drawn shares (activities without an override). If O + D ≤ 1, nothing changes.
3. Else each drawn share d becomes `round(d × (1 − O) / D, 4)`; override shares stay as written. If the
   eight shares then do not sum to exactly 1.0000, the largest scaled share (first in column order on a tie)
   takes the difference. With O = 1 every drawn share becomes 0.

Nothing else depends on the shares (grades use intensity, green share and E score), so A2 changes only the
eight columns of those 30 companies.

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
  2,538 distinct ISINs (2,530 companies as "Key" defines them). 14 of them have `Weighting` `N/A` in every file (12 in
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
  max(month end, `at` of the latest ESG load), picking, among sources with an observation on or before that
  date, the highest-ranked source, then its latest `observed_at`, and
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

1. One simulated row per company in the seven files (except the ISINs of `written_off.csv`, Amendment A1), with the seven climate columns, further ESG scores,
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
- A Decision Studio credibility rework (owner decision 5).
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
`Depository Receipts` or `Preferred Stock`, sorted by ISIN, except the ISINs of
`<holdings-dir>/written_off.csv`, whose lines are dropped before anything else (Amendment A1). Other rows with
weight `N/A` are kept.

**Key.** A key is the `Name` (upper-cased, stripped) + the country translated to English with the import's
table (PR 1 carries the same entries as "English labels" below, so `Vereinigte Staaten von Amerika` and
`United States` are one country). A **company** is the set of keys linked by a shared ISIN: two keys that
share any ISIN are one company (`SAP` and `SAP SE` share `DE0007164600`). Share classes and dual listings
with the same key are one company; `EQT` in the US and `EQT` in Sweden are two. Draws come from SHA-256 of
the company's first key. Every ISIN of a company gets identical values in every column except `isin`,
`company_id`, `files`. Name, country and sector are the company's, taken from its first line in the file
order `MSCI_World`, `SP500`, `MSCI_Europe`, `MSCI_EM`, `AI_Big_Data`, `EURO_STOXX_50`, `DAX`. Below,
"key" in Size, Controversial revenue and Transition grade means the company.

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
  CNE1000007Q1, INE002A01018 (RU0007661625, Gazprom, removed: written off, Amendment A1)

**Total at most 1 (Amendment A2).** A company's eight shares sum to at most 1.0000; where the draws push them
above 1, the drawn shares are scaled by the rule in Amendment A2 and override shares stay as written.

## Transition grade (PR 1, owner decisions 2 and 5)

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
| Seven climate columns | Observations, source `simulated`, one set per month 2026-06 to 2026-11 | `bi_published` rows with `source` `simulated`; Ask the Portfolio answers and monitoring alerts built on them show `Simulated`; the TI card and the company page |
| The 25 `simulated_esg` fields (below) | Observations, source `simulated`, period 2026-11 | `bi_published` `company_profile` rows with `source` `simulated`; the TI card and the company page |
| Grade breakdown per portfolio | `bi_published` `portfolio_climate_metrics` keys | Superset later (PR #424) |
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

1. `import`: the seven files through `import_holdings_file`, `AI_Big_Data` with fund ISIN IE00BGV5VN51,
   skipping the lines of the ISINs in `<holdings-dir>/written_off.csv` (Amendment A1).
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

## Grades on screens (PR 3, owner decision 6)

Wherever a simulated value or grade shows, the word `Simulated` shows next to it. The grade shows as
`<letter> <label>`, e.g. `B Credible`, with its peer group.

## PRs

| PR | Contents | Risk | Waits for |
|---|---|---|---|
| 1 | `AI_Big_Data.xlsx` to `main`, `arp showcase simulate`, `data/simulated/` (dataset, overrides, README), grades | normal | nothing |
| 2 | `import_holdings_file`, English labels, `simulated` source and schema, provider fallback, `arp showcase load`, monthly runs, `Simulated` on Ask the Portfolio and alerts | high | #419 merged |
| 3 | Grades and labels on the TI card, the company page and `bi.company_profile` | normal | PR 2 |
| 4 (Amendment A) | `data/holdings/written_off.csv`, `arp showcase simulate` reading it and capping the revenue shares, the regenerated dataset and overrides, `data/simulated/README.md` gaining the written-off rule under "Rows and companies" and the A2 rule under "Controversial revenue", the loader skipping listed lines, the index loader not offering them | high (changes what the loader imports) | PR 2 (#434) merged |

My call against the intake plan: the loader moves from PR 1 to PR 2, because it needs the import fixes;
PR 1 stays independent so `index-starting-universe` can start on the file.

## Left to the builder

- Where `Simulated` is rendered on Ask the Portfolio and alerts, within AC-58 and AC-59.
- The override list beyond the ISINs above, within the rules.

## Acceptance

`<N>` is the number of distinct ISINs over equity rows (`Aktien`, `Equities`, `Depository Receipts`,
`Preferred Stock`) of the seven files, minus the ISINs listed in `data/holdings/written_off.csv` (Amendment A);
tests compute it (2,523 today; 2,538 before Amendment A); a company is the set of keys linked by a shared ISIN,
as "Key" defines it, over those rows (2,515 today). "The list" is `data/holdings/written_off.csv`. "The e2e stack" is `backend/scripts/e2e_stack.sh up` (seed-demo data only). "The loader ran" means
`arp showcase load` on the e2e stack with the committed dataset.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The seven files and the list in `data/holdings/` | `arp showcase simulate --out <tmp>` runs from `backend/` | exit 0; `<tmp>` has `<N>` data rows (the list's ISINs excluded, Amendment A), one per ISIN, sorted by ISIN, with the columns of "Columns" in that order | holdout |
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
| AC-16 | `activity_overrides.csv` and the seven files | each override row is checked | its `isin` appears in a file with exactly its `name` and is not in the list (Amendment A); `activity` is one of the eight activities, `controversial_weapons` or `norms_violation`; `reason` is not blank; `share` lies in its activity's override range (flags: 1) | holdout |
| AC-17 | `activity_overrides.csv`; the list in "Controversial revenue" as amended (RU0007661625 removed, Amendment A; its absence is AC-100) | it is read | every ISIN listed in "Controversial revenue" has a row with that activity (oil and gas: one `oil` and one `gas` row) | holdout |
| AC-18 | The dataset | rows whose key has an override for an activity are read | the share equals the override's `share` | holdout |
| AC-19 | The dataset | every revenue-share column is read | every value is between 0 and 1 | holdout |
| AC-20 | The dataset | rows are grouped by company | rows of one company have equal values in every column except `isin`, `company_id`, `files` | holdout |
| AC-21 | The dataset | `esg_score` is recomputed | it equals the mean of `esg_e_score`, `esg_s_score`, `esg_g_score` within 0.01 | holdout |
| AC-22 | The dataset | `transition_grade` and `transition_grade_label` are read | the pairs are exactly `A`/`Leader`, `B`/`Credible`, `C`/`Gaps`, `D`/`Emerging`, `E`/`Not credible`, `F`/`Disqualified` | holdout |
| AC-23 | The dataset | per sector, the n companies are counted by grade | A = floor(0.10 n), B = floor(0.30 n) − floor(0.10 n), C = floor(0.60 n) − floor(0.30 n), D = floor(0.85 n) − floor(0.60 n), E = floor(0.95 n) − floor(0.85 n), F = n − floor(0.95 n) | holdout |
| AC-24 | The dataset | per sector, companies are sorted by `transition_score` descending, ties by smallest ISIN | grades never go back up along that order | holdout |
| AC-25 | The dataset | `transition_score` is recomputed per company from the file's values by the rule in "Transition grade" | it equals the file's value within 0.0001 | holdout |
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
| AC-70 | The loader ran | a user opens the company with the largest weight in `DAX.xlsx` | the page shows `Transition grade`, the grade as `<letter> <label>`, its peer group and the word `Simulated` | evaluator |
| AC-71 | Same | the user looks at any climate value or revenue share on that page | the word `Simulated` shows next to it | evaluator |
| AC-72 | Same | a user searches for that company's name | it is found and opens the page of AC-70 | evaluator |
| AC-73 | The loader ran | a user opens Risk Monitoring → Company Profiles and picks the company with the largest weight in `DAX.xlsx` | a card titled `Simulated ESG` shows the grade as `<letter> <label>`, the peer group, scope 1, carbon intensity and the eight revenue shares | evaluator |
| AC-74 | Same | `bi_published` `portfolio_climate_metrics` rows for 2026-11 of `portfolio_dax` are read | keys `grade_a_weight_pct` to `grade_f_weight_pct`, each a share of the weight of graded holdings, summing to 100 within 0.1 percentage points | holdout |
| AC-75 | Same | the `bi.company_profile` view is queried for `transition_grade` in 2026-11 | a text column holds the grade letter for every dataset company | holdout |

| AC-80 | The list and the seven files (Amendment A1) | the list is read | header `isin,name,reason`; its ISINs are exactly the equity ISINs (`Aktien`, `Equities`, `Depository Receipts`, `Preferred Stock`) of the files that have at least one numeric `Weighting` and whose every numeric `Weighting` is below 0.000001 (15 today) | holdout |
| AC-81 | The committed dataset and the list | the dataset's `isin` column is read | no ISIN of the list appears | holdout |
| AC-82 | `<dir>` = a copy of the seven files plus a `written_off.csv` holding only the row of RU0007661625 | `arp showcase simulate --holdings-dir <dir> --out <tmp>` | exit 0; `<tmp>` has one data row per distinct equity ISIN of the files minus 1 (2,537 today), none with ISIN RU0007661625 | holdout |
| AC-83 | `<dir>` = a copy of the seven files without `written_off.csv` | `arp showcase simulate --holdings-dir <dir> --out <tmp>` | exit 0; `<tmp>` has one data row per distinct equity ISIN of the files (2,538 today) | holdout |
| AC-84 | A copy of `activity_overrides.csv` with the added row `RU0007661625,GAZPROM PJSC,gas,0.50,test` | `arp showcase simulate --overrides <copy> --out <tmp>` | exit 1; stderr contains `RU0007661625` and `written off` | holdout |
| AC-85 | The committed dataset (Amendment A2) | the eight revenue shares of every row are summed as written, in decimal | every sum is at most 1.0000 | holdout |
| AC-86 | Same | the row of AEA007301012 (`ADNOC DRILLING COMPANY`, no override) is read | `oil_revenue_pct` 0.6183, `gas_revenue_pct` 0.3817, the other six 0.0000 | holdout |
| AC-87 | Same | the row of CNE000000WV6 (`YANKUANG ENERGY GROUP A`, `coal` override 0.85) is read | `coal_revenue_pct` 0.8500, `oil_revenue_pct` 0.1500, the other six 0.0000 | holdout |
| AC-88 | Same | the row of CNE1000002R0 (`CHINA SHENHUA ENERGY LTD H`, `coal` override 0.70) is read | `coal_revenue_pct` 0.7000, `oil_revenue_pct` 0.1257, `gas_revenue_pct` 0.1743, the other five 0.0000 | holdout |
| AC-89 | Must not change: same | the row of AN8068571086 (`SLB`, shares summing below 1) is read | `oil_revenue_pct` 0.7811, `gas_revenue_pct` 0.1472, the other six 0.0000 | holdout |
| AC-90 | A copy of `activity_overrides.csv` with the added row `US7181721090,PHILIP MORRIS INTERNATIONAL,alcohol,0.30,test` (its `tobacco` override is 0.95, so 1.25) | `arp showcase simulate --overrides <copy> --out <tmp>` | exit 1; stderr contains `overrides: the activity shares of US7181721090 (PHILIP MORRIS INTERNATIONAL) add up to 1.2500, more than 1` | holdout |
| AC-91 | A fresh e2e stack on which only the loader ran (Amendment A1) | companies `isin_<ISIN>` are looked up for every ISIN of the list | none exists | holdout |
| AC-92 | Same as AC-91 | the holdings of every snapshot of the seven portfolios of AC-43 are read | no holding's security has an ISIN of the list | holdout |
| AC-93 | The e2e stack, the seven files imported with `import-constituents` as in AC-36, then the loader ran | the 2026-11-02 snapshot of `portfolio_msci_em` is read | none of the 13 MSCI EM ISINs of the list is held | holdout |
| AC-94 | Must not change: a fresh e2e stack, the loader has not run | `arp portfolio import-constituents data/holdings/MSCI_EM.xlsx` runs | the 2026-11-02 snapshot of `portfolio_msci_em` holds all 13 MSCI EM ISINs of the list (the import does not read the list) | holdout |
| AC-95 | The e2e stack (default `holdings_dir`), the committed list | `GET /api/index/universes/file:MSCI_EM` | 200; the last entry of `notes` is `Written-off lines not offered (index weight below 0.0001 %): 13.` | holdout |
| AC-96 | Same | same | the `Simulated ESG data` note reads `matched <n> of <n> companies.` with both numbers equal to `company_count` | holdout |
| AC-97 | Must not change: same | `GET /api/index/universes/file:DAX` | `notes` has exactly 4 entries, none starting `Written-off` | holdout |
| AC-98 | `holdings_dir` with a `written_off.csv` listing RU0007661625; a stored portfolio `p1` whose latest snapshot holds an equity security of company `isin_RU0007661625` (weight_pct 10) and one of company `c_b` (weight_pct 90) | `GET /api/index/universes/portfolio:p1` | `company_count` 1; `notes[1]` `Dropped 0 lines: 0 cash, 0 other asset class, 0 zero or negative weight, 0 without a weight, 0 not linked to a company.`; the last note `Written-off lines not offered (index weight below 0.0001 %): 1.` | unit |
| AC-99 | Must not change: `holdings_dir` = a directory with one file `X.xlsx` (DAX layout, two equity lines with positive weights) and no `written_off.csv` | `GET /api/index/universes/file:X` | `company_count` 2; no note starts `Written-off` | unit |
| AC-100 | `activity_overrides.csv` (Amendment A1) | it is read | no row has `isin` RU0007661625 | holdout |
| AC-101 | The list and the seven files | each row of the list is read | its `name` is a `Name` of its ISIN in a file | holdout |
| AC-102 | The list | each row is read | `reason` is not blank | holdout |
| AC-103 | The e2e stack (default `holdings_dir`), the committed list | `GET /api/index/universes/file:MSCI_World` | 200; the last entry of `notes` is `Written-off lines not offered (index weight below 0.0001 %): 2.` | holdout |

Rows by PR: PR 1 AC-1 to AC-28; PR 2 AC-30 to AC-61; PR 3 AC-70 to AC-75; PR 4 (Amendment A) AC-80 to AC-103
and the amended AC-1, AC-16, AC-17, which PR 4 makes pass again.

**When the hidden tests change:** the test-writer updates AC-1, AC-16 and AC-17 and adds AC-80 to AC-103 only
after PR 2 (#434) has merged, so the Holdout job on #434 still runs the approved rows; PR 4 is the first PR
the amended tests run on.

Amendment A, rows by kind (for the test-writer; derived from row ids and wording only):

- **Changed, hidden test needs an update:** AC-1 (`<N>` excludes the list), AC-16 (override ISIN not in the
  list), AC-17 (RU0007661625 out of the required list).
- **Wording unchanged, now read against the amended dataset or loader; no test update expected:** AC-2 (the
  committed file is regenerated), AC-3 to AC-15, AC-18 to AC-27, AC-31 (`import-constituents` on DAX, no
  listed line), AC-38 (`import-constituents`, the 14 all-`N/A` ISINs are not on the list), AC-45 (the
  loader's MSCI World snapshots both lack the 2 listed ISINs; ratios and sums unaffected), AC-49 and AC-52
  ("each dataset company" is now 2,515 companies). A hidden test of these that hard-codes 2,538 or 2,530, or
  a Gazprom row, needs the update too.
- **New:** AC-80 to AC-97 and AC-100 to AC-103 (holdout), AC-98 and AC-99 (unit).
- **Removed:** none.
