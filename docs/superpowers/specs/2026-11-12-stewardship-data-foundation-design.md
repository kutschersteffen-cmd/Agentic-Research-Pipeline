# Stewardship data foundation: engagements (VOICE) and votes in Postgres

Slug: `stewardship-data-foundation`. Risk: high (new system of record for engagements, a data migration,
an API contract change).

Status: **approved by the owner on 12 Nov 2026** (buttons in the spec session).

Owner decisions so far (12 Nov 2026, buttons in this session):

- Engagements are never typed into the tool by hand. They arrive by API or Excel upload and are stored per
  company in Postgres.
- Votes are stored in Postgres too, so every vote decision can be traced back across years.
- One house, no multi-tenancy (no `tenant_id`, no row-level security).
- The engagement model follows the FIR VOICE method (8 June 2026): company → engagement → objective → activities,
  with influence assessed per objective.
- Mock data: 400 MSCI World companies, each with 3–5 objectives. Each objective is either a new topic or a
  follow-up to an earlier one.
- The real SEC N-PX votes of the iShares MSCI World ETF (URTH, series `S000035395`) for three reporting years
  are loaded **as the house's own vote history**, labelled as demo data.
- Approach 1: Postgres becomes the only engagement store, with the same functions as today's file store.

## Why

Engagement records today are JSON files per company (`engagements/<company_id>/record.json`, written by
`arp.storage.engagement_store.EngagementStore`). Votes exist only inside `proxy_voting` run outputs. That blocks
three things the owner wants next:

1. **Bulk intake.** Engagement activity is documented elsewhere and must be loaded by API or Excel, not keyed in.
2. **History.** A vote or an engagement step must stay traceable over years, by company, across runs.
3. **Reporting.** VOICE reporting (Table 2, one row per objective), Superset dashboards and the client report
   need cross-company queries, which files can't serve.

This spec builds the foundation only: tables, the store, intake, migration, demo data, the monitoring read and
one UI label. Influence grading, VOICE reporting and dashboards come in later specs (see Non-goals).

## Goals

1. Postgres tables for engagements in the VOICE shape, plus a vote ledger.
2. `PostgresEngagementStore`: the same public methods as `EngagementStore`, chosen by a setting, so every caller
   (stewardship stages, orchestrator, `/api/engagement` routes, monthly run) keeps working unchanged.
3. Intake by API (JSON batch) and by Excel upload, for engagements and for votes. Intake is idempotent: loading
   the same data twice changes nothing.
4. A one-time migration of today's file records into Postgres.
5. Demo data: 400 MSCI World companies with mock VOICE objectives, and URTH N-PX votes for three years.
6. Monitoring reads votes against management from the ledger, so the existing `vote_against_management` rule
   runs on real ballots.
7. The engagement panel shows each objective, and labels mock and N-PX rows as demo data.

## Non-goals (later specs)

- The influence decision tree, the categorisation grid and governance validation (VOICE plan phase 2).
  `influence_level` is stored as given, never computed here.
- The VOICE Table 2 report, its export and Superset dashboards (phase 3). A vote ledger screen is phase 3 too.
- The RFP resources questionnaire (phase 4).
- Semantic search over notes, the annotated performance timeline, cohort analysis.
- Multi-tenancy, a new login provider, a Next.js/Tailwind/Tremor frontend.
- Casting votes or any proxy-platform integration.
- Mocked ESG data and putting MSCI World into the house portfolios: both come from the approved
  `showcase-portfolio-data` spec (`arp showcase load`). This spec creates no ESG data.

## Anti-goals

- Mock data that could be mistaken for real engagement. Mock rows carry `source = 'mock_voice_seed'`, N-PX rows
  `source = 'npx_urth_demo'`, and the engagement panel labels both (AC-30).
- Two copies of the truth. With `engagement_store = postgres` the app never writes the file directory (AC-27).
- Changing the VOICE definitions or grids. Field values are VOICE's own option lists, written out below.
- Dropping or rewriting existing tables. The legacy `engagement_issues` and `engagement_commitments` stay (AC-28).

## Constraints

- Schema changes go through `arp/storage/postgres_schema.py` (`ensure_schema`: `create_all`, additive columns,
  recorded steps). No Alembic, nothing is dropped.
- Company keys are the registry's `company_id`. For holdings this is `isin_<ISIN>`, as in `showcase-portfolio-data`.
- Request and response models change, so `scripts/export_openapi.py` and `npm run gen:api` run and both generated
  files are committed.
- `openpyxl` (already a dependency) reads and writes the Excel files. No new dependencies.
- Writes need role `analyst` or above, reads `viewer`, as for every other `/api/stewardship` route.

## Approaches considered

1. **Postgres as the only store, behind today's store interface (picked).** Normal tables, plus a
   `PostgresEngagementStore` with the same methods. Files are migrated once. One source of truth; reporting and
   Superset query the tables. The largest first PR.
2. Postgres as an import and reporting copy, synced into the files. A smaller first step, but two truths that drift.
3. One JSONB document per company. The fastest migration, but cross-company VOICE and vote queries become awkward.

## VOICE option lists

Copied from FIR, *The VOICE method*, 8 June 2026, Table 2 and the FIR theme list (p. 21–22). Stored as the
snake_case value; the Excel `lists` sheet shows both.

- **FIR theme (`fir_theme`):** `climate_mitigation` (Climate Mitigation & Paris Alignment), `climate_adaptation`
  (Climate Adaptation & Resilience), `natural_capital` (Natural Capital, Land Use & Biodiversity Preservation),
  `resources_circular` (Resources Management: Waste & Circular Economy), `pollution` (Pollution: Air, water & land),
  `human_capital` (Human Capital Management), `human_rights` (Human Rights and Fundamental Rights),
  `consumer_protection` (Consumer Protection, Product Responsibility & Access), `digital_responsibility` (Digital
  Responsibility, Social Impact of Technology and AI), `communities` (Communities & stakeholder relations),
  `governance_board_pay` (Governance Structure, Board Effectiveness & Executive Remuneration), `business_ethics`
  (Business Ethics, Corporate Conduct, Anti-corruption, Audit), `tax_accounting` (Tax & Accounting Practices),
  `shareholder_rights` (Shareholder rights), `other` (Other).
- **ESG pillar:** `E`, `S`, `G` (one or more).
- **Engager role:** `bilateral`, `lead` (Lead, Co-Lead or equivalent), `active_support`, `passive_support`
  (Passive support, Signatory).
- **Objective type:** `transparency`, `operational`, `strategic`.
- **Receptiveness:** `very_good`, `good`, `neutral`, `insufficient`, `refusal` (Refusal/Blockage).
- **Objective status:** `initiated`, `in_progress`, `closed`, `abandoned`.
- **Result:** `deterioration`, `not_achieved`, `partially_achieved`, `achieved`, `abandoned`.
- **Influence level:** `1` (No influence), `2` (Not demonstrable), `3` (Probable), `4A` (Very likely, converging
  clues), `4B` (Very likely, convergent loop), `5` (Recognised).

## Data model

All tables live in the existing Postgres database. Timestamps are `timestamptz`. Every table has a primary key,
`source text not null` and `external_id text`, with a unique index on (`source`, `external_id`) and an index on
`company_id` where the table has one. `source` values: `api`, `excel`, `file_migration`, `app`, `mock_voice_seed`,
`npx_urth_demo`.

### Engagements

| Table | One row per | Columns besides pk, `source`, `external_id` |
|---|---|---|
| `stw_companies` | company with an engagement record (today's `EngagementRecord`) | `company_id` (pk), `name`, `sector`, `created_at`, `updated_at` |
| `stw_engagements` | engagement (today's `EngagementIssue`) | `engagement_id`, `company_id` fk, `theme` (free text, as today), `fir_theme`, `esg_pillars` text[], `rationale`, `engager_role`, `started_at`, `status`, `severity`, `trigger_source`, `source_detail`, `milestone_stage`, `escalation_stage`, `tags` text[] |
| `stw_objectives` | VOICE objective | `objective_id`, `engagement_id` fk, `description`, `objective_type`, `status`, `result`, `receptiveness`, `escalated` bool, `follows_objective_id` fk nullable, `started_at`, `target_date`, `closed_at`, `outcome`, `influence_level`, `influence_evidence`, `evidence_url` |
| `stw_activities` | activity (today's `CorrespondenceEntry`) | `activity_id`, `engagement_id` fk, `objective_id` fk nullable, `occurred_at`, `activity_type` (`email`, `letter`, `call`, `meeting`, `agm_intervention`, `resolution_filed`, `other`), `interaction_type` (E6, as today), `is_initiation` bool, `summary`, `doc_ref`, `logged_by` |
| `stw_commitments` | company commitment | today's `Commitment` fields, plus `engagement_id` fk and `objective_id` fk nullable |
| `stw_contacts` | company contact | today's `Contact` fields, plus `company_id` fk |
| `stw_transitions` | milestone or escalation change | `transition_id`, `engagement_id` fk, `kind` (`milestone`/`escalation`), `stage`, `changed_at`, `decided_by`, `reason` |
| `stw_events` | audit log entry | `event_id`, `company_id`, `event_type`, `detail` jsonb, `at` |

ESG pillars and role live on the engagement; an objective's Table 2 row reads them from there. The activity count
is a count of `stw_activities` for the objective, not a column.

`stw_events` gets one row for every store write that changes data, with today's event types from `events.jsonl`
plus `objective_added`, `objective_updated` and `intake_upserted` (`detail` = table, key, changed fields). A write
that changes nothing adds no event.

### Votes

| Table | One row per | Columns besides pk, `source`, `external_id` |
|---|---|---|
| `vote_meetings` | shareholder meeting | `meeting_id`, `company_id` (null when unmatched), `issuer_name`, `isin`, `cusip`, `meeting_date`, `meeting_type` |
| `vote_items` | ballot item | `item_id`, `meeting_id` fk, `item_number` (nullable: N-PX has none), `description`, `categories` text[], `proponent` (`issuer`/`shareholder`), `management_recommendation` |
| `vote_decisions` | one vote record on an item | `decision_id`, `item_id` fk, `vote`, `vote_label` (as filed), `against_management` bool nullable, `shares_voted`, `rationale`, `decided_by`, `decided_at`, `run_id` nullable |

`vote` is one of `for`, `against`, `abstain`, `withhold`, `do_not_vote`, `one_year`, `two_years`, `three_years`,
`other`. N-PX `how_voted` maps as: `FOR`→`for`, `AGAINST`→`against`, `ABSTAIN`→`abstain`, `WITHHOLD`→`withhold`,
`DO NOT VOTE`→`do_not_vote`, `ONE YEAR`/`1 YEAR`→`one_year`, `TWO YEARS`/`2 YEARS`→`two_years`,
`THREE YEARS`/`3 YEARS`→`three_years`, anything else→`other`. `vote_label` keeps the filed text.

`rationale` is required when `against_management` is true, for every source except `npx_urth_demo` (N-PX has none).

## Store and callers

- `PostgresEngagementStore` in `arp/storage/postgres_engagement_store.py`, with every public method of
  `EngagementStore`, the same arguments and the same return types (`EngagementRecord`), reading and writing the
  tables above. It adds `add_objective`, `update_objective` and `list_objectives`. Per-company writes take a
  Postgres advisory lock on the `company_id`, in place of `KeyedLock`.
- `EngagementIssue` gains optional fields `fir_theme`, `esg_pillars`, `rationale`, `engager_role` and
  `objectives: list[Objective]`, with defaults, so existing JSON still validates.
- Setting `engagement_store` (`file` | `postgres`), env `ARP_ENGAGEMENT_STORE`, **default `file`**. Switching it
  is the owner's step after `migrate-files` has run, so no install loses its records on screen. `api/deps.py`,
  `cli/_shared.py` and `portfolio/monthly_run.py` build the store through one new factory,
  `arp/storage/engagement_store_factory.py`, as `portfolio_store_factory.py` does for portfolios.
- `backend/scripts/e2e_stack.sh up` sets `ARP_ENGAGEMENT_STORE=postgres`, so holdout and evaluator rows run on the
  Postgres store.

## Intake

Both paths run the same validation and upsert code (`arp/stewardship/intake.py`).

**Report.** Every intake returns this JSON, status 200 when `rejected` is empty, else 422 with the same body and
nothing written:

```json
{"created": 0, "updated": 0, "unchanged": 0,
 "rejected": [{"sheet": "objectives", "row": 3, "field": "objective_type", "reason": "not one of transparency, operational, strategic"}]}
```

`created`, `updated` and `unchanged` count rows across all tables the batch touches, `stw_companies` included;
`stw_events` rows are never counted. For Excel, `row` is the
worksheet row number (header = row 1). For JSON, `sheet` is the batch key and `row` the 1-based index in it.

**Endpoints and CLI.**

- `POST /api/stewardship/intake/engagements` and `POST /api/stewardship/intake/votes`: JSON batches.
- `POST /api/stewardship/intake/engagements.xlsx` and `POST /api/stewardship/intake/votes.xlsx`: multipart upload.
- `arp stewardship intake <file> --kind engagements|votes`: the Excel path from the command line. It prints the
  report as one line, `created N, updated N, unchanged N, rejected N`, and exits 1 when anything is rejected.
- `GET /api/stewardship/intake/template?kind=engagements|votes`: an empty workbook with the sheets below and a
  `lists` sheet of the allowed values from "VOICE option lists" and the `vote` values.

**Engagement batch** (JSON keys = sheet names, field names = column headers, in this order):

- `engagements`: `external_id`, `company_id`, `isin`, `company_name`, `theme`, `fir_theme`, `esg_pillars`
  (`;`-separated in Excel), `rationale`, `engager_role`, `started_at`, `status`, `severity`
- `objectives`: `external_id`, `engagement_external_id`, `follows_external_id`, `description`, `objective_type`,
  `status`, `result`, `receptiveness`, `escalated`, `started_at`, `target_date`, `closed_at`, `outcome`,
  `influence_level`, `influence_evidence`, `evidence_url`
- `activities`: `external_id`, `engagement_external_id`, `objective_external_id`, `occurred_at`, `activity_type`,
  `interaction_type`, `is_initiation`, `summary`, `doc_ref`, `logged_by`

**Vote batch** (one sheet or key `votes`, one row per decision): `external_id`, `company_id`, `isin`, `cusip`,
`issuer_name`, `meeting_date`, `meeting_type`, `item_number`, `description`, `categories`, `proponent`,
`management_recommendation`, `vote`, `shares_voted`, `rationale`, `decided_by`, `decided_at`, `run_id`. Meetings and
items are found or created from (`company_id` or `isin` or `cusip`, `meeting_date`) and (meeting, `item_number`).
A vote row must carry `external_id`, `meeting_date`, `item_number`, `vote`, and at least one of `company_id`, `isin`
or `cusip`; a row missing any of them is rejected with one `rejected` entry per missing field, `reason` `required`
(a row with none of the three identifiers gets one entry, `field` `company_id`, `reason`
`one of company_id, isin, cusip required`). A field is missing when its key is absent, null, or empty after trimming
whitespace (an empty cell in Excel). Each failed check, the rationale rule included, adds its own entry; the rationale
rule runs only when `vote` is present. A row whose only issuer identifier is a `company_id` that matches no company
is rejected with one entry, `field` `company_id`, `reason` `unknown company`. These rules apply to intake only, not to
`load-npx`.

**Rules.**

- An engagement matches its company by `company_id`, else by `isin` through the registry. If neither matches it is
  rejected with reason `unknown company`. A company matched by `company_id` or ISIN that has no `stw_companies`
  row gets one, named from `company_name`.
- Vote intake derives `against_management`: true when `vote` is `against` or `withhold` and
  `management_recommendation` is `for`, or `vote` is `for` and the recommendation is `against`; false when `vote`
  equals the recommendation; null when the recommendation is empty or `vote` is `abstain`, `do_not_vote`, `other`
  or a frequency value.
- A vote row that carries `isin` or `cusip` and whose company matches nothing is stored with `company_id` null.
- `source` is `api` for JSON and `excel` for uploads. The upsert key is (`source`, `external_id`). A row whose
  values equal the stored row counts as `unchanged` and writes nothing, events included.

## Migration

`arp stewardship migrate-files [--dry-run]` reads every `engagements/*/record.json` and `events.jsonl` and writes
companies, engagements, activities, commitments, contacts, transitions and events with `source = 'file_migration'`
and the file's ids as `external_id`. It prints one line, `created N, updated N, unchanged N` (counted over those
seven tables). `--dry-run` prints `would create N` and writes nothing. It is idempotent. It writes no events of its own: the
only `stw_events` rows it creates are the ones migrated from `events.jsonl`. The file directory is
left in place. Migrated engagements have no objectives; they count as "not yet a VOICE engagement" until one is
added.

## Demo data

PR 3 starts after `arp showcase load` from `showcase-portfolio-data` is merged; that command registers the MSCI
World companies and puts them in the house portfolios, so `house_universe()` includes them.

`arp stewardship seed-demo [--companies 400] [--seed 7]`:

1. **Companies:** in `data/holdings/MSCI_World.xlsx` (header on worksheet row 4), rows with
   `Type of Security` = `Aktien`, sorted by `Weighting` descending, first 400 distinct ISINs, keyed `isin_<ISIN>`.
   If **any** of the 400 is not in the registry, it exits 1, prints `run arp showcase load first` to stderr and
   writes nothing.
2. **Engagements and objectives:** one engagement per company and FIR theme; 3–5 objectives per company; a
   follow-up objective sits under the same engagement as the objective it follows, with a later `started_at`.
   About a third are follow-ups. Every objective fills every Table 2 field: description, type, receptiveness,
   escalated, status, result, `started_at`, 1–8 activities with dates (one marked `is_initiation`), and, when
   closed, `closed_at`, `outcome`, `influence_level` and `influence_evidence`. Themes follow the company's sector
   (Energy leans to `climate_mitigation`, Financials to `governance_board_pay`, and so on). Closed objectives get
   influence levels in roughly this mix: `1` 30 %, `2` 30 %, `3` 25 %, `4A`/`4B` 12 %, `5` 3 %.
   `passive_support` objectives never get `4A`, `4B` or `5`. All rows: `source = 'mock_voice_seed'`.
3. **Re-running:** the same seed is idempotent. A different `--seed` deletes every `mock_voice_seed` row first and
   writes the new set. No other source is touched.
4. **Votes:** `arp stewardship load-npx data/voting/npx_urth/` loads the three committed N-PX CSVs
   (`source = 'npx_urth_demo'`):

   | Period ending | Accession | CSV rows | Decisions (non-empty vote) | Items | Meetings |
   |---|---|---|---|---|---|
   | 2024-06-30 | 0001021408-24-004974 | 22,026 | 21,781 | 21,985 | 1,500 |
   | 2025-06-30 | 0001438934-25-002318 | 19,586 | 17,566 | 19,557 | 1,273 |
   | 2026-06-30 | 0001438934-26-002287 | 20,529 | 20,439 | 20,422 | 1,358 |
   | **Total** | | 62,141 | **59,786** | 61,964 | 4,131 |

   - Meeting key: (`accession`, `cusip`, `meeting_date`). Item key: meeting + `vote_description`. Rows with the same
     item key (split votes, or repeated agenda text) share one item and each keep their own decision.
   - Decision `external_id`: `<csv file name>:<line number>`, so fully identical rows stay separate decisions.
   - A row with an empty `how_voted` creates its item and no decision.
   - `against_management` comes from the CSV's `for_against_management` (`AGAINST`→true, `FOR`→false, empty→null).
     That column was derived by the fetch script, not filed by SEC; see `data/voting/npx_urth/README.md`.
   - Numbers are normalised (`508531.000000`→`508531`); labels are kept as filed in `vote_label`.
   - Companies are matched by `isin`, else by `cusip` through the registry; the rest stay unmatched.
   - The fetch script that produced the CSVs is added as `data/voting/npx_urth/fetch_npx.py`, next to them, for
     refreshes. Loading never fetches.

## Monitoring

`stewardship/process.vote_items()` returns the run votes (as today) plus ledger decisions, in the same row shape
(`company_id`, `meeting_date` as an ISO `YYYY-MM-DD` string, `vote`, `against_management` with null mapped to
`false`, `overrode_policy = false`). `voting_feed.issuer_fields` stays unchanged. Rules:

- Only ledger decisions whose meeting falls within `vote_monitoring_window_days` (setting, default 365) before the
  newest `meeting_date` in the ledger count. With the demo data that is the 2025–26 proxy year, so 2024 votes alone
  raise nothing.
- A ledger decision with a `run_id` and the same (`run_id`, `company_id`, `item_number` = `proposal_number`) as a
  run vote replaces that run row, so the vote counts once.
- Decisions with `against_management` null count in `vote.decided`, not in `vote.against_management`.

The house rule `vote_against_management` (`vote.against_management > 0`) is unchanged and shows up in
`GET /api/stewardship/studio/monitoring/triggers`.

## UI

The issue panel on `#/engagement` (`frontend/src/components/EngagementIssuePanel.tsx`) lists the issue's
objectives: description, type, status, result. Each row from `mock_voice_seed` or `npx_urth_demo` shows the label
`Demo data`. `e2e_stack.sh up` seeds no stewardship data; the evaluator runs
`arp showcase load && arp stewardship seed-demo --companies 20` itself before checking AC-30.

## Left to the builder

- Index choices beyond those named above.
- Exact mock wording (rationales, outcomes, evidence). Plain and realistic; it must pass the E8 style check.
- PR split, in this order: (1) tables, store, factory and migration; (2) intake API, Excel, CLI and template;
  (3) seeding, N-PX load, monitoring read and the UI list. Each PR leaves the app working.

## Acceptance

All holdout rows run on the e2e stack with `ARP_ENGAGEMENT_STORE=postgres`. Each holdout test truncates the `stw_*`
and `vote_*` tables first, unless the row says otherwise.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | An empty Postgres database | `arp db init-postgres` runs twice | Both runs exit 0, and the tables `stw_companies`, `stw_engagements`, `stw_objectives`, `stw_activities`, `stw_commitments`, `stw_contacts`, `stw_transitions`, `stw_events`, `vote_meetings`, `vote_items`, `vote_decisions` exist | holdout |
| AC-2 | AC-1 done once | `arp db init-postgres` runs again | Every table's column list and row count are the same as before the run | holdout |
| AC-3 | The same calls made on a file store and on a Postgres store | `GET /api/engagement/records`, `GET /api/engagement/records/{id}`, `POST .../issues`, `POST .../escalate` | Responses are equal apart from generated ids and timestamps | unit |
| AC-4 | The e2e stack | `POST /api/engagement/records`, then `POST /api/engagement/records/{id}/issues`, then `GET /api/engagement/records/{id}` | The GET returns the record with 1 issue, with the posted theme and severity | holdout |
| AC-5 | A file store with 3 companies, 5 issues, 7 correspondence entries, 2 commitments, 0 contacts, 4 transitions, 9 events | `arp stewardship migrate-files` runs | It prints `created 30, updated 0, unchanged 0` | holdout |
| AC-6 | AC-5 done | `migrate-files` runs again | It prints `created 0, updated 0, unchanged 30` | holdout |
| AC-7 | The file store from AC-5 | `arp stewardship migrate-files --dry-run` runs | It prints `would create 30`, and `stw_engagements` holds 0 rows | holdout |
| AC-8 | Two companies created through `POST /api/engagement/records`, and a workbook with 2 engagements (one per company), 3 objectives, 5 activities | It is uploaded to `POST /api/stewardship/intake/engagements.xlsx` | Status 200, body `{"created": 10, "updated": 0, "unchanged": 0, "rejected": []}` (10 = 2 + 3 + 5; the companies already exist) | holdout |
| AC-9 | AC-8 done | The same workbook is uploaded again | Status 200, body `{"created": 0, "updated": 0, "unchanged": 10, "rejected": []}` | holdout |
| AC-10 | AC-8 done | The same workbook is uploaded again | `stw_events` row count is the same as before the upload | holdout |
| AC-11 | AC-8 done | The workbook is uploaded with one activity's `summary` changed | Status 200, body has `"updated": 1, "unchanged": 9` | holdout |
| AC-12 | A workbook whose `objectives` sheet has `objective_type = ambitious` on worksheet row 3 | It is uploaded | Status 422; `rejected` holds exactly one entry with `sheet` `objectives`, `row` 3, `field` `objective_type` | holdout |
| AC-13 | The workbook from AC-12 | It is uploaded | `stw_engagements`, `stw_objectives` and `stw_activities` hold 0 rows | holdout |
| AC-14 | A JSON engagement batch with 1 engagement whose `company_id` and `isin` match nothing | It is posted to `POST /api/stewardship/intake/engagements` | Status 422; `rejected` holds one entry with `sheet` `engagements`, `row` 1, `reason` `unknown company` | holdout |
| AC-15 | A company created through `POST /api/engagement/records`, and a valid JSON engagement batch with 1 engagement for it and 1 objective | It is posted | Status 200, body `{"created": 2, "updated": 0, "unchanged": 0, "rejected": []}` | holdout |
| AC-16 | A JSON vote batch with one row that is valid except for its rationale: `external_id`, `isin`, `meeting_date`, `item_number`, `vote` `against`, `management_recommendation` `for`, empty `rationale` | It is posted to `POST /api/stewardship/intake/votes` | Status 422; `rejected` holds exactly one entry, with `field` `rationale` and `reason` `rationale required when voting against management` | holdout |
| AC-17 | A votes workbook with 3 valid rows at one new meeting, `item_number` 1, 2 and 3 | It is uploaded to `POST /api/stewardship/intake/votes.xlsx` | Status 200, body `{"created": 7, "updated": 0, "unchanged": 0, "rejected": []}` (1 meeting + 3 items + 3 decisions) | holdout |
| AC-18 | The workbook from AC-8 saved to disk | `arp stewardship intake <file> --kind engagements` runs | It exits 0 and prints `created 10, updated 0, unchanged 0, rejected 0` | holdout |
| AC-19 | A `viewer` user (non-dev auth) | `POST /api/stewardship/intake/engagements` | Status 403 | unit |
| AC-20 | — | `GET /api/stewardship/intake/template?kind=engagements` is opened in openpyxl | Sheets are `engagements`, `objectives`, `activities`, `lists`; each data sheet's header row equals that sheet's field list under "Engagement batch", in order | holdout |
| AC-21 | — | `GET /api/stewardship/intake/template?kind=votes` is opened in openpyxl | Sheets are `votes`, `lists`; the `votes` header row equals the "Vote batch" field list, in order | holdout |
| AC-22 | — | The `lists` sheet of the engagements template is read | Its `fir_theme` column holds the 15 values listed under "VOICE option lists", in that order | holdout |
| AC-23 | Showcase companies loaded | `arp stewardship seed-demo --seed 7` runs | Exactly 400 distinct `company_id` have rows in `stw_engagements` with `source` `mock_voice_seed`, and each has 3, 4 or 5 objectives | holdout |
| AC-24 | AC-23 done | Closed objectives are read | None has a null `result`, `closed_at`, `outcome` or `influence_level` | holdout |
| AC-25 | AC-23 done | Objectives are read | 25–45 % have `follows_objective_id` set; each points to an objective in the same engagement with an earlier `started_at` | holdout |
| AC-26 | AC-23 done | Objectives under engagements with `engager_role` `passive_support` are read | None has `influence_level` `4A`, `4B` or `5` | holdout |
| AC-27 | `ARP_ENGAGEMENT_STORE=postgres`, a file `engagements/<id>/record.json` present, and the same company created through `POST /api/engagement/records` | `POST /api/engagement/records/{id}/issues` | Status 200, and the file's bytes are unchanged | holdout |
| AC-28 | A database with rows in legacy `engagement_issues` and `engagement_commitments` | `arp db init-postgres` runs | Both tables exist with the same row counts | holdout |
| AC-29 | AC-23 done | `seed-demo --seed 7` runs again | Row counts of every `stw_*` table are unchanged | holdout |
| AC-30 | Seeded data on the e2e stack | A user opens `#/engagement` and a seeded company's issue | Each objective shows description, type, status and result, and the label `Demo data` | evaluator |
| AC-31 | Showcase companies not loaded | `seed-demo` runs | Exit code 1; stderr is `run arp showcase load first` | unit |
| AC-32 | AC-31 | — | 0 rows with `source` `mock_voice_seed` exist | unit |
| AC-33 | A fixture CSV: 3 meetings, 10 distinct items; 8 items with one vote record (2 of them `AGAINST` with `for_against_management` `AGAINST`), 1 item with 2 records (`FOR`/`FOR`, management `FOR`), 1 item with an empty vote | `arp stewardship load-npx <dir>` runs | `vote_meetings` holds 3 rows, `vote_items` 10, `vote_decisions` 10 | holdout |
| AC-34 | AC-33 done | `vote_decisions` is read | Exactly 2 rows have `against_management` true, and the empty-vote item has no decision | holdout |
| AC-35 | The committed CSVs in `data/voting/npx_urth/` | `load-npx` runs | `select count(*) from vote_decisions where source = 'npx_urth_demo'` = 59,786 and `vote_items` = 61,964 | holdout |
| AC-36 | AC-35 done | `load-npx` runs again | Both counts are unchanged | holdout |
| AC-37 | AC-35 done | Rows with `vote_label` `ONE YEAR` or `1 YEAR` are read | All 122 have `vote` `one_year` | holdout |
| AC-38 | The AC-33 fixture with meeting dates in the newest year, one meeting's ISIN registered and in the house universe, default monitoring rules | `GET /api/stewardship/studio/monitoring/triggers` | That company has exactly one trigger with `type` `vote_outcome` and `rule` `vote_against_management` | holdout |
| AC-39 | A ledger whose only against-management decision for a company is more than 365 days before the newest `meeting_date` | `GET /api/stewardship/studio/monitoring/triggers` | No `vote_against_management` trigger for that company | holdout |
| AC-40 | A `proxy_voting` run with one decided vote, and a ledger decision with the same `run_id`, `company_id` and `item_number` | The company's fields are read (`load_sample`) | `vote.decided` = 1 | unit |
| AC-41 | `ARP_ENGAGEMENT_STORE` unset | The backend test suite runs | The file store is used, and the existing engagement and stewardship tests pass unchanged | unit |

Must not change: the existing `/api/engagement` routes and their responses (AC-3, AC-4, AC-41); stewardship stage
outputs on the file store (AC-41); the legacy engagement tables (AC-28); the house monitoring rules (AC-38 uses the
defaults).
