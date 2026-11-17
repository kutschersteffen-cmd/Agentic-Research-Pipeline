# App-wide top bar, PR 2 (shared parts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship PR 2 of the app-wide top bar spec:
- squares instead of dots on workspace pages;
- run status as a square and a word;
- ThemeResearch's channel tag as a chip;
- the workspace drawing in each overview header;
- the step-card hover.

**Architecture:** CSS in `frontend/src/index.css`, plus three small TSX edits:
- `ProcessHub.tsx`: the process state uses `.hub-mark`, and the overview renders `WorkspaceDrawing`;
- `ThemeResearch.tsx`: the channel tag becomes a chip.

Source-read checks go in a new `frontend/tests/topbarPr2.test.ts`; rendered checks in a new
`backend/tests/e2e/test_top_bar_pr2.py`.

**Tech Stack:** React 19 + TS, `node --test --experimental-strip-types`, pytest + Playwright e2e on `backend/scripts/e2e_stack.sh`.

**Spec:** `docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md`, section "PR 2: the shared parts", rows AC-25 to AC-32.

**Starts from:** `main`.

## Global Constraints

- **Status marks** are 8px × 8px squares with no `border-radius` above 0. They use the existing `.hub-mark-<state>` and
  `.hub-status-<state>` classes and the `STATE_LABEL` words.
- **Running is `var(--run)`.** Amber appears only for waiting. `.status-running { --edge: … }` (the pipeline-card rule, ~l.1494)
  is unchanged.
- **Workspace header drawing** (the owner's choice, 16 Nov: "Third column"):
  - At ≥1100px: title | intro | drawing, with bottoms aligned. The drawing is 120px wide.
  - At 761–1099px: the title and intro stack, and the drawing sits at the head's top right.
  - At ≤760px: `display: none`.
  - It appears on the four overviews `ProcessHub`'s `WorkspaceOverview` renders, not on `#/argus` or `#/home`.
- **The drawing's accent** follows the start-page card rule: `wait` → `ws-accent-wait`, `now` → `ws-accent-now`, otherwise
  none. It is derived from `cardView(w, runs, flow, now).status.tone`.
- **Polish 2 rows that must keep passing:**
  - AC-11: the intro's left edge is ≥ the title's right edge, with bottoms within 4px, at 1440.
  - AC-3: the intro's max-width is 62ch.
- **No new `!important`.** Every changed test is listed in the PR.

## Review Focus

- **Long workspace intro at 1100–1300px.** The intro, in the narrower middle column, must not run under the drawing. Test:
  Task 3 `test_drawing_clears_intro[1100|1280|1440]` (the intro's right edge ≤ the drawing's left edge).
- **761–1099px, title plus intro.** Neither the title nor the intro may overlap the absolutely placed drawing. Test: Task 3
  `test_drawing_clears_head_tablet[900|1024]`.
- **A workspace that is running (not waiting).** The drawing's accent is `ws-accent-now`, never amber. Test: Task 3
  `test_drawing_now_accent` (stub `/api/runs` with a running calibration run on `#/rdLab`).
- **Status pills inside phone cards** (VotingRuns at 390, from polish 2's L9). The square and word must fit the card with no
  sideways scroll. Test: Task 2 `test_status_pill_in_phone_card`.
- **Keyboard focus on a step card after the hover change.** The focus ring must stay visible. Covered by the global
  `:focus-visible` outline; Task 1 asserts that `.hub-step:focus-visible` has a computed outline (`test_step_focus_visible`).

---

### Task 1: Squares on workspace pages, square step status, step hover (AC-25, AC-26)

**Files:**
- Modify `frontend/src/pages/ProcessHub.tsx:179-182`:
  - `<span className={`hub-dot hub-dot-${state}`} aria-hidden />` becomes `<span className={`hub-mark hub-mark-${state}`} aria-hidden />`;
  - the word is wrapped in `<span className={`hub-status-${state}`}>`.
- Modify `frontend/src/index.css`:
  - delete the `.hub-dot` / `.hub-dots li` block (~l.1695-1702, with its comment);
  - `.hub-step-status::before` (~l.2343) becomes `width: 8px; height: 8px; border-radius: 0`;
  - `.hub-step:hover` (~l.1723) uses `border-color: var(--text)`.
- Tests: `frontend/tests/topbarPr2.test.ts` (new) and `backend/tests/e2e/test_top_bar_pr2.py` (new; copy the fixture,
  `_open`, `_style` and `_probe` from `test_ui_polish_2.py` by import).

- [ ] **Step 1: Write the failing tests.**
  - Unit `pr2_ac26_css`:
    - no `.hub-dot` anywhere in `index.css`;
    - the `.hub-step-status::before` body has `width: 8px` and `height: 8px`, and no `border-radius` above 0;
    - the `.hub-step:hover {` body has `border-color: var(--text)`.
  - E2E `test_ac25_process_state_square` (`#/stewardiq`). For every `.hub-process-state`:
    - exactly one `.hub-mark` child;
    - its box is 8×8;
    - its text is one of the `STATE_LABEL` words: "Waiting on you", "Running", "Last run failed", "Up to date", "No runs yet";
    - `page.locator('.hub-dot').count() == 0`.
  - E2E `test_step_focus_visible`: Tab to a `.hub-step` link; its computed `outlineStyle` is not `none`.
- [ ] **Step 2:** Run the tests. Expected: FAIL (`.hub-dot` exists; the step status is 7px round).
- [ ] **Step 3:** Implement. Confirm the `STATE_LABEL` words in `lib/workspaceCard.ts` first, and use them in the test as they are.
- [ ] **Step 4:**
  1. `cd frontend && npm test && npx tsc -b && npm run lint`.
  2. Rebuild, then run the e2e file plus `test_ui_polish_1.py`.

  Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): squares, not dots, on workspace pages; ink hover on step cards`.

### Task 2: Run status as square and word, channel tag as a chip (AC-27, AC-28, AC-29)

**Files:**
- Modify `frontend/src/index.css`:
  - `.status-pill` (~l.634): drop the `border` and the pill radius. It becomes `display: inline-flex; align-items: center;
    gap: var(--s-1_5)`, keeping its padding and `--text-xs`.
  - Add `.status-pill::before { content: ""; width: 8px; height: 8px; background: currentColor; flex: none; }`.
  - `.status-running` (~l.640, the colour rule) uses `color: var(--run)` and drops `border-color`. Drop the other
    `.status-*` `border-color` declarations in that block too, since there is no border left to colour.
- Modify `frontend/src/pages/ThemeResearch.tsx:~285`: `className="status-pill status-pending"` becomes `className="chip"`.
- Tests: `topbarPr2.test.ts`, `test_top_bar_pr2.py`.

- [ ] **Step 1: Write the failing tests.**
  - Unit `pr2_ac27_status_pill`:
    - the `.status-pill {` body has no `border:` other than `0`/`none`, and no `border-radius` above 0;
    - a `.status-pill::before` rule exists with `width: 8px`, `height: 8px` and `background: currentColor`;
    - the `.status-running {` rule that sets `color` uses `var(--run)`.
  - Unit `pr2_ac29_channel_chip`: `ThemeResearch.tsx` contains `className="chip"` around the channel words and no
    `status-pill` on that line.
  - E2E `test_ac28_running_status_is_run_blue`: on `#/history`, stub `/api/runs` with one `running` run (reuse the
    `_runs_stub` pattern from `test_ui_polish_2b.py`). The run's `.status-pill`:
    - computed `color` equals `_probe('--run')`;
    - its `::before` is 8×8 with radius `0px`;
    - its text is the status word.
  - E2E `test_status_pill_in_phone_card`: `#/voting` at 390 with a stubbed `proxy_voting` run. The pill is inside its card,
    and `document.documentElement.scrollWidth` ≤ 390.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. List every `.status-pill` user in the PR: XbrlFetchArea, RunProgress, EngagementIssuePanel,
  BackgroundAgents, ReportBuilder, EmergingThemesDetector, FactsTable, RunHistory, VotingRuns and Plans, plus ThemeResearch,
  which moves to `.chip`.
- [ ] **Step 4:**
  1. `npm test && npx tsc -b && npm run lint`.
  2. Rebuild, then run the e2e file plus `test_showcase_themes_pr2_screens.py`, which reads `.status-pill` text.

  Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): run status as a square and a word; channel tag is a chip`.

### Task 3: Workspace header drawing, third column (AC-30, AC-30b, AC-31) and DESIGN.md

**Files:**
- Modify `frontend/src/pages/ProcessHub.tsx` `WorkspaceOverview`:
  - directly after the intro `<p className="help-text">`, render `<WorkspaceDrawing id={w.id} accent={…} />`;
  - `accent` is `"wait"` or `"now"` from `cardView(w, runs, flow, new Date()).status.tone`, otherwise `null`;
  - no wrapper element, so the `svg.ws-drawing` is a direct child of `.page.hub`.
- Modify `frontend/src/index.css`, scoped to `.page.hub:not(.hub-start)`:
  - **≥1100px:**
    - the existing polish 2 two-column rules (~l.297-301) change their widths to
      `calc((100% - 120px - 2 * var(--s-8)) / 2)`; the title and intro keep `margin-right: var(--s-8)` and
      `vertical-align: bottom`;
    - `> .ws-drawing` is `display: inline-block; width: 120px; height: auto; vertical-align: bottom;
      margin-bottom: var(--s-8)`.
  - **761–1099px:**
    - `.page.hub:not(.hub-start)` gets `position: relative`;
    - `> .ws-drawing` is `position: absolute; top: 0; right: 0; width: 120px; height: auto`;
    - `> h1` and `> h1 + .help-text` get `max-width: min(<their current max>, calc(100% - 120px - var(--s-8)))`.
  - **≤760px:** `> .ws-drawing { display: none }`.
- Modify `DESIGN.md`:
  - **Status pill** reads "a square and the status word" (check the current wording first).
  - Add one line under Process Card or Navigation: "Workspace overview header: title, intro and the workspace drawing
    (120px) in three columns at 1100px and up; the drawing sits top right below that and is hidden on phones."
- Tests: `test_top_bar_pr2.py`; unit `pr2_design_md` in `topbarPr2.test.ts`.

- [ ] **Step 1: Write the failing tests.**
  - `test_ac30_drawing_right_of_title` (`#/stewardiq` 1440): exactly one `svg.ws-drawing` in `.page`; its width is 120 (±1);
    its left edge ≥ the `h1`'s right edge.
  - `test_ac30b_drawing_hidden_on_phone` (390): computed `display` is `none`.
  - `test_ac31_wait_accent`: `#/stewardiq` on the seed, which waits on open decisions. Exactly one
    `svg.ws-drawing .ws-accent-wait`.
  - `test_drawing_now_accent` (Review Focus): `#/rdLab` with a stubbed `running` calibration run. One `.ws-accent-now`, no
    `.ws-accent-wait`.
  - `test_drawing_clears_intro[1100|1280|1440]` and `test_drawing_clears_head_tablet[900|1024]` (Review Focus).
  - Unit `pr2_design_md`.
- [ ] **Step 2:** Run the tests. Expected: FAIL (no drawing on the overview).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:**
  1. `npm test && npx tsc -b && npm run lint`.
  2. Rebuild, then run `test_top_bar_pr2.py`, `test_ui_polish_2.py` (AC-3) and `test_ui_polish_2b.py` (AC-11, AC-11b).

  Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): workspace drawing in the overview header`.

### Task 4: Verify and open the PR (AC-32 and everything above)

- [ ] Run the full e2e suite on a fresh separate database. The stack and pytest both use `ARP_POSTGRES_DSN=…/arp_e2e`, so the
  Stop hook's unit tests can't empty it mid-run. AC-32's #482 rows run inside the existing start-page e2e files.
- [ ] Take screenshots of `#/stewardiq`, `#/rdLab` and `#/history` at 1440, 1024 and 390, light and dark. Run
  `/impeccable:impeccable audit` on them.
- [ ] Get a fresh whole-branch review. Fix Critical and Important findings, each with a failing test first.
- [ ] Open the PR against `main` with `risk:low` and `Spec: app-wide-top-bar` ("PR 2 of 3"). List every test change, and any
  `frontend/tests` check of `.hub-dot` or `.status-pill` borders found on the way (the spec's Supersedes for PR 2).
