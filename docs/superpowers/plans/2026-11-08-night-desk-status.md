# Night Desk Release 2 (status lines, running colour, rounded cards, sidebar dots) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show one coloured status line per workspace step, a blue running colour, rounded start-page cards, and a status dot per workspace in the sidebar.

**Architecture:** Two pure functions in `frontend/src/lib/workspaceCard.ts` (`stepStatusLine`, `workspaceState`) built on the existing `stepState`/`processState`; `ProcessHub.tsx` and `App.tsx` render their output; CSS in `index.css`. No backend change.

**Tech Stack:** React + TypeScript, CSS custom properties, `node --test --experimental-strip-types`.

**Spec:** `docs/superpowers/specs/2026-11-08-night-desk-status-design.md`

## Global Constraints

- `--run`: light `#2563c9`, both dark blocks `#6cb4ff`.
- Status texts exactly as the spec table: `"<n> waiting on you"`, `"<n> decisions open"` / `"1 decision open"`, `"Running"`, `"Last run failed"`, `"Done · <d MMM>"`, `"No runs yet"`.
- The only new amber-token reference is the `.nav-dot-wait` rule.
- `stepState`, `processState`, `cardView` are not changed.
- `.touchpad button`, `.grl-dn`, `.view-toggle button:last-child` keep their radius.

## Review Focus

- `App.tsx`'s runs list is capped at the 50 most recent: an older waiting run won't light the sidebar dot. Ledger it in the PR; no test.
- Runs start as `[]` in `App.tsx`, not `null`: without a separate loaded flag the sidebar would show "idle" (no dots) while loading, which happens to satisfy AC-18b; the test asserts the helper returns no dot for `null`.
- A step with `waiting > 0` and state `failed` must read "N waiting on you" (waiting wins): AC-4-style test with state `failed`.
- `Done · <date>` depends on locale/TZ: the test pins `en-GB`/`UTC` by passing the date and formatting with an explicit locale argument.
- Release-1 test `ac13_amber_usage_unchanged` will fail on this PR's new `.nav-dot-wait` line unless its allow-list is extended (spec AC-20).

---

### Task 1: Pure status helpers

**Files:**
- Modify: `frontend/src/lib/workspaceCard.ts` (append)
- Test: `frontend/tests/workspaceCard.test.ts` (append)

**Interfaces:**
- Produces:
  - `type StatusTone = "wait" | "now" | "failed" | "done" | "idle"`
  - `stepStatusLine(state: StepState, waiting: number, decisions: number, lastUpdated: string | null, locale?: string): { text: string; tone: StatusTone }` — `locale` defaults to `undefined` (browser); tests pass `"en-GB"`; date formatted with `{ day: "numeric", month: "short", timeZone: "UTC" }`.
  - `workspaceState(w: Workspace, runs: RunManifest[] | null): StepState` — `"idle"` for `null`, else first of `RANK` present among `w.processes.map(p => processState(p, runs, null))`.

- [ ] **Step 1: Tests** `ac3`…`ac10` exactly as the spec rows, plus `failed_with_waiting_reads_waiting` (`stepStatusLine("failed", 2, 0, null)` → `{ text: "2 waiting on you", tone: "wait" }`); `ac11`/`ac12` build a `Workspace` from 3 processes and runs fixtures (reuse the fixture style already in `workspaceCard.test.ts`) asserting `"wait"` / `"failed"`; `ac13` asserts `workspaceState(w, null) === "idle"`; `ac19b` asserts `WORKSPACES.map(w => w.name)` order and that `cardView(w, runs, null, now).dots` equals the processes' `stepState` for a fixture.
- [ ] **Step 2:** `cd frontend && node --test --experimental-strip-types tests/workspaceCard.test.ts` — Expected: new tests fail (not exported), old ones pass.
- [ ] **Step 3:** Implement the two functions.
- [ ] **Step 4:** Same command — Expected: all pass.
- [ ] **Step 5:** Commit `feat(frontend): step status line and workspace state helpers`.

### Task 2: CSS, step cards, sidebar dots

**Files:**
- Modify: `frontend/src/index.css` (`--run` in three blocks; `.hub-card` radius; `.dashboard-grid .stat-tile` and `.pipeline-pill` radius; new `.hub-step-status*` and `.nav-dot*` rules)
- Modify: `frontend/src/pages/ProcessHub.tsx` (`StepCard`: replace the `hub-step-banner` span)
- Modify: `frontend/src/App.tsx` (nav items for the 5 workspaces)
- Modify: `frontend/tests/nightDeskTokens.test.ts` (add AC-1, AC-2, AC-14..16b; extend `ac13_amber_usage_unchanged` allow-list by exactly the `.nav-dot-wait` line)

**Interfaces:**
- Consumes: `stepStatusLine`, `workspaceState`, `STATE_LABEL` from Task 1 / `workspaceCard.ts`.

- [ ] **Step 1: Tests** in `nightDeskTokens.test.ts`: `r2_ac1_run_token` (values per block), `r2_ac2_run_contrast` (≥ 4.5 on `--panel`, each theme), `r2_ac14_hub_card_radius`, `r2_ac15_tiles_rounded`, `r2_ac15b_square_controls_unchanged` (rule text equal to `origin/main`), `r2_ac16b_status_colours` (declarations reference `--run`/`--low`/`--muted` as the spec row lists, no amber token). Extend `ac13_amber_usage_unchanged`: the HEAD list equals the `origin/main` list plus one `.nav-dot-wait` occurrence of `var(--hi)`.
- [ ] **Step 2:** `cd frontend && node --test --experimental-strip-types tests/nightDeskTokens.test.ts` — Expected: the new `r2_*` tests fail.
- [ ] **Step 3:** CSS per the spec. `StepCard`: `const line = stepStatusLine(state, waiting, decisions, last?.updated_at ?? null)`, render `<span className={\`hub-step-status hub-step-status-${line.tone}${line.tone === "wait" ? " hub-step-banner" : ""}\`}>{line.text}</span>` where the banner was. `App.tsx`: after the label of each nav item whose id is a workspace id, `const st = runsLoaded ? workspaceState(ws, recentRuns) : "idle"`; render `<span className={\`nav-dot nav-dot-${st}\`} aria-label={\`${ws.name}: ${STATE_LABEL[st]}\`} />` only when `st !== "idle"`. Add `runsLoaded` state set true where `setRecentRuns` is called.
- [ ] **Step 4:** Same command — Expected: all pass. Then `cd frontend && npm run lint && npx tsc -b && npm test` — Expected: exit 0.
- [ ] **Step 5:** Playwright screenshots of a workspace page and the start page, light and dark (dev server, port 5199); `/impeccable:impeccable audit`.
- [ ] **Step 6:** Commit `feat(frontend): Night Desk status lines, running colour, rounded cards, sidebar dots`.

AC-17, AC-17b, AC-18, AC-19 are evaluator rows, checked after CI is green. AC-18b is covered by `workspaceState(w, null)` plus the `runsLoaded` guard.
