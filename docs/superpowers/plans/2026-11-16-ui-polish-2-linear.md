# UI polish 2 (Linear ideas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the owner's 12 picked Linear-inspired ideas as two PRs. PR A covers type and surfaces (L1–L4, L6, L10, L12, L13).
PR B covers layout and components (L5, L7, L8, L9).

**Architecture:**
- Almost everything is tokens plus rules in `frontend/src/index.css`.
- TSX changes in only two places: the "All"/"Only mine" chips (L8), and a `data-status` attribute on the Argus status cell
  (L9), both in `ArgusStart.tsx`.
- CSS reads are checked with `node --test` source tests. Everything rendered is checked with Playwright e2e in two new files.
- The mockup overlays in the session scratchpad (`linear-mock/css/<id>.css`) are the visual reference. Port them without
  `!important` and without mockup-only DOM.

**Tech Stack:** React 19 + TS, `node --test --experimental-strip-types`, pytest + Playwright e2e against `backend/scripts/e2e_stack.sh`.

**Spec:** `docs/superpowers/specs/2026-11-16-ui-polish-2-linear-design.md` (AC-1 to AC-18; PR A = AC-1…AC-10, PR B = AC-11…AC-18).

**Starts from:**
- **PR A:** `main` once UI polish 1 and the waiting count have merged. Until then, local branch `polish-2`, stacked on
  `waiting-count`.
- **PR B:** `main` after PR A.

## Global Constraints

- **Token values, verbatim:**
  - `--text-2: color-mix(in oklch, var(--text) 80%, var(--muted))`
  - `--track-display: -0.025em`, `--track-title: -0.015em`, `--track-body: -0.008em`
  - `--dur-fast: 100ms`, `--dur-slow: 240ms`, `--ease-out: cubic-bezier(0.25, 0.46, 0.45, 0.94)`
  - dark `--panel-border: rgb(232 235 240 / 0.12)`
  - top bar `color-mix(in srgb, var(--bg) 80%, transparent)` with `blur(20px)`
- **Breakpoints:** lead and top-bar blur above 760px; two-column head at ≥1100px; tile strip stacks at ≤640px; phone cards at
  ≤560px; chips are 44px tall at ≤1024px.
- **Colour rules:** amber only for waiting; running is `--run`, failed is `--low`; status dots are square (radius 0).
- **Copy:** chip labels "All" and "Only mine", in a group named "Show runs".
- **No new `!important`.** Light-mode `--panel-border` stays `#d8dee7`. `--field-border` is unchanged.
- **Tests:** every changed test is listed in the PR. E2E probes compare colours through an element styled with the token
  (`color: var(--x)`), never with `getPropertyValue`.

## Review Focus

- **Long run name on a phone card.** A 60-character name must wrap under or beside the status pill, never under it. Test: Task B3
  `test_long_name_clears_pill` (the name's text rects do not intersect the pill's rect).
- **Keyboard on the chips.** Tab reaches "All" then "Only mine", Space toggles, and focus stays visible. Test: Task B2
  `test_chips_keyboard`.
- **Focus ring on a strip tile.** A focused tile's outline must not be hidden under its neighbour. Test: Task B1
  `test_focused_tile_on_top` (computed z-index of `:focus-visible` tile > neighbour's).
- **Badge on the translucent bar in light mode.** AC-9c runs only in dark. Test: Task A2 runs AC-9c in light too.
- **Empty Argus table on a phone.** The "No runs yet. Start one" row must stay readable inside a card. Test: Task B3
  `test_empty_row_card` (the text is fully inside the card's box and "Start one" is clickable).

---

## PR A

### Task A1: Text tier, tracking, weights, lead (L1–L4)

**Files:**
- Modify `frontend/src/index.css`:
  - `:root` tokens;
  - `.page h1` (l.264) weight and tracking;
  - `body` tracking;
  - `.hub-card-name`, `.card h2`, `.section-heading h2`, and the start hero `h1`;
  - new rules for the intro paragraph (`:where(.page, .page-body) > h1 + :is(.help-text, .muted)`), `.hub-process .help-text`,
    `.hub-card-purpose`, and `kbd, code { letter-spacing: normal }`.
- Tests:
  - `frontend/tests/polish2.test.ts` (new);
  - `backend/tests/e2e/test_ui_polish_2.py` (new; copy the fixture and `_open` pattern from `test_ui_polish_1.py`, plus a
    `_probe(page, token)` helper returning the computed colour of a span styled `color: var(token)`).

**Interfaces:**
- Produces:
  - tokens `--text-2`, `--track-display`, `--track-title` and `--track-body` (A2 and B tasks may use them);
  - e2e helpers `_open` and `_probe` in `test_ui_polish_2.py` (reused by later tasks).

- [ ] **Step 1: Write the failing tests.**
  - Unit `p2_ac1_text2_token`: `:root` body contains `--text-2: color-mix(in oklch, var(--text) 80%, var(--muted))`.
  - Unit `p2_ac4_tracking_tokens`: the three tracking tokens with their exact values.
  - E2E `test_ac2_intro_text2[dark|light]`: the intro equals `_probe('--text-2')`, differs from `_probe('--muted')`, and has
    contrast ≥ 4.5 on `_probe('--bg')` used as a background colour.
  - E2E `test_ac2b_card_purpose`, `test_ac2c_process_help`.
  - E2E `test_ac3_lead_desktop`: 17px, 25.5px, `textWrap == "pretty"`, max-width ≈ 62 × width of "0".
  - E2E `test_ac3b_lead_phone`: font-size equals body's; the `.hub-step-handoff-key` height ≈ its line-height.
  - E2E `test_ac4b_tracking`: body is `-0.12px`; h1 is −0.025 × size; h2 is −0.015 × size, each ±0.05px.
  - E2E `test_ac4c_kbd_normal`.
  - E2E `test_ac5_heading_weights` (`#/stewardiq` h1, `#/home` hero h1 and `.hub-card-name`: weight `500`, size ≥ 20px).
  - E2E `test_ac5b_small_h2_stays_600`.
- [ ] **Step 2:** `cd frontend && node --test --experimental-strip-types tests/polish2.test.ts`. Then rebuild (`node_modules/.bin/vite build`)
  and run `pytest -m e2e tests/e2e/test_ui_polish_2.py -k "ac2 or ac3 or ac4 or ac5"`. Expected: FAIL.
- [ ] **Step 3:** Implement the tokens and rules. The lead applies above 760px only. `.hub-step-handoff-key` inside the lead gets
  `white-space: nowrap`. The weight-500 change applies to the four heading selectors only.
- [ ] **Step 4:**
  1. `npm test && npx tsc -b && npm run lint`.
  2. Rebuild, then run the e2e file.
  3. Run `test_ui_polish_1.py` and `test_app_smoke.py` (regression).

  Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): text tier, tracking tokens, medium-weight headings, lead paragraph`.

### Task A2: Hairlines, motion tokens, text-wrap, translucent bar, DESIGN.md (L6, L10, L12, L13)

**Files:**
- Modify `frontend/src/index.css`:
  - the dark `--panel-border` in both dark blocks (l.~109 and l.~150);
  - new tokens `--dur-fast`, `--dur-slow` and `--ease-out`;
  - the shared hover transition at l.338 (use `--dur-fast`);
  - `.progress-bar-fill` (l.591: `var(--dur-slow) var(--ease-out)`);
  - the flow-node transition (l.1243: `var(--dur)`);
  - `.hub-step-go` (l.1640: `var(--dur-fast) var(--ease-out)`);
  - new `:where(h1, h2, h3, h4)` and `:where(p, li, dd, figcaption)` rules;
  - dark-only body smoothing;
  - `.start-topbar` background and blur above 760px.
- Modify `DESIGN.md`: colour (`--text-2`), type (the tracking tokens and the 500 weight), and a motion line naming `--dur-fast`,
  `--dur-slow` and `--ease-out`.
- Modify `frontend/tests/nightDeskTokens.test.ts:43`: DARK `--panel-border` becomes `rgb(232 235 240 / 0.12)`. This is a changed
  test value, per spec AC-6.
- Tests: `polish2.test.ts`, `test_ui_polish_2.py`.

**Interfaces:**
- Consumes: `_open` and `_probe` (Task A1).
- Produces: `--dur-fast`, `--dur-slow` and `--ease-out`.

- [ ] **Step 1: Write the failing tests.**
  - Unit `p2_ac7_motion`: the three tokens are present; no `transition` declaration matches `/0\.15s|0\.4s/`;
    `.progress-bar-fill` contains `var(--dur-slow) var(--ease-out)`.
  - Unit `p2_ac8_wrap_smoothing`: both `:where` rules are present; every `-webkit-font-smoothing: antialiased` occurrence sits
    inside a dark block (scan the enclosing rule's selector for `dark`).
  - Unit `p2_ac10_design_md`: DESIGN.md contains `--text-2`, `--track-display`, `--dur-fast`, `--dur-slow` and `--ease-out`.
  - E2E `test_ac6_dark_hairline` (`.argus-waiting` border `rgba(232, 235, 240, 0.12)`; Ctrl+K, then `.palette-input` border
    equals `_probe('--field-border')` with alpha 1).
  - E2E `test_ac6b_light_hairline`, `test_ac7b_button_duration`.
  - E2E `test_ac9_bar_translucent[dark|light]`: parse `rgba()`/`color(srgb …)`; alpha 0.8 ± 0.01.
  - E2E `test_ac9b_phone_bar_opaque`.
  - E2E `test_ac9c_badge_solid[dark|light]` (Review Focus adds the light run).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement the CSS changes and the DESIGN.md lines.
- [ ] **Step 4:**
  1. `npm test && npx tsc -b && npm run lint`.
  2. Rebuild, then run `test_ui_polish_2.py`.

  Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): translucent dark hairlines, motion tokens, text-wrap, blurred top bar`.

### Task A3: Verify and open PR A

- [ ] Full e2e suite on a fresh stack (`e2e_stack.sh down`; drop and recreate `arp_test`; `up`).
- [ ] Screenshots at 1440 and 390, in light and dark, of `#/home`, `#/stewardiq`, `#/argus` and `#/review`. Compare with the
  mockup "after" shots.
- [ ] Run `/impeccable:impeccable audit` on those routes, then a fresh whole-branch review. Fix Critical and Important findings,
  each with a failing test first.
- [ ] Merge `origin/main`, push, and open the PR with `risk:low`, `Spec: ui-polish-2-linear` and "PR A of 2". List every test
  change, including `nightDeskTokens.test.ts:43`.

---

## PR B

### Task B1: Two-column head and tile strip (L5, L7)

**Files:**
- Modify `frontend/src/index.css`:
  - `.page.hub:not(.hub-start) > h1` and `+ .help-text` at ≥1100px, using inline-blocks as in the L5 mockup;
  - `.argus-tiles`, `.argus-tile` and the ≤640px block, as in the L7 mockup;
  - plus `.argus-tile:focus-visible` in the raised set.
- Test: `backend/tests/e2e/test_ui_polish_2b.py` (new; import `_open` and `_probe` from `test_ui_polish_2`).

**Interfaces:**
- Consumes: `_open` and `_probe`.
- Produces: `_runs_stub(page, runs: list[dict])`, a route on `**/api/runs` that adds manifests in the shape `/api/runs` returns
  (reuse `body["runs"][0]` as the template). B2 and B3 use it.

- [ ] **Step 1: Write the failing tests.**
  - `test_ac11_two_column_head[stewardiq|rdLab]`.
  - `test_ac11b_stacked_below_1100_and_elsewhere` (`#/stewardiq` at 1099; `#/review` at 1440).
  - `test_ac12_strip_desktop` (adjacent `left == prev.right - 1 ± 0.5`; first and last outer radii `12px`; inner radii `0px`).
  - `test_ac12b_strip_phone`.
  - `test_ac12c_failed_tile_on_top` (stub two failed extraction runs at step 4).
  - `test_focused_tile_on_top` (Review Focus).
- [ ] **Step 2:** Rebuild and run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rebuild and run `test_ui_polish_2b.py`, `test_argus_start.py`, `test_ui_polish_1.py` and `test_argus_showcase_fixes.py`.
  Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): two-column workspace head and Argus tile strip`.

### Task B2: Filter chips (L8)

**Files:**
- Modify `frontend/src/pages/ArgusStart.tsx`: replace the `label.argus-mine` checkbox (l.~170) with
  `<div role="group" aria-label="Show runs" className="filter-chips">` holding two `<button type="button" className="chip"
  aria-pressed=…>`: "All" (`onClick={() => setOnlyMine(false)}`) and "Only mine" (`disabled={me === null}`,
  `onClick={() => setOnlyMine(true)}`). `onlyMine` state and its filtering stay as they are.
- Modify `frontend/src/index.css`:
  - `.filter-chips` and `.chip`: pill, 32px, 44px at ≤1024px, pressed background `--accent-tint` with `--text`, otherwise
    `--muted`;
  - delete the now-unused `.argus-mine` rule (l.2058).
- Update the e2e callers that used the checkbox:
  - `backend/tests/e2e/test_argus_start.py:39,87`: `get_by_label("Only mine").check()` becomes
    `get_by_role("button", name="Only mine").click()`; `is_checked()` becomes `get_attribute("aria-pressed") == "false"`.
  - `test_argus_showcase_fixes.py:82,88`: the same change.
- Test: `test_ui_polish_2b.py`.

**Interfaces:** Consumes `_runs_stub`.

- [ ] **Step 1: Write the failing tests.**
  - `test_ac13_chips_present` (group "Show runs"; All pressed; each chip 32px tall; radius ≥ 16px; no checkbox named
    "Only mine").
  - `test_ac13b_pressed_state` (background equals `_probe('--accent-tint')` used as a background).
  - `test_ac13c_touch_height` (at 1024: ≥ 44px).
  - `test_ac13d_signed_out` (`/api/me` stubbed to 401).
  - `test_ac13e_filters_rows` (`_runs_stub` with 3 extraction runs whose `started_by` is `dev`, `dev`, `other`; Only mine
    shows 2 rows, All shows 3).
  - `test_chips_keyboard` (Review Focus).
- [ ] **Step 2:** Rebuild and run. Expected: FAIL.
- [ ] **Step 3:** Implement and update the two e2e callers.
- [ ] **Step 4:**
  1. `npm test && npx tsc -b && npm run lint`.
  2. Rebuild, then run `test_ui_polish_2b.py`, `test_argus_start.py` and `test_argus_showcase_fixes.py`.

  Expected: PASS.
- [ ] **Step 5:** Commit `feat(argus): All / Only mine filter chips`.

### Task B3: Phone cards (L9) and DESIGN.md

**Files:**
- Modify `frontend/src/index.css`, inside the existing `@media (max-width: 560px)` block at l.~452:
  - generic card frame for `.data-table.stack-on-phone tr` (border, `--r-md`, `--panel`, `--s-3` padding, `--s-2` gap via the
    `tbody` grid);
  - the `td[data-label="Status"]` pill with a 6px square dot;
  - the dot colours by `data-status` (`running`, `needs-you`, `failed`, `finished`, `stopped`, `draft` per the spec);
  - the Argus compact layout scoped to `.argus-start`, as in the L9 mockup but without `!important`. The existing
    `white-space: normal !important` stays.
- Modify `frontend/src/pages/ArgusStart.tsx` (l.~223): the status `td` gets
  `data-status={r.status.toLowerCase().replace(" ", "-")}`.
- Modify `DESIGN.md`: **Tile strip**, **Filter chips** and **Phone tables** entries (the last contains "card").
- Tests: `test_ui_polish_2b.py`; unit `p2_ac17_design_md` and `p2_ac18_no_new_important` (runs
  `git diff origin/main -- frontend/src/index.css` via `child_process.execSync`; no added line has `!important`; skip with a
  message if `origin/main` is missing) in `polish2.test.ts`.

**Interfaces:** Consumes `_runs_stub`.

- [ ] **Step 1: Write the failing tests.**
  - `test_ac14_argus_card_frame`.
  - `test_ac14b_voting_card_frame` (stub one `proxy_voting` run on `#/voting`).
  - `test_ac15_argus_compact_card` (regex `^\d+ compan(y|ies) · \d \w+`; no visible "Run", "Companies", "Step" or "Status"
    label text).
  - `test_ac15b_status_dots`: stub `/api/runs`, `/api/argus/flows` and `/api/review/items` for one row of each of the six
    statuses; compare with `_probe` per token.
  - `test_ac16_desktop_table_unchanged`.
  - `test_long_name_clears_pill` and `test_empty_row_card` (Review Focus).
  - The two unit tests above.
- [ ] **Step 2:** Rebuild and run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:**
  1. `npm test && npx tsc -b && npm run lint`.
  2. Rebuild, then run `test_ui_polish_2b.py`, plus any e2e file that reads a stacked table on a phone
     (`grep -l "390\|360" backend/tests/e2e/*.py`).

  Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): phone tables as cards; Argus compact run cards`.

### Task B4: Verify and open PR B

- [ ] Full e2e suite on a fresh stack.
- [ ] Screenshots: `#/argus` and `#/voting` at 390 in light and dark, `#/stewardiq` at 1440, and `#/argus` at 1440 and 1024.
- [ ] Run `/impeccable:impeccable audit`, then a fresh whole-branch review. Fix Critical and Important findings, each with a
  failing test first.
- [ ] Merge `origin/main` and push. Open the PR with `risk:low`, `Spec: ui-polish-2-linear` and "PR B of 2". List the test
  changes: `test_argus_start.py:39,87` and `test_argus_showcase_fixes.py:82,88` (checkbox to chips).
