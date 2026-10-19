# Failure details and "Resume all failed" in Run History

Date: 2026-10-18
Status: approved by the owner 2026-10-18 (spec-critic rounds 1 and 2 fixed; no third round run)
Origin: gap-list items 3 (failed jobs with details) and 4 (notifications) from the 2026-10-17 review of the
`setup.sh` script. The owner chose in-app notifications only and asked for both items. This is the first of
two specs: it covers the failed-jobs part. Run-finished notifications are a separate spec that follows.
The owner skipped the interview for this feature, so choices marked **(my call)** are mine.

## Intent

After PR #178 a failed run shows in "Needs you" and can be resumed. A person still cannot see why it
failed: Run History shows one line (`RuntimeError: provider down`), the per-company errors have only a
message, and the traceback goes to the server log, which the people using ARP do not read.

After this change an analyst can open a failed run in Run History, read the error, the traceback and every
company's error, and resume all failed runs with one click.

## Goals

1. **Keep the traceback.**
   - A company that fails inside a batch run keeps its traceback in its error row (new field `traceback`).
   - A run that fails as a whole keeps its traceback in an event row (`type: "run_failed"`) in the run's
     existing events store.
   - A stored traceback is cut to its last 8,000 characters **(my call)**.
2. **One read endpoint,** `GET /api/runs/{run_id}/failure`, for analysts and approvers **(my call: a
   traceback can show file paths and fragments of data, so viewers do not get it)**. It returns the run's
   error line, its traceback, and its company errors.
3. **Details in Run History.** Each failed or partially completed row gets a Details button that opens the
   error, the traceback and the company errors under the row.
4. **Resume all failed.** One button in Run History's toolbar resumes every failed or partially completed
   resumable run in the list, one after another, and reports the ones the server refused.

## Non-goals

- Dismissing or discarding a failed run, or any new stored status (no table, no manifest field).
- Tracebacks for runs that failed before this change. They show the error line and "No traceback was
  recorded for this run."
- Run-finished notifications (browser notification, tab title, toast). Next spec.
- Changing how a run is resumed or what a resume does. It stays `POST /api/runs/{run_id}/resume`.
- Showing review-required rows (`review: true`) as failures. They are not failures.
- Redacting secrets from tracebacks beyond the viewer restriction above.

## Anti-goals (a failure even if it works)

- A viewer able to read a traceback.
- "Resume all failed" starting a run twice, or resuming a run that is not failed.
- A traceback so large it slows the page or the run store.

## Current state (what this builds on)

- `batch_runner.py` (`_run_one`): a failed company appends `{"key", "error": str(exc)}` to the run's errors
  file and logs the traceback; review-required exceptions add `review: true` and a `report`.
- `jobs.py` (`_mark_failed`): a run-level crash calls `finish_run(run_id, error="<Type>: <message>")`
  and logs the traceback.
- `RunStore` already has `append_event(run_id, row)` and `read_events(run_id)`; nothing reads events over
  the API today.
- `GET /api/runs/{run_id}/errors` returns the error rows (`{"errors": [...]}`); `RunManifest.error` is one
  string. Run History shows `r.error` and `N companies failed`, and (PR #178) a per-row Resume button.
- `useResume()` and `canResumeRun(runType, status)` exist; `api.resumeRun(runId)` posts the resume.
- Roles: `require_role("analyst")` exists (viewer < analyst < approver).

## Design

**Backend capture.**
- In `_run_one`'s except block, a non-review failure's row also gets `"traceback"`: the last 8,000
  characters of `traceback.format_exc()`. Review rows are unchanged.
- In `_mark_failed`, after `finish_run`, append the event
  `{"type": "run_failed", "at": <now_iso>, "traceback": <last 8,000 characters of the formatted exception>}`
  with `run_store.append_event`. A failure to write the event is logged and never raised.

**Endpoint.** `GET /api/runs/{run_id}/failure`, dependency `require_role("analyst")`. Response model
`RunFailure`: `run_id: str`, `status: JobStatus`, `error: str | None`, `traceback: str | None` (from the
latest `run_failed` event, else null), `company_errors: list[CompanyError]` where `CompanyError` is
`key: str`, `error: str`, `traceback: str | None`, built from the errors file by dropping `review: true` rows first, then keeping one entry per key (the last remaining row for that key, the latest attempt), ordered by first appearance among the remaining rows. `traceback` of the run is the one from the latest `run_failed` event (a run that fails, is resumed and fails again has two). 404 `Run not found` for an unknown run. A run that did not fail returns 200 with
`error` null, `traceback` null and `company_errors: []` when it has none.

**Existing errors endpoint.** `GET /api/runs/{run_id}/errors` keeps returning its rows but without the `traceback` field, so viewers never see one. The `/failure` endpoint is the only place a traceback is served.

**API contract.** The new response model means: `cd backend && python scripts/export_openapi.py`,
`cd frontend && npm run gen:api`, both generated files committed, and a line for the new `request<T>()` in
`frontend/src/api/contract.ts`.

**Run History.**
- Every row whose status is `failed` or `partially_completed`, of any run type, gets a button `Details` (shown to every role: a viewer who clicks it sees the 403 message). Rows in any other status get none. The button with
  `aria-label="Details for <run_id>"` and `aria-expanded`. Each open (a click that goes from closed to open) sends one `GET /api/runs/<id>/failure` and shows, under the row, in this order: the error line (omitted when `error` is null); the traceback in a `<pre>` (or the text
  `No traceback was recorded for this run.`); the company errors as a list `<key>: <error>` (the first 50,
  then `and <n> more` when there are more; no list at all when there are none). A second click closes it; opening it again fetches again.
- A failed load shows the client's error text `<status>: <detail>` in a `role="alert"` element in the same
  place.
- Toolbar: a button `Resume all failed (<n>)`, where n counts rows currently listed whose status is `failed`
  or `partially_completed` and whose type `canResumeRun` accepts. It is absent when n is 0. Click disables
  it, then for each such row in list order calls `api.resumeRun` one at a time, then reloads the list once
  (with the current filter, as the per-row Resume does). Refusals do not stop the loop. Afterwards a
  `role="alert"` summary reads `Resumed <k> of <n>.` and, when some were refused,
  ` Refused: <run_id>: <status>: <detail>; <run_id>: ...` (each refused run, in list order).
- The summary alert stays visible after the reload, even when the reloaded list has no failed rows. A refusal that has no status (a network error) is listed with the client's error text as is. While any resume (a per-row one or a pass) is in flight, the toolbar button and every per-row Resume button are disabled, and they are enabled again when it ends (the toolbar button only if failed rows are still listed), so a run is never resumed twice at once. A double click on the toolbar button starts one pass.

## Constraints

- Existing keys of error rows and of `GET /api/runs/{run_id}/errors` stay as they are; `traceback` is
  additive.
- Backend checks `cd backend && ruff check . && python3 -m pytest tests/<file>`; frontend checks
  `cd frontend && npm run lint && npx tsc -b && npm test`. Frontend unit tests cover `lib/` only.
- The `HOLDOUT_TOKEN` state is unknown to the author, so backend rows are `unit` (pytest); screens are
  `evaluator`. If the owner wants the API rows in the holdout repo, they must say so.
- **How the evaluator works:** as in the failed-run-recovery spec: seed run manifests and error rows, or
  intercept responses in the browser; count requests and fake answers with Playwright route interception.

## Left to the builder

- Whether the `traceback` cut is a helper in `arp/orchestration` or inline.
- Styling of the details block, reusing existing classes.
- Test fixtures.

## Risks

- A traceback can contain fragments of model output or file paths. Access is limited to analysts and
  approvers; nothing else redacts it.
- `Resume all failed` can start many runs at once; the server's lease returns 409 for a run already
  running, and runs are started one request at a time, not in parallel.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | a batch run whose worker raises `ValueError("boom")` for company `C1` | the run finishes | the errors file has a row with `key` `C1`, `error` `boom`, and a `traceback` that contains `Traceback (most recent call last)` and `ValueError: boom` | unit |
| AC-2 | a worker that raises `ReviewRequired` | the run finishes | that error row still has `review` true and `report`, and has no `traceback` key | unit |
| AC-3 | a worker whose exception text makes its traceback longer than 8,000 characters | the run finishes | the stored company `traceback` is exactly the last 8,000 characters of the formatted traceback | unit |
| AC-4 | a launched job that raises `RuntimeError("provider down")` | the job ends | the manifest status is `failed` with `error` `RuntimeError: provider down` | unit |
| AC-5 | the same job | the job ends | the run's events are exactly one row, with `type` `run_failed`, an `at` that `datetime.fromisoformat` parses and that has a timezone offset, and a `traceback` containing `RuntimeError: provider down` | unit |
| AC-6 | a job raising an exception whose traceback is longer than 8,000 characters | the job ends | the `run_failed` event's `traceback` is exactly the last 8,000 characters of the formatted traceback | unit |
| AC-7 | the event store raising on append during that failure | the job ends | the manifest is `failed` with `error` `RuntimeError: provider down` and the job runner returns without raising to the code that started the job | unit |
| AC-8 | the failed run of AC-4 and an analyst | `GET /api/runs/<id>/failure` | status 200 and body `run_id` the run's id, `status` `failed`, `error` `RuntimeError: provider down`, `traceback` containing `RuntimeError: provider down`, `company_errors` `[]` | unit |
| AC-9 | a run with errors-file rows `C1` (`error` `boom1`, traceback containing `ValueError: boom1`), `C2` (`error` `boom2`, traceback containing `ValueError: boom2`) and a `review: true` row for `C3` | `GET /api/runs/<id>/failure` | `company_errors` has exactly two entries, keys `C1` then `C2`, with those `error` values and tracebacks | unit |
| AC-10 | an errors-file row for `C4` with no `traceback` key (written before this change) | `GET /api/runs/<id>/failure` | the `C4` entry has `error` as stored and `traceback` null | unit |
| AC-11 | errors-file rows `C1` (`error` `first`), `C2`, then `C1` again (`error` `second`) | `GET /api/runs/<id>/failure` | `company_errors` has two entries, `C1` (`error` `second`) then `C2` | unit |
| AC-12 | a run with two `run_failed` events whose tracebacks contain `T1` then `T2` | `GET /api/runs/<id>/failure` | `traceback` is the second one (contains `T2`, not `T1`) | unit |
| AC-13 | a failed run created before this change (no event rows), `manifest.error` `Boom: x` | `GET /api/runs/<id>/failure` | status 200, `error` `Boom: x`, `traceback` null | unit |
| AC-14 | a completed run with no errors | `GET /api/runs/<id>/failure` | status 200, `status` `completed`, `error` null, `traceback` null, `company_errors` `[]` | unit |
| AC-15 | no run `nope` | `GET /api/runs/nope/failure` | status 404 and `detail` `Run not found` | unit |
| AC-16 | a viewer token | `GET /api/runs/<id>/failure` for the failed run | status 403 | unit |
| AC-17 | an analyst token and an approver token | the same request | status 200 for both | unit |
| AC-18 | a run whose errors file has a row with a `traceback` | `GET /api/runs/<id>/errors` with a viewer token | status 200, each row keeps its `key` and `error` values, and no row has a `traceback` key | unit |
| AC-19 | a failed extraction run, a `partially_completed` theme run, a failed `holdings` run, a `cancelled` tnfd run, a `running` extraction run and a completed financials run in Run History | the page is opened, logged in as a viewer and again as an analyst | in both cases the first three rows each have a button named `Details for <run_id>` with `aria-expanded` `false`; the last three have no button whose name starts `Details for` | evaluator |
| AC-20 | the failed extraction row; failure response `error` `RuntimeError: provider down`, traceback `Traceback (most recent call last): ... RuntimeError: provider down`, company errors `C1: boom` | Details is clicked | `aria-expanded` is `true`, exactly one `GET /api/runs/<id>/failure` was sent, and under the row the error line, a `<pre>` with the traceback text and the item `C1: boom` appear in that order | evaluator |
| AC-21 | that open row | Details is clicked again | `aria-expanded` is `false` and the details are not visible | evaluator |
| AC-22 | that closed row | Details is clicked a third time | a second `GET /api/runs/<id>/failure` is sent (two in total) and the details are visible again | evaluator |
| AC-23 | the failure response has `traceback` null | Details is clicked | the text `No traceback was recorded for this run.` is shown and no `<pre>` is present | evaluator |
| AC-24 | the failure response has `error` null, `company_errors` `[]` and `traceback` `T1` | Details is clicked | no error line and no company list are present, and a `<pre>` containing `T1` is shown | evaluator |
| AC-25 | the failure response has 62 company errors | Details is clicked | 50 items are listed and the text `and 12 more` is shown | evaluator |
| AC-26 | logged in as a viewer; the failure request answers 403 with detail `Forbidden` | Details is clicked | a `role="alert"` element under the row reads `403: Forbidden` | evaluator |
| AC-27 | four listed runs: `A` failed (extraction), `B` partially_completed (theme), `C` completed (financials), `D` failed (holdings); `extraction` and `theme` are resumable types, `holdings` is not | Run History is opened | the toolbar has a button named `Resume all failed (2)` | evaluator |
| AC-28 | only completed and cancelled runs listed | Run History is opened | no button whose name starts `Resume all failed` is present | evaluator |
| AC-29 | the list of AC-27 and answers `ok` for every resume | the toolbar button is clicked | `POST /api/runs/A/resume` then `POST /api/runs/B/resume` are sent, nothing is sent for `C` or `D`, and exactly one list reload follows | evaluator |
| AC-30 | `A`'s resume answer held until released | the toolbar button is clicked | no `POST /api/runs/B/resume` is sent before `A`'s answer is released, and it is sent after | evaluator |
| AC-31 | the run-type filter set to extraction before the click | the toolbar pass ends | the one list reload uses the same filter as the list before the click | evaluator |
| AC-32 | `B` answers 409 `busy`, `A` answers ok | the button is clicked and the reload finishes | both POSTs were sent and a `role="alert"` element reads `Resumed 1 of 2. Refused: B: 409: busy` | evaluator |
| AC-33 | `A` answers 409 `busy` and `B` answers 500 `down` | the button is clicked | the alert reads `Resumed 0 of 2. Refused: A: 409: busy; B: 500: down` | evaluator |
| AC-34 | every resume answers ok and the reloaded list has no failed rows | the button is clicked and the reload finishes | the alert reads `Resumed 2 of 2.` and is still visible | evaluator |
| AC-35 | the resume responses held for 2 seconds | the toolbar button is clicked twice within 200 ms | each of `A` and `B` receives exactly one POST | evaluator |
| AC-36 | the per-row Resume of `A` in flight (its answer held) | the page is inspected | the toolbar button and every per-row `Resume run` button are disabled | evaluator |
| AC-37 | errors-file rows `C1` (`error` `first`), `C1` (`review: true`), then `C2` | `GET /api/runs/<id>/failure` | `company_errors` is `C1` (`error` `first`) then `C2` | unit |
| AC-38 | `A`'s resume request aborted at the network level, `B` answers ok | the toolbar button is clicked | the alert reads `Resumed 1 of 2. Refused: A: Failed to fetch` | evaluator |
| AC-39 | a pass in flight (`A`'s answer held) | the page is inspected, then the answer is released and the list reloads with `B` still failed | while held, the toolbar button and every per-row `Resume run` button are disabled; after the reload the per-row button of `B` and the toolbar button are enabled | evaluator |

Must not change (each also a row):

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-40 | a failed extraction run `X` with `error` `RuntimeError: provider down` and 3 failed companies | Run History is opened | its row has a button named `Resume run X`, a `.run-error` element reading `RuntimeError: provider down`, and the text `3 companies failed` | evaluator |
| AC-41 | the PR | its changed-file list is inspected | `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts` and `frontend/src/api/contract.ts` are listed, and no file under `frontend/src/pages` other than `RunHistory.tsx` is listed | evaluator |
| AC-42 | the branch | the backend suite and `npm test` run | both pass | unit |
| AC-43 | the PR | the diff of existing test files is inspected | no existing test line is removed or changed, and any assertion that had to change is listed in the PR description | evaluator |
