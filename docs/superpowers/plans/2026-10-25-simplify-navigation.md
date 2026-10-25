# Simplify Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 9-link sidebar, four duplicate screens removed with their routes redirected, and the Dashboard's engagement counts on Start.

**Architecture:** The sidebar, hub and redirect rules move out of `App.tsx` into a pure `src/lib/nav.ts` so `node --test` can check them (tests cannot import `.tsx`). The engagement counts get a pure `src/lib/engagement.ts`; Start renders its line. Removed pages are deleted; their shared stage components stay because Extraction renders them.

**Tech Stack:** React + TypeScript (Vite), `node --test --experimental-strip-types` for unit tests, Playwright e2e in `backend/tests/e2e`.

**Spec:** `docs/superpowers/specs/2026-10-25-simplify-navigation-design.md` (approved 2026-10-25).

## Global Constraints

- Sidebar, verbatim: (no label) Start · `Needs you`: Review Queue · `Workspaces`: StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub · `Output`: Presentations & Reports · (no label) Arcade.
- Redirects: `#/dashboard`→`#/home`, `#/tape`→`#/review`, `#/identity`→`#/extraction/identify`, `#/discovery`→`#/extraction/documents`; every sub-path of an old route lands on the same target; the address bar is replaced, not pushed.
- Engagement line text before the link: `Engagement · <open> open · <stalled> stalled · <escalated> escalated`; unknown counts `—`; on error `Engagement · counts unavailable`; link `Open Engagement →` to `#/engagement`.
- No backend file changes. No test removed except `frontend/tests/tapeData.test.ts` (owner applies `tests-weakened-ok`).

## Review Focus

- A stored or pasted old link with a run id (`#/identity/<run>`): must land on `#/extraction/identify`, not on Start. Pinned in Task 1 (`redirectHash("#/identity/abc")`).
- The Back button after a redirect: replaceState means Back skips the dead route instead of bouncing into it again. Checked by hand in Task 5.
- An engagement record with zero issues, or records with an unknown escalation stage string: counts must not throw; unknown stages count as escalated if not resolved/closed. Pinned in Task 3.
- Hub tabs whose hub left the sidebar (`#/history`, `#/search`): no sidebar link current, and the hub tab strip still renders. Pinned in Task 1, checked in Task 5.
- A deep link to a removed screen from the command palette's recent runs: palette items for identity/discovery runs must not point at removed routes. Checked in Task 2 (`runItem` hrefs).

---

### Task 1: Sidebar, hub and redirect rules as pure functions

**Files:**
- Create: `frontend/src/lib/nav.ts`
- Test: `frontend/tests/nav.test.ts`

**Interfaces:**
- Produces:
  - `NAV_GROUPS: { label: string | null; ids: readonly string[] }[]` — exactly the five groups of Global Constraints, ids `home`; `review`; `stewardiq, argus, transitionIntel, rdLab, dataHub`; `reporting`; `arcade`.
  - `HUBS: { label: string; tabs: [string, string][] }[]` — the current `Library` and `Runs` hubs moved verbatim from `App.tsx`; `Onboard issuers` dropped.
  - `redirectHash(hash: string): string | null` — target hash for a removed route or any path under it, else `null`.
  - `currentNavIds(active: string): string[]` — sidebar ids that get `aria-current="page"` for the open tab id (a nav id matches itself, or a hub whose tabs include `active`; `transitionPlan` maps to `extraction`, which is not in the sidebar).
  - `navCount(id: string, waiting: { review: number } | null): number` — `waiting.review` for `review`, else `0`.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/nav.test.ts`:
  - `redirectHash`: `"#/dashboard"`→`"#/home"`, `"#/dashboard/x"`→`"#/home"`, `"#/tape"`→`"#/review"`, `"#/identity"` and `"#/identity/abc"`→`"#/extraction/identify"`, `"#/discovery"`→`"#/extraction/documents"`, `"#/review"`→`null`, `"#/dashboardx"`→`null`, `""`→`null`.
  - `NAV_GROUPS.flatMap(g => g.ids)` deep-equals `["home","review","stewardiq","argus","transitionIntel","rdLab","dataHub","reporting","arcade"]`; labels deep-equal `[null,"Needs you","Workspaces","Output",null]`.
  - `currentNavIds("argus")` → `["argus"]`; `("review")` → `["review"]`; `("search")`, `("history")`, `("argusUniverse")` → `[]`.
  - `navCount("review", { review: 1 })` → `1`; `navCount("argus", { review: 1 })` → `0`; `navCount("review", null)` → `0`.
- [ ] **Step 2: Run** `cd frontend && node --test --experimental-strip-types tests/nav.test.ts` — expect FAIL (module not found).
- [ ] **Step 3: Implement `frontend/src/lib/nav.ts`** with the Interfaces above; a removed route matches when the hash equals `#/<id>` or starts with `#/<id>/`.
- [ ] **Step 4: Run** the same command — expect PASS.
- [ ] **Step 5: Commit** `feat(frontend): sidebar groups, hubs and redirects as pure nav rules`.

### Task 2: Wire the rules into App and delete the four screens

**Files:**
- Modify: `frontend/src/App.tsx` (TABS, HUBS, NAV_GROUPS, `parseHash`, nav rendering, badge counts, lazy imports, route switch)
- Modify: `frontend/src/pages/ArgusFlow.tsx:150` (`href="#/identity"` → `href="#/history"`)
- Modify: `frontend/src/lib/processes.ts` (StewardIQ `screens`: append `["#/rfp", "RFP Answers"]`)
- Modify: `frontend/tests/processes.test.ts` (add: StewardIQ screens include `["#/rfp", "RFP Answers"]`)
- Modify: `backend/tests/e2e/test_schema_rules.py:70-72` (open Extraction by `page.goto(URL + "#/extraction")` instead of the removed `All screens` group)
- Modify: `backend/tests/e2e/test_argus_step1.py` (after the identity run starts, assert the `Open identity runs` link has `href="#/history"`; AC-19)
- Delete: `frontend/src/pages/MonitoringDashboard.tsx`, `frontend/src/pages/IdentityResolution.tsx`, `frontend/src/pages/DocumentDiscovery.tsx`, `frontend/src/pages/tape/` (all three files), `frontend/tests/tapeData.test.ts`

**Interfaces:**
- Consumes: `NAV_GROUPS`, `HUBS`, `redirectHash`, `currentNavIds`, `navCount` from Task 1.

- [ ] **Step 1: Write the failing test** in `processes.test.ts`: `assert.ok(stewardiq.screens.some(([h, l]) => h === "#/rfp" && l === "RFP Answers"))`. Run `node --test --experimental-strip-types tests/processes.test.ts` — expect FAIL.
- [ ] **Step 2: Add the RFP link** in `processes.ts`; rerun — expect PASS.
- [ ] **Step 3: Update `App.tsx`:** drop `dashboard`, `tape`, `identity`, `discovery` from `TABS` and the route switch; import the four nav rules; in the hash handler and initial state, call `redirectHash(location.hash)` first and, when it returns a target, `history.replaceState(null, "", target)` before parsing; render badges with `navCount`, `aria-current` with `currentNavIds`; remove the `voting` badge sum and `openDecisions` if nothing else reads them (lint will say).
- [ ] **Step 4: Delete the files** listed above and change the ArgusFlow link. Confirm `runItem` sends no palette item to a removed route (identity runs go to `#/review/identity/<id>` or `#/history`).
- [ ] **Step 5: Run** `cd frontend && npm run lint && npx tsc -b && npm test` — expect all PASS, 0 lint errors.
- [ ] **Step 6: Delete CSS left with no user:** for each class in `TapeReader.css` (deleted with the folder) nothing else is needed; grep `index.css` for selectors only the deleted pages used (`dashboard-grid`, `dashboard-columns`, `dashboard-column`) and remove those with zero remaining `className` hits.
- [ ] **Step 7: Commit** `feat(frontend): nine-link sidebar; remove Dashboard, Tape Reader, Identity Resolution, Document Discovery`.

### Task 3: Engagement counts as a pure function

**Files:**
- Create: `frontend/src/lib/engagement.ts`
- Test: `frontend/tests/engagement.test.ts`

**Interfaces:**
- Produces:
  - `engagementCounts(records: Pick<EngagementRecord, "issues">[]): { open: number; stalled: number; escalated: number }` — open = status `open`|`stalled`; stalled = status `stalled`; escalated = `escalation_stage !== "private_engagement"` and status not `resolved`/`closed`.
  - `engagementLine(counts: { open: number; stalled: number; escalated: number } | null | "error"): string` — `null` → `Engagement · — open · — stalled · — escalated`; `"error"` → `Engagement · counts unavailable`.

- [ ] **Step 1: Write the failing tests:** the AC-14 fixture (5 issues: open@private_engagement, open@joint_engagement, stalled@joint_engagement, resolved@joint_engagement, closed@joint_engagement) gives `{open: 3, stalled: 1, escalated: 2}` and `engagementLine(...)` → `"Engagement · 3 open · 1 stalled · 2 escalated"`; `engagementCounts([])` → all `0`; a record with `issues: []` → all `0`; `engagementLine(null)` and `engagementLine("error")` → the two exact strings above.
- [ ] **Step 2: Run** `node --test --experimental-strip-types tests/engagement.test.ts` — expect FAIL.
- [ ] **Step 3: Implement** `frontend/src/lib/engagement.ts`.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** `feat(frontend): engagement counts for the start page`.

### Task 4: The engagement line on Start, and ballots in Needs you

**Files:**
- Modify: `frontend/src/pages/ProcessHub.tsx` (`StartPage`: load `api.listEngagementRecords()` once; render the line directly after the `hub-now` nav)
- Modify: `frontend/src/lib/runs.ts` (add `ballotRows`), `frontend/src/components/NeedsYou.tsx` (use it)
- Modify: `frontend/src/index.css` (one rule for the line, reusing `.hub-now` spacing)
- Test: `frontend/tests/runs.test.ts`

**Interfaces:**
- Consumes: `engagementCounts`, `engagementLine` (Task 3).
- Produces: `ballotRows(runs: RunManifest[]): { runId: string; count: number; what: string; href: string }[]` — one per `proxy_voting` run with `review_count > 0`; `what` = `Proxy voting run <id>: <n> ballot(s) to decide` (`1 ballot`, `2 ballots`); `href` = `#/voting/<encoded id>`.

- [ ] **Step 1: Write the failing test** in `runs.test.ts`: a `proxy_voting` run `pv-1` with `review_count: 2` → `[{ runId: "pv-1", count: 2, what: "Proxy voting run pv-1: 2 ballots to decide", href: "#/voting/pv-1" }]`; `review_count: 0` and an `extraction` run → `[]`.
- [ ] **Step 2: Run** `node --test --experimental-strip-types tests/runs.test.ts` — expect FAIL.
- [ ] **Step 3: Implement `ballotRows`** and replace the inline proxy-voting loop in `NeedsYou.tsx` with it (same row keys `ballots/<id>`, workspace `StewardIQ`, `since` from the run).
- [ ] **Step 4: Render the line in `StartPage`:** state `null` until loaded, `"error"` on rejection; text from `engagementLine`, then `<a href="#/engagement">Open Engagement →</a>`.
- [ ] **Step 5: Run** `cd frontend && npm run lint && npx tsc -b && npm test` — expect PASS.
- [ ] **Step 6: Commit** `feat(frontend): engagement line on Start; ballots row from a tested helper`.

### Task 5: Pin the discovery schedule API (AC-27)

No test calls `GET /api/discovery/schedule` today, and its only screen is going.

**Files:**
- Test: `backend/tests/test_discovery_schedule_api.py`

- [ ] **Step 1: Write `test_schedule_defaults_when_nothing_saved`:** a bare `FastAPI()` with `discovery.router`, `deps.settings_dep` overridden to `Settings(anthropic_api_key="unused", discovery_state_dir=tmp_path)`, auth overridden as in `tests/test_run_started_by.py`; `GET /api/discovery/schedule` → status `200`, body `enabled` `False`, `interval_hours` `24.0`, `universe_path` `None`.
- [ ] **Step 2: Run** `cd backend && ruff check . && python3 -m pytest tests/test_discovery_schedule_api.py` — expect PASS on the first run (it pins existing behaviour; if it fails, stop and report: the spec assumed today's defaults).
- [ ] **Step 3: Commit** `test(api): pin the discovery schedule defaults`.

### Task 6: Verify in the browser and open the PR

- [ ] **Step 1:** `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up`, then `cd backend && ARP_E2E_URL=http://localhost:5173 ARP_CHROMIUM_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome | head -1) pytest -m e2e tests/e2e` — expect all PASS.
- [ ] **Step 2:** Screenshot `#/home`, `#/argus`, `#/stewardiq`, `#/search` at 1440×900 and the phone drawer at 390×844; check AC-1–3, AC-10–13, AC-18, AC-21–26, AC-28–31 by hand; open `#/dashboard`, `#/tape`, `#/identity/abc`, `#/discovery`, then press Back once: it must not return to the dead route.
- [ ] **Step 3:** `/ponytail:ponytail-review` and `/code-review` on the branch; fix findings.
- [ ] **Step 4:** Open the PR against `main` with `Spec: simplify-navigation`, label `risk:normal`, list every test change (new `nav`, `engagement`, `test_discovery_schedule_api` tests; `processes`, `runs`, two e2e tests edited; `tapeData.test.ts` deleted) and ask the owner for `tests-weakened-ok`.
