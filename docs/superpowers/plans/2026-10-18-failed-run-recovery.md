# Failed-Run Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resume works for every resumable run type from the progress panel, Run History and "Needs you", and failed runs appear in "Needs you".

**Architecture:** Frontend only. Pure helpers in `lib/runs.ts` decide what is resumable and what needs attention. One small hook, `lib/useResume.ts`, owns the click, the in-flight lock and the error text for Run History and "Needs you". The progress panel keeps its own handler and only swaps the helper and the API call.

**Tech Stack:** React 19, TypeScript, Vite, `node:test` for helper tests (`npm test`), oxlint.

**Spec:** `docs/superpowers/specs/2026-10-18-failed-run-recovery-design.md` (approved by the owner 2026-10-18). Row IDs below (AC-n) are that spec's.

## Global Constraints

- Frontend only: no path under `backend/` changes; `frontend/src/api/openapi.json`, `schema.gen.ts`, `contract.ts` and `frontend/src/App.tsx` stay untouched (AC-50).
- Resumable types, exactly: `theme`, `extraction`, `financials`, `tnfd`, `transition_plan`, `identity`, `discovery`, `xbrl_fetch`.
- Resumable statuses, exactly: `failed`, `partially_completed`, `cancelled`. "Needs you" shows only `failed` and `partially_completed`, updated at most 14 days (14 x 24 h) before `now`.
- The one endpoint is `POST /api/runs/{run_id}/resume`. The error text shown is the client's `Error.message`, which is `<status>: <detail>`.
- Button accessible names: progress panel `Resume run`; Run History and "Needs you" `Resume run <run_id>`.
- No new dependency. Never delete or weaken an existing test.
- Checks: `cd frontend && npm run lint && npx tsc -b && npm test`.

## Review Focus

- A run whose `updated_at` is after `now` (clock skew) must still show in "Needs you" (AC-52).
- A run with `company_count` 0 must not render `(0/0 companies done)` (AC-29).
- A double click on any Resume button must send one request (AC-16, AC-23, AC-36).
- A resume that fails with a server error must leave the button enabled and show `<status>: <detail>` (AC-38 to AC-45).
- Run History reloads with the filter that is active when the resume finishes, not the one at mount.

## File Structure

- Modify `frontend/src/lib/runs.ts`: add `RESUMABLE_RUN_TYPES`, `canResumeRun`, `needsAttentionRuns`.
- Create `frontend/tests/runs.test.ts`: helper tests.
- Create `frontend/src/lib/useResume.ts`: the shared resume hook.
- Modify `frontend/src/api/client.ts:537`: replace `resumeThemeRun` with `resumeRun`.
- Modify `frontend/src/components/RunProgress.tsx`: use the helper and `resumeRun`.
- Modify `frontend/src/pages/RunHistory.tsx`: Resume button per row.
- Modify `frontend/src/components/NeedsYou.tsx` and `frontend/src/index.css`: failed-run rows.

### Task 1: Helpers in `lib/runs.ts`

**Files:**
- Modify: `frontend/src/lib/runs.ts`
- Test: `frontend/tests/runs.test.ts` (create)

**Interfaces:**
- Produces: `RESUMABLE_RUN_TYPES: ReadonlySet<string>`; `canResumeRun(runType: string, status: string): boolean`; `needsAttentionRuns(runs: RunManifest[], now: Date): RunManifest[]`; `NEEDS_ATTENTION_DAYS = 14`.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/runs.test.ts` (same `node:test` + `assert/strict` style as `tests/jobs.test.ts`, importing from `../src/lib/runs.ts`). Test names and assertions, one per spec row:
  - `canResumeRun is true for all 8 resumable types x failed, partially_completed, cancelled` (24 pairs, AC-1)
  - `canResumeRun is false for resumable types x completed, running, pending` (24 pairs, AC-2)
  - `canResumeRun is false for proxy_voting, holdings, emerging_themes, taxonomy_research, calibration, transition_barrier_refresh x failed, partially_completed, cancelled` (18 pairs, AC-3)
  - `needsAttentionRuns drops cancelled, completed, running, pending` (each resumable type, updated 1 hour before `now`; result `[]`, AC-4)
  - `needsAttentionRuns drops non-resumable types` (`holdings` failed, `proxy_voting` partially_completed; `[]`, AC-5)
  - `needsAttentionRuns keeps exactly 14 days, drops 14 days and 1 second` (AC-6)
  - `needsAttentionRuns returns failed and partially_completed in input order` (AC-7)
  - `needsAttentionRuns drops empty and unparseable updated_at` (`""`, `"not a date"`; `[]`, AC-8)
  - `needsAttentionRuns keeps a run updated 1 minute after now` (AC-52)

  Build runs with a small local helper `run(type, status, updatedAt)` that casts a partial object to `RunManifest`.
- [ ] **Step 2: Run to verify failure.** `cd frontend && node --test --experimental-strip-types tests/runs.test.ts`. Expected: FAIL, the three exports are missing.
- [ ] **Step 3: Implement** the three exports and the constant in `lib/runs.ts`. `needsAttentionRuns` compares `now.getTime() - Date.parse(r.updated_at)` with `14 * 24 * 3600 * 1000` (at most; negative values pass) and drops `NaN`.
- [ ] **Step 4: Run to verify pass.** Same command. Expected: all tests pass.
- [ ] **Step 5: Commit.** `git add frontend/src/lib/runs.ts frontend/tests/runs.test.ts && git commit -m "Add canResumeRun and needsAttentionRuns helpers"`

### Task 2: Client call, shared hook, progress panel

**Files:**
- Modify: `frontend/src/api/client.ts:537`
- Create: `frontend/src/lib/useResume.ts`
- Modify: `frontend/src/components/RunProgress.tsx` (lines 7, 78-90, 107)

**Interfaces:**
- Consumes: `canResumeRun` (Task 1).
- Produces: `api.resumeRun(runId: string)`; `useResume(): { busyId: string | null; error: { runId: string; message: string } | null; resume: (runId: string, after?: () => void | Promise<void>) => Promise<void> }`.

- [ ] **Step 1: Replace** `resumeThemeRun` in `client.ts` with `resumeRun: (runId: string) => request(\`/api/runs/${runId}/resume\`, { method: "POST" })`. `RunProgress.tsx` is its only caller.
- [ ] **Step 2: Create `useResume`.** `resume` returns at once if a request is in flight (check a `useRef` lock, so a second click before re-render is ignored), sets `busyId`, clears `error`, awaits `api.resumeRun(runId)`, then awaits `after` if given; on a throw it sets `error = { runId, message: (err as Error).message }`; it always clears the lock and `busyId`.
- [ ] **Step 3: Progress panel.** Replace `RESUMABLE_STATUSES`/`runType === "theme"` with `canResumeRun(runType, manifest.status)` (remove the now-unused set); in `resumeRun()` call `api.resumeRun(runId)`. Keep the button text `Resume run`, the `actionBusy` disabling and the `role="alert"` paragraph.
- [ ] **Step 4: Verify.** `cd frontend && npm run lint && npx tsc -b && npm test`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "Resume any resumable run type from the progress panel"` (add `lib/useResume.ts` first).

### Task 3: Run History Resume button

**Files:**
- Modify: `frontend/src/pages/RunHistory.tsx`

**Interfaces:**
- Consumes: `canResumeRun`, `useResume`; its own `load()` (reloads with the current `filter`).

- [ ] **Step 1: In the last column**, after the existing links, render for rows where `canResumeRun(r.run_type, r.status)`: `<button className="link-button" aria-label={\`Resume run ${r.run_id}\`} disabled={busyId !== null} onClick={() => resume(r.run_id, load)}>Resume</button>`.
- [ ] **Step 2: Show the error** in the existing `role="alert"` paragraph above the table: `{(error ?? resumeError?.message) && ...}` (the hook's message is `<status>: <detail>` already; do not prefix it).
- [ ] **Step 3: Verify.** Lint, `npx tsc -b`, `npm test`. Expected: pass.
- [ ] **Step 4: Commit.** `git commit -am "Add Resume to Run History rows"`

### Task 4: Failed runs in "Needs you"

**Files:**
- Modify: `frontend/src/components/NeedsYou.tsx`, `frontend/src/index.css` (near line 1732)

**Interfaces:**
- Consumes: `needsAttentionRuns`, `useResume`, `runTypeLabel`, the existing `WORKSPACE` map and `Row` list.
- Produces: rows with an optional `resumeRunId` field; the renderer shows a Resume button for them.

- [ ] **Step 1: Add rows.** For each run in `needsAttentionRuns(runs ?? [], new Date())` push a `Row` with: `key` `failed/<run_id>`, `workspace` `WORKSPACE[type] ?? "Review"`, `count` 1, `since` `run.updated_at`, `href` `#/history`, `resumeRunId` `run.run_id`, and `what` `<runTypeLabel> run <id>: <failed|partially completed>` plus ` (<completed_count>/<company_count> companies done)` only when `company_count > 0`.
- [ ] **Step 2: Render.** In the list, a row with `resumeRunId` renders `<li>` containing the existing `<a>` and, as a sibling after it, `<button aria-label="Resume run <id>" disabled={busyId !== null}>Resume</button>`; when `error?.runId` equals the row's run, show `<p role="alert" className="error-text">{error.message}</p>` under the link. The Resume button calls `resume(runId)`; the 3-second runs poll removes the row once the run is `running`. The existing sort and the "Nothing waits on you." branch stay as they are.
- [ ] **Step 3: CSS.** Make `.needs-you-list li` a flex row so the button sits beside the link without nesting; reuse existing button classes; no new colours.
- [ ] **Step 4: Verify.** Lint, `npx tsc -b`, `npm test`.
- [ ] **Step 5: Commit.** `git commit -am "Show failed runs in Needs you with Resume"`

### Task 5: Whole-change verification and handoff

- [ ] **Step 1: Run the checks.** `cd frontend && npm run lint && npx tsc -b && npm test`; then `cd ../backend && python3 -m pytest -q tests/e2e/test_app_smoke.py`. Expected: all pass.
- [ ] **Step 2: Check the diff rules (AC-49, AC-50).** `git diff origin/main --name-only` lists no `backend/` path and none of `openapi.json`, `schema.gen.ts`, `contract.ts`, `App.tsx`; `git diff origin/main --numstat -- frontend/tests` shows only added lines for existing files.
- [ ] **Step 3: Screenshot** Run History and the start page with a seeded failed run (Playwright, per CLAUDE.md) and run `/impeccable:impeccable audit` on both.
- [ ] **Step 4: Push** `ccr-3a859410-lsolbs`. Do not open a PR until the owner asks; every `evaluator` row is checked by a fresh session once CI is green.
