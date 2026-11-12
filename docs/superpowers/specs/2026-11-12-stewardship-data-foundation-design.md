# Stewardship data foundation: engagements (VOICE) and votes in Postgres

Slug: `stewardship-data-foundation`. Risk: high (new system of record for engagements, a data migration,
an API contract change).

Status: **draft, waiting for the owner's approval.**

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

This spec builds only the foundation: tables, the store, intake, migration and demo data. Influence grading,
VOICE reporting and dashboards come in later specs (see Non-goals).

## Goals

1. Postgres tables for engagements in the VOICE shape, plus a vote ledger.
2. `PostgresEngagementStore`: the same public methods as `EngagementStore`, so every caller (stewardship stages,
   orchestrator, API, monthly run) keeps working unchanged, chosen by a setting.
3. Intake by API (JSON batch) and by Excel upload, for engagements and for votes. Intake is idempotent: loading
   the same file twice changes nothing.
4. A one-time migration of today's file records into Postgres.
5. Demo data: 400 MSCI World companies with mock VOICE objectives, and URTH N-PX votes for three years.
6. Monitoring reads votes against management from the ledger, so the existing `vote_outcome` trigger runs on
   real ballots.

## Non-goals (later specs)

- The influence decision tree, the categorisation grid and governance validation (VOICE plan phase 2).
- The VOICE Table 2 report, its export and Superset dashboards (phase 3).
- The RFP resources questionnaire (phase 4).
- Semantic search over notes, the annotated performance timeline, cohort analysis.
- Multi-tenancy, a new login provider, a Next.js/Tailwind/Tremor frontend.
- Casting votes or any proxy-platform integration.
- Mocked ESG data: it comes from the approved `showcase-portfolio-data` spec. This spec uses that dataset and
  creates none of its own.

## Anti-goals

- Mock data that could be mistaken for real engagement. Every mock row carries `source = 'mock_voice_seed'`, and
  every vote loaded from N-PX carries `source = 'npx_urth_demo'`. Both labels are shown wherever those rows appear.
- Two copies of the truth. After migration the file store is read-only history, and the app reads Postgres only.
- Changing or weakening the VOICE definitions or grids. Field values use VOICE's own option lists.
- Dropping or rewriting existing tables. `engagement_issues` and `engagement_commitments` are legacy and stay.

## Constraints

- Schema changes go through `arp/storage/postgres_schema.py` (`ensure_schema`: `create_all`, additive columns,
  recorded steps). No Alembic, nothing is dropped.
- Company keys are the registry's `company_id`. For holdings this is `isin_<ISIN>`, as in `showcase-portfolio-data`.
- Request and response models change, so `scripts/export_openapi.py` and `npm run gen:api` run and both generated
  files are committed.
- `openpyxl` (already a dependency) reads the Excel files. No new dependencies.
- The Stop hook and CI checks in `.claude/CLAUDE.md` apply.

## Approaches considered

1. **Postgres as the only store, behind today's store interface (picked).** Normal tables, plus a
   `PostgresEngagementStore` with the same methods. Files are migrated once. One source of truth; reporting and
   Superset query the tables. The largest first PR.
2. Postgres as an import and reporting copy, synced into the files. A smaller first step, but two truths that drift.
3. One JSONB document per company. The fastest migration, but cross-company VOICE and vote queries become awkward.

## Data model

All tables live in the existing Postgres database. Timestamps are `timestamptz`. Every table has
`source text not null` (e.g. `api`, `excel`, `file_migration`, `mock_voice_seed`, `npx_urth_demo`), and intake
tables have `external_id text` for idempotent upserts.

### Engagements (VOICE)

| Table | One row per | Key columns |
|---|---|---|
| `stw_engagements` | engagement (today's `EngagementIssue`) | `engagement_id` pk, `company_id`, `theme` (free text, as today), `fir_theme` (one of the 15 FIR themes, nullable), `esg_pillars` text[] (`E`/`S`/`G`), `rationale`, `engager_role` (`bilateral`, `lead`, `active_support`, `passive_support`), `started_at`, `status`, `severity`, `trigger_source`, `source_detail`, `milestone_stage`, `escalation_stage`, `tags` text[], `source`, `external_id` |
| `stw_objectives` | VOICE objective | `objective_id` pk, `engagement_id` fk, `description`, `objective_type` (`transparency`, `operational`, `strategic`), `status` (`initiated`, `in_progress`, `closed`, `abandoned`), `result` (`deterioration`, `not_achieved`, `partially_achieved`, `achieved`, `abandoned`, nullable), `receptiveness` (`very_good`, `good`, `neutral`, `insufficient`, `refusal`, nullable), `follows_objective_id` fk nullable (a follow-up of an earlier objective), `target_date`, `closed_at`, `outcome`, `influence_level` (`1`, `2`, `3`, `4A`, `4B`, `5`, nullable: recorded, not computed here), `influence_evidence`, `evidence_url`, `source`, `external_id` |
| `stw_activities` | activity (today's `CorrespondenceEntry`) | `activity_id` pk, `engagement_id` fk, `objective_id` fk nullable, `occurred_at`, `activity_type` (`email`, `letter`, `call`, `meeting`, `agm_intervention`, `resolution_filed`, `other`), `interaction_type` (E6, as today), `is_initiation` bool, `summary`, `doc_ref`, `logged_by`, `source`, `external_id` |
| `stw_commitments` | company commitment | as today's `Commitment`, plus `engagement_id` fk and `objective_id` fk nullable |
| `stw_contacts` | company contact | as today's `Contact`, plus `company_id` |
| `stw_transitions` | milestone or escalation change | `engagement_id`, `kind` (`milestone`/`escalation`), `stage`, `changed_at`, `decided_by`, `reason` |
| `stw_events` | audit log entry | as today's `events.jsonl`: `company_id`, `event_type`, `detail` jsonb, `at` |

`stw_` is a new prefix, so nothing collides with the legacy `engagement_*` tables.

### Votes

| Table | One row per | Key columns |
|---|---|---|
| `vote_meetings` | shareholder meeting | `meeting_id` pk, `company_id` (nullable when unresolved), `issuer_name`, `isin`, `cusip`, `meeting_date`, `meeting_type`, `source`, `external_id` |
| `vote_items` | ballot item | `item_id` pk, `meeting_id` fk, `item_number`, `description`, `categories` text[], `proponent` (`issuer`/`shareholder`), `management_recommendation` |
| `vote_decisions` | our vote on an item | `decision_id` pk, `item_id` fk, `vote` (`for`, `against`, `abstain`, `withhold`, `do_not_vote`), `against_management` bool, `shares_voted`, `rationale` (required when `against_management` is true and `source` is not `npx_urth_demo`), `decided_by`, `decided_at`, `run_id` nullable (a `proxy_voting` run), `source`, `external_id` |

N-PX rows hold no rationale, so the rationale rule applies to API, Excel and app votes only.

## Store and callers

- `PostgresEngagementStore` in `arp/storage/postgres_engagement_store.py`. It has every public method of
  `EngagementStore`, with the same arguments and return types (`EngagementRecord`), reading and writing the tables
  above. It also adds `add_objective`, `update_objective` and `list_objectives`, which the API exposes.
- `EngagementRecord` and `EngagementIssue` gain optional VOICE fields (`fir_theme`, `esg_pillars`, `rationale`,
  `engager_role`, `objectives: list[Objective]`). With defaults, so existing JSON still validates.
- A setting `engagement_store` (`file` | `postgres`) picks the store. `api/deps.py`, `cli/_shared.py` and
  `portfolio/monthly_run.py` build the store through one factory, the way `portfolio_store_factory.py` does for
  portfolios. Default: `postgres` when `ARP_POSTGRES_DSN` is set, else `file`, so tests without Postgres still run.
- `stewardship/voting_feed.issuer_fields()` also reads `vote_decisions`. A company's `vote.*` fields count ledger
  votes plus run votes, and a vote is never counted twice: a ledger row with a `run_id` replaces the run's row.

## Intake

Both paths run the same validation and upsert code (`arp/stewardship/intake.py`) and return the same report:
rows created, rows updated, rows unchanged, and rows rejected (row number, field, reason). A batch with any
rejected row writes nothing.

- **API:** `POST /api/stewardship/intake/engagements` and `POST /api/stewardship/intake/votes`. Body: a JSON
  batch in the shapes above. Role: `analyst` or above (same as other writes).
- **Excel:** `POST /api/stewardship/intake/engagements.xlsx` and `.../votes.xlsx` (multipart upload), and
  CLI `arp stewardship intake <file> --kind engagements|votes`.
  - Engagement workbook: sheets `engagements`, `objectives`, `activities`. Column names are the table columns
    above, linked by `external_id`.
  - Vote workbook: one sheet `votes`, one row per item and decision.
  - `GET /api/stewardship/intake/template?kind=engagements|votes` returns an empty workbook with these sheets,
    headers and a `lists` sheet of allowed values.
- **Matching companies:** by `company_id`, else by ISIN through the registry. Unmatched votes are stored with
  `company_id` null. Unmatched engagements are rejected, because an engagement must belong to a company.
- **Idempotency:** the upsert key is (`source`, `external_id`). A row whose values match the stored row is
  counted as unchanged and writes no event.

## Migration

`arp stewardship migrate-files [--dry-run]` reads every `engagements/*/record.json` and `events.jsonl` and writes
them with `source = 'file_migration'` and `external_id = <issue_id>` (etc.). It is idempotent. `--dry-run`
prints counts only. The file directory is left in place and no longer written once the setting is `postgres`.
Migrated issues have no objectives. They count as "not yet a VOICE engagement" until an objective is added.

## Demo data

`arp stewardship seed-demo [--companies 400] [--seed 7]`, deterministic for a given seed:

1. **Companies:** the first 400 equity rows of `data/holdings/MSCI_World.xlsx` by weight, keyed `isin_<ISIN>`.
   The seeder needs those companies in the registry, which `arp showcase load` (from `showcase-portfolio-data`)
   creates. If they are missing, it stops with the message `run arp showcase load first`.
2. **Engagements and objectives:** 3–5 objectives per company, `source = 'mock_voice_seed'`. Each objective has
   every VOICE Table 2 field filled: FIR theme, pillar, rationale, start date, role, description, type,
   receptiveness, escalation flag, status, result, activity count (1–8 activities with dates), closure date,
   outcome, influence level, evidence. About a third are follow-ups (`follows_objective_id` set to an earlier
   objective on the same company and theme). Themes follow the company's sector (e.g. Energy leans to Climate
   Mitigation). Closed objectives get influence levels in roughly this mix: 1: 30 %, 2: 30 %, 3: 25 %,
   4A/4B: 12 %, 5: 3 %. Passive-support objectives never get 4 or 5.
3. **Votes:** `arp stewardship load-npx data/voting/npx_urth/` loads the three N-PX CSVs into the vote ledger
   with `source = 'npx_urth_demo'`. Meetings are matched to companies by ISIN, else by CUSIP through the registry;
   the rest stay unmatched.

   The CSVs are already fetched (12 Nov 2026) and documented in `data/voting/npx_urth/README.md`:

   | Period ending | Accession | Rows | Issuers | Against management |
   |---|---|---|---|---|
   | 2024-06-30 | 0001021408-24-004974 | 22,026 | 1,445 | 3.83 % |
   | 2025-06-30 | 0001438934-25-002318 | 19,586 | 1,221 | 4.16 % |
   | 2026-06-30 | 0001438934-26-002287 | 20,529 | 1,287 | 3.35 % |

   What the loader must handle:
   - One CSV row is one vote record. A split vote (part for, part against) gives several rows for one item. Each
     row becomes one `vote_decisions` row, and the item is stored once.
   - Rows with an empty vote (245, 2,020 and 90 by year) are items without a decision: store the item, no decision.
   - `for_against_management` was derived by the fetch script, not filed by SEC. It is empty when management made
     no recommendation and for say-on-pay frequency votes. Empty means `against_management` is null.
   - Number formats and labels differ by year (`508531.000000` against `508531`, `ONE YEAR` against `1 YEAR`):
     normalise numbers and keep labels as filed.
   - The CSVs (14.6 MB, public SEC data) are committed so every session can seed without network access; the
     fetch script is committed as `backend/scripts/fetch_npx.py` beside them for refreshes.

## Monitoring

With demo data loaded, `stewardship/monitoring.evaluate` gets each MSCI World company's `vote.*` fields from the
ledger and its ESG fields from the showcase dataset. The house rules are unchanged. A vote against management in
the latest N-PX year raises a `vote_outcome` trigger, as it already does for run votes.

## Left to the builder

- Indexes beyond primary keys (at least `company_id` on every table, and (`source`, `external_id`) unique).
- How `PostgresEngagementStore` locks per company (a row lock or advisory lock in place of `KeyedLock`).
- Exact mock wording (rationales, outcomes, evidence). Keep it plain and realistic, and pass the E8 style check.
- PR split. Suggested order: (1) tables, store and migration; (2) intake API, Excel and template; (3) seeding,
  N-PX load and the monitoring read. Each PR leaves the app working.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | An empty Postgres database | `arp db init-postgres` runs | The tables `stw_engagements`, `stw_objectives`, `stw_activities`, `stw_commitments`, `stw_contacts`, `stw_transitions`, `stw_events`, `vote_meetings`, `vote_items`, `vote_decisions` exist; running it a second time prints no error and changes no table | holdout |
| AC-2 | `engagement_store = postgres` and a company with one open issue | Each public method of `EngagementStore` is called with the same arguments on both stores | Both return `EngagementRecord`s that are equal apart from generated ids and timestamps | holdout |
| AC-3 | A file store with 3 companies, 5 issues, 7 correspondence entries, 2 commitments | `arp stewardship migrate-files` runs twice | After both runs Postgres holds 3 companies, 5 engagements, 7 activities, 2 commitments; the second run prints `created 0, updated 0, unchanged 17` | holdout |
| AC-4 | The same file store | `arp stewardship migrate-files --dry-run` runs | It prints the counts and Postgres holds 0 engagement rows | holdout |
| AC-5 | A valid engagements workbook with 2 engagements, 3 objectives, 5 activities | It is uploaded to `POST /api/stewardship/intake/engagements.xlsx` | Response 200 with `{"created": 10, "updated": 0, "unchanged": 0, "rejected": []}` | holdout |
| AC-6 | The workbook from AC-5 already loaded | It is uploaded again | Response 200 with `created 0, updated 0, unchanged 10`, and no new rows in `stw_events` | holdout |
| AC-7 | A workbook in which row 3 of `objectives` has `objective_type = "ambitious"` | It is uploaded | Response 422; `rejected` holds `{"sheet": "objectives", "row": 3, "field": "objective_type"}`; no rows from this workbook are stored | holdout |
| AC-8 | An engagement row whose company matches neither `company_id` nor ISIN | It is posted to the JSON intake | It is rejected with reason `unknown company`; nothing is stored | holdout |
| AC-9 | A vote row with `against_management = true`, `source = excel` and an empty `rationale` | It is posted | It is rejected with reason `rationale required when voting against management` | holdout |
| AC-10 | `GET /api/stewardship/intake/template?kind=engagements` | It is opened in openpyxl | It has sheets `engagements`, `objectives`, `activities`, `lists`, and the header row of each data sheet equals the column list in this spec | holdout |
| AC-11 | Showcase companies loaded | `arp stewardship seed-demo --seed 7` runs | 400 companies have engagements; every company has 3–5 objectives; every objective has `source = mock_voice_seed`; every closed objective has a non-null `result`, `closed_at`, `outcome` and `influence_level` | holdout |
| AC-12 | The seed from AC-11 | The objectives are counted | At least 25 % and at most 45 % have `follows_objective_id` set, and every such id points to an objective of the same company with an earlier `started_at` | holdout |
| AC-13 | The seed from AC-11 | Objectives with `engager_role = passive_support` are listed | None has `influence_level` `4A`, `4B` or `5` | holdout |
| AC-14 | The seed from AC-11 | `seed-demo --seed 7` runs again | Row counts are unchanged | holdout |
| AC-15 | Showcase companies not loaded | `seed-demo` runs | It exits non-zero and prints `run arp showcase load first`; no rows are written | holdout |
| AC-16 | A fixture N-PX CSV with 3 meetings and 10 items: 8 items with one vote record (2 of them against management), 1 split item with 2 vote records, 1 item with an empty vote | `arp stewardship load-npx <dir>` runs | `vote_items` holds 10 rows; `vote_decisions` holds 10 rows with `source = npx_urth_demo`, 2 of them with `against_management = true`; the empty-vote item has no decision | holdout |
| AC-21 | The real CSVs in `data/voting/npx_urth/` | `load-npx` runs, then runs again | After the first run `vote_decisions` holds one row per non-empty vote row in the three CSVs; the second run adds no rows | holdout |
| AC-17 | The fixture from AC-16 loaded, one meeting's ISIN in the registry | `monitoring.evaluate` runs on that company | Its `vote.*` fields show 2 votes against management, and a `vote_outcome` trigger is raised for it | holdout |
| AC-18 | A `proxy_voting` run whose decided vote is also in `vote_decisions` with the same `run_id` | `voting_feed.issuer_fields` runs | That vote is counted once | holdout |
| AC-19 | The engagement panel for a seeded company | A user opens it in the app | Each objective shows its description, type, status and result, and a `Demo data` label | evaluator |
| AC-20 | No `ARP_POSTGRES_DSN` set | The backend test suite runs | The file store is used and the existing engagement tests pass unchanged | unit |

Must not change: the stewardship stage outputs for file-store data (AC-20); the existing engagement API routes and
their responses (covered by the existing tests, which stay unchanged); the legacy `engagement_issues` and
`engagement_commitments` tables (AC-1 checks only additions).
