# Start Page Simplified Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The start page (`#/home`) without a sidebar: a top bar, the greeting alone, and 3 + 2 workspace cards with drawn icons and a status word. Duplicates are removed.

**Architecture:**
- Pure logic goes in `lib/` and is unit-tested: `cardStatus`, `reviewBadge` and the drawing geometry.
- Presentation goes in three components: `ArpLockup`, `StartTopbar` and `WorkspaceDrawing`.
- `App.tsx` swaps the sidebar for `StartTopbar` on `home`.
- `ProcessHub.StartPage` renders the new header and cards.
- CSS goes in `index.css`.

**Tech Stack:** React 19, TypeScript, CSS, `node --test`, pytest + Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-11-15-start-page-simplified-design.md` (mockup: `specs/assets/2026-11-15-start-page-mockup.html`)

## Global Constraints

- Only `#/home` changes. Every other route renders exactly as on `main`.
- Today's tokens and Geist; no colour literals in new code.
- Amber (`--hi`, `--hi-ink`, `--await-edge`) appears only in the four allow-listed rules.
- Retire or edit only the tests listed under the spec's Supersedes. New tests may be added.
- One item per PR. The paused Arctic foundation spec and plan leave this branch; they return in their
  own PR.

## Review Focus

1. **Theme switch from the user menu:** the start page must re-render colours without a reload. Task 3
   checks it in the browser.
2. **Ask panel focus on `#/home`:** `closeAsk` used to target refs that don't exist there. AC-6c is
   checked in Task 5.
3. **Narrow widths 761–1100px:** the cards span 3 each and nothing overflows. Task 5 checks it at
   900px.
4. **Long reviewer names:** the user menu button shows only the initial, and the popover wraps the name.
   Task 3 adds a long-name check.
5. **Runs unknown or erroring:** the cards show "Status unknown" and the Retry message stays (AC-20).

---

### Task 1: Card status and review badge logic

**Files:** `frontend/src/lib/workspaceCard.ts`, `frontend/tests/workspaceCard.test.ts`, delete
`frontend/src/lib/useWaitingTotal.ts`.

**Interfaces (produces):**
- `cardStatus(states: (StepState | "unknown")[] | null, titles: string[], lastLine: string): { word: string; tone: StepState | "unknown"; detail: string }`
- `reviewBadge(count: number): { text: string; title: string } | null`
- `CardView` loses `footer` and gains `status`.

- [ ] Write the failing tests:
  - AC-4: `reviewBadge(0)` returns `null`; `reviewBadge(1)` returns `{ text: "1 item", title: "1 review item waiting on you" }`; `reviewBadge(15)` returns `{ text: "15 items", title: "15 review items waiting on you" }`.
  - AC-12 and AC-12b: the six cases in the spec, with exact words, tones and details, and `detail !== word` in every case.
  - AC-19: `cardView(...).label` is unchanged for the busy, calm and down fixtures.
- [ ] Retire the listed tests:
  - the footer test;
  - `r4_ac1` to `r4_ac9`, `r4_ac8b`, `r4_ac8c`;
  - `r4_runs_error_wins`, `r4_nan_is_no_link`;
  - `r6_ac1` to `r6_ac8`.
- [ ] Run `cd frontend && npm test`. Expected: the new tests fail.
- [ ] Implement `cardStatus` and `reviewBadge`, then set `cardView().status`. Remove `footer`,
  `waitingSentence`, `waitingLink`, `waitingStat`, `waitingTarget` and `useWaitingTotal.ts`. Fix
  their imports.
- [ ] Run `npm test && npx tsc -b`. Expected: both pass, with `ProcessHub` errors expected until Task 4. Rule on this in the ledger.
- [ ] Commit: `feat(start): card status and review badge logic`.

### Task 2: Workspace drawings

**Files:**
- `frontend/src/lib/workspaceDrawing.ts`, exporting `drawing(id, accent)`: shapes with `d`, `part` and
  `accent`; geometry only.
- `frontend/src/components/WorkspaceDrawing.tsx`: an SVG with classes `ws-drawing`, `ws-face`, `ws-top`,
  `ws-accent-wait` and `ws-accent-now`.
- Tests: `frontend/tests/workspaceDrawing.test.ts`.

- [ ] Write the failing tests:
  - AC-13a: accent `null`, `"wait"` and `"now"` give 0, 1 and 1 accented shapes, for all five ids.
  - AC-13b: the five shape lists differ.
  - AC-14: neither file has a colour literal (hex, `rgb(`, `rgba(`, `hsl(`, `oklch(`, or named colours
    such as `white` or `black`).
- [ ] Run `npm test`. Expected: the new tests fail.
- [ ] Port the mockup's isometric primitives (`box`, `disc`, the 30° projection) and the five
  compositions. Each composition marks exactly one shape as the accent slot.
- [ ] Run `npm test`. Expected: all tests pass.
- [ ] Commit: `feat(start): wireframe workspace drawings`.

### Task 3: Lockup, top bar and app shell

**Files:**
- `frontend/src/components/ArpLockup.tsx` (extracted from `Landing.tsx`; landing tests must still
  pass);
- `frontend/src/components/StartTopbar.tsx`;
- `frontend/src/App.tsx`;
- tests in `frontend/tests/startTopbar.test.ts`.

- [ ] Write the failing source tests:
  - AC-3b: `StartTopbar.tsx` renders the Ask ARP button only under `canAsk &&`.
  - AC-5: `App.tsx` and `StartTopbar.tsx` both call `reviewBadge(`.
  - The `kbd` hints are `aria-hidden="true"`.
- [ ] Run `npm test`. Expected: the new tests fail.
- [ ] Build the top bar and wire the shell.
  - `StartTopbar({ canAsk, onSearch, onAsk, askRef, reviewCount, me })` holds, in order:
    - the lockup link "ARP start";
    - the search button with its `kbd`;
    - Ask ARP;
    - `<nav aria-label="Main">` with Review Queue (`reviewBadge`), Reports and the user menu.
  - The user menu is a disclosure popover: `aria-expanded` and `aria-controls`; focus moves to the
    first focusable element on open; Esc or an outside click closes it and returns focus; Tab past the
    last element closes it. It holds `ReviewerField`, `SignedInAs`, `ThemeSwitch` and the Arcade link.
  - In `App.tsx`:
    - when `active === "home"`, render `<StartTopbar …/>` and no `.app-topbar` or `.app-sidebar`;
    - the sidebar badge uses `reviewBadge`;
    - `closeAsk` focuses the start top bar's Ask button on `home`.
- [ ] Run `npm test && npx tsc -b && npm run lint`. Expected: everything passes, landing tests
  included.
- [ ] Commit: `feat(start): top bar replaces the sidebar on the start page`.

### Task 4: Start page markup and CSS

**Files:** `frontend/src/pages/ProcessHub.tsx`, `frontend/src/index.css`,
`frontend/tests/nightDeskTokens.test.ts`, `frontend/tests/startPage.test.ts`.

- [ ] Write the failing CSS tests:
  - AC-10: the grid at all three widths;
  - AC-12c: status word colours;
  - AC-12d: the marks;
  - AC-12e: no amber on "now" rules;
  - AC-13c: the drawing look.
- [ ] Edit the existing tests:
  - retire `r4_ac10`, `r4_ac10b`, `r4_ac10c`, `r4_ac11`, `r4_ac11b`, `r4_ac11c` and
    `r4_waiting_link_wraps`;
  - edit `ac13`'s allow-list as the spec says.
- [ ] Run `npm test`. Expected: the new tests fail.
- [ ] Rewrite `StartPage`.
  - The header is the greeting `h1`, keeping `.hub-hero-greet` typography; the runs error with Retry
    stays.
  - The cards:
    - `.hub-cards` as a 6-column grid;
    - each card is an `a` with `.hub-card` (plus `.hub-card-await` when the tone is `wait`);
    - each card holds `.hub-card-fig` (caption "Fig 0n · N process(es)" and `WorkspaceDrawing` with the
      accent from the tone), then the name, the purpose, and `.hub-card-status` with the
      `.hub-mark-<state>` squares and the word and detail.
  - Delete `StateLegend`, the stats, the waiting link, "What counts?", the Now row, the old `ICONS` and
    their CSS, including the `.hub-card-await .hub-ico` lines.
  - Each new amber rule goes on one line.
- [ ] Run `npm test && npx tsc -b && npm run lint`. Expected: everything passes.
- [ ] Commit: `feat(start): simplified start page with drawn workspace cards`.

### Task 5: DESIGN.md, e2e, verification and PR

- [ ] Update DESIGN.md as the spec says: Process Card, layout, the "Needs you" count, the theme switch
  and the Icon Accent Rule. Check that `workspaceCard.test.ts` "AC-20" still passes.
- [ ] Edit the e2e tests as the spec says:
  - in `test_opening_arp_lands…`, expect `.start-topbar`;
  - in `test_start_page_signs_in…`, open the user menu first.
- [ ] Run the e2e suite: `bash backend/scripts/e2e_stack.sh up`, then `pytest -m e2e tests/e2e`.
  Expected: it passes.
- [ ] Check every evaluator row with Playwright at 1440×900, 900×900 and 390×844, in light and dark.
  Take screenshots.
- [ ] Run `/impeccable:impeccable audit` and a fresh whole-branch review. Fix findings rated Critical,
  Important, P0 or P1, each with a failing test first.
- [ ] Remove the paused Arctic foundation spec and plan from this branch (copies kept), merge
  `origin/main`, then push.
- [ ] Open the PR against `main`.
  - Label `risk:normal`.
  - Description: `Spec: start-page-simplified`, every test edited or retired, and screenshots.
