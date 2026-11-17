# App-wide Top Bar PR 3: Interactive Process Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the four workspace overviews, the step cards become a live track: the running step is highlighted
and pulses, reached steps are joined by ink connectors, and a click opens a details panel under the flow instead
of navigating.

**Architecture:** One pure helper, `flowTrack`, in `lib/workspaceCard.ts`, computes the track. `ProcessFlow` in
`pages/ProcessHub.tsx` holds which step is open (`useState<number | null>`). It works out each step's view once
and passes it to both `StepCard`, which is now a `<button>`, and a new `StepPanel`. The styling goes in
`index.css`, next to the existing `.hub-step` rules. No backend or API change.

**Tech Stack:** React 19 + TS (Vite), `node --test --experimental-strip-types`, pytest + Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md`, section "PR 3: interactive process
flows", rows AC-33 to AC-42.

## Global Constraints

- The scope is `WorkspaceOverview` only. `#/argus` (`ArgusStart`) and the start page are untouched.
- Amber is used only for waiting. The `.hub-step-wait` rule line (index.css, the line starting
  `.hub-step-wait, .hub-step:has(.hub-step-banner)`) stays byte-identical. Test ac13 needs no change.
- Colours and tokens: no new tokens. Running is `var(--run)`, ink is `var(--text)`, idle connectors are
  `var(--panel-border)`.
- The lede copy is exactly "Click a step for its details; open it from there.", replacing "Open a step to work in
  its screen; a bar there shows the next step." The rest of the lede is unchanged.
- The pulse is opacity 1 → 0.3 → 1 over 1.6s, repeating. It is `animation: none` under
  `prefers-reduced-motion: reduce`.
- Planned steps (`s.planned`) stay a non-interactive `div`.

## Review Focus

1. **A folded (idle) process.** The panel must sit inside the `<details>`, after the `ol`. It must not leak
   outside, and it must not reopen the fold on poll. Test: `test_panel_inside_fold`.
2. **A step's state changes while its panel is open** (for example, a run finishes between polls). The panel
   stays open, and its Status line updates. Test: `test_panel_follows_state` (stub runs: first `running`, then
   `completed`).
3. **Keyboard only.** Tab reaches each step button. Enter and Space toggle it. Esc from the button itself also
   closes the panel and leaves focus on the button. Test: `test_keyboard_toggle_and_esc`.
4. **Global `button` styles leaking onto the card** (accent fill on hover, centred text, button font). Hover must
   keep the panel fill and the left-aligned mono title. Test: `test_step_button_looks_like_card` (hover
   background equals the `--panel` computed colour; `text-align` is `left`).
5. **Two processes, each with a panel open.** Panels are per process, and opening one in process B leaves A's
   open. The id and `aria-controls` must be unique per process. Test: `test_panels_per_process`.

---

### Task 1: `flowTrack` helper

**Files:**
- Modify: `frontend/src/lib/workspaceCard.ts` (add after `processState`)
- Test: `frontend/tests/topbarPr3.test.ts` (new)

**Interfaces:**
- Produces: `export function flowTrack(states: StepState[]): { reached: number; runInto: boolean[] }`

- [ ] **Step 1: Write the failing test `pr3_ac39_flow_track`**

```ts
assert.deepEqual(flowTrack(["done","idle","done","now","idle"]), { reached: 2, runInto: [false,false,false,true,false] });
assert.deepEqual(flowTrack(["now","idle"]), { reached: -1, runInto: [true,false] });
assert.deepEqual(flowTrack(["idle","wait"]), { reached: -1, runInto: [false,false] });
assert.deepEqual(flowTrack([]), { reached: -1, runInto: [] });
```

- [ ] **Step 2: Run** `cd frontend && node --test --experimental-strip-types tests/topbarPr3.test.ts`. Expected: FAIL
  (`flowTrack` is not exported).
- [ ] **Step 3: Implement it.** `reached` is `states.lastIndexOf("done")`. `runInto[i]` is
  `states[i] === "now" && i <= reached + 1`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): flowTrack helper for the process track`.

### Task 2: Step buttons, details panel, track and styles

**Files:**
- Modify: `frontend/src/pages/ProcessHub.tsx`:
  - `ProcessFlow`: open state, the views, the track, the panel, Esc;
  - `StepCard`: becomes a button;
  - new `StepPanel`;
  - the `WorkspaceOverview` lede.
- Modify: `frontend/src/index.css`, the `.hub-flow` / `.hub-step` block (~1727–1770): add rules, remove
  `.hub-step-go` and its reduced-motion line.
- Modify: `DESIGN.md`: a new **Process flow** entry under the workspace overview entries.
- Modify: `backend/tests/e2e/test_top_bar_pr2.py::test_step_focus_visible`: the locator changes from
  `a.hub-step:visible` to `button.hub-step:visible`. List this in the PR's test changes.
- Test: `frontend/tests/topbarPr3.test.ts`

**Interfaces:**
- Consumes: `flowTrack` (Task 1); the existing `stepState`, `stepStatusLine`, `STATE_LABEL`, `openCount`,
  `stepActivity` (workspaceCard.ts); `REVIEWABLE_RUN_TYPES` (`lib/runs.ts`); `stepHref`, `writeWalk`.
- Produces (DOM contract for Task 3):
  - A step button: `button.hub-step.hub-step-<state>`, `type="button"`, `id="step-<p.id>-<i>"`,
    `aria-expanded`, `aria-controls="step-panel-<p.id>"`.
  - The panel: `div.hub-step-panel`, `role="region"`, `id="step-panel-<p.id>"`,
    `aria-label="<label> details"`. It is the next sibling of the process's `ol.hub-flow`.
  - A track item: `li.hub-flow-item`, plus `reached` when `i <= reached` and `run-into` when `runInto[i]`.

- [ ] **Step 1: Write the failing tests in `topbarPr3.test.ts`.** Use the same `rule()` CSS reader as
  `topbarPr2.test.ts`.
  - `pr3_ac38_css`:
    - `.hub-step-now` has `border-color: var(--run)`, and its `box-shadow` contains `var(--run)`;
    - a `@keyframes` name is used in the `animation` of `.hub-step-now .hub-step-status::before`;
    - inside `@media (prefers-reduced-motion: reduce)` that selector has `animation: none`;
    - `.hub-step[aria-expanded="true"]` has `outline: 1px solid var(--text)` and `outline-offset: 3px`;
    - the `.hub-step-wait, .hub-step:has(.hub-step-banner), …` line equals the one in `git show origin/main:frontend/src/index.css`
      (skipped, not passed, when `origin/main` is missing, as `p2_ac18_no_new_important` does).
  - `pr3_track_css`:
    - `.hub-flow-item.reached + .hub-flow-item::before` sets `background: var(--text)`;
    - `.hub-flow-item + .hub-flow-item.run-into::before` sets `background: var(--run)` and comes later in the file;
    - there is no `.hub-step-go` rule.
  - `pr3_ac42_copy`: the `ProcessHub.tsx` source contains "Click a step for its details; open it from there." and
    not "Open a step to work in its screen".
  - `pr3_design_md`: `DESIGN.md` has a `**Process flow**` entry that mentions `aria-expanded` and `--run`.
- [ ] **Step 2: Run** `node --test --experimental-strip-types tests/topbarPr3.test.ts`. Expected: these four FAIL.
- [ ] **Step 3: Implement `ProcessHub.tsx`.**
  - **The view.** Pull the per-step computation out of `StepCard` into a local
    `stepView(s, runs, flow, activity): { state; line; last; stage; fromRuns: boolean }`, where `fromRuns` is
    `waiting > 0`. `ProcessFlow` computes `views` once, then `track = flowTrack(views.map((v) => v.state))`.
  - **The open state.** `const [open, setOpen] = useState<number | null>(null)`. A click on step i runs
    `setOpen(open === i ? null : i)`.
  - **Esc.** On the wrapper that holds the `ol` and the panel, an `onKeyDown`: on `Escape` with `open !== null`,
    `setOpen(null)`, then focus `document.getElementById(`step-${p.id}-${open}`)`.
  - **The fold.** `steps` becomes that wrapper (the `ol` plus `{open !== null && <StepPanel …/>}`), so a folded
    process keeps the panel inside its `<details>`.
  - **`StepCard`.** It keeps the same inner markup, minus `.hub-step-go`, on a
    `<button type="button" className={`hub-step hub-step-${state}`}>` with the id and aria attributes above. It
    no longer calls `writeWalk`. The `li` gets the `reached` / `run-into` classes.
  - **`StepPanel({ s, i, p, view })`** renders, in order:
    - `<p className="meta">Step {i + 1} of {p.steps.length}</p>`;
    - `<h3>{s.label}</h3>`;
    - `<p>{s.does}</p>`;
    - a `<dl>` with:
      - **Status**: `<span className={`hub-mark hub-mark-${state}`} aria-hidden />` plus `STATE_LABEL[state]`;
      - **Now**: `line.text`, as a link when `line.tone === "wait"`. The link goes to `#/review` when
        `fromRuns && s.runTypes!.every((t) => REVIEWABLE_RUN_TYPES.has(t))`, else to `stepHref(s)`;
      - **Latest run**, only when `last`: `<code>{last.run_id}</code> · {last.status.replace(/_/g, " ")}`;
    - `<a className="button-link" href={stepHref(s)} onClick={() => writeWalk({ id: p.id, step: i })}>Open {s.label} →</a>`.
  - **The lede.** Swap the sentence exactly as Global Constraints says.
- [ ] **Step 4: Implement `index.css`**, in the `.hub-step` block.
  - The button reset on `.hub-step`: `width: 100%; text-align: left; font: inherit; font-size: var(--text-xs);
    cursor: pointer;`. Also `button.hub-step:hover:not(:disabled) { background: var(--panel); }`, so the global
    accent hover does not apply.
  - `.hub-step-now, .hub-step-now:hover { border-color: var(--run); box-shadow: 0 0 0 3px color-mix(in srgb, var(--run) 18%, transparent); }`
    replaces today's `.hub-step-now { border-color: var(--text); }`.
  - `@keyframes hub-pulse { 50% { opacity: 0.3; } }`, then
    `.hub-step-now .hub-step-status::before { animation: hub-pulse 1.6s ease-in-out infinite; }`. The existing
    reduced-motion line becomes
    `@media (prefers-reduced-motion: reduce) { .hub-step-now .hub-step-status::before { animation: none; } }`.
  - `.hub-step[aria-expanded="true"] { outline: 1px solid var(--text); outline-offset: 3px; }` goes **before**
    `.hub-step:focus-visible`. Both have the same specificity, so focus wins by order.
  - The track: the two connector rules from Step 1. The stacked (≤900px) rule keeps its geometry; colour comes
    from these rules.
  - The panel `.hub-step-panel`:
    - `margin-top: var(--s-3)`, `padding: var(--s-3) var(--s-4)`;
    - `border: 1px solid var(--panel-border)`, `border-radius: var(--r-md)`, `background: var(--panel)`;
    - its `dl` is a two-column grid (`max-content 1fr`), with `dt` in `--muted`.
  - At ≤760px, `.hub-step-panel .button-link { min-height: 44px; display: inline-flex; align-items: center; }` (AC-41).
  - Delete `.hub-step-go`, `.hub-step:hover .hub-step-go` and the reduced-motion `.hub-step-go` line.
- [ ] **Step 5: DESIGN.md.** One **Process flow** entry that says:
  - the running step is a `--run` edge plus a pulsing square, still under reduced motion;
  - reached steps are joined in ink;
  - a step is a button with `aria-expanded` that opens one details panel per process, and Esc closes it;
  - only the panel's "Open" link navigates.
- [ ] **Step 6: Run** `node --test --experimental-strip-types tests/topbarPr3.test.ts`, then
  `npm run lint && npx tsc -b && npm test`. Expected: all pass.
- [ ] **Step 7: Commit** `feat(ui): interactive process flows: step buttons, details panel, live track`.

### Task 3: E2E rows and Review Focus

**Files:**
- Create: `backend/tests/e2e/test_top_bar_pr3.py`. Copy the `_open`, `_style` and `_runs_stub` helpers from
  `test_top_bar_pr2.py`.

**Interfaces:**
- Consumes: the DOM contract from Task 2.

- [ ] **Step 1: Write the tests.** P is the first `section.hub-process` whose `ol.hub-flow` is visible without a
  `details` ancestor.

| Test | Asserts |
|---|---|
| `test_ac33_steps_are_buttons` | every `.hub-step:not(.hub-step-planned)` in P is a `button` with `aria-expanded="false"`; `page.get_by_role("region", name=re.compile(r" details$")).count() == 0` |
| `test_ac34_panel_contents` | after clicking P's second step: `aria-expanded="true"`; `P ol.hub-flow + [role=region]` has the name "<label> details"; it contains "Step 2 of <n>", the step's `.hub-step-about` text and `STATE_LABEL[state]` (state taken from the card's `hub-step-<state>` class); the link "Open <label> →" has an `href` equal to the step's route |
| `test_ac35_moves_panel` | after clicking the third step: only it is expanded, and P has 1 region |
| `test_ac35b_closes` | after clicking the second step twice: no region, and `aria-expanded="false"` |
| `test_ac36_open_navigates` | click Open: the hash equals the step route, and `nav[aria-label="Process progress"]` contains "Step 2 of <n>" |
| `test_ac37_esc` | focus the Open link, press Escape: no region, and the focused element is P's second button |
| `test_ac39b_reached` | for each visible flow, the `li.reached` indices are exactly `0…last hub-step-done` (or none) |
| `test_ac40_survives_poll` | open a panel, wait 20 s: still open and expanded |
| `test_ac41_phone` | at 390×844, open a panel: the step buttons' left edges are within ±1px, the Open link height is ≥ 44, and `scrollWidth` ≤ 390 |
| `test_ac42_lede` | the lede contains the new sentence and not the old one |
| `test_running_step_blue` | a stub with one `running` run for a P step: its button's border colour equals the computed `--run`, and the connector into it (`::before`) is `--run` when the previous step is reached or it is step 1 |

- [ ] **Step 2: Add the Review Focus tests** to the same file: `test_panel_inside_fold`,
  `test_panel_follows_state`, `test_keyboard_toggle_and_esc`, `test_step_button_looks_like_card` and
  `test_panels_per_process`, with the assertions from the Review Focus list.
- [ ] **Step 3: Run** them on a fresh `arp_e2e` database:
  `psql "postgresql://arp:arp@localhost:5432/postgres" -qc "DROP DATABASE IF EXISTS arp_e2e" -c "CREATE DATABASE arp_e2e"`,
  then
  `ARP_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_e2e ARP_ENGAGEMENT_STORE=postgres bash backend/scripts/e2e_stack.sh up`,
  then `pytest -m e2e tests/e2e/test_top_bar_pr3.py tests/e2e/test_top_bar_pr2.py`. Expected: all pass.
- [ ] **Step 4: Commit** `test(e2e): interactive process flows (AC-33 to AC-42)`.

### Task 4: Verify and open the PR

- [ ] Run the full e2e suite on a fresh `arp_e2e`. Expected: no failures beyond today's skips.
- [ ] Take screenshots of `#/stewardiq` with a panel open: 1440 dark, 1024 light, 390 light. Then run
  `/impeccable:impeccable audit`.
- [ ] Get a fresh whole-branch review. Fix Critical and Important findings test-first, and defer minors.
- [ ] Open a PR against `main`:
  - title "App-wide top bar (3 of 3): interactive process flows";
  - `Spec: app-wide-top-bar`, label `risk:low`;
  - the test changes section lists the `test_step_focus_visible` locator change.
