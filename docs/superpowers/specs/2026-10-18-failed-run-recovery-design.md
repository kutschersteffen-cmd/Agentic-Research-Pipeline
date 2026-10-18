# Failed-run recovery: Resume everywhere, and failed runs in "Needs you"

Date: 2026-10-18
Status: approved by the owner 2026-10-18 (spec-critic rounds 1-3 fixed; no fourth round run)
Origin: the 2026-10-17 review of the `setup.sh` script (Celery, dead-letter queue, re-drive) against ARP.
That script's idea worth keeping is "a failed job is visible and one click re-runs it". ARP already has
the engine (`POST /api/runs/{run_id}/resume`); this spec closes the UI gap. Items 1 and 2 of the
review's gap list. The owner skipped the interview, so the choices marked **(my call)** are mine.

## Intent

Someone opens ARP after a weekend and a run has failed. Today:

- The Resume button exists only for thematic runs (`RunProgress.tsx`: `runType === "theme"`), although the
  backend resumes eight run types.
- Run History shows the error text but has no action.
- "Needs you" lists review items, ballots, stewardship stages and blocking data issues, but not failed
  runs. A failed run is seen only by opening Run History.

After this change: a failed or partially completed run of a resumable type shows up in "Needs you", and
can be resumed from there, from Run History and from the run's progress panel, with one click.

## Goals

1. **Resume for every resumable run type** in the run progress panel. Resumable types are the backend's
   `RESUMABLE` set: theme, extraction, financials, tnfd, transition_plan, identity, discovery, xbrl_fetch.
2. **Resume in Run History**: a Resume button in each row whose run is resumable.
3. **Failed runs in "Needs you"**: one row per failed or partially completed run of a resumable type,
   with a Resume button and a link to Run History.
4. The client uses the one endpoint that serves all types, `POST /api/runs/{run_id}/resume`. The theme-only
   client call `resumeThemeRun` is replaced by it; the theme endpoint stays on the server unchanged.
5. A refused or failed resume (400 not resumable, 403 role, 409 run busy) shows the client's error text,
   which is `<status>: <server detail>` (for example `409: busy`), and leaves the button usable.

## Non-goals

- Retrying only the failed companies of a completed run. Resume continues a run; the backend decides what
  is left (completed companies are skipped).
- Any backend change, new endpoint, new table or API contract change. This is frontend only.
- A failed-jobs table with tracebacks, notifications on completion or failure, role-aware hiding of
  buttons, session-expiry prompts. These are later items from the review.
- Showing cancelled runs in "Needs you" **(my call)**: cancelling is something a person chose.
- Run types the backend cannot resume (proxy_voting, holdings, emerging_themes, taxonomy_research,
  calibration, transition_barrier_refresh). They keep today's behaviour and get no Resume button.
- Changing the sidebar in any way.

## Anti-goals (a failure even if it works)

- A failed run that sits in "Needs you" for months. See the 14-day window below.
- A Resume button for a run type or status that `canResumeRun` excludes (a holdings run, a completed run). A run the server still refuses (for example "run has no stored inputs") is shown the button and gets the server's message; see Risks.
- Resume starting a second copy of a run because of a double click.

## Current state (what this builds on)

- `RunProgress.tsx`: `canResume = runType === "theme" && RESUMABLE_STATUSES.has(status)`, with
  `RESUMABLE_STATUSES = {failed, partially_completed, cancelled}`. The click calls
  `api.resumeThemeRun` (`/api/themes/runs/{id}/resume`), then polls. Buttons are disabled while an action
  is in flight (`actionBusy`).
- `RunHistory.tsx`: shows `r.error` and `failed_count`; last column has CSV, Ballot and Review links. It
  loads the list on mount and on filter change; it does not poll.
- `NeedsYou.tsx` (shown on the start page, `ProcessHub.tsx`): builds `Row[]` from review items, proxy
  voting runs, stewardship stages and blocking issues, sorted by `since` (a run's `updated_at`), oldest
  first, rows without a date last. `runs` comes from the app's 3-second poll (`listAllRuns`). Rows are
  `<a>` elements. Meta text is `WORKSPACE[type] ?? "Review"`, then ` · waiting since ` plus
  `new Date(since).toLocaleDateString()`.
- Server: `POST /api/runs/{run_id}/resume` (role `analyst`) returns 404 unknown run, 409 busy, 400
  `NotResumable` ("already completed", "<type> runs are not resumable; start a new run", "run has no
  stored inputs"), otherwise `{run_id, status: "resumed"}`.
- `runTypeLabel(type)` gives the label from `RUN_TYPE_LABEL` (`extraction` is `Data extraction`, `theme` is `Thematic universe`), else the type with `_` replaced by a space
  (so `xbrl_fetch` reads `xbrl fetch`).

## Design

**Shared helpers, `lib/runs.ts`** (new exports, pure functions, unit-tested):

- `RESUMABLE_RUN_TYPES`: the eight types above. It mirrors the backend `RESUMABLE`; the two must change
  together (see Risks).
- `canResumeRun(runType, status)`: true when the type is in `RESUMABLE_RUN_TYPES` and status is one of
  `failed`, `partially_completed`, `cancelled`. (Progress panel and Run History offer Resume after a
  cancel too, as the progress panel does today for theme runs.)
- `needsAttentionRuns(runs, now: Date)`: runs whose type is in `RESUMABLE_RUN_TYPES`, whose status is
  `failed` or `partially_completed`, and whose `updated_at` parses as a date and is at most 14 days (14 x 24 h) before `now` (an `updated_at` after `now`, from clock skew, counts as inside the window)
  **(my call)**. A run with a missing or unparseable `updated_at` is excluded. It returns the matching runs in input order, takes `now` as an argument and never reads the clock.

**Progress panel.** `canResume` becomes `canResumeRun(runType, manifest.status)`. The Resume button's accessible name is exactly `Resume run`. The click calls
`api.resumeRun(runId)` (`POST /api/runs/{id}/resume`). The button is disabled while the request is in
flight, as today. Everything after the click is as today. Error text appears in the existing
`role="alert"` paragraph directly under the toolbar.

**Run History.** In the last column, rows where `canResumeRun` is true get a "Resume" link-style button
(`aria-label="Resume run <run_id>"`), disabled while its request is in flight. Click: call
`api.resumeRun`, then reload the list once (one `GET /api/runs...` after the POST). On error, show the
text in the existing `role="alert"` paragraph above the table.

**Needs you.** One row per `needsAttentionRuns` entry, in the same list and the same ordering as the
other rows (by `updated_at`, oldest first; a review item's date is its run's `updated_at`, as today). Row text (the `.needs-you-what` element):
`<runTypeLabel> run <run_id>: <failed|partially completed> (<completed_count>/<company_count> companies done)`;
when `company_count` is 0 the parenthesis is left out. Count cell: `1`. Meta (the `.needs-you-meta` element): `WORKSPACE[type] ?? "Review"`
(the existing map; today `extraction`, `financials`, `tnfd`, `transition_plan`, `identity` map to `Argus`, `theme` to `R&D Lab`), then
` · waiting since ` plus the date, formatted as the existing rows format theirs. The row is a `<li>`
containing the link to `#/history` and, beside it (not inside the `<a>`), a "Resume" button
(`aria-label="Resume run <run_id>"`), disabled while its request is in flight. After a successful click the
row disappears when the next poll shows the run as `running`; on error the text appears inside the row
under the link, `role="alert"`.

**Client.** `api.resumeRun(runId)` replaces `api.resumeThemeRun`; theme runs now post to
`/api/runs/{id}/resume`. Its response is the plain `{run_id, status}` dict (no response model), so no
line in `frontend/src/api/contract.ts` and no generated-file change.

## Constraints

- Frontend only; follow the existing component style. No new dependency.
- Frontend checks: `npm run lint && npx tsc -b && npm test`.
- Frontend unit tests in this repo cover `lib/` functions only (`frontend/tests/*.test.ts`), so `unit`
  rows below are about the pure helpers; anything a person sees is an `evaluator` row.
- The `HOLDOUT_TOKEN` secret state is not known to the author. The holdout repo holds backend and
  browser tests; for this frontend-only change the pure helpers are `unit` (vitest) and the screens are
  `evaluator`. No row is `holdout`; if the owner wants helper rows in the holdout repo, they must say so.
- **How the evaluator works:** it seeds run manifests in the dev run store (or intercepts the runs-list and
  run-status responses in the browser) so a run has exactly the status and counts a row names. Dates in
  rows are relative (`now - 1 day`), never absolute, as full timestamps. It counts requests and holds or
  fails responses through browser network interception. "Dates as the existing rows format them" means
  `new Date(updated_at).toLocaleDateString()` evaluated in that same browser.
- **Coverage choice:** the progress panel and Run History decide through `canResumeRun` (AC-1 to AC-3), so
  the screens are sampled with a few types (extraction, theme, tnfd, financials, holdings), not all eight.

## Left to the builder

- CSS for the Resume button inside a "Needs you" row, reusing existing classes where possible.
- Whether Run History shows a hint when a run is not resumable (not required).

## Risks

- `RESUMABLE_RUN_TYPES` can drift from the backend `RESUMABLE`. Effect of drift: a missing type shows no
  button; an extra type shows a button the server refuses with a 400 message. Accepted for now; a
  backend field (`resumable: bool` on the manifest list) would remove it and is a later change.
- Resume is role `analyst`. A viewer sees the button and gets `403: ...`. Role-aware hiding is a separate
  item.
- Failed rows for `discovery` and `xbrl_fetch` runs show meta `Review`, because the existing workspace map
  has no entry for them. Accepted; naming their workspace is a later change.

## Acceptance

`<run_id>` is the seeded run's id. "Panel" is the run progress panel. "Status pill" is the `.status-pill`
element. Every row that says "exactly one POST" means one `POST /api/runs/<run_id>/resume`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `canResumeRun` | called with each of the 8 resumable types and each status in `failed`, `partially_completed`, `cancelled` | returns `true` for all 24 pairs | unit |
| AC-2 | `canResumeRun` | called with each of the 8 resumable types and each status in `completed`, `running`, `pending` | returns `false` for all 24 pairs | unit |
| AC-3 | `canResumeRun` | called with each of `proxy_voting`, `holdings`, `emerging_themes`, `taxonomy_research`, `calibration`, `transition_barrier_refresh` and each status in `failed`, `partially_completed`, `cancelled` | returns `false` for all 18 pairs | unit |
| AC-4 | `needsAttentionRuns(runs, now)` | given resumable-type runs with status `cancelled`, `completed`, `running`, `pending`, each updated 1 hour before `now` | returns none of them | unit |
| AC-5 | `needsAttentionRuns(runs, now)` | given a `failed` `holdings` run and a `partially_completed` `proxy_voting` run, each updated 1 hour before `now` | returns none of them | unit |
| AC-6 | `needsAttentionRuns(runs, now)` | given a `failed` resumable run updated exactly 14 days before `now`, and another updated 14 days and 1 second before `now` | returns the first and not the second | unit |
| AC-7 | `needsAttentionRuns(runs, now)` | given one `failed` and one `partially_completed` resumable run, each updated 1 day before `now` | returns both runs, in the same order as the input | unit |
| AC-8 | `needsAttentionRuns(runs, now)` | given a `failed` resumable run whose `updated_at` is the empty string, and another whose `updated_at` is `"not a date"` | returns neither | unit |
| AC-9 | a `failed` extraction run | its panel is shown | a button with accessible name `Resume run` is visible | evaluator |
| AC-10 | that panel | the button is clicked | exactly one POST is sent | evaluator |
| AC-11 | that click, then the status endpoint returns `running` | the next status refresh arrives | the status pill reads `running` | evaluator |
| AC-12 | the same state as AC-11 | the next status refresh arrives | no button named `Resume run` is present | evaluator |
| AC-13 | a `failed` `theme` run | `Resume run` is clicked in its panel | exactly one POST is sent and no request goes to `/api/themes/runs/<run_id>/resume` | evaluator |
| AC-14 | a `cancelled` `tnfd` run | its panel is shown | a button named `Resume run` is visible | evaluator |
| AC-15 | a `failed` `holdings` run | its panel is shown | no button named `Resume run` is present | evaluator |
| AC-16 | the resume response held for 2 seconds | the panel's Resume button is clicked twice within 200 ms | exactly one POST is sent | evaluator |
| AC-17 | a `failed` `financials` run in the run list | Run History is opened | its row has a button with accessible name `Resume run <run_id>` | evaluator |
| AC-18 | a `completed` `financials` run in the run list | Run History is opened | its row has no button with an accessible name starting `Resume run` | evaluator |
| AC-19 | a `cancelled` `tnfd` run in the run list | Run History is opened | its row has a button named `Resume run <run_id>` | evaluator |
| AC-20 | a `failed` `holdings` run in the run list | Run History is opened | its row has no button with an accessible name starting `Resume run` | evaluator |
| AC-21 | the row of AC-17 | its button is clicked | exactly one POST is sent, followed by exactly one repeat of the list request Run History makes on load (same path and query) | evaluator |
| AC-22 | that repeat returns the run as `running` | the list renders | that row's status pill reads `running` | evaluator |
| AC-23 | the resume response held for 2 seconds | the row's button is clicked twice within 200 ms | exactly one POST is sent | evaluator |
| AC-24 | a `failed` extraction run, 3 of 10 companies done, updated `now - 1 day` | the start page is opened | its row's `.needs-you-what` element reads `Data extraction run <run_id>: failed (3/10 companies done)` | evaluator |
| AC-25 | that row | the start page is opened | its `.needs-you-count` element reads `1` | evaluator |
| AC-26 | that row | the start page is opened | its `.needs-you-meta` element reads `Argus · waiting since ` followed by `new Date(updated_at).toLocaleDateString()` | evaluator |
| AC-27 | that row | the start page is opened | its link's `href` ends with `#/history` | evaluator |
| AC-28 | a `partially_completed` theme run, 7 of 10 done, updated `now - 1 day` | the start page is opened | its `.needs-you-what` element reads `Thematic universe run <run_id>: partially completed (7/10 companies done)` | evaluator |
| AC-29 | a `failed` `xbrl_fetch` run with `company_count` 0, updated `now - 1 day` | the start page is opened | its `.needs-you-what` element reads `xbrl fetch run <run_id>: failed` | evaluator |
| AC-30 | that run | the start page is opened | its `.needs-you-meta` element reads `Review · waiting since ` followed by `new Date(updated_at).toLocaleDateString()` | evaluator |
| AC-31 | the row of AC-24 | its Resume button is clicked | exactly one POST is sent and the URL hash is unchanged | evaluator |
| AC-32 | the row of AC-24 | its link is clicked | the URL hash becomes `#/history` | evaluator |
| AC-33 | the click of AC-31, then the runs poll returns the run as `running` | the next poll arrives | no row mentioning `<run_id>` is present | evaluator |
| AC-34 | failed run A updated `now - 5 days`, a review item whose run was updated `now - 3 days`, failed run B updated `now - 1 day` | the start page is opened | the rows appear top to bottom as A, the review item, B | evaluator |
| AC-35 | a `cancelled` `tnfd` run and a `failed` `holdings` run, each updated `now - 1 hour` | the start page is opened | no row mentions either run id | evaluator |
| AC-36 | the resume response held for 2 seconds | a "Needs you" Resume button is clicked twice within 200 ms | exactly one POST is sent | evaluator |
| AC-37 | no review items, ballots, stages or blocking issues, and only runs that are `completed`, `running` or `cancelled`, each updated `now - 1 hour`, plus a `failed` extraction run updated `now - 15 days` | the start page is opened | the text `Nothing waits on you.` is shown | evaluator |
| AC-38 | the server answers the resume call with 409 and detail `busy` | Resume is clicked in the panel | a `role="alert"` element in the panel reads `409: busy` | evaluator |
| AC-39 | the same answer | Resume is clicked in Run History | the `role="alert"` paragraph above the table reads `409: busy` | evaluator |
| AC-40 | the same answer | Resume is clicked in a "Needs you" row | a `role="alert"` element inside that row reads `409: busy` | evaluator |
| AC-41 | the server answers with 400 and detail `already completed` | Resume is clicked in the panel | a `role="alert"` element in the panel reads `400: already completed` | evaluator |
| AC-42 | the server answers with 403 and detail `Forbidden` | Resume is clicked in the panel | a `role="alert"` element in the panel reads `403: Forbidden` | evaluator |
| AC-43 | the 409 answer of AC-38 | the error is shown in the panel | the panel's Resume button is enabled | evaluator |
| AC-44 | the 409 answer of AC-39 | the error is shown in Run History | that row's Resume button is enabled | evaluator |
| AC-45 | the 409 answer of AC-40 | the error is shown in the "Needs you" row | that row's Resume button is enabled | evaluator |
| AC-51 | a `failed` extraction run updated `now - 15 days` | the start page is opened | no row mentions its run id | evaluator |
| AC-52 | `needsAttentionRuns(runs, now)` | given a `failed` resumable run updated 1 minute after `now` | returns it | unit |

Must not change (each also a row):

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-46 | a `running` extraction run | its panel is shown | a button named `Cancel run` is present and no button with an accessible name starting `Resume run` | evaluator |
| AC-47 | a `failed` extraction run | its panel is shown | no button named `Cancel run` is present | evaluator |
| AC-48 | a `failed` extraction run with error `boom` and `failed_count` 2 | Run History is opened | its `.run-error` element reads `boom`, its progress cell contains `2 companies failed`, and its row still has a CSV link | evaluator |
| AC-49 | the branch | `npm test` in `frontend/` and `pytest tests/e2e/test_app_smoke.py` in `backend/` are run, and `git diff origin/main` is inspected for test files | both pass, and the diff of existing test files has no removed lines | unit (CI) |
| AC-50 | the branch | `git diff origin/main --name-only` is run | no path starts with `backend/`; none of `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`, `frontend/src/api/contract.ts`, `frontend/src/App.tsx` is listed | unit (CI) |
| AC-53 | a `failed` extraction run updated `now - 1 hour` | the app is opened | the sidebar's entries and count badges are identical to the same page with that run `completed` | evaluator |
| AC-54 | a `proxy_voting` run with `review_count` 2, updated `now - 1 day` | the start page is opened | its row's `.needs-you-what` element reads `Proxy voting run <run_id>: 2 ballots to decide` and its `.needs-you-meta` element starts with `StewardIQ · waiting since ` | evaluator |
| AC-55 | that row | the start page is opened | the row contains no button with an accessible name starting `Resume run` | evaluator |
