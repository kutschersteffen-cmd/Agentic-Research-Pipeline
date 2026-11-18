# Authority Taxonomy UI Implementation Plan

Status: approved by the owner, 2026-11-04. Execution: factory implement session.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Taxonomy Library screen that drives the authority-taxonomy run (start → sources → review → accept/cancel), with discovery and extraction moved to background tasks.

**Architecture:** The backend splits `start_run`/`select_sources` into a fast "save the next stage" part and a background part launched through `get_job_launcher()`; the CLI keeps calling the composed (awaiting) functions. The frontend keeps all decisions in pure functions in `src/lib/authorityTaxonomy.ts` (tested with `node:test`), and two page components render them. DOM-only behaviour is checked by Playwright e2e tests with the API stubbed by route interception.

**Tech Stack:** FastAPI, Pydantic, pytest; React + TypeScript, `node:test`; Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-11-03-authority-taxonomy-ui-design.md` (AC ids below refer to it).

## Global Constraints

- Stages: `discovering`, `awaiting_sources`, `extracting`, `awaiting_review`, `accepted`, `cancelled`, `failed`.
- Interrupted error text exactly: `interrupted by a server restart`.
- Upload: types `.pdf`, `.txt`, `.md`; else 422 `unsupported file type`; over `max_upload_bytes` 413; folder `documents_dir/_authority/`; no overwrite (`-2`, `-3`).
- Start-form required text exactly: `Theme name is required`.
- Poll every 3000 ms, only while `document.visibilityState === "visible"`; one immediate poll on becoming visible.
- File input `accept=".pdf,.txt,.md"`.
- Routes: `#/taxonomy/authority`, `#/taxonomy/authority/<runId>`.
- After any request/response model change: `cd backend && python scripts/export_openapi.py`, `cd frontend && npm run gen:api`, commit both; new `request<T>()` calls get a line in `frontend/src/api/contract.ts`.
- No new dependencies. Do not change `POST /api/documents/upload` or `safe_id`.

## Review Focus

1. Two quick clicks on Build draft: the second `POST /sources` must get 409 (stage is `extracting`), and the UI reloads the run instead of showing a raw error. Test in Task 2.
2. Background step raising after the user cancelled: state stays `cancelled`, `error` stays null. Test in Task 1 (AC-8/AC-9 plus `error is None`).
3. Upload with an empty filename or a name that `safe_filename` rejects: 422 with its message, nothing written. Test in Task 2.
4. A run id in the URL that does not exist: the screen shows "Run not found" and a link to `#/taxonomy/authority`, not a spinner. Test in Task 4 (`viewFor(null)`).
5. Removing the last citation-bearing activity, then Save: `PUT /draft` with zero activities succeeds (the API only rejects activities without citations), and Accept still works. Test in Task 1 (`put_draft` with `activities=[]`).

---

### Task 1: Run stages, background steps, interrupted runs

**Files:**
- Modify: `backend/arp/research/authority_taxonomy/run.py`
- Test: `backend/tests/test_authority_taxonomy_run.py` (add tests; change none)

**Interfaces:**
- Produces (all in `run.py`):
  - `Stage` adds `"discovering"`, `"extracting"`, `"failed"`.
  - `class SourceSelection(BaseModel): urls: list[str] = []; files: list[str] = []`
  - `RunState` adds `error: str | None = None`, `selection: SourceSelection | None = None`, `step_started_at: str | None = None` (ISO UTC).
  - `INTERRUPTED = "interrupted by a server restart"`
  - `def create_run(theme_name, theme_key, scope, guidance, value_chain, *, run_store) -> RunState` — manifest + state at `discovering`, `step_started_at` now.
  - `async def discover(run_id, *, run_store, search_client, llm, user_agent, use_library=True, library_root=None) -> RunState` — on success `awaiting_sources`, `error=None`; on exception `failed`, `error=str(e)`; never overwrites a `cancelled` state (reload before save; if `cancelled`, return it unsaved).
  - `def begin_extraction(run_id, urls: list[str], files: list[Path], *, run_store) -> RunState` — requires `awaiting_sources`, saves `extracting`, `selection`, `step_started_at`.
  - `async def extract(run_id, *, run_store, llm, settings, user_agent, value_chain_model=None) -> RunState` — reads files from `state.selection`; success → `awaiting_review`, `error=None`; exception (incl. `ValueError("no selected source could be read")`) → `awaiting_sources`, `error=str(e)`, selection kept; same cancel rule.
  - `def refresh(state: RunState, run_store) -> RunState` — if stage in (`discovering`, `extracting`), `step_started_at` older than `jobs._LEASE_GRACE` and `not run_alive(run_store, run_id)`: apply the failure rule with `error=INTERRUPTED`, save, return; else return unchanged.
  - `start_run(...)` and `select_sources(...)` keep their signatures and now `return await discover(...)` after `create_run`, and `begin_extraction` then `return await extract(...)`. They raise as before on failure (CLI behaviour, AC-48): if the returned state has `error`, raise `ValueError(state.error)`.
  - `cancel` accepts `discovering`, `extracting`, `awaiting_sources`, `awaiting_review`.

- [ ] **Step 1: Write failing tests** in `test_authority_taxonomy_run.py`, reusing its existing stubs:
  - `test_create_run_is_discovering`: `create_run(...)` → `stage == "discovering"`, `step_started_at` set.
  - `test_discover_success` (AC-2): after `await discover(...)` with a 2-candidate stub → `awaiting_sources`, 2 candidates, `error is None`.
  - `test_discover_failure` (AC-3): stub raises `RuntimeError("boom")` → `stage == "failed"`, `"boom" in error`.
  - `test_extract_unreadable_keeps_selection` (AC-7): fetch stub returns `None` → `awaiting_sources`, `"no selected source could be read" in error`, `selection.urls == [url]`.
  - `test_extract_after_failure_clears_error` (AC-10).
  - `test_cancel_during_extract` (AC-8) and `test_cancel_during_discover` (AC-9): cancel, then finish the step → `cancelled`, `draft is None` / `candidates == []`, `error is None`.
  - `test_refresh_interrupted_discovering` (AC-11) / `..._extracting` (AC-12): state with `step_started_at` 2 min ago, `run_alive` monkeypatched to `False` → `failed` / `awaiting_sources`, `error == INTERRUPTED`.
  - `test_refresh_fresh_step_alive` (AC-54/55): `step_started_at` = now, `run_alive` → `False` → unchanged.
  - `test_put_draft_empty_activities` (Review Focus 5).
- [ ] **Step 2:** `cd backend && python3 -m pytest tests/test_authority_taxonomy_run.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above. `refresh` uses `arp.orchestration.jobs.run_alive` and `_LEASE_GRACE` unchanged.
- [ ] **Step 4:** run the file, plus `tests/test_cli_taxonomy_author.py` and `tests/test_authority_taxonomy_regressions.py` → all PASS (CLI unchanged, AC-48).
- [ ] **Step 5: Commit** `feat(authority-taxonomy): background-ready run stages`.

### Task 2: API — background launch, refresh on read, uploads

**Files:**
- Modify: `backend/arp/api/routers/authority_taxonomy.py`
- Modify: `backend/arp/config.py` only if no `max_upload_bytes` exists (it does; reuse).
- Test: `backend/tests/test_api_authority_taxonomy.py` (add tests; existing ones must still pass — update only where a test asserted the old synchronous stage, and list it in the PR)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces:
  - `POST /api/authority-taxonomy/runs` → 201 `{id, stage: "discovering"}`; launches `discover` via `get_job_launcher().launch(run_id, job, run_store=run_store)`.
  - `GET /runs/{id}` → `run.refresh(state, run_store)`.
  - `POST /runs/{id}/sources` → validation unchanged (422s), then `begin_extraction`, launch `extract`, return state (`stage == "extracting"`). Wrong stage → 409.
  - `POST /api/authority-taxonomy/uploads` (multipart `file: UploadFile`) → `{"path": str}`; `safe_filename` from `arp.storage.safe_path`; suffix check case-insensitive.
  - `RunState` in the OpenAPI now carries `error`, `selection`, `step_started_at`.

- [ ] **Step 1: Write failing tests:**
  - `test_start_returns_before_discovery` (AC-1) and `test_get_right_after_start` (AC-54): discovery stub awaits an `asyncio.Event` never set during the request → 201 `discovering`; immediate `GET` → `discovering`, `error is None`.
  - `test_sources_returns_extracting` (AC-4), `test_sources_bad_file_422` (AC-5, AC-6), `test_sources_twice_409` (Review Focus 1).
  - `test_upload_txt` (AC-14), `test_upload_twice_suffix` (AC-15), `test_upload_docx_422` (AC-16), `test_upload_path_accepted_by_sources` (AC-17), `test_upload_traversal_name` (AC-52), `test_upload_too_large_413` (AC-53, set `max_upload_bytes` small via settings override), `test_upload_bad_name_422` (Review Focus 3).
  - `test_put_draft_does_not_create_taxonomy` (AC-13).
  - `test_documents_upload_unchanged` (AC-51): `company_id=acme`, `doc_type=other` → path `<documents_dir>/acme/other/<name>`.
- [ ] **Step 2:** `python3 -m pytest tests/test_api_authority_taxonomy.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** the endpoints. Background jobs build their LLM/search clients the same way the current endpoint does (`Depends`), passed into the closure.
- [ ] **Step 4:** tests PASS; `ruff check .`; export OpenAPI and `npm run gen:api`; `cd frontend && npx tsc -b` passes.
- [ ] **Step 5: Commit** `feat(api): authority-taxonomy runs in background, uploads endpoint`.

### Task 3: Client calls

**Files:**
- Modify: `frontend/src/api/client.ts` (add to `api`), `frontend/src/api/contract.ts`

**Interfaces:**
- Produces (types from `schema.gen.ts`: `AuthorityRunState = components["schemas"]["RunState"]`, `ThemeDefinition`):
  - `startAuthorityRun(body: AuthorityRunRequest): Promise<{ id: string; stage: string }>`
  - `getAuthorityRun(id: string): Promise<AuthorityRunState>`
  - `selectAuthoritySources(id: string, body: { urls: string[]; files: string[] }): Promise<AuthorityRunState>`
  - `putAuthorityDraft(id: string, draft: ThemeDefinition): Promise<AuthorityRunState>`
  - `acceptAuthorityRun(id: string): Promise<{ taxonomy_id: string }>`
  - `cancelAuthorityRun(id: string): Promise<void>`
  - `uploadAuthorityDocument(file: File): Promise<{ path: string }>` (FormData field `file`)
- Errors: whatever `request()` throws today; Task 4 reads its status (check `request()` for the error type and status field and use it as is).

- [ ] **Step 1:** add the seven calls and their `contract.ts` lines.
- [ ] **Step 2:** `npx tsc -b` and `npm test` pass (contract test, if present, covers the lines).
- [ ] **Step 3: Commit** `feat(client): authority-taxonomy calls`.

### Task 4: Screen logic (pure functions)

**Files:**
- Create: `frontend/src/lib/authorityTaxonomy.ts`
- Test: `frontend/tests/authorityTaxonomy.test.ts`

**Interfaces:**
- Consumes: Task 3 types.
- Produces:
  - `THEME_KEYS: readonly { key: string; label: string }[]` — the 10 keys from `library.THEME_KEYS`, in that order.
  - `CHECKLIST_KEYS = ["theme_description","activities","boundaries","technologies","definitions","sector_codes","value_chain","thresholds"] as const`
  - `type StartForm = { theme_name: string; theme_key: string | null; scope: string; guidance: string; value_chain: boolean }`
  - `startBody(f: StartForm): { body: AuthorityRunRequest } | { error: "Theme name is required" }` (trims name)
  - `prefill(run: AuthorityRunState): StartForm`
  - `type Selection = { ticked: string[]; urls: string[]; files: { name: string; path: string }[]; uploading: number }`
  - `initialSelection(run: AuthorityRunState): Selection`
  - `sourcesBody(s: Selection): { urls: string[]; files: string[] }` — ticked first, then added URLs.
  - `canBuild(s: Selection): boolean` — something selected and `uploading === 0`.
  - `isWorking(stage: string): boolean` — `discovering` | `extracting`.
  - `startPolling(get: () => Promise<AuthorityRunState>, onState: (r: AuthorityRunState) => void, doc: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">): () => void` — loads at once, then every 3000 ms while visible and `isWorking`; on `visibilitychange` to visible polls once at once; returns a stop function.
  - `saveThenAccept(dirty: boolean, save: () => Promise<unknown>, accept: () => Promise<{ taxonomy_id: string }>): Promise<{ taxonomy_id: string }>` — rejects with the save error without calling `accept`.
  - `viewFor(run: AuthorityRunState | null): "not_found" | "working" | "sources" | "review" | "accepted" | "ended"`.
  - Draft edits keep citations: `editText<T extends { citations: SourceCitation[] }>(item: T, patch: Partial<Omit<T, "citations">>): T`.

- [ ] **Step 1: Write failing tests** (`node:test`, `mock.timers` for polling):
  - AC-18: `startBody({ theme_name: "  " ... })` → `{ error: "Theme name is required" }`.
  - AC-57: filled form → body exactly `{"theme_name":"Hydrogen","theme_key":"hydrogen","scope":"S1","guidance":"G1","value_chain":true}`.
  - AC-25: selection with nothing ticked, urls `["u1"]` after removing `u2`, file P → `{"urls":["u1"],"files":["P"]}`.
  - AC-24: one ticked, `uploading: 1` → `canBuild === false`; AC-38 analogue: empty → `false`.
  - AC-26: candidates A (`from_library:false`), B (library+fetchable), `selection.urls = [A, "u9"]` → ticked `[A]`, urls `["u9"]`; without selection → ticked `[B]` (AC-36 logic).
  - AC-20: responses `discovering ×3` then `awaiting_sources`, tick 15 s → exactly 4 `get` calls at 0, 3, 6, 9 s.
  - AC-21 / AC-56: hidden after first load, tick 10 s → 1 call total; fire `visibilitychange` visible → 2 calls.
  - AC-28: `editText(criterion, { text: "new" })` keeps `citations` identical (deepEqual and same reference).
  - AC-30 / AC-31: `saveThenAccept(true, ok, accept)` calls both in order; with failing save, `accept` not called and the error propagates.
  - AC-46 logic: `prefill(run)` returns the run's five inputs.
  - Review Focus 4: `viewFor(null) === "not_found"`.
- [ ] **Step 2:** `cd frontend && npm test` → new tests FAIL.
- [ ] **Step 3: Implement** the module.
- [ ] **Step 4:** `npm run lint && npx tsc -b && npm test` PASS.
- [ ] **Step 5: Commit** `feat(frontend): authority-taxonomy screen logic`.

### Task 5: Screens, routing, old flow removed

**Files:**
- Create: `frontend/src/pages/AuthorityTaxonomyRun.tsx` (start form, working, sources, accepted, ended/failed, not found; owns polling)
- Create: `frontend/src/pages/AuthorityDraftReview.tsx` (review sections in spec order, Save/Accept/Cancel)
- Modify: `frontend/src/App.tsx:403` — `active === "taxonomy" && route.params[0] === "authority"` renders `<AuthorityTaxonomyRun key={route.params[1] ?? "new"} runId={route.params[1]} />`, else `TaxonomyLibrary` as now
- Modify: `frontend/src/pages/TaxonomyLibrary.tsx` — remove `authority_source` from the method list (lines ~25, ~37), its state and branch (~301–425); add a header button "Build from authority sources" → `navigate`/`location.hash = "#/taxonomy/authority"`
- Delete: client calls and components only the old flow used (check with grep before deleting; `SourceDiscoveryPanel` stays if thematic-fund discovery uses it, `discoverTaxonomySources` stays if anything else calls it)
- Test: `backend/tests/e2e/test_authority_taxonomy_page.py` (Playwright, API stubbed by `page.route`, style of `test_rfp_page.py`)

**Interfaces:**
- Consumes: Task 3 calls, Task 4 functions; `setLeaveGuard` from `lib/leaveGuard.ts` and the `beforeunload` pattern from `DecisionStudio.tsx:185-194` while the review has unsaved edits.
- Error handling: a 409 from any call → `getAuthorityRun` and re-render; a 422 → show `detail` text.

- [ ] **Step 1: Write failing e2e tests** (stubbed API):
  - AC-34 fields and 11 theme-key options; AC-35 URL after Start.
  - AC-19 working message with `Hydrogen` and Cancel.
  - AC-36/37 cards (badge, warning, link `target=_blank`, 8 chips, 2 covered); AC-23 file input `accept`.
  - AC-22: choosing `note.txt` sends `POST /api/authority-taxonomy/uploads` and lists it.
  - AC-27 failed run shows `boom` and "Start a new run"; AC-26 error above list.
  - AC-39 section order and checklist cells; AC-40 citation (quote not editable, link, location); AC-41 exiobase badge, no add-code control; AC-42 no add-activity control.
  - AC-29: Save with 422 shows message, edits kept; AC-32: Save with 409 then `accepted` run shows `T`.
  - AC-33: with unsaved edit, `page.evaluate` dispatches a cancelable `beforeunload` → `defaultPrevented === true`.
  - AC-44: unsaved edit, click another sidebar tab, dismiss the confirm → still on review with the edit.
  - AC-45/46 cancel then "Start a new run" prefilled; AC-47/58 Taxonomy Library has no "Authority source" option and the header button routes.
  - AC-49/50: existing create methods and thematic-fund discovery send the same requests as before (stub records request bodies; compare to fixtures captured from `main` before the change).
- [ ] **Step 2:** start the stack (`.claude/CLAUDE.md` → Browser flow) and run `pytest -m e2e tests/e2e/test_authority_taxonomy_page.py` → FAIL.
- [ ] **Step 3: Implement** the two pages, routing and the Taxonomy Library change, styled with existing classes and `DESIGN.md`.
- [ ] **Step 4:** e2e PASS; `npm run lint && npx tsc -b && npm test` PASS; screenshot the four stages and run `/impeccable:impeccable audit`; fix what it flags.
- [ ] **Step 5: Commit** `feat(frontend): authority taxonomy run screen replaces old authority-source flow`.

### Task 6: Stand-in walk for the evaluator

**Files:**
- Create: `backend/tests/fixtures/authority_taxonomy_ui/standins/` (search results, fetched text, model answers per `arp/standins.py` file format)
- Create: `backend/tests/e2e/test_authority_taxonomy_walk.py` (no route stubs; real API with `ARP_STANDINS_DIR`)

**Interfaces:**
- Consumes: everything above. The fixture must produce the spec's evaluator preamble exactly (two candidates `EU Taxonomy hydrogen` / `Blocked report`; draft with 2 activities, activity 1 role `core` with one `exiobase` code, 1 threshold, checklist `activities`+`thresholds` found, the other 6 `not_in_source`).
- Library entry for `EU Taxonomy hydrogen` (`from_library: true`): the library on `main` is empty, and #325's spec forbids an agent adding an entry without a user step. Before writing fixtures, ask the owner (button mode) to approve one `hydrogen` entry via `arp authority-library propose` then `approve`. If declined, stop and mark the PR `factory:blocked` on AC-36's "From library" part.

- [ ] **Step 1:** write the walk test: start form as in the preamble → sources → tick → review → set activity 1 role to `upstream`, Save, reload → `upstream` (AC-43) → Accept → confirmation.
- [ ] **Step 2:** run with `ARP_STANDINS_DIR=backend/tests/fixtures/authority_taxonomy_ui/standins bash backend/scripts/e2e_stack.sh up` → FAIL until fixtures are complete.
- [ ] **Step 3:** write the fixtures.
- [ ] **Step 4:** walk PASSes.
- [ ] **Step 5: Commit** `test(e2e): authority taxonomy stand-in walk`; open the PR with `Spec: authority-taxonomy-ui`, `risk:normal`, every test change listed.
