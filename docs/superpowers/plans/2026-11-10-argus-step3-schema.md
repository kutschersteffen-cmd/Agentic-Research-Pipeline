# Argus step 3 Schema (slice 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step 3 of the Argus flow (`#/argus/<flow_id>/3`) picks what to extract (a saved schema, a template, or fields drafted from words), shows its fields, warns when a company would be extracted again from the same files with the same schema version, and starts the run on exactly the files kept in step 2.

**Architecture:** The flow gains the chosen schema (`schema_id` + `version`, or a fixed profile `financials` / `tnfd`), `settings`, `repeat` choices and `run_id`. Step 3 reuses the existing endpoints: `GET /api/extraction/schemas`, `GET /schemas/{id}`, `POST /schemas` (new version), `POST /schemas/{id}/versions/{v}/release` (approver), `GET /presets` + `POST /presets/{id}/install`, `POST /schemas/draft`. Starting goes through a new `POST /api/argus/flows/{id}/start`, which builds the existing `StartRequest` and calls the same dispatch `POST /api/extraction/start` uses, adding the kept file keys per company so the run reads only those files. The repeat rule compares the chosen version and the kept files' content keys with each company's latest run (`argus/rows.py` already finds it; its result rows hold `documents[].content_key`).

**Tech Stack:** FastAPI + pydantic, React 19 + TypeScript, `node:test`, pytest + Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` ("Step 3: Schema", "The repeat rule", slice 4). Builds on slices 2 and 3 (`arp/argus/*`, `routers/argus.py`, `ArgusFlow.tsx`, `ArgusDocuments.tsx`, `lib/argusFlow.ts`).

## Global Constraints

- Exact copy: picker groups `Saved schemas`, `Templates`, `Describe it in words` with button `Draft fields`; each saved schema `v<n>` and `released` or `draft`; table columns `Field`, `Type`, `Unit`, `What it means`, `Look in`; `Add field`; `Edit as v<n+1>`; `Release`; `Settings (optional)`; repeat box buttons `Skip, keep earlier results`, `Run again`, `See earlier results`; start button `Extract <schema> v<n> for <N> companies` (released) or `Try <schema> on 1 company` (draft); `1 new document since the last run` / `<k> new documents since the last run`.
- `What it means` is `FieldDefinition.description`; `Look in` is `extraction_instructions` (empty shows `—`).
- Templates list the presets from `GET /api/extraction/presets` (including `Transition plan`) plus `Financials` and `TNFD` as fixed profiles. Choosing a preset installs it (`POST /presets/{id}/install`) and selects the returned schema version. Fixed profiles show their fields read-only and have no `Edit` or `Release`.
- `Settings (optional)` is a collapsed `<details>` with: quality mode (`cheap` / `normal` / `max`), `Evidence passages` (`step_settings.evidence_max_chunks`), batch, and the Decision Studio scoring template (`ScoringTemplatePicker`). No `PipelineEditor` canvas (spec AC-66 removes it in slice 6).
- A draft schema runs as a trial (`trial: true`) on the first company with kept files only; a trial writes no facts (existing behaviour). Financials and TNFD have no draft state.
- The run reads only the files kept in step 2 for each company; a company with no kept file is not in the run. Skipped companies (repeat rule) are left out.
- Steps 4 and 5 are not built yet: after start the flow is at step 4 with `run_id` set, and the page sends the user to `#/argus`, where the run is listed as `Running` (spec, "Until the new steps exist").
- After response models change: export OpenAPI, `npm run gen:api`, commit both.
- Delivers AC-25, AC-26, AC-27, AC-28, AC-29, AC-32, AC-34, AC-36, AC-77, AC-15, AC-16, AC-17, and AC-9 for step 3. AC-30, AC-31, AC-33, AC-35 (holdout) rely on existing trial behaviour plus this slice's repeat rule; the PR lists them.

## Review Focus

1. **A run must not read removed files.** Today extraction fetches every document of a company (`registry.fetch_all`). Task 3 adds an allow-list; test that a removed file's doc never reaches extraction, and that runs started without the list behave as before.
2. **Content keys vs file keys.** Step 2 keys files by path (`cid/type/name`) or `doc:<doc_id>`; the repeat rule needs content keys. Map once in `argus/documents.py` (the check cache already hashes content); never compare paths to content keys.
3. **Repeat rule edges:** no earlier run (no warning); earlier run was a trial (counts as an earlier run of that version, spec does not exempt it); earlier set contained in the current one (no warning, `<k> new documents` line); same set but other version (no warning).
4. **Start disabled until every listed repeat company has a choice;** `See earlier results` is a link, not a choice.
5. **Double click on Start:** one run only (409 when the flow already has a `run_id` whose run is running).
6. **Release by a non-approver:** the button is hidden for analysts and the API refuses (existing role check).

---

### Task 1: Flow schema choice and settings

**Files:** Modify `backend/arp/argus/flows.py`, `backend/arp/api/routers/argus.py`; Test `backend/tests/test_argus_schema_step.py` (new)

**Produces:** `ArgusFlow` gains `schema_choice: SchemaChoice | None` (`kind: "schema" | "profile"`, `schema_id: str | None`, `version: int | None`, `profile: "financials" | "tnfd" | None`), `settings: FlowSettings` (`mode: "cheap" | "normal" | "max" = "normal"`, `evidence_passages: int | None`, `batch: bool = False`, `decision_framework_id: str | None`, `decision_framework_version: int | None`), `repeat: dict[str, Literal["skip", "run"]] = {}`, `run_id: str | None`. `FlowPatch` accepts `schema_choice`, `settings`, `repeat`.

- [ ] Tests: patch a schema choice and settings, read back; a profile choice clears `schema_id`; `repeat` for a company not in the flow is refused (400). Implement, pass, commit.

### Task 2: The repeat rule

**Files:** Create `backend/arp/argus/repeat.py`; Modify `backend/arp/argus/documents.py` (content key per flow file), `backend/arp/api/routers/argus.py` (`ArgusFlowView.repeat_rows`); Test `backend/tests/test_argus_repeat.py`

**Produces:** `repeat_rows(flow, kept: dict[company_id, set[content_key]], last_runs) -> list[RepeatRow]` with `company_id`, `kind: "same" | "added" | None`, `added: int`, `run_id`, `date`, `approved`, `waiting`. Last run per company from the same source `rows.py` uses; its version from `manifest.params["schema_id"]` / `["schema_version"]`, its content keys from that company's result row `documents[].content_key`.

- [ ] Tests for AC-32 (same version, same set → `same` with the run's date and counts), AC-33 (one file different → none), AC-34 (one file added → `added`, 1), AC-35 (other version → none), no earlier run → none. Implement, pass, commit.

### Task 3: Start the run on the kept files

**Files:** Modify `backend/arp/extraction/pipeline.py` (`_extract_company`: optional allow-list), the run request path used by `start_extraction` (pass it through, stored in `start_request.json`), `backend/arp/api/routers/argus.py` (`POST /flows/{id}/start`); Test `backend/tests/test_argus_start.py`

**Produces:** `RunRequest`/`StartRequest` gain `only_documents: dict[str, list[str]] | None` (company_id → content keys); `_extract_company` keeps only fetched documents whose `content_key` is listed when the map has the company. `POST /api/argus/flows/{id}/start` (analyst) builds the `StartRequest` from the flow: companies with kept files minus `repeat == "skip"`, the schema (custom: the saved version's `DataPointSchema`; profile: `financials` / `tnfd`, TNFD `as_of` = `FY<reporting_year>`), `trial` and the first company only for a draft, settings mapped to `mode`, `step_settings.evidence_max_chunks`, `batch`, `decision_framework_*`; refuses 400 while a listed repeat company has no choice, 409 while the flow's run is running; saves `run_id` and `step = 4`.

- [ ] Tests: a removed file's content never reaches `_extract_company`'s kept list; no map → unchanged behaviour (an existing pipeline test passes untouched); start excludes a skipped company (AC-36); evidence passages 3 lands in the run's stored settings (AC-28); scoring template attached (AC-77); draft → trial with 1 company; 400 and 409 cases. Implement, pass, commit.

### Task 4: Frontend model for step 3

**Files:** Modify `frontend/src/lib/argusFlow.ts`; Test `frontend/tests/argusFlow.test.ts` (append)

**Produces:** `startLabel(choice, schemaName, version, released, companies): string` (both forms), `newDocsLine(added: number): string | null`, `canStart(repeatRows, repeat): boolean`.

- [ ] Tests for both start labels, `1 new document since the last run`, `3 new documents since the last run`, 0 → null, and `canStart` with one unanswered `same` row. Implement, pass, commit.

### Task 5: Step 3 on the flow page

**Files:** Create `frontend/src/pages/ArgusSchema.tsx`; Modify `frontend/src/pages/ArgusFlow.tsx` (route step 3, step bar link), `ArgusDocuments.tsx` (Continue goes to step 3 instead of the old screen), `frontend/src/api/client.ts` (install preset, list presets, register schema, start flow), `frontend/src/index.css` (`.argus-schema*`); e2e `backend/tests/e2e/test_argus_step3.py`

- [ ] Picker left, field table right (two columns, stacked below 900px); `Draft fields` fills the table from `draftSchema` (unsaved until `Edit as v<n+1>` / save); `Add field` adds an editable row; `Release` for approvers; the repeat box with the three buttons per listed company; the `Settings (optional)` details; the start button from `startLabel`, disabled per `canStart`; after start, go to `#/argus`.
- [ ] `cd frontend && npm run lint && npx tsc -b && npm test`; backend ruff and the argus tests; the e2e test (choose a saved schema, see 4 rows, open settings, start a trial, see the run on `#/argus`); light and dark screenshots of step 3 in `docs/design-shots/`; `/impeccable:impeccable audit`. Commit, push, PR with `Spec: argus-simplified-pipeline` and `risk:normal`.
