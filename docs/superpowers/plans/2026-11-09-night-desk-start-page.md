# Night Desk Release 4 (start page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the start page: greeting-only headline, amber "waiting on you" first in the counts, an amber link to the Review Queue directly above the cards, cards with an icon tile and footer strip.

**Architecture:** Three pure helpers in `frontend/src/lib/workspaceCard.ts` (`waitingSentence`, `waitingLink`, `waitingStat`) carry the texts and states; `StartPage` in `frontend/src/pages/ProcessHub.tsx` renders them; CSS in `index.css`.

**Tech Stack:** React + TypeScript, CSS, `node --test --experimental-strip-types` (no DOM).

**Spec:** `docs/superpowers/specs/2026-11-09-night-desk-start-page-design.md`

## Global Constraints

- Sentences exactly as today: `"Runs could not be loaded."`, `"Loading runs…"`, `"What waits on you could not be loaded."`, `"Loading what waits on you…"`, `"1 decision waits on you."`, `"<n> decisions wait on you."`, `"Nothing waits on you."`.
- Link form when `needsTotal > 0`: sentence without its final `"."` + `" →"`, `href "#/review"`.
- `waitingStat`: number as text, else `"—"`.
- New amber references only in `.hub-waiting` and `.hub-card-await .hub-card-icon`.
- `cardView`, `stepState`, `processState`, `stepStatusLine` unchanged.

## Review Focus

- `needsTotal` is a number but `known` is false (runs failed after a total loaded): the sentence follows today's order (runs first), so the link must not show; test `waitingLink(false, "x", 3)` → `href: null`, text `"Runs could not be loaded."`.
- A negative or `NaN` total from a bad response: treat as not > 0 (no link); test `waitingLink(true, null, NaN)` → `href: null`.
- The "What counts?" note must still only show when the total is a number (today's guard), now below the cards.
- Screen readers: the `h1` must not lose the greeting when no name is set (`"Good morning."`).
- The amber test `ac13_amber_usage_unchanged` must learn the two new selectors, or CI goes red.

---

### Task 1: Helpers

**Files:** Modify `frontend/src/lib/workspaceCard.ts` (append); Test `frontend/tests/workspaceCard.test.ts` (append)

**Interfaces — Produces:**
- `waitingSentence(known: boolean, error: string | null, needsTotal: number | "error" | null): string`
- `waitingLink(known: boolean, error: string | null, needsTotal: number | "error" | null): { text: string; href: "#/review" | null }`
- `waitingStat(needsTotal: number | "error" | null): string`

- [ ] **Step 1:** Tests `r4_ac1`…`r4_ac9` with the spec rows' exact inputs/outputs, plus `r4_runs_error_wins` and `r4_nan_is_no_link` from Review Focus.
- [ ] **Step 2:** `cd frontend && node --test --experimental-strip-types tests/workspaceCard.test.ts` — Expected: new tests fail.
- [ ] **Step 3:** Implement; `waitingSentence` is today's ternary from `StartPage` verbatim; `waitingLink` links only when `known && typeof needsTotal === "number" && needsTotal > 0`.
- [ ] **Step 4:** Same command — Expected: pass. Commit `feat(frontend): start page waiting helpers`.

### Task 2: Page and CSS

**Files:** Modify `frontend/src/pages/ProcessHub.tsx` (`StartPage`, `WorkspaceCard`), `frontend/src/index.css`, `frontend/tests/nightDeskTokens.test.ts` (AC-10..12 rows; extend the amber allow-list regex with `\.hub-waiting|\.hub-card-await \.hub-card-icon`)

**Interfaces — Consumes:** Task 1 helpers.

- [ ] **Step 1:** Tests `r4_ac10`, `r4_ac10b`, `r4_ac10c`, `r4_ac11`, `r4_ac11b`, `r4_ac11c` reading the rules via the existing `rule()` helper, with the spec's exact declarations.
- [ ] **Step 2:** `node --test --experimental-strip-types tests/nightDeskTokens.test.ts` — Expected: new tests fail.
- [ ] **Step 3:** `StartPage`: `h1` keeps only the greeting span; first `.hub-stats` item `<div className="you"><dt>waiting on you</dt><dd>{waitingStat(needsTotal)}</dd></div>` (shown as `"—"` while runs are unknown); `const link = waitingLink(known, error, needsTotal)` rendered right before `.hub-cards` as `a.hub-waiting` or `p.hub-waiting.hub-waiting-quiet`; the `<details>` moves to directly after `.hub-cards` under the same `waiting !== null` guard. `WorkspaceCard`: wrap `{ICONS[w.id]}` in `<span className="hub-card-icon">`. CSS per the spec.
- [ ] **Step 4:** Commit, then `cd frontend && npm run lint && npx tsc -b && npm test` — Expected: exit 0.
- [ ] **Step 5:** Playwright screenshots of the start page, light and dark, with mocked runs (`**/api/runs**` → `{runs:[…]}` including one waiting and one running run); `/impeccable:impeccable audit`. Commit screenshots.

AC-13a–c, AC-14, AC-15 are evaluator rows; AC-16/17/17b are checked with `git diff` and the suite in the PR.
