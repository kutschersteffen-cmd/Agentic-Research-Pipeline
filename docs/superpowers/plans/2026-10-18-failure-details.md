# Failure Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the traceback of failed runs and companies, serve it to analysts, show it in Run History, and add "Resume all failed".

**Architecture:** The backend adds a `traceback` to company error rows and a `run_failed` event for a whole-run failure, plus one endpoint `GET /api/runs/{run_id}/failure` (analyst and above) that merges them with the manifest; `/errors` stops returning `traceback`. The frontend reads that endpoint in a details block under each failed Run History row, and one toolbar button resumes every failed run through an extended `useResume` hook.

**Tech Stack:** Python 3.11, FastAPI, pydantic, pytest (`pg` fixture); React 19, TypeScript, `node:test` for `frontend/tests/*.test.ts`.

**Spec:** `docs/superpowers/specs/2026-10-18-failure-details-design.md` (approved 2026-10-18). Row IDs below (AC-n) are that spec's.

## Global Constraints

- A stored traceback is the last 8,000 characters of the formatted traceback.
- `GET /api/runs/{run_id}/failure` needs role `analyst` (`require_role("analyst")`); viewer gets 403; unknown run 404 `Run not found`.
- `GET /api/runs/{run_id}/errors` keeps its rows and the key `errors`, but its rows have no `traceback` key.
- `company_errors`: drop `review: true` rows first, then one entry per key (the last remaining row), ordered by first appearance among the remaining rows. The run's `traceback` is the latest `run_failed` event's.
- Run History: Details button on rows with status `failed` or `partially_completed` (any run type), `aria-label="Details for <run_id>"`, `aria-expanded`; each open fetches once; 50 company errors shown, then `and <n> more`.
- Toolbar button `Resume all failed (<n>)` (n = listed rows with status `failed` or `partially_completed` whose type `canResumeRun` accepts; absent at 0). Summary alert `Resumed <k> of <n>.` plus ` Refused: <run_id>: <message>; <run_id>: <message>` when any were refused; it stays visible after the reload.
- API contract: after the response-model change run `cd backend && python scripts/export_openapi.py` and `cd frontend && npm run gen:api`, commit both generated files, add a line to `frontend/src/api/contract.ts`.
- No new dependency. Never delete or weaken an existing test; list any test change in the PR description.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; `cd frontend && npm run lint && npx tsc -b && npm test`.

## Review Focus

- An errors file holding only `review: true` rows gives `company_errors: []` (AC-37 covers a review row after a failure for the same key).
- Whole-run failures recorded outside `_mark_failed` (`replication/pipeline.py`, `emerging_themes/pipeline.py` call `finish_run(error=...)` themselves) get no event: their Details show "No traceback was recorded for this run." This is accepted; do not widen the change to them.
- A run resumed after a failure appends a second `run_failed` event if it fails again: the endpoint returns the later one (AC-12).
- The summary alert must survive the list reload that `load()` triggers, and `clearError` must not clear it.
- A Details block open on a row whose run is resumed disappears with the row's Details button when the reload shows it as `running`; no stale block remains.

## File Structure

- Modify `backend/arp/orchestration/jobs.py`: `traceback_tail`, `_mark_failed` event.
- Modify `backend/arp/orchestration/batch_runner.py`: company `traceback`.
- Modify `backend/arp/api/routers/runs.py`: `/failure`, `/errors` strip, response models.
- Tests: `backend/tests/test_batch_runner.py`, `backend/tests/test_jobs.py`, create `backend/tests/test_api_run_failure.py`.
- Modify `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts` (generated), `frontend/src/api/contract.ts`, `frontend/src/api/client.ts`, `frontend/src/types.ts`.
- Modify `frontend/src/lib/runs.ts`, `frontend/src/lib/useResume.ts`; test `frontend/tests/runs.test.ts`.
- Create `frontend/src/components/FailureDetails.tsx`; modify `frontend/src/pages/RunHistory.tsx`, `frontend/src/index.css`.

### Task 1: Capture tracebacks

**Files:**
- Modify: `backend/arp/orchestration/jobs.py` (`_mark_failed`, ~line 86)
- Modify: `backend/arp/orchestration/batch_runner.py` (`_run_one`, ~line 105)
- Test: `backend/tests/test_batch_runner.py`, `backend/tests/test_jobs.py`

**Interfaces:**
- Produces: `traceback_tail(exc: BaseException, limit: int = 8000) -> str` in `arp.orchestration.jobs`, the last `limit` characters of `"".join(traceback.format_exception(exc))`. Error rows gain `"traceback": str` (non-review failures only). A whole-run failure appends `{"type": "run_failed", "at": <ISO-8601 with timezone offset>, "traceback": str}` via `run_store.append_event(run_id, row)`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_batch_runner.py` (style of `test_run_batch_isolates_failures`): `test_company_failure_keeps_traceback` (AC-1: worker raises `ValueError("boom")` for `C1`; the errors row has `key` `C1`, `error` `boom`, `traceback` containing `Traceback (most recent call last)` and `ValueError: boom`); `test_review_required_row_has_no_traceback` (AC-2: the row keeps `review` true and `report`, and has no `traceback` key); `test_company_traceback_is_cut_to_8000_characters` (AC-3: `ValueError("x" * 20000)`; stored traceback has length 8000 and equals the last 8000 characters of the formatted traceback). In `tests/test_jobs.py` (style of `test_local_launcher_runs_job_under_lease`): `test_failed_job_records_run_failed_event` (AC-4, AC-5: a job raising `RuntimeError("provider down")` under `hold_run`; manifest `failed` with `error` `RuntimeError: provider down`; `read_events` is exactly one row, `type` `run_failed`, `datetime.fromisoformat(at).tzinfo is not None`, `traceback` containing `RuntimeError: provider down`); `test_run_failed_event_traceback_is_cut` (AC-6: exception text of 20000 characters; event traceback length 8000); `test_event_write_failure_does_not_break_mark_failed` (AC-7: `append_event` patched to raise; the manifest is still `failed` and `_mark_failed` raises nothing).
- [ ] **Step 2: Run to verify failure.** `cd backend && python3 -m pytest tests/test_batch_runner.py tests/test_jobs.py -q`. Expected: the new tests FAIL (no `traceback` key, no events).
- [ ] **Step 3: Implement** `traceback_tail` in `jobs.py`; call it in `_mark_failed` after `finish_run`, inside its own `try/except Exception` that logs and never raises (`run_store.append_event`, `at` from `datetime.now(UTC).isoformat()`); in `batch_runner._run_one` add `row["traceback"] = traceback_tail(exc)` only when `exc` is not a `ReviewRequired`.
- [ ] **Step 4: Run to verify pass.** Same command. Expected: all pass, no stray warnings.
- [ ] **Step 5: Commit.** `git add backend/arp backend/tests && git commit -m "Keep tracebacks of failed companies and runs"`

### Task 2: The `/failure` endpoint and the `/errors` strip

**Files:**
- Modify: `backend/arp/api/routers/runs.py` (next to `get_run_errors`, ~line 133)
- Test: create `backend/tests/test_api_run_failure.py`

**Interfaces:**
- Consumes: Task 1's error rows and `run_failed` events.
- Produces: pydantic models `CompanyError(key: str, error: str, traceback: str | None)` and `RunFailure(run_id: str, status: JobStatus, error: str | None, traceback: str | None, company_errors: list[CompanyError])` defined in `runs.py`; route `GET /{run_id}/failure` with `response_model=RunFailure` and `dependencies=[Depends(require_role("analyst"))]`; `get_run_errors` returns rows without the `traceback` key.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_run_failure.py`, modelled on `tests/test_auth.py` (`users_file` and `real_client` fixtures; tokens for viewer, analyst, approver; seed the store with `RunStore(pg, tmp_path)`, `save_manifest`, `append_error`, `append_event`). Test names with assertions from the spec: `test_failure_of_failed_run` (AC-8), `test_company_errors_values_and_order_skip_review_rows` (AC-9: keys `C1` then `C2`, `boom1`/`boom2`, tracebacks containing `ValueError: boom1`/`boom2`), `test_row_without_traceback_gives_null` (AC-10), `test_repeated_key_keeps_latest_row` (AC-11), `test_review_row_after_failure_hides_the_key` (AC-37: `C1` `first`, `C1` `review: true`, `C2` gives `C1` `first` then `C2`; follow the spec's row exactly), `test_latest_run_failed_event_wins` (AC-12), `test_legacy_failed_run_has_null_traceback` (AC-13), `test_completed_run_has_no_failure` (AC-14), `test_unknown_run_404` (AC-15: detail `Run not found`), `test_viewer_gets_403_analyst_and_approver_200` (AC-16, AC-17), `test_errors_endpoint_has_no_traceback` (AC-18, viewer token).
- [ ] **Step 2: Run to verify failure.** `cd backend && python3 -m pytest tests/test_api_run_failure.py -q`. Expected: FAIL (404 route not found / key present).
- [ ] **Step 3: Implement** the models and route; build `company_errors` with the spec's rule (drop review rows, then one per key by last row, ordered by first appearance among the remaining rows); `traceback` from the last `run_failed` event in `run_store.read_events(run_id)`; 404 `Run not found` when `load_manifest` is None; strip `traceback` from `/errors` rows.
- [ ] **Step 4: Run to verify pass.** Same command plus `ruff check .`. Expected: pass, no warnings.
- [ ] **Step 5: Commit.** `git commit -m "Add GET /api/runs/{id}/failure and hide tracebacks from /errors"`

### Task 3: API contract, client and types

**Files:**
- Modify (generated): `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`
- Modify: `frontend/src/api/contract.ts`, `frontend/src/api/client.ts`, `frontend/src/types.ts`

**Interfaces:**
- Consumes: Task 2's `RunFailure` and `CompanyError`.
- Produces: `export interface RunFailure { run_id: string; status: JobStatus; error: string | null; traceback: string | null; company_errors: { key: string; error: string; traceback: string | null }[] }` in `types.ts`; `api.getRunFailure(runId: string): Promise<RunFailure>` in `client.ts` (`GET /api/runs/<encoded id>/failure`); `api.getRunErrors` return type unchanged.

- [ ] **Step 1: Regenerate.** `cd backend && python scripts/export_openapi.py && cd ../frontend && npm run gen:api`. Expected: both generated files change.
- [ ] **Step 2: Add** the `RunFailure` type, `api.getRunFailure` using `request<RunFailure>(...)`, and one line in `ApiContract`: `Satisfies<Served<S["RunFailure"]>, RunFailure>,`.
- [ ] **Step 3: Verify.** `cd frontend && npx tsc -b && npm test`. Expected: clean. Deliberately breaking a field name in `RunFailure` must make `tsc -b` fail (check once, then revert).
- [ ] **Step 4: Commit.** `git add frontend/src backend && git commit -m "Add RunFailure to the API contract and client"`

### Task 4: Helpers and the "Resume all failed" hook

**Files:**
- Modify: `frontend/src/lib/runs.ts`, `frontend/src/lib/useResume.ts`
- Test: `frontend/tests/runs.test.ts`

**Interfaces:**
- Produces in `lib/runs.ts`: `hasFailureDetails(status: string): boolean` (true for `failed`, `partially_completed`); `resumableFailedRuns(runs: RunManifest[]): RunManifest[]` (status `failed` or `partially_completed` and `canResumeRun(run_type, status)`, input order); `resumeSummary(total: number, refused: { runId: string; message: string }[]): string` (`Resumed <total - refused.length> of <total>.` plus ` Refused: <runId>: <message>; ...` when any); `COMPANY_ERRORS_SHOWN = 50`.
- Produces in `useResume()`: existing `{ busyId, error, resume, clearError }` unchanged, plus `summary: string | null` and `resumeAll(runIds: string[], after?: () => void | Promise<void>): Promise<void>`. `resumeAll` takes the same `useRef` lock as `resume` (a call while any resume is in flight returns at once), sets `busyId` to a non-null value for the whole pass, sends `api.resumeRun` one run at a time in order, records each failure's `(err as Error).message` (a network error has no status and is listed as is), then awaits `after` once and sets `summary = resumeSummary(runIds.length, refused)`. `summary` is cleared when the next `resume` or `resumeAll` starts, not by `clearError`.

- [ ] **Step 1: Write the failing tests** in `tests/runs.test.ts`: `hasFailureDetails is true only for failed and partially_completed`; `resumableFailedRuns keeps failed and partially_completed resumable runs in order` (the spec's AC-27 list: `A` failed extraction, `B` partially_completed theme, `C` completed financials, `D` failed holdings gives `[A, B]`); `resumeSummary all resumed` (`Resumed 2 of 2.`); `resumeSummary lists refusals in order` (`Resumed 0 of 2. Refused: A: 409: busy; B: 500: down`); `resumeSummary with one refusal` (`Resumed 1 of 2. Refused: B: 409: busy`).
- [ ] **Step 2: Run to verify failure.** `cd frontend && node --test --experimental-strip-types tests/runs.test.ts`. Expected: FAIL (exports missing).
- [ ] **Step 3: Implement** the helpers and extend `useResume`. (`useResume` has no unit test: the repo has no React test harness; the Run History rows below are the evaluator's.)
- [ ] **Step 4: Verify.** `cd frontend && npm run lint && npx tsc -b && npm test`. Expected: pass.
- [ ] **Step 5: Commit.** `git commit -m "Add failure helpers and resumeAll"`

### Task 5: Run History details and toolbar

**Files:**
- Create: `frontend/src/components/FailureDetails.tsx`
- Modify: `frontend/src/pages/RunHistory.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: `api.getRunFailure`, `RunFailure`, `hasFailureDetails`, `resumableFailedRuns`, `COMPANY_ERRORS_SHOWN`, `useResume().{summary, resumeAll, busyId}`.
- Produces: `FailureDetails({ runId }: { runId: string })`: fetches `api.getRunFailure(runId)` on mount and renders, in order: the `error` line (omitted when null); the traceback in a `<pre>` or the text `No traceback was recorded for this run.`; the company errors as a list of `<key>: <error>` (first 50, then `and <n> more`; no list when empty); a fetch failure as `<p role="alert" className="error-text">` with the thrown message as is. It is mounted only while its row is open, so each open fetches once.

- [ ] **Step 1: Details.** In `RunHistory.tsx`, keep a `Set` of open run ids in state. Rows where `hasFailureDetails(r.status)` get a link-style button `Details` (`className="link-button"`, `aria-label={`Details for ${r.run_id}`}`, `aria-expanded`) that toggles the id; when open render a second `<tr>` with a `<td colSpan>` holding `<FailureDetails runId={r.run_id} />`. Rows in other statuses get no Details button. Existing buttons, `.run-error` and `N companies failed` stay as they are.
- [ ] **Step 2: Toolbar.** Next to Refresh, when `resumableFailedRuns(runs).length > 0`, a button `Resume all failed (<n>)` (`disabled={busyId !== null}`) calling `resumeAll(resumableFailedRuns(runs).map((r) => r.run_id), load)`. Per-row Resume buttons are already disabled while `busyId !== null`. Render `summary` in a `role="alert"` paragraph above the table; it must remain after the reload (it is hook state, so `load()`'s `clearError()` does not touch it).
- [ ] **Step 3: Styles.** Add the minimum CSS for the details block (`<pre>` scrolls horizontally, monospace, existing colour variables). No new colours.
- [ ] **Step 4: Verify.** `cd frontend && npm run lint && npx tsc -b && npm test`. Expected: pass.
- [ ] **Step 5: Commit.** `git commit -m "Show failure details and Resume all failed in Run History"`

### Task 6: Whole-change verification and handoff

- [ ] **Step 1: Run the suites.** `cd backend && ruff check . && python3 -m pytest tests/test_batch_runner.py tests/test_jobs.py tests/test_api_run_failure.py tests/test_auth.py tests/test_run_company_batch.py -q`; `cd frontend && npm run lint && npx tsc -b && npm test`.
- [ ] **Step 2: Diff rules (AC-41, AC-43).** `git diff origin/main...HEAD --name-only` lists `openapi.json`, `schema.gen.ts`, `contract.ts` and no file under `frontend/src/pages` except `RunHistory.tsx`; `git diff origin/main...HEAD --numstat -- backend/tests frontend/tests` shows no removed lines in existing test files (if an existing exact-match assertion on error rows had to change, list it in the PR description).
- [ ] **Step 3: Look at it.** Start the stack (`bash backend/scripts/e2e_stack.sh up`), seed a failed run with a company error and traceback in the store, screenshot Run History with a Details block open and the toolbar button (Playwright), run `/impeccable:impeccable audit`, then `e2e_stack.sh down`.
- [ ] **Step 4: Push** the branch. Do not open the PR until the owner asks. `openwiki/` is regenerated by the weekly context refresh; say so in the PR.
