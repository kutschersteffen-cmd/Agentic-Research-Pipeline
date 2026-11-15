# Showcase: each curated demo company appears once (`showcase-curated-company-keys`)

Status: draft for owner approval, 15 Nov 2026. Size S, one PR. Proposed risk: `risk:normal`.

## Why

The showcase database is shown live to senior management on about 27 Nov 2026 (bank JupyterLab, one uvicorn
process, Postgres, fresh load). On a database where both `arp portfolio seed-demo` and `arp showcase load` ran,
15 well-known companies exist twice: once under the seed's slug (`totalenergies`, named `TotalEnergies SE`) and
once under the holdings files' key (`isin_FR0000120271`, named `TOTALENERGIES`). Two rows for one company make
every per-company figure wrong in a way a viewer notices: the Ask panel example "How much do we hold in
TotalEnergies across all portfolios?" has two answers, and the stewardship cockpit's financed-emissions panel
counts the seed's holdings of these 15 as "not engaged", because engagements are recorded on the `isin_` key.

## Today

- `arp portfolio seed-demo` (`backend/arp/portfolio/mock_data.py`; the app's "Seed demo dataset" button,
  `POST /api/portfolio/demo/seed`, and `backend/scripts/e2e_stack.sh` run the same code) writes 15 companies
  keyed by slug (`_COMPANIES`), their securities (`{slug}_eq`, `{slug}_bond1` with mock ISINs
  `{country}0MOCK{idx:04d}0`), 4 portfolios, `internal_api` climate observations with `snapshot:<date>` periods,
  and mock news keyed by slug (`portfolio/news/mock_source.py`).
- `arp showcase load` (`backend/arp/showcase/load.py`) imports the seven files in `data/holdings/`, keying each
  company `isin_<ISIN>` with the file's name, country and sector (the MSCI World file is imported last, so its
  values stand), and writes `simulated` observations.
- `save_company` overwrites the whole row (last write wins).

## Owner decisions (15 Nov 2026)

1. **Names.** The 15 companies show the name exactly as the holdings files write it (`TOTALENERGIES`,
   `SIEMENS N AG`, …), like the other 2,566 companies, on every database: the seed writes these names too, so a
   seed-only database (the e2e stack) shows them as well. The curated names (`TotalEnergies SE`, …) go.
   (Owner, 15 Nov, dispatcher session: "Why not the original names", "Check the original provided holding
   files"; confirmed by button in this session: "File name everywhere".)
2. **Volkswagen is replaced** by Mercedes-Benz Group (`isin_DE0007100000`, `MERCEDES-BENZ GROUP N AG`, an
   ordinary share in DAX, EURO STOXX 50, MSCI Europe and MSCI World). The files hold Volkswagen only as its
   non-voting preference share, which must not stand in for the company. Mercedes-Benz takes every place
   Volkswagen had: second row of `_COMPANIES`, a bond in `_BOND_ISSUERS`, equity in Multi-Asset Balanced, bond
   in Corporate Bond Income. (Owner, 15 Nov: "Use another company"; Mercedes-Benz picked by button in this
   session over Continental AG.)
3. **Existing databases are rebuilt**, not purged, before 27 Nov. No purge step is built or tested
   (owner, 15 Nov: "Rebuild before 27 Nov"). See "Rebuild".

## Goals

- G1. After `seed-demo` alone, the 15 curated companies are keyed `isin_<ISIN>` with the name, country and
  sector `arp showcase load` writes for that ISIN (table T).
- G2. After both commands, in either order, each of the 15 exists once, and its row is the same in both orders.
- G3. Everything else the seed writes stays as it is (portfolios, security ids, mock ISINs, prices, quantities,
  FX, the unresolved note), apart from the Volkswagen to Mercedes-Benz swap.

## Non-goals

- No purge or migration of a database that already has the slug rows (decision 3).
- No change to `arp showcase load`, the holdings import, the simulated dataset, or how a consumer picks between
  observations of different sources on one company.
- No change to alerts, triggers or engagements already stored under a slug: a rebuilt database has none.
- No loose name matching between the seed and the files: the map is the 15 fixed ISINs below. `SAPUTO`,
  `SIEMENS ENERGY` and `ENEL CHILE` are different issuers.

## Table T: the 15 companies

Values as `arp showcase load` writes them from the files of 15 Nov 2026 (MSCI World row; the other files write
the same names).

| Slug (internal) | Company key | Name | Country | Sector |
|---|---|---|---|---|
| bmw | isin_DE0005190003 | BMW | Germany | Consumer Discretionary |
| mercedes | isin_DE0007100000 | MERCEDES-BENZ GROUP N AG | Germany | Consumer Discretionary |
| siemens | isin_DE0007236101 | SIEMENS N AG | Germany | Industrials |
| sap | isin_DE0007164600 | SAP | Germany | Information Technology |
| allianz | isin_DE0008404005 | ALLIANZ | Germany | Financials |
| totalenergies | isin_FR0000120271 | TOTALENERGIES | France | Energy |
| lvmh | isin_FR0000121014 | LVMH | France | Consumer Discretionary |
| airbus | isin_NL0000235190 | AIRBUS | France | Industrials |
| iberdrola | isin_ES0144580Y14 | IBERDROLA | Spain | Utilities |
| novartis | isin_CH0012005267 | NOVARTIS AG | Switzerland | Health Care |
| nestle | isin_CH0038863350 | NESTLE SA | Switzerland | Consumer Staples |
| asml | isin_NL0010273215 | ASML HOLDING | Netherlands | Information Technology |
| shell | isin_GB00BP6MXD84 | SHELL | Netherlands | Energy |
| orsted | isin_DK0060094928 | OERSTED | Denmark | Utilities |
| enel | isin_IT0003128367 | ENEL | Italy | Utilities |

The files give Airbus as France and Shell as the Netherlands; the seed follows the files.

## Approaches

1. **Re-key inside the seed (chosen).** `mock_data.py` carries the ISIN, file name, country and sector per curated
   company and writes `CompanyRef(company_id="isin_<ISIN>", …)`; `SecurityRef.company_id`, the news lookup and
   the climate observations use the same key. The slug stays the internal key of `_BOND_ISSUERS`,
   `_PORTFOLIO_*_HOLDINGS`, `_CLIMATE_MISMATCH_COMPANIES` and the security ids, so prices and quantities (seeded by
   security id) stay identical. Because the seed writes exactly the row the showcase writes, the order of the two
   commands does not matter. Smallest change; works on a fresh database, which is all decision 3 needs.
2. Merge at load time: `arp showcase load` folds slug rows into their `isin_` twins. Rejected: it only helps a
   database that already has both, which decision 3 rules out, and it leaves the e2e stack on slugs.
3. Keep slugs and alias them in the company registry. Rejected: `legacy_companies` would still hold two rows, so
   every portfolio read would still show the company twice.

## Design (approach 1)

- `_COMPANIES` rows gain the ISIN and use the file's name, country and sector (table T). Volkswagen's row becomes
  Mercedes-Benz (slug `mercedes`, currency EUR), keeping its position, so its mock ISINs are the ones Volkswagen
  had (`DE0MOCK00020`, bond `DE0MOCK0005B`).
- The mock climate generator keeps using the curated sector label (`Automobiles`, `Energy`, `Software`, …) to pick
  its baseline, so each company's emissions keep their order of magnitude; that label is not stored. My call:
  the exact mock values may change, because the generator's random draws are seeded by the company key
  (`mock_esg_source._rng_for(company_id)`); no row pins them.
- Mock news is stored under the `isin_` key with the same headlines as today.
- `DemoDatasetSummary.climate_mismatch_companies` lists the two `isin_` keys.
- The `qa_agent.py` prompt example `{"company_id": "bmw", …}` should name a key that exists:
  `isin_DE0005190003` (my call).

## Risks the builder must handle

- **Two observation sources on one company.** On a database with both loads, each of the 15 carries the seed's
  `internal_api` observations (`snapshot:<date>` periods) and the showcase's `simulated` ones. Both are kept
  (AC-12); which one a screen shows follows the existing selection rules, unchanged by this spec.
- **Mock climate values shift** (above). Tests that pin seeded climate values are updated, never weakened.
- **Ask panel.** The example question must resolve to one company (AC-15).
- **Old alerts/triggers** keep their slug ids on an old database. Not handled: the database is rebuilt.
- **Tests that assert slugs** (at least `test_stewardship_universe.py`, `test_stewardship_vote_ledger_feed.py`,
  `test_mock_data.py`, `test_monthly_run.py`, `test_showcase_holdings_intake.py`) are updated to the `isin_` keys;
  every changed test is listed in the PR description, as `.claude/CLAUDE.md` requires.

## Effect on the cockpit figure (cockpit PR 2)

The figure that changes is "Financed emissions covered" (`emissions.engaged_tco2e / emissions.total_tco2e` from
`GET /api/stewardship/cockpit`) and its "not engaged" bucket (`selected_not_engaged_tco2e` plus
`not_selected_tco2e`). Before this fix the seed's holdings of the 15 (about 49 % of financed emissions) sit under
slug ids no engagement names, so they land in "not engaged". After it they land on the `isin_` company, so they
count as engaged wherever that company has an engagement. To see it: on the e2e stack call the cockpit endpoint
for `multi_asset_balanced` before and after this PR and compare `engaged_tco2e`. Once cockpit PR 2 is merged,
the builder of whichever of the two PRs merges second records both `emissions` objects in its PR description.

## Sequencing

Independent of cockpit PR #481, cockpit PR 2 and workbench PR #480: none of them touches `mock_data.py`,
`news/mock_source.py`, `mock_esg_source.py`, `qa_agent.py` or the five tests above (checked on 15 Nov against
#480 and #481). It can merge before or after them. Cockpit PR 2's evaluator row AC-60 reads the demo stack, so if
PR 2 is evaluated after this PR merges, its percentage is the post-fix one; that is the intended figure.

## Rebuild (for 27 Nov)

The implementation PR adds this as a `## Rebuild` section to `demo/showcase/README.md`:

1. Start from an empty Postgres database (a new database, or drop and recreate the existing one).
2. `scripts/launch_jupyter.sh up`
3. From `backend/`: `python scripts/load_showcase_pack.py` (runs `arp showcase load`).
4. Optional, only if the seeded demo portfolios are wanted: `arp portfolio seed-demo`.

No manual purge is documented: an existing database is rebuilt, never cleaned in place.

## Other specs this changes

`2026-11-12-showcase-portfolio-fixes.md` AC-120 uploads an ESG row "for `bmw`". After this change the seeded BMW is
`isin_DE0005190003`; the evaluator uses that key when it checks AC-120. The row's expectation is unchanged.

## Left to the builder

Where the slug-to-ISIN data lives in `mock_data.py`, how the curated baseline label reaches the climate
generator, and how the news lookup finds articles for the `isin_` key.

## Acceptance

Definitions for every row:

- **Seed**: `generate_demo_dataset(store)` without `today` (fixed `SNAPSHOT_DATES`) on an empty store, the same
  code `arp portfolio seed-demo` runs. No issuer-sector master is loaded.
- **Load**: `arp showcase load` (`arp.showcase.load.load`) with `data/holdings/` and
  `data/simulated/esg_simulated.csv` of the repo, on Postgres.
- **Main**: the same command on `main` at `ed22752`, used where a row says "as on main".
- **Companies**: `store.list_companies()` (what `GET /api/portfolio/companies` returns).
- **T keys**: the 15 company keys of table T. **Old slugs**: `bmw`, `volkswagen`, `siemens`, `sap`, `allianz`,
  `totalenergies`, `lvmh`, `airbus`, `iberdrola`, `novartis`, `nestle`, `asml`, `shell`, `orsted`, `enel`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | an empty store | Seed | Companies holds exactly 15 companies and their `company_id`s are exactly the T keys | holdout |
| AC-2 | an empty store | Seed | each of the 15 companies has `name`, `country` and `sector` exactly as its row in table T | holdout |
| AC-3 | an empty store | Seed | `store.list_securities()` holds exactly 24 securities: `<slug>_eq` for the 15 slugs of T, `<slug>_bond1` for `bmw`, `totalenergies`, `shell`, `siemens`, `mercedes`, `enel`, `airbus`, `nestle`, and `unmapped_note_1` | holdout |
| AC-4 | an empty store | Seed | every `<slug>_eq` and `<slug>_bond1` security has `company_id` equal to its slug's T key; `unmapped_note_1` has `company_id` null | holdout |
| AC-5 | an empty store | Seed | `mercedes_eq` has ISIN `DE0MOCK00020` and `mercedes_bond1` has ISIN `DE0MOCK0005B`; every other security has the ISIN it has as on main | holdout |
| AC-6 | an empty store | Seed | for every portfolio and snapshot date, every holding of a security other than `mercedes_eq` and `mercedes_bond1` has the same `quantity`, `price`, `market_value` and `market_value_eur` as on main | holdout |
| AC-7 | an empty store | Seed | `multi_asset_balanced` holds `mercedes_eq` and `corporate_bond_income` holds `mercedes_bond1` on each of the 4 snapshot dates; no holding's security id starts with `volkswagen` | holdout |
| AC-8 | an empty store | Seed | the summary has `company_count` 15, `security_count` 24, `portfolio_count` 4 and `climate_mismatch_companies` `["isin_FR0000120271", "isin_GB00BP6MXD84"]` | holdout |
| AC-9 | an empty store | Seed | every item of `store.list_news()` has a `company_id` among the T keys, and the headlines stored for each T key equal the headlines stored for its slug as on main | holdout |
| AC-10 | an empty store | Seed | for each T key and each climate field, `store.load_observations(key, field)` holds as many observations as main holds for its slug (Mercedes: as many as main holds for `volkswagen`), each with period `snapshot:<date>`; for every Old slug it holds none | holdout |
| AC-11 | an empty Postgres store | Seed, then Load | Companies holds each T key exactly once with `name`, `country` and `sector` as in table T; no `company_id` is an Old slug; the number of companies equals the number after Load alone | holdout |
| AC-12 | as AC-11 | `load_observations("isin_FR0000120271", "climate_scope1_tco2e")` | it holds observations with source `internal_api` and period `snapshot:<date>`, and observations with source `simulated` | holdout |
| AC-13 | an empty Postgres store | Load, then Seed | the same as AC-11: each T key once with `name`, `country` and `sector` as in table T, no Old slug, as many companies as after Load alone | holdout |
| AC-14 | an empty Postgres store | Load alone | Companies, and the observations of `isin_DE0005140008` (DEUTSCHE BANK AG, not curated), are the same as on main | holdout |
| AC-15 | the e2e stack with Seed and Load both run | the Ask panel example "How much do we hold in TotalEnergies across all portfolios?" is asked | the answer names one company, `TOTALENERGIES` (`isin_FR0000120271`), and gives one total | evaluator |
| AC-16 | the implementation PR | `demo/showcase/README.md` is read | it has a `## Rebuild` section with the four steps of this spec's "Rebuild", in that order | evaluator |
| AC-17 | the e2e stack (`e2e_stack.sh up`, which runs `seed-demo`) | the existing E2E (browser) suite runs | it passes with no test removed or skipped | unit |

Must not change:

- AC-5, AC-6: mock ISINs and every price, quantity and FX value of the seed, apart from the Mercedes-Benz swap.
- AC-14: what `arp showcase load` writes on its own.
- AC-17: the browser flows on a seed-only stack.
