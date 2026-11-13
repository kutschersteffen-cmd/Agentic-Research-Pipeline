# Stewardship Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move StewardIQ engagements (VOICE shape) and a proxy-vote ledger into Postgres, with API/Excel intake, a file migration, demo data and the monitoring read.

**Architecture:** New SQLAlchemy models in `postgres_models.py` (created by `ensure_schema`), a `PostgresEngagementStore` with the file store's public interface, chosen by a setting through a factory. Intake is one validation/upsert module shared by JSON, Excel and CLI. Demo data and N-PX votes are CLI loaders; the ledger feeds `process.vote_items()`.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, Postgres 16, openpyxl, Typer; React + Vite frontend.

**Spec:** `docs/superpowers/specs/2026-11-12-stewardship-data-foundation-design.md` (approved 12 Nov 2026). Acceptance IDs below (AC-n) refer to its table. Read the spec's "VOICE option lists", "Data model" and "Intake" sections before any task: the plan does not repeat them.

## Global Constraints

- Schema via `arp/storage/postgres_schema.py` `ensure_schema` only; no Alembic; nothing dropped. Legacy `engagement_issues`, `engagement_commitments` untouched.
- Every new table: pk, `source text not null`, `external_id text`, unique (`source`, `external_id`), index on `company_id` where present.
- `source` values: `api`, `excel`, `file_migration`, `app`, `mock_voice_seed`, `npx_urth_demo`.
- Setting `engagement_store: Literal["file", "postgres"] = "file"`, env `ARP_ENGAGEMENT_STORE`.
- Setting `vote_monitoring_window_days: int = 365`.
- No new dependencies. Excel via `openpyxl==3.1.5` (already pinned).
- Writes need `analyst`, reads `viewer` (router-level `authorize`, as other `/api/stewardship` routes).
- After request/response model changes: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`; commit both generated files; add `frontend/src/api/contract.ts` lines for new `request<T>()` calls.
- Never weaken an existing test. List every test change in the PR description.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; Postgres tests need `ARP_TEST_POSTGRES_DSN` (`bash .claude/hooks/ensure-deps.sh postgres`).
- PR order: PR 1 = Tasks 1–6, PR 2 = Tasks 7–10, PR 3 = Tasks 11–14. PR 3 starts only after `arp showcase load` (spec `showcase-portfolio-data`) is on `main`.
- Each PR body says `Spec: stewardship-data-foundation` and carries the `risk:high` label (steward skill).

## Review Focus

1. **Excel cells typed by Excel, not by us:** dates arrive as `datetime`, booleans as `TRUE`/`1`, numbers as floats (`1.0` for an `item_number`). Intake must accept them as the same value as the text form, else re-uploads of an Excel-saved file report `updated` instead of `unchanged`. Test in Task 8.
2. **Messy identifiers:** ISINs with spaces or lowercase (` us0378331005 `), CUSIPs with leading zeros dropped by Excel (`37833100` vs `037833100`). Normalise before matching. Tests in Tasks 7 and 12.
3. **Wrong workbook:** missing sheet, renamed header, empty sheet, or a votes file posted to the engagements endpoint. Expect 422 with a `rejected` entry naming the sheet/header, never a 500. Test in Task 8.
4. **Two intakes for one company at once:** the advisory lock must serialise them, and totals must equal sequential runs. Test in Task 3 (store lock) with two threads.
5. **Foreign text:** issuer names with accents and CJK characters in N-PX and Excel must round-trip byte-equal. Test in Task 12.

---

## PR 1: tables, store, factory, migration

### Task 1: VOICE fields on the engagement schema

**Files:**
- Modify: `backend/arp/schemas/engagement.py`
- Test: `backend/tests/test_engagement_schema_voice.py`

**Interfaces:**
- Produces: enums `FirTheme`, `EsgPillar`, `EngagerRole`, `ObjectiveType`, `Receptiveness`, `ObjectiveStatus`, `ObjectiveResult`, `InfluenceLevel` (values exactly as spec "VOICE option lists"; `InfluenceLevel` values `"1"`,`"2"`,`"3"`,`"4A"`,`"4B"`,`"5"`); `ActivityType` (`email`,`letter`,`call`,`meeting`,`agm_intervention`,`resolution_filed`,`other`); model `Objective` (fields = `stw_objectives` columns from the spec, `objective_id` default `new_id("obj")`, plus `source: str = "app"`); `EngagementIssue` gains `fir_theme: FirTheme | None = None`, `esg_pillars: list[EsgPillar] = []`, `rationale: str = ""`, `engager_role: EngagerRole = EngagerRole.BILATERAL`, `objectives: list[Objective] = []`, `source: str = "app"`; `CorrespondenceEntry` gains `objective_id: str | None = None`, `activity_type: ActivityType | None = None`, `is_initiation: bool = False`.

- [ ] **Step 1: Write the failing tests**

```python
def test_old_record_json_still_validates():
    rec = EngagementRecord.model_validate(json.loads(FIXTURE_PRE_VOICE))  # a record.json from before this change
    assert rec.issues[0].objectives == [] and rec.issues[0].engager_role == "bilateral"

def test_fir_theme_has_the_15_values_in_order():
    assert [t.value for t in FirTheme] == ["climate_mitigation", "climate_adaptation", "natural_capital",
        "resources_circular", "pollution", "human_capital", "human_rights", "consumer_protection",
        "digital_responsibility", "communities", "governance_board_pay", "business_ethics",
        "tax_accounting", "shareholder_rights", "other"]

def test_influence_levels():
    assert [l.value for l in InfluenceLevel] == ["1", "2", "3", "4A", "4B", "5"]
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_engagement_schema_voice.py -v` → FAIL (ImportError).
- [ ] **Step 3: Add the enums and fields** listed under Interfaces. Each `FirTheme` member also carries its FIR label (a module dict `FIR_THEME_LABELS`), used by the Excel `lists` sheet.
- [ ] **Step 4: Run** the test file and `tests/test_engagement_store.py` → PASS.
- [ ] **Step 5: Commit** `feat(engagement): VOICE fields on engagement schema`.

### Task 2: Postgres tables

**Files:**
- Modify: `backend/arp/storage/postgres_models.py`, `backend/tests/postgres_helpers.py` (`reset_postgres_tables` truncates the new tables)
- Test: `backend/tests/test_stewardship_tables.py`

**Interfaces:**
- Produces: models `StwCompanyModel`, `StwEngagementModel`, `StwObjectiveModel`, `StwActivityModel`, `StwCommitmentModel`, `StwContactModel`, `StwTransitionModel`, `StwEventModel`, `VoteMeetingModel`, `VoteItemModel`, `VoteDecisionModel`; table names and columns exactly as the spec's "Data model" tables. Constant `STEWARDSHIP_TABLES: tuple[str, ...]` (the 11 names, in FK order) in `postgres_models.py`.

- [ ] **Step 1: Write the failing tests** (`pg` fixture):
  - `test_init_creates_tables` (AC-1): run `ensure_schema(dsn)` twice; both return without error; `inspect(engine).get_table_names()` ⊇ the 11 names.
  - `test_second_init_changes_nothing` (AC-2): snapshot `{table: (columns, count)}` for all 11, run again, equal.
  - `test_legacy_tables_untouched` (AC-28): insert one row each into `engagement_issues`/`engagement_commitments` if they exist in the test DB (else create via the legacy DDL used in `test_postgres_schema.py`), run `ensure_schema`, counts unchanged.
  - `test_unique_source_external_id`: inserting two `stw_engagements` rows with the same (`source`,`external_id`) raises `IntegrityError`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Add the models.** `create_all` makes them; unique constraints and indexes go in `__table_args__` (they are new tables, so no `SchemaStep` is needed).
- [ ] **Step 4: Run** the test file and `tests/test_postgres_schema.py` → PASS.
- [ ] **Step 5: Commit** `feat(storage): stewardship and vote ledger tables`.

### Task 3: PostgresEngagementStore

**Files:**
- Create: `backend/arp/storage/postgres_engagement_store.py`
- Modify: `backend/tests/test_engagement_store.py` (parametrise the existing tests over both stores; no assertion changes)
- Test: `backend/tests/test_postgres_engagement_store.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 tables.
- Produces: `class PostgresEngagementStore` with `__init__(self, dsn: str)` and every public method of `EngagementStore` (same names, arguments, return types: `get`, `get_or_create`, `list_all`, `events`, `lock`, `add_contact`, `open_issue`, `open_issues_for_theme`, `set_issue_status`, `add_correspondence`, `add_commitment`, `update_commitment_status`, `set_milestone_stage`, `set_escalation_stage`, plus any other public method present on `main`). New: `add_objective(company_id: str, issue_id: str, objective: Objective) -> EngagementRecord`, `update_objective(company_id: str, issue_id: str, objective_id: str, **fields) -> EngagementRecord`, `list_objectives(company_id: str, issue_id: str) -> list[Objective]`.
- Behaviour: `lock(company_id)` = `pg_advisory_xact_lock(hashtext(company_id))` in the write transaction. Every write that changes data inserts one `stw_events` row (`event_type` as the file store's, `objective_added`/`objective_updated` for the new methods). A write that changes nothing inserts none.

- [ ] **Step 1: Parametrise** `tests/test_engagement_store.py` with a fixture `store` yielding `EngagementStore(tmp_path)` and, when the `pg` fixture is usable, `PostgresEngagementStore(pg)`. Assertions unchanged.
- [ ] **Step 2: Write new tests** in `test_postgres_engagement_store.py`:
  - `test_parity_ignoring_ids` (AC-3, unit): run the same scripted sequence (create record, open issue, add correspondence, commitment, escalate) on both stores; `_strip(rec.model_dump())` equal, where `_strip` drops keys ending `_id` and `_at` and `date`.
  - `test_objective_round_trip`: `add_objective` then `list_objectives` returns it with all fields.
  - `test_concurrent_writes_serialise` (Review Focus 4): two threads each add 20 correspondence entries to one issue; final count 40; `stw_events` count 40.
  - `test_noop_write_adds_no_event`: `set_issue_status` to the current status → `stw_events` count unchanged.
- [ ] **Step 3: Run** → new tests FAIL.
- [ ] **Step 4: Implement** the store. Assemble `EngagementRecord` from rows (one query per table, filtered by `company_id`).
- [ ] **Step 5: Run** both test files → PASS.
- [ ] **Step 6: Commit** `feat(storage): Postgres engagement store`.

### Task 4: Store factory, setting and callers

**Files:**
- Create: `backend/arp/storage/engagement_store_factory.py`
- Modify: `backend/arp/config.py` (two settings from Global Constraints), `backend/arp/api/deps.py:261-264`, `backend/arp/cli/_shared.py:43`, `backend/arp/portfolio/monthly_run.py:63`, `backend/scripts/e2e_stack.sh` (export `ARP_ENGAGEMENT_STORE=postgres` in `up`)
- Test: `backend/tests/test_engagement_store_factory.py`

**Interfaces:**
- Produces: `build_engagement_store(settings: Settings) -> EngagementStore | PostgresEngagementStore` (`file` → `EngagementStore(settings.engagements_dir)`; `postgres` → `PostgresEngagementStore(require_dsn(settings))`).

- [ ] **Step 1: Tests:**
  - `test_default_is_file` (AC-41): settings without `ARP_ENGAGEMENT_STORE` → `EngagementStore`.
  - `test_postgres_setting` → `PostgresEngagementStore`.
  - `test_postgres_never_writes_files` (AC-27): `engagement_store=postgres`, write a `record.json` for `c1`, create `c1` through `POST /api/engagement/records` (TestClient), `POST /api/engagement/records/c1/issues` → 200; file bytes unchanged.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; replace the three direct `EngagementStore(...)` constructions with the factory. **Step 4: Run** this file plus `tests/test_api_stewardship.py tests/test_monthly_run.py tests/test_engagement_*.py` → PASS.
- [ ] **Step 5: Commit** `feat(engagement): choose engagement store by setting`.

### Task 5: `arp stewardship migrate-files`

**Files:**
- Create: `backend/arp/stewardship/migrate.py`, `backend/arp/cli/stewardship.py`
- Modify: `backend/arp/cli/__init__.py` (register `stewardship_app` as `stewardship`)
- Test: `backend/tests/test_stewardship_migrate.py`

**Interfaces:**
- Produces: `migrate_files(engagements_dir: Path, dsn: str, dry_run: bool = False) -> dict[str, int]` returning `{"created", "updated", "unchanged"}` over the seven tables (companies, engagements, activities, commitments, contacts, transitions, events). `stewardship_app = typer.Typer(...)` with command `migrate-files [--dry-run]`. Writes rows with `source="file_migration"`, `external_id` = the file id (`company_id`, `issue_id`, `entry_id`, `commitment_id`, `contact_id`, `<issue_id>:<kind>:<index>` for transitions, `<company_id>:<line>` for events). Writes no events of its own.

- [ ] **Step 1: Fixture** `tests/fixtures/engagements_migration/` with 3 companies, 5 issues, 7 correspondence entries, 2 commitments, 0 contacts, 4 transitions, 9 events.
- [ ] **Step 2: Tests:** `test_migrate_counts` (AC-5: stdout `created 30, updated 0, unchanged 0`), `test_migrate_again` (AC-6: `created 0, updated 0, unchanged 30`), `test_dry_run` (AC-7: `would create 30`, `stw_engagements` 0 rows). Use `typer.testing.CliRunner`.
- [ ] **Step 3: Run** → FAIL. **Step 4: Implement.** **Step 5: Run** → PASS.
- [ ] **Step 6: Commit** `feat(stewardship): migrate file engagement records to Postgres`.

### Task 6: PR 1 wrap-up

- [ ] Run the full backend checks for touched files, `ruff check .`, and the CLAUDE.md API-contract steps if any response model changed (Task 1 adds fields to `EngagementRecord`, so yes).
- [ ] Commit generated `openapi.json` and `schema.gen.ts`. Open PR 1 against `main` (`Spec: stewardship-data-foundation`, `risk:high`). Do not merge.

---

## PR 2: intake

### Task 7: Engagement intake core (JSON)

**Files:**
- Create: `backend/arp/stewardship/intake.py`
- Test: `backend/tests/test_stewardship_intake.py`

**Interfaces:**
- Produces: `class IntakeReport(BaseModel)`: `created: int`, `updated: int`, `unchanged: int`, `rejected: list[Rejection]`; `class Rejection(BaseModel)`: `sheet: str`, `row: int`, `field: str`, `reason: str`. `ENGAGEMENT_COLUMNS: dict[str, list[str]]` and `VOTE_COLUMNS: list[str]` = the spec's batch field lists, in order. `intake_engagements(batch: dict[str, list[dict]], dsn: str, source: str) -> IntakeReport`. All-or-nothing: one transaction, rolled back when `rejected` is non-empty. `stw_events` rows (`intake_upserted`) are written but never counted.
- Company matching: `company_id`, else normalised ISIN (strip, upper) via the registry (`arp.db` `resolve_ref` / `IdScheme`), else rejection `unknown company`. Missing `stw_companies` row → create it from `company_name` (counted).

- [ ] **Step 1: Tests:** `test_unknown_company_rejected` (AC-14: report row `{"sheet":"engagements","row":1,"reason":"unknown company"}`), `test_valid_batch` (AC-15: company pre-created → `created 2`), `test_bad_enum_rejected_nothing_stored` (AC-12/13 on the JSON path: `rejected[0].field == "objective_type"`; three `stw_` tables 0 rows), `test_isin_normalised` (Review Focus 2: `" us0378331005 "` matches `isin_US0378331005`), `test_follow_up_must_exist` (`follows_external_id` unknown → rejection on that field).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS. **Step 5: Commit** `feat(stewardship): engagement intake`.

### Task 8: Excel read and templates

**Files:**
- Create: `backend/arp/stewardship/intake_excel.py`
- Test: `backend/tests/test_stewardship_intake_excel.py`

**Interfaces:**
- Consumes: Task 7 `ENGAGEMENT_COLUMNS`, `VOTE_COLUMNS`, `intake_engagements`.
- Produces: `read_workbook(data: bytes, kind: Literal["engagements","votes"]) -> tuple[dict[str, list[dict]], list[Rejection]]` (row numbers = worksheet rows, header = 1; values coerced: `datetime`→ISO date, `TRUE`/`1`→`True`, `1.0`→`"1"` for id-like columns; `;`-split for `esg_pillars`/`categories`). `template(kind) -> bytes` (sheets per spec, plus `lists` with one column per option list; `fir_theme` column holds the 15 values in order and a second column their labels).

- [ ] **Step 1: Tests** (build workbooks with openpyxl in the test): `test_upload_counts` (AC-8 via `intake_engagements(read_workbook(...))`: `created 10`), `test_reupload_unchanged` (AC-9), `test_reupload_no_events` (AC-10), `test_changed_summary_updates_one` (AC-11), `test_worksheet_row_number` (AC-12: `row == 3`), `test_excel_saved_types_unchanged` (Review Focus 1: same data with datetime/bool/float cells → `unchanged 10`), `test_wrong_workbook` (Review Focus 3: missing `objectives` sheet → rejection `{"sheet":"objectives","row":0,"field":"","reason":"missing sheet"}`; renamed header → `reason` `unknown column <name>`), `test_template_engagements_headers` (AC-20), `test_template_votes_headers` (AC-21), `test_lists_fir_theme` (AC-22).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS. **Step 5: Commit** `feat(stewardship): Excel intake and templates`.

### Task 9: Vote intake

**Files:**
- Modify: `backend/arp/stewardship/intake.py`
- Create: `backend/arp/schemas/vote_ledger.py`
- Test: `backend/tests/test_stewardship_vote_intake.py`

**Interfaces:**
- Produces: `VoteValue` enum (`for`, `against`, `abstain`, `withhold`, `do_not_vote`, `one_year`, `two_years`, `three_years`, `other`); `against_management(vote: VoteValue, recommendation: str | None) -> bool | None` (rule exactly as the spec's Intake "Rules"); `intake_votes(rows: list[dict], dsn: str, source: str) -> IntakeReport`. Meeting found or created by (company key, `meeting_date`), item by (meeting, `item_number`).

- [ ] **Step 1: Tests:** `test_against_management_rule` (table-driven: (`against`,`for`)→True, (`withhold`,`for`)→True, (`for`,`against`)→True, (`for`,`for`)→False, (`abstain`,`for`)→None, (`one_year`,`for`)→None, (`against`,None)→None), `test_rationale_required` (AC-16), `test_three_items_counts` (AC-17: `created 7`), `test_unmatched_company_stored_null`.
- [ ] **Step 2–4:** FAIL, implement, PASS. **Step 5: Commit** `feat(stewardship): vote intake`.

### Task 10: Intake routes and CLI

**Files:**
- Create: `backend/arp/api/routers/stewardship_intake.py` (prefix `/api/stewardship/intake`, same router dependency as `stewardship.py`); register in `backend/arp/api/main.py`
- Modify: `backend/arp/cli/stewardship.py` (command `intake <file> --kind engagements|votes`)
- Test: `backend/tests/test_api_stewardship_intake.py`

**Interfaces:**
- Produces: `POST /engagements`, `POST /votes` (JSON, `source="api"`), `POST /engagements.xlsx`, `POST /votes.xlsx` (multipart field `file`, `source="excel"`), `GET /template?kind=` (xlsx, `Content-Disposition: attachment; filename=<kind>_template.xlsx`). All POSTs return `IntakeReport`: 200 when `rejected == []`, else 422 with the same body (a `JSONResponse`, not `HTTPException`). CLI prints `created N, updated N, unchanged N, rejected N`, exit 1 when rejected > 0.

- [ ] **Step 1: Tests:** one per route through `TestClient` (AC-8 HTTP form, AC-14, AC-16, AC-17), `test_cli_intake` (AC-18), `test_viewer_forbidden` (AC-19: non-dev auth with a viewer user → 403).
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** API contract steps (export_openapi, gen:api, `contract.ts`), `tsc -b`.
- [ ] **Step 6: Commit**, open PR 2 against `main` (`Spec: stewardship-data-foundation`, `risk:high`).

---

## PR 3: demo data, N-PX, monitoring, UI (after `arp showcase load` is on `main`)

### Task 11: `arp stewardship seed-demo`

**Files:**
- Create: `backend/arp/stewardship/seed_demo.py`
- Modify: `backend/arp/cli/stewardship.py`
- Test: `backend/tests/test_stewardship_seed_demo.py`

**Interfaces:**
- Produces: `select_companies(xlsx: Path, n: int) -> list[tuple[str, str, str]]` (isin, name, sector; header row 4, `Type of Security == "Aktien"`, sort `Weighting` desc, first n distinct ISINs); `seed_demo(dsn: str, n: int = 400, seed: int = 7) -> dict[str, int]`. Uses `random.Random(seed)` only. Sector→theme weights: a module dict `SECTOR_THEMES` keyed by the German `Industry Classification` values in the file. Writes through `intake_engagements(..., source="mock_voice_seed")`; a different seed first deletes all `mock_voice_seed` rows. Missing registry company → `SystemExit(1)` with stderr `run arp showcase load first`, nothing written.

- [ ] **Step 1: Tests** (registry seeded with the 400 companies through the showcase loader, or a 20-company variant with `n=20` for speed, plus one full-400 test marked `slow`): AC-23, AC-24, AC-25, AC-26, AC-29, `test_missing_registry_exit` (AC-31), `test_missing_registry_writes_nothing` (AC-32), `test_mock_text_passes_style_check` (every rationale/outcome/evidence string → `arp.stewardship.style.check(text, blocklist) == []`).
- [ ] **Step 2–4:** FAIL, implement, PASS. **Step 5: Commit** `feat(stewardship): VOICE demo seed`.

### Task 12: `arp stewardship load-npx`

**Files:**
- Create: `backend/arp/stewardship/npx_load.py`; `data/voting/npx_urth/fetch_npx.py` (copy the fetch script from this session's scratchpad `npx/parse.py`, re-run it once end to end to confirm it reproduces the committed CSVs, and fix the README if counts differ)
- Modify: `backend/arp/cli/stewardship.py`
- Test: `backend/tests/test_stewardship_npx_load.py`, fixture `backend/tests/fixtures/npx/fixture.csv`

**Interfaces:**
- Produces: `load_npx(directory: Path, dsn: str) -> dict[str, int]`. Keys and mapping exactly as the spec's Demo data step 4 (meeting key, item key, decision `external_id` = `<file name>:<line number>`, `how_voted`→`VoteValue` map, `against_management` from `for_against_management`, numbers normalised, `vote_label` as filed). CUSIP normalised to 9 characters with leading zeros before registry matching.

- [ ] **Step 1: Tests:** AC-33, AC-34 on the fixture; AC-35, AC-36, AC-37 on the committed CSVs (mark `slow`); `test_cusip_leading_zero` (Review Focus 2); `test_unicode_names_round_trip` (Review Focus 5: fixture row `Société Générale` and `トヨタ自動車` read back byte-equal).
- [ ] **Step 2–4:** FAIL, implement, PASS. **Step 5: Commit** `feat(stewardship): load N-PX votes into the ledger`.

### Task 13: Ledger votes in monitoring

**Files:**
- Modify: `backend/arp/stewardship/process.py:47-53` (`vote_items`)
- Create: `backend/arp/stewardship/vote_ledger_feed.py`
- Test: `backend/tests/test_stewardship_vote_ledger_feed.py`

**Interfaces:**
- Produces: `ledger_rows(dsn: str, window_days: int) -> list[dict]` in the `voting_feed.items()` row shape (`company_id`, `meeting_date` ISO `YYYY-MM-DD` string, `item` = `item_number`, `vote`, `against_management` null→`False`, `overrode_policy=False`, `run_id`), only meetings within `window_days` before the ledger's newest `meeting_date`. `vote_items()` returns run rows plus ledger rows, dropping a run row when a ledger row has the same (`run_id`, `company_id`, `item`). `voting_feed.issuer_fields` unchanged.

- [ ] **Step 1: Tests:** AC-38 (through `GET /api/stewardship/studio/monitoring/triggers` with the AC-33 fixture dated in the newest year and the company in the house universe: exactly one trigger with `type == "vote_outcome"`, `rule == "vote_against_management"`), AC-39 (old-only against vote → no such trigger), AC-40 (`load_sample(...)` → `vote.decided == 1`), `test_null_against_counts_decided_only`.
- [ ] **Step 2–4:** FAIL, implement, PASS. **Step 5: Commit** `feat(stewardship): monitoring reads the vote ledger`.

### Task 14: Objectives in the issue panel

**Files:**
- Modify: `frontend/src/components/EngagementIssuePanel.tsx`, `frontend/src/index.css` (only if a new class is needed; use existing tokens)
- Test: `frontend/tests/engagementObjectives.test.ts`

**Interfaces:**
- Consumes: `EngagementIssue.objectives` and `source` from the regenerated API types.
- Produces: an "Objectives" list under the issue header: per objective, description, type, status, result; a `Demo data` tag when the issue's or objective's `source` is `mock_voice_seed` or `npx_urth_demo`. Nothing renders when `objectives` is empty.

- [ ] **Step 1: Test** a pure helper `objectiveRows(issue)` in `frontend/src/lib/engagement.ts`: returns `[{description, type, status, result, demo}]`; `demo` true for both demo sources, false for `app`.
- [ ] **Step 2–4:** FAIL, implement helper + render, PASS (`npm run lint && npx tsc -b && npm test`).
- [ ] **Step 5:** Start the stack, run `arp showcase load && arp stewardship seed-demo --companies 20`, screenshot `#/engagement` with a seeded issue open (Playwright), run `/impeccable:impeccable audit` and fix findings it raises on this panel.
- [ ] **Step 6: Commit**, open PR 3 (`Spec: stewardship-data-foundation`, `risk:high`). Once CI is green the `evaluator` skill checks AC-30.

---

## Spec coverage check

AC-1, 2, 28 → Task 2 · AC-3 → Task 3 · AC-4 → existing route tests + Task 4 parity run on the e2e stack · AC-5–7 → Task 5 · AC-8–13, 20–22 → Tasks 7–8 · AC-14–15 → Task 7 · AC-16–17 → Task 9 · AC-18–19 → Task 10 · AC-23–26, 29, 31–32 → Task 11 · AC-27, 41 → Task 4 · AC-30 → Task 14 · AC-33–37 → Task 12 · AC-38–40 → Task 13. Holdout rows are written separately by the `test-writer` skill; the tests here are the implementer's own.

Openwiki: `openwiki/` will need a refresh after PR 1 (new system of record for engagements); the weekly `/context-refresh` PR covers it.
