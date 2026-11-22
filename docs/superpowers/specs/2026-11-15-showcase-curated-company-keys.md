# Showcase: each curated demo company appears once (`showcase-curated-company-keys`)

Status: approved by the owner (button), 15 Nov 2026. Size S, one PR. Proposed risk: `risk:normal`.

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
  FX, the unresolved note), apart from the Volkswagen to Mercedes-Benz swap and the security names, which follow
  the company name (decision 1).

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

- `_COMPANIES` rows gain the ISIN and store the file's name, country and sector (table T). Volkswagen's row becomes
  Mercedes-Benz (slug `mercedes`, currency EUR), keeping its position, so its mock ISINs are the ones Volkswagen
  had (`DE0MOCK00020`, bond `DE0MOCK0005B`).
- The two-letter code that builds each mock ISIN stays as today (Airbus `NL`, Shell `GB`, Mercedes-Benz `DE`);
  only the stored `country` takes the file's value.
- Security names follow the new company name (my call, from decision 1): `TOTALENERGIES (Ordinary Shares)`,
  `TOTALENERGIES 3.25% 2030`.
- The mock climate generator keeps using the curated sector label (`Automobiles`, `Energy`, `Software`, …) to pick
  its baseline, so each company's emissions keep their order of magnitude; that label is not stored.
  Mercedes-Benz uses `Automobiles`, Volkswagen's label. My call:
  the exact mock values may change, because the generator's random draws are seeded by the company key
  (`mock_esg_source._rng_for(company_id)`); no row pins them.
- Mock news is stored under the `isin_` key with the same headlines as today.
- `DemoDatasetSummary.climate_mismatch_companies` lists the two `isin_` keys.
- The `qa_agent.py` prompt example `{"company_id": "bmw", …}` should name a key that exists:
  `isin_DE0005190003` (my call).

## Risks the builder must handle

- **Two observation sources on one company.** On a database with both loads, each of the 15 carries the seed's
  `internal_api` observations (`snapshot:<date>` periods) and the showcase's `simulated` ones. Both are kept
  (AC-23, AC-24); which one a screen shows follows the existing selection rules, unchanged by this spec.
- **Mock climate values shift** (above). Tests that pin seeded climate values are updated, never weakened.
- **Ask panel.** The example question must resolve to one company (AC-26).
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

Re-pointed by `2026-11-21-agent-panel-code-mode.md` Phase 7 (slice 13): AC-26 is the same question asked in the Agent composer's `Ask` mode, on `#/agent/ask/<id>`.

Definitions for every row:

- **Stack**: the app started by `backend/scripts/e2e_stack.sh up`, which runs `arp portfolio seed-demo` (today's
  dates). The `holdout` rows read it through the API.
- **Seed**: `generate_demo_dataset(store)` without `today` (fixed `SNAPSHOT_DATES`) on an empty JSON
  `PortfolioStore` in a temporary directory, with no issuer-sector master. Used by `unit` rows.
- **Seed (Postgres)**: the same call, where `store` is the `PostgresPortfolioStore` on the Fresh Postgres schema
  that Load also writes to.
- **Load**: `arp.showcase.load.load` with the repo's `data/holdings/` and `data/simulated/esg_simulated.csv`.
- **Fresh Postgres**: an empty schema on `ARP_TEST_POSTGRES_DSN`, initialised as `arp db init-postgres` does.
- **As on main**: the value the same code gives on `main` at `ed22752`; the builder captures these values from
  main into the test.
- **Companies**: `store.list_companies()`, which is what `GET /api/portfolio/companies` returns.
- **T keys**: the 15 company keys of table T. **Old slugs**: `bmw`, `volkswagen`, `siemens`, `sap`, `allianz`,
  `totalenergies`, `lvmh`, `airbus`, `iberdrola`, `novartis`, `nestle`, `asml`, `shell`, `orsted`, `enel`.
- **Six climate fields**: `climate_scope1_tco2e`, `climate_scope2_tco2e`, `climate_scope3_tco2e`,
  `climate_carbon_intensity`, `climate_evic_eur_m`, `climate_green_revenue_pct` (what the mock generator writes).

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Stack | `GET /api/portfolio/companies` | for each T key, exactly one entry has that `company_id`, and its `name`, `country` and `sector` are as in table T | holdout |
| AC-2 | Stack | `GET /api/portfolio/companies` | no entry's `company_id` is an Old slug | holdout |
| AC-3 | Stack | `POST /api/portfolio/demo/seed` | the response has `company_count` 15 and `security_count` 24 | holdout |
| AC-4 | Stack | `POST /api/portfolio/demo/seed` | the response's `climate_mismatch_companies` is `["isin_FR0000120271", "isin_GB00BP6MXD84"]` | holdout |
| AC-5 | Seed | Companies is read | it holds exactly 15 companies, whose `company_id`s are exactly the T keys | unit |
| AC-6 | Seed | `store.list_securities()` | its security ids are exactly: `<slug>_eq` for the 15 slugs of T; `<slug>_bond1` for `bmw`, `totalenergies`, `shell`, `siemens`, `mercedes`, `enel`, `airbus`, `nestle`; `unmapped_note_1` (24 in all) | unit |
| AC-7 | Seed | `store.list_securities()` | each `<slug>_eq` and `<slug>_bond1` has `company_id` equal to its slug's T key; `unmapped_note_1` has `company_id` null | unit |
| AC-8 | Seed | `store.list_securities()` | `totalenergies_eq` is named `TOTALENERGIES (Ordinary Shares)` and `totalenergies_bond1` is named `TOTALENERGIES 3.25% 2030` | unit |
| AC-9 | Seed | `store.list_securities()` | `mercedes_eq` has ISIN `DE0MOCK00020` and `mercedes_bond1` has `DE0MOCK0005B` | unit |
| AC-10 | Seed | every portfolio's snapshot on each of the 4 dates is read | every holding of a security other than `mercedes_eq` and `mercedes_bond1` has `quantity`, `price`, `market_value`, `fx_rate_to_eur` and `market_value_eur` as on main | unit |
| AC-11 | Seed | the snapshots of the 4 dates are read | `multi_asset_balanced` holds `mercedes_eq` and `corporate_bond_income` holds `mercedes_bond1` on each date | unit |
| AC-12 | Seed | the snapshots of the 4 dates are read | no holding's `security_id` starts with `volkswagen` | unit |
| AC-13 | Seed | `store.list_news()` | every item's `company_id` is a T key | unit |
| AC-14 | Seed | `store.list_news(key)` for each T key | its headlines equal the headlines stored for that key's slug as on main | unit |
| AC-15 | Seed | `store.load_observations(key, field)` for each T key and each of the six climate fields | it holds exactly 4 observations, with periods `snapshot:2025-11-28`, `snapshot:2026-02-27`, `snapshot:2026-05-29`, `snapshot:2026-08-12` | unit |
| AC-16 | Seed | `store.load_observations(slug, field)` for each Old slug and each of the six climate fields | it holds none | unit |
| AC-17 | Fresh Postgres | Seed (Postgres), then Load | Companies holds each T key exactly once, with `name`, `country` and `sector` as in table T | unit |
| AC-18 | as AC-17 | Companies is read | no `company_id` is an Old slug | unit |
| AC-19 | as AC-17 | Companies is read | it holds as many companies as after Load alone on Fresh Postgres | unit |
| AC-20 | Fresh Postgres | Load, then Seed (Postgres) | Companies holds each T key exactly once, with `name`, `country` and `sector` as in table T | unit |
| AC-21 | as AC-20 | Companies is read | no `company_id` is an Old slug | unit |
| AC-22 | as AC-20 | Companies is read | it holds as many companies as after Load alone on Fresh Postgres | unit |
| AC-23 | as AC-17 | `load_observations("isin_FR0000120271", "climate_scope1_tco2e")` | it holds 4 observations with source `internal_api` and a `snapshot:` period | unit |
| AC-24 | as AC-17 | `load_observations("isin_FR0000120271", "climate_scope1_tco2e")` | its observations with source `simulated` are as many as after Load alone on Fresh Postgres | unit |
| AC-25 | Fresh Postgres | Load alone | Companies holds as many companies as Load alone gives as on main | unit |
| AC-26 | Stack started with `ARP_ANTHROPIC_API_KEY` in the environment of `e2e_stack.sh up`, then `arp showcase load` run from `backend/` against the Stack's `ARP_POSTGRES_DSN` | the Ask panel example "How much do we hold in TotalEnergies across all portfolios?" is asked | the answer names one company, `TOTALENERGIES`, and gives one EUR total | evaluator |
| AC-27 | the implementation PR | `demo/showcase/README.md` is read | it has a `## Rebuild` section with the four steps of this spec's "Rebuild", in that order | evaluator |
| AC-28 | Stack | CI's "E2E (browser)" job runs | it passes, with no test removed or skipped by this PR | unit |
| AC-29 | Seed | `store.list_securities()` | every security other than `mercedes_eq` and `mercedes_bond1` has its ISIN as on main | unit |
| AC-30 | Fresh Postgres | Load alone | `isin_DE0005140008` has `name` `DEUTSCHE BANK AG`, and `country` and `sector` as on main | unit |
| AC-31 | Fresh Postgres | Load alone | `load_observations("isin_DE0005140008", field)` holds as many observations as on main, for each of the six climate fields | unit |
| AC-32 | Seed | `store.list_portfolios()` | its portfolio ids are exactly `core_equity_europe`, `sustainable_leaders`, `multi_asset_balanced`, `corporate_bond_income` | unit |

Must not change:

- AC-29, AC-10, AC-32: mock ISINs, portfolios and every price, quantity and FX value of the seed, apart from the Mercedes-Benz swap.
- AC-25, AC-30, AC-31: what `arp showcase load` writes on its own.
- AC-28: the browser flows on a seed-only stack.
