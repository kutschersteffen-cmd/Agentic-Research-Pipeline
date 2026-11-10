# Argus steps 4 Extract and 5 Results (slice 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After Start, the flow moves to step 4 (`#/argus/<flow_id>/4`), which shows the run live per company with Stop, Retry and Replace file, and then to step 5 (`#/argus/<flow_id>/5`), which lists every extracted value with its decision, lets the user review in place, open the cited page, filter to what needs them and download a CSV. The old Extraction screen is no longer needed to follow or review an Argus run.

**Architecture:** One read endpoint, `GET /api/argus/flows/{id}/progress`, joins what already exists: the run manifest (`created_at`, counts, `estimated_cost_usd`, status, `cancel_requested`), `GET /api/extraction/runs/{id}/companies` statuses, the live step tally (`orchestration/step_tally.py`, same process as the API's background task) and the run's error rows. It maps them to the spec's fixed statuses. Stop is the existing `POST /api/runs/{id}/cancel`. Retry adds a company filter to the existing resume path. Step 5 reads `GET /api/extraction/runs/{id}/results` plus `GET /api/review/items?run_id=` and decides through the existing item decision endpoint (`ReviewControls` with `item`). The CSV is the existing `GET /api/runs/{id}/export.csv`. The source panel is the existing `SourcePanel` with the `CitationList` source shape.

**Tech Stack:** FastAPI + pydantic, React 19 + TypeScript, `node:test`, pytest + Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` ("Step 4: Extract", "Step 5: Results", slice 5). Builds on slices 2 to 4 (`arp/argus/*`, `ArgusFlow.tsx`, `ArgusSchema.tsx`, `lib/argusFlow.ts`).

## Global Constraints

- Exact copy:
  - Step 4 header: `Started <HH:MM> · <done> of <N> done · about <m> minutes left · $<cost> so far`, with `Stop`. Until the first company finishes, the time part reads `estimating time left`.
  - Statuses: `Waiting`, `Reading documents`, `Extracting`, `Checking the answers`, `Done`, `Stopped`, `Failed`.
  - Failure: the reason in words, with `Retry`, and for a document problem `Replace file`. A document with no text reads `No text could be read from <file name>`.
  - Step 5: `Only what needs me`, `Download CSV`. Per row: `Approve` / `Edit` / `Reject`; for a not-found value `Confirm not disclosed` / `Enter value`.
- Status mapping:
  - `done` and `review` → `Done` (what needs the user shows in the row).
  - `failed` → `Failed`.
  - `waiting` with the run `cancelled` → `Stopped`.
  - `waiting` with no step counted yet → `Waiting`.
  - Otherwise by the last step counted: `parse_index` / `gather_evidence` → `Reading documents`; `extract` → `Extracting`; `verify` / `adjudicate` / `aggregate` / `rules` → `Checking the answers`.
  - Progress bar: steps counted out of the run's step list; 100% when `Done`.
- `done` = completed + failed. Time left = elapsed × (N − done) ÷ done, rounded up to whole minutes.
- **Unreadable documents fail the company.** In a run with a kept-files list (Argus), a kept document with no extractable text fails that company with `No text could be read from <file name>`. That error is marked as a document problem. Runs without a kept-files list are unchanged.
- **Retry** (analyst) re-runs one failed company inside the same run. It re-reads that company's kept files from the flow first, so a file replaced in step 2 is used. It returns 409 while the run is running, because other companies are still in flight. Replace file opens step 2; the user uploads the new file, removes the old one, comes back and clicks Retry.
- **Confirm not disclosed** posts `reject` with reason `not_disclosed` if `DecisionReason` has it, else the nearest existing reason. The PR names the one used. **Enter value** posts `correct` with the typed value.
- **Conflict rows** (`Accepted:` / `New:`) are not in this slice: conflicts are created by data rule slice 7.
- After Start, step 3 now goes to step 4 of the flow, not `#/argus`. On the start page, a run that has a flow opens that flow's step 4 or 5, not the old Extraction screen. When the run is no longer pending or running, the flow's `step` becomes 5.
- After response models change: export OpenAPI, `npm run gen:api`, commit both.
- Delivers AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-72, and AC-9 for steps 4 and 5.

## Review Focus

1. **Status mapping edge cases:**
   - a run cancelled after some companies finished (`Done` stays `Done`, the rest `Stopped`);
   - a pending run (all `Waiting`);
   - the API restarted mid-run, so the live tally is gone (show `Waiting` / `Done` / `Failed` from persisted data, never crash);
   - a review stop (`review` → `Done`, with the review shown in "what needs you").
2. **The no-text rule must not change other runs.** Prove an existing extraction test with an empty document passes unchanged without the kept-files list.
3. **Retry must not double count:** `failed_count` goes down when the retried company succeeds or fails again. Retry of a company that is not failed → 400.
4. **Step 5 decisions use the item endpoint with `context_etag`.** A stale etag (someone else decided) shows the existing error, not a silent overwrite.
5. **Polling stops** once the run is final; leaving step 4 and coming back resumes it.

---

### Task 1: Progress endpoint and status mapping

**Files:** Create `backend/arp/argus/progress.py`; Modify `backend/arp/api/routers/argus.py`; Test `backend/tests/test_argus_progress.py`

**Produces:** `company_status(company_status, run_status, last_step, error) -> (status, percent, reason, document_problem)`; `GET /api/argus/flows/{id}/progress` → `{started_at, done, total, minutes_left, cost_usd, status, companies: [{company_id, name, status, percent, reason, document_problem, needs_you}]}`.

- [ ] Tests for every mapping row in Global Constraints, the time-left arithmetic, a cancelled run, a restarted API (no tally), a flow with no run (404). Implement, pass, commit.

### Task 2: No text fails the company (Argus runs only)

**Files:** Modify the kept-files path (`arp/ingestion/registry.py` `KeptDocuments` or where parsed text is first available in `arp/extraction/pipeline.py`); Test `backend/tests/test_argus_no_text.py`

- [ ] Tests: with a kept-files list, a kept PDF with no text fails the company with `No text could be read from a.pdf`, and the error row carries `document_problem: true`; without the list, an existing empty-document extraction test passes unchanged. Implement, pass, commit.

### Task 3: Retry one company

**Files:** Modify `backend/arp/orchestration/jobs.py` (`resume_run(..., company_ids=None)`), `backend/arp/api/routers/argus.py` (`POST /flows/{id}/companies/{company_id}/retry`); Test `backend/tests/test_argus_retry.py`

- [ ] Tests: retry runs only that company, clears its error row, adjusts `failed_count`, and uses the flow's current kept files (`only_documents.json` rewritten for it); 409 while running; 400 for a company that did not fail; an existing resume test passes unchanged. Implement, pass, commit.

### Task 4: Frontend model for steps 4 and 5

**Files:** Modify `frontend/src/lib/argusFlow.ts`; Test `frontend/tests/argusFlow.test.ts` (append)

**Produces:** `progressHeader(p): string`, `resultRows(results, items, decisions): Row[]` (one row per value: company, field, value, source page, decision, `needsYou`, `notFound`), sorted with `needsYou` first, and `onlyNeedsYou(rows)`.

- [ ] Tests: the header with and without a finished company; 7 rows with 2 to review → the 2 first, and the filter keeps exactly 2 (AC-40, AC-41); a not-found review row has `notFound`. Implement, pass, commit.

### Task 5: Steps 4 and 5 on the flow page

**Files:** Create `frontend/src/pages/ArgusExtract.tsx`, `frontend/src/pages/ArgusResults.tsx`; Modify `ArgusFlow.tsx` (route steps 4 and 5, step bar links), `ArgusSchema.tsx` (after Start go to step 4), `lib/argusStart.ts` (start page opens a run's flow step), `api/client.ts`, `index.css` (`.argus-progress*`, `.argus-results*`); e2e `backend/tests/e2e/test_argus_steps45.py`

- [ ] Step 4:
  - the header, Stop and a company table with status, bar, needs-you and reason;
  - Retry and Replace file on failed rows;
  - polls every 2.5 s while the run is active, and offers `See results` once it is final.
- [ ] Step 5:
  - the table, with `Only what needs me` and `Download CSV` (`api.exportRunCsvUrl`);
  - `ReviewControls` with `item` for rows to review, and `Confirm not disclosed` / `Enter value` for not-found rows;
  - a click on a source opens `SourcePanel` at the page with the quote.
- [ ] E2E: on CI's key-less stack, use a run made through the existing fixtures or seed path (no model call) to check steps 4 and 5 render from stored data. A key-gated test drives a live trial (skips without a key, like step 3's).
- [ ] Checks and wrap-up:
  - `npm run lint && npx tsc -b && npm test`, backend ruff and tests, the e2e tests;
  - light and dark screenshots of steps 4 and 5 in `docs/design-shots/`, and `/impeccable:impeccable audit`;
  - commit, push, PR with `Spec: argus-simplified-pipeline` and `risk:normal`.
