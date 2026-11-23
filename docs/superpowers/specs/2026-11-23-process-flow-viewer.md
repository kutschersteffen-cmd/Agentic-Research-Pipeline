# Process flow viewer: scroll and zoom every process flow

Status: **draft, waiting for the owner's approval**
Slug: `process-flow-viewer`
Risk: this spec PR is `risk:low`. The build is 1 PR, `risk:normal`.
Size: S
Checked against `origin/main` `3f94c96` and PR #674 at `20544e8` (expressive-ui-orb slice 3, which changes
`ProcessHub.tsx`). The builder starts after #674 has merged.

## Decisions for the owner

Approving this spec accepts all of them as recommended. Each one changes acceptance rows.

| # | Decision | Recommended | If not |
|---|---|---|---|
| D1 | **How wide a step is at 100%.** Every step card is 180 px wide at 100%, the width a card has today in a four-step flow. A flow that needs more room than the page gives scrolls sideways instead of shrinking its cards. Today the seven cards of "Build a thematic portfolio" are about 150 px wide on its own page and under 100 px inside R&D Lab. | 180 px (AC-2, AC-3, AC-13, AC-14) | 220 px: roomier, but then four-step flows scroll too inside a workspace. |
| D2 | **On a phone the flow is one row that scrolls sideways**, as on a laptop. Today the steps stack in one long column below 900 px. | One row at every width (AC-3, AC-5, AC-17) | The column stays below 900 px and the viewer applies only above it; AC-3, AC-17, AC-26, AC-35 and AC-37 are struck. |
| D3 | **Zoom runs from 50% to 200% and is remembered** in this browser, one value for every flow. | Remembered (AC-40 to AC-42) | Every visit starts at 100%; AC-40 to AC-42 are struck, and rows with a stored-zoom Given reach that zoom with the buttons instead. |
| D4 | **A flow opens on the step that needs attention**: the first step waiting on a person, else the first running, else the first failed is scrolled into the middle of the window. | Yes (AC-43 to AC-45) | Every flow opens at step 1; AC-43 and AC-45 are struck. |

## Why

Owner, 23 Nov 2026: "These process flows look very squeezed. Lets [put] this and other flow charts of this kind
into a scrollable window, which also allows to make the process larger/smaller." And: "Like in the screenshot.
'Build a thematic portfolio' and similar."

`ProcessFlow` lays its steps out as equal shares of the page width (`.hub-flow-item { flex: 1 1 0 }`), so a
seven-step flow gets seven narrow columns and its text wraps into tall, thin cards. After #674 a workspace page
gives the flows about 780 px, which makes it worse.

## What the user can do afterwards that they cannot do today

- Read every step of a long flow at full size, and move along it by scrolling, dragging or swiping.
- Make a flow larger or smaller with buttons, the keyboard, ctrl or cmd + wheel, or a pinch, and see the level.
- See the whole flow at once with one press ("Fit").
- Open a flow and land on the step that is running or waiting, not on step 1.
- Keep the size they chose on the next visit.

## Three versions

1. Safe: cards keep a fixed width and the flow scrolls sideways. No zoom.
2. Strong: plus zoom in, zoom out and reset by button, keyboard, ctrl or cmd + wheel and pinch, with a visible
   level and limits.
3. Most ambitious, specified here: plus "Fit", a remembered zoom, opening on the step that needs attention, and
   dragging the flow with the mouse.

The next step up is a full-screen flow with a minimap. It needs a decision on where a step's details panel
lives in full screen, and a mock.

## What exists today

- `ProcessFlow` in `frontend/src/pages/ProcessHub.tsx` is the only component that draws a process step flow. It
  renders in `WorkspaceOverview` (`#/stewardiq`, `#/transitionIntel`, `#/rdLab`, `#/dataHub`: one flow per
  process, ten processes of four to seven steps from `frontend/src/lib/processes.ts`; Argus's two processes are
  not drawn by `ProcessFlow`) and in
  `frontend/src/pages/DesignStrategy.tsx` (`#/designStrategy`, "Build a thematic portfolio", seven steps, never
  folded).
- Inside each `section.hub-process`, after #674: the step rail (`span.hub-step-rail[data-rail]`, one `data-seg`
  per step), then `ol.hub-flow` with one `li.hub-flow-item` per step holding the step card (`.hub-step`, a
  button with id `step-<process id>-<index>`, or a `div` for a planned step), then, when a step is open, its
  details panel (`.hub-step-panel`, `role="region"`) as the next sibling of the `ol`. A process with no activity
  holds all of this inside `details.hub-process-fold` ("Show n steps").
- Below 900 px `.hub-flow` switches to a column.
- Existing tests rely on the details panel being the next sibling of `ol.hub-flow`
  (`backend/tests/e2e/test_top_bar_pr3.py`, top-bar spec AC-34) and on the `.hub-flow-item` track rules in
  `index.css` (`frontend/tests/topbarPr3.test.ts`).

## Goals

1. No process flow squeezes its steps: a step card has a fixed width at a given zoom, and the flow scrolls
   inside its own window when it does not fit.
2. The user can zoom every flow between 50% and 200% by button, keyboard, ctrl or cmd + wheel and pinch, sees
   the level, and can reset it or fit the flow to the window.
3. It works with a keyboard alone and on a phone.
4. The page around the flow never scrolls sideways.
5. The look from expressive-ui-orb (black, pixel titles, panels, status rails) and every existing behaviour of
   the steps (open details, Esc, fold, process bar) stay as they are.

## Non-goals

- Flows that do not render through `ProcessFlow`: the Steward Workflow stage tabs, the Argus pipeline cards and
  Argus flow, the agent board diagrams.
- A new layout of the steps (branches, several rows), a minimap, full screen.
- Any backend change.

## Anti-goals

- No zooming of the whole page, and no blocking of the browser's own ctrl + plus and ctrl + minus.
- No new colour meaning: the zoom controls use neither the amber signal colour nor the running blue.
- Nothing animates when the zoom changes or the flow scrolls to a step.

## Design

All of it lives in `ProcessFlow`, so both places that render it get it. `DesignStrategy.tsx` does not change.

**The window is the `ol.hub-flow` itself.** It becomes the scroll container: `overflow: auto` in both
directions, `tabindex="0"`, `aria-label="<process title> steps"`, a hairline frame (`--panel-border`, 8 px
corners, 14 px padding, background `--well`), a thin scrollbar (`scrollbar-width: thin`),
`overscroll-behavior-x: contain`, `touch-action: pan-x pan-y`, and a height of at most 70% of the window's
inner height. Its children stay the `li.hub-flow-item` elements and the details panel stays its next sibling,
so nothing wraps the `ol` and nothing sits between it and the panel. The focus ring is the one step buttons use.

**One row at every width.** The 900 px rule that turns the flow into a column is removed, with the vertical
connector rule that belongs to it.

**Size.** The zoom is a number `z` from 50 to 200 (percent), 100 by default. Each step card is `180 × z / 100`
px wide, and everything in the flow scales by the same factor: text, paddings, the step number square, the gap
and the connector lines. When the cards and gaps at that size are narrower than the window, the cards grow by
equal shares to fill it, without scaling their text further. The rail above the flow and the details panel
below it do not zoom and do not scroll: the rail keeps the full width of the panel. The layout inside a card
is the same at every zoom: the existing 140 px container rule on `.hub-flow-item` compares the unzoomed card
width, which is never below 180 px.

**The zoom bar.** `div[data-flow-zoom-bar]` with `role="group"` and `aria-label="Zoom, <process title>"` is the
first element of the steps block, before the rail, aligned right; inside a folded process it is inside the
fold. In this order it holds: a button "−" named "Zoom out", `output[data-flow-zoom]` with `aria-live="polite"`
showing the rounded zoom as "100%", a button "+" named "Zoom in", a button "Reset" named "Reset zoom", a button
"Fit" named "Fit to width". Mono type, hairline buttons 28 px high; at 760 px and below every button is at
least 44 × 44 px. "Zoom out" is disabled at 50%, "Zoom in" at 200%, "Reset zoom" at 100%.

**Changing the zoom.**

| Input | Effect |
|---|---|
| "Zoom in" / "Zoom out" | to the next multiple of 10 above / below the current zoom |
| "Reset zoom" | 100 |
| "Fit to width" | the largest whole number from 50 to 100 at which the flow has no sideways overflow; 50 when there is none |
| `+` or `=`, `-`, `0` with no ctrl, cmd or alt, while the focus is on the `ol` or on a step in it | as "Zoom in", "Zoom out", "Reset zoom" |
| wheel with ctrl or cmd held, pointer over the `ol` | the zoom changes by `−deltaY / 10`; the event is cancelled so the page does not zoom |
| two fingers on the `ol` moving apart or together | zoom at the start of the gesture × (distance now / distance at the start) |

Every result is clamped to 50 to 200. The zoom is kept unrounded; the reading, the stored value, the steps of
buttons and keys and the disabled states all use the zoom rounded to a whole number (at 109.6 the reading is
"110%" and "Zoom in" goes to 120). Keys with ctrl, cmd or alt held are left to the browser. Wheel and pinch keep the point under the pointer, or between the
fingers, where it is, as far as the scroll range allows; buttons and keys keep the middle of the window. A
wheel without ctrl or cmd scrolls as it does today. The pure rules live in `frontend/src/lib/flowZoom.ts`:
`stepZoom(z, dir)`, `wheelZoom(z, deltaY)`, `fitZoom(innerWidth, steps)` and `readStoredZoom(raw)`, where
`innerWidth` is the `ol`'s width inside its padding and a flow of `n` steps needs `n × 180 + (n − 1) × 18` px
at 100%.

**Remembered.** Every change writes the rounded zoom to `localStorage["arp.flowZoom"]` (for example `"120"`).
A flow reads it when it mounts; anything that is not a number from 50 to 200 counts as 100. Other flows already
on the page keep their zoom until the page is opened again.

**Moving along the flow.** Scrollbar, shift + wheel, a trackpad and one finger on a touch screen work natively.
Left and right arrows scroll the focused `ol`. Tabbing to a step scrolls it into view. With a mouse, pressing
the primary button anywhere in the `ol` and moving more than 5 px drags the flow (the content follows the
pointer one to one in both directions, counted from the point of the press and not from where the 5 px were
passed; the cursor shows a closed hand, no text is selected), and the release does not open the step under it. A press that moves 5 px or less is a click, as today.

**Opening on the step that needs attention.** Exactly once per mount, on the first render where the runs have
loaded and, for a process with a stewardship stage step, the house flow has answered or failed, the first
step in order whose state is `wait`, else the first `now`, else the first `failed`, is scrolled sideways to the
middle of the window, as far as the scroll range allows. Only the `ol` scrolls, never the page, and later polls
do not scroll it again; if no step qualifies at that moment, nothing scrolls later. A folded flow does it on
its first unfold only. The flow's `scroll-behavior` is `auto`.

**Unchanged.** Step cards, their states and colours, the rail, the details panel and Esc, the fold. "Run
process", the process bar and the legend sit outside the flow and their code is not touched, so they have no
row here; their own specs' rows stay in the hidden regression set.

## Supersedes

No earlier acceptance row changes. The column layout below 900 px is removed; no row of the top-bar, night-desk,
ui-polish or expressive-ui-orb specs pins it.

## Acceptance

All rows run on the app started by `backend/scripts/e2e_stack.sh up` (dev auth, role `approver`, no model key),
in headless Chromium at 1440 × 900 with `localStorage["arp.orb"] = "low"` and no `arp.flowZoom` entry, unless
the Given says otherwise.

Terms used in the rows:

- **The flow** is the `ol.hub-flow` in the section labelled "Build a thematic portfolio" on `#/designStrategy`
  unless the row names another page; **the bar** is the `[data-flow-zoom-bar]` in the same section; **the
  reading** is the text of the bar's `output[data-flow-zoom]`. **Card k** is `#step-thematic-k`, counted from 0.
- **Stored zoom N** means the test sets `localStorage["arp.flowZoom"] = "N"` before the app loads.
- **Runs R0, R1, R5** mean the test answers every `GET /api/runs*` with `{"runs": [...]}`: R0 an empty list; R1
  one run `{run_id: "r1", run_type: "emerging_themes", status: "running", review_count: 0, company_count: 480,
  completed_count: 212, failed_count: 0, …}` (step "Spot", card 0, runs); R5 the same run with `run_id: "r5"`
  and `run_type: "calibration"` (step "Construct", card 5, runs). Other manifest fields take any valid value;
  `created_at` and `updated_at` are `2026-11-22T10:00:00Z`. Rows that do not name runs use R1.
- **Ctrl + wheel d** is one `wheel` event with `ctrlKey` and `deltaY = d`, with the pointer over the middle of
  card 0 unless the row says otherwise.
- Widths, heights and edges are `getBoundingClientRect()` values; "± n" is in px.

### The window

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | | open `#/designStrategy` | the section holds one bar with exactly four buttons, named in order "Zoom out", "Zoom in", "Reset zoom", "Fit to width" | holdout |
| AC-2 | | open `#/designStrategy` | each of the seven `.hub-step` in the flow is 180 ± 1 wide | holdout |
| AC-3 | 390 × 844 | open `#/designStrategy` | the seven `.hub-step` are each 180 ± 1 wide and their top edges are equal ± 1 | holdout |
| AC-4 | | open `#/designStrategy` | the flow's `scrollWidth` is greater than its `clientWidth` | holdout |
| AC-5 | 390 × 844 | open `#/designStrategy` | `document.documentElement.scrollWidth` is at most 390 | holdout |
| AC-6 | | open `#/designStrategy` | the flow's computed `overflow-x` and `overflow-y` are both `auto` | holdout |
| AC-7 | 1440 × 400, stored zoom 200 | open `#/designStrategy` | the flow is at most 280 high and its `scrollHeight` is greater than its `clientHeight` | holdout |
| AC-8 | | press card 1 | the next element sibling of the flow is a region named "Define details" | holdout |
| AC-9 | stored zoom 200 | open `#/designStrategy` | the section's `[data-rail]` is not inside the flow, and it is as wide (± 1) as with no stored zoom | holdout |
| AC-10 | 1440 × 900, stored zoom 50 | open `#/designStrategy` | the flow's `scrollWidth` equals its `clientWidth`, and the seven `.hub-step` are equally wide ± 1 and each wider than 91 | holdout |
| AC-11 | runs R0 | open `#/rdLab` | no `[data-flow-zoom-bar]` is visible | holdout |
| AC-12 | runs R1 | open `#/rdLab`, then `#/designStrategy` | the flow sits in a hairline frame inside its panel, the bar is right-aligned above the rail in mono type, the scrollbar is thin and dark, no step text is cut off or overlaps another card, and the last visible card is visibly cut by the frame so it reads as "more to the right" | evaluator |

### Zoom

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-13 | | press "Zoom in" once | the reading is "110%" and card 0 is 198 ± 1 wide | holdout |
| AC-14 | stored zoom 150 | open `#/designStrategy` | card 0 is 270 ± 1 wide and its `.hub-step-num` is 36 ± 1 wide and 36 ± 1 high | holdout |
| AC-15 | | press "Zoom in" until it is disabled | it took 10 presses and the reading is "200%" | holdout |
| AC-16 | | press "Zoom out" until it is disabled | it took 5 presses and the reading is "50%" | holdout |
| AC-17 | 390 × 844 | press "Fit to width" | the reading is "50%" | holdout |
| AC-18 | | press "Fit to width" | the flow's `scrollWidth` is at most its `clientWidth`, and the reading is a whole percent from 50% to 99% | holdout |
| AC-19 | stored zoom 170 | press "Reset zoom" | the reading is "100%" and "Reset zoom" is disabled | holdout |
| AC-20 | | ctrl + wheel −100 | the reading is "110%" | holdout |
| AC-21 | | ctrl + wheel 100 | the reading is "90%" | holdout |
| AC-22 | | one `wheel` event with `metaKey` and `deltaY = −100` over card 0 | the reading is "110%" | holdout |
| AC-23 | a `wheel` listener on `window` | ctrl + wheel −100 | the listener sees the event with `defaultPrevented === true` | holdout |
| AC-24 | | one `wheel` event with no modifier key and `deltaY = 100` over card 0 | the reading is "100%" | holdout |
| AC-25 | | ctrl + wheel −300 with the pointer at the middle of card 3 | `document.elementFromPoint` at the pointer is still card 3 or inside it | holdout |
| AC-26 | 390 × 844, a touch context | two touch points on the flow 100 px apart move to 150 px apart and lift (CDP `Input.dispatchTouchEvent`) | the reading is from "140%" to "160%" and `window.visualViewport.scale` is 1 | holdout |
| AC-27 | | `fitZoom(1000, 7)`, `fitZoom(2000, 7)`, `fitZoom(300, 7)`, `stepZoom(104, 1)`, `stepZoom(104, -1)`, `wheelZoom(195, -100)`, `readStoredZoom("abc")`, `stepZoom(109.6, 1)`, `stepZoom(100.4, -1)` | 73, 100, 50, 110, 100, 200, 100, 120, 90 | unit |

### Keyboard and touch

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-28 | | read the flow | it has `tabindex="0"` and the accessible name "Build a thematic portfolio steps" | holdout |
| AC-29 | the flow is focused | press `+` | the reading is "110%" | holdout |
| AC-30 | the flow is focused | press `-` | the reading is "90%" | holdout |
| AC-31 | stored zoom 170, card 2 is focused | press `0` | the reading is "100%" | holdout |
| AC-32 | the flow is focused | press ArrowRight three times | the flow's `scrollLeft` is greater than 0 | holdout |
| AC-33 | | call `focus()` on card 6 | card 6's right edge is at most the flow's right edge | holdout |
| AC-34 | runs R1, `#/rdLab` | type `+` into the "Ask about R&D Lab" box | the box holds "+" and the reading in the "Build a thematic portfolio" section is "100%" | holdout |
| AC-35 | 390 × 844 | open `#/designStrategy` | each of the bar's four buttons is at least 44 wide and 44 high | holdout |
| AC-36 | | read the bar | its `output[data-flow-zoom]` has `aria-live="polite"` | holdout |
| AC-37 | 390 × 844, a touch context | swipe one finger sideways on the flow, then pinch it | the flow scrolls sideways under the finger, the pinch resizes the flow only, and the page itself neither scrolls sideways nor zooms | evaluator |

### Dragging

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-38 | | press the mouse on the middle of card 1, move 150 px left in steps of 10 px, release | the flow's `scrollLeft` is 150 ± 2 and card 1 has `aria-expanded="false"` | holdout |
| AC-39 | | press the mouse on the middle of card 1, move 3 px left, release | card 1 has `aria-expanded="true"` | holdout |

### Remembered

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-40 | | press "Zoom in" twice | `localStorage["arp.flowZoom"]` is `"120"` | holdout |
| AC-41 | stored zoom 140, runs R1 | open `#/designStrategy`, then `#/rdLab` | the reading is "140%" on `#/designStrategy` and in the "Build a thematic portfolio" section of `#/rdLab` | holdout |
| AC-42 | stored zoom `abc`, then 10, then 500 | open `#/designStrategy` each time | the reading is "100%" each time | holdout |

### Opening on the step that needs attention

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-43 | runs R5 | open `#/designStrategy`, wait until card 5 has the class `hub-step-now` | card 5's left and right edges are inside the flow's, the flow's `scrollLeft` is greater than 0 and `window.scrollY` is 0 | holdout |
| AC-44 | runs R1 | open `#/designStrategy`, wait until card 0 has the class `hub-step-now` | the flow's `scrollLeft` is 0 | holdout |
| AC-45 | runs R5 | after AC-43's state, set the flow's `scrollLeft` to 0 and wait 4 s | the flow's `scrollLeft` is still 0 | holdout |

### Must not change

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-46 | runs R1 | open `#/designStrategy` | the section's rail has seven `data-seg` elements reading `now`, then six `idle` (expressive-ui-orb AC-82) | holdout |
| AC-47 | runs R1 | open `#/rdLab` | in the section labelled "Build a thematic portfolio" the `.hub-step-title` texts read, in order, Spot, Define, Match, Review, Score, Construct, Report, and pressing `#step-thematic-0` sets its `aria-expanded` to `true` (expressive-ui-orb AC-87) | holdout |
| AC-48 | | open `#/rdLab` at 390 × 844, and `#/transitionIntel` at 390 × 844 | `document.documentElement.scrollWidth` is at most 390 on both (expressive-ui-orb AC-80) | holdout |
| AC-49 | card 1's details panel is open and the focus is on its "Open" link | press Escape | the panel is gone and card 1 has the focus (top-bar AC-37) | holdout |
| AC-50 | runs R0, `GET /api/waiting` answered with all four counts 0, `localStorage["arp.orb"] = "still"` | open `#/rdLab`, press "Show 7 steps" | no visible element has a computed `color`, `background-color` or `border-top-color` of `rgb(224, 178, 90)` | holdout |
| AC-52 | the flow is focused, a `keydown` listener on `window` | press Control+`=`, then Control+`-` | the reading stays "100%" and both events have `defaultPrevented === false` | holdout |
| AC-53 | | open `#/designStrategy`, then hover and focus each of the bar's buttons in turn | no element of the bar ever has a computed `color`, `background-color` or `border-top-color` of `rgb(95, 176, 255)` (the running blue) or `rgb(224, 178, 90)` (amber) | holdout |
| AC-54 | | in one `evaluate` call, click "Zoom in" and measure | card 0 is 198 ± 1 wide, the flow's `getAnimations({subtree: true})` is empty and its computed `scroll-behavior` is `auto` | holdout |
| AC-55 | no stored zoom | open `#/designStrategy` | the reading is "100%" | holdout |
| AC-56 | runs R0 | open `#/rdLab`, press "Show 7 steps" | exactly one `[data-flow-zoom-bar]` is visible | holdout |
| AC-51 | the frontend suite | `cd frontend && npm run lint && npx tsc -b && npm test` | exits 0 | unit |

Must not change: the rail and its segments (AC-46), the steps, their order and opening a step (AC-47), no
sideways page scroll on a phone (AC-48), Esc closing the details panel (AC-49), amber only where a person must
act (AC-50), the browser's own zoom keys (AC-52), the details panel as the next sibling of the flow (AC-8).

## Slices

One PR, `risk:normal`, with `Spec: process-flow-viewer` in its description and every test it changes listed.

| Slice | PR contents | Rows |
|---|---|---|
| 1 | The flow window, zoom bar, zoom by button, key, wheel and pinch, drag, remembered zoom, opening on the step that needs attention; `lib/flowZoom.ts` | AC-1 to AC-56 |

## Defaults decided without the owner

- The window is the existing `ol.hub-flow`, not a new wrapper, so tests that find the details panel as the
  flow's next sibling keep passing.
- The rail and the details panel stay outside the window and do not zoom.
- Each flow has its own bar; with four flows on a workspace page a zoom change applies to the flow it was made
  on, and to the others from the next page open.
- The zoom bar is always shown for an unfolded flow, also when the flow fits.
- "Fit" never goes above 100%: cards already grow to fill a wider window.
- Zoom and scrolling change at once, with no animation, so reduced motion needs no extra rule.
- The window is at most 70% of the screen height; a flow zoomed taller than that scrolls up and down inside it.
- Dragging is for the mouse; touch uses the native swipe.
- After this change the wiki needs an update: the `openwiki/` page on the workspace overview. The weekly
  `/context-refresh` regenerates it.

## Later (own specs)

- A full-screen flow with a minimap.
- The same viewer for the Steward Workflow stage tabs and the Argus pipeline, if the owner wants them in it.
- Pressing a rail segment to jump to its step.
