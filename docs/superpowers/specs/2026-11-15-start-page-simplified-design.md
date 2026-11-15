# Start page, simplified

## Intent

Make the start page (`#/home`) say each thing once and give the workspaces room. The owner reviewed the
current page and asked for these changes:
- remove all duplication;
- give the cards more space and the icons a different look;
- remove the sidebar on this page;
- drop the headline's sub-lines about waiting decisions and runs;
- keep the Review Queue reachable from a top bar.

The approved mockup is `docs/superpowers/specs/assets/2026-11-15-start-page-mockup.html` (artifact "Start
Without Sidebar", version 2). Visitors are the stewardship and research team opening ARP to see where to
go next.

The waiting total ("15 decisions wait on you") leaves the start page with the headline link. Waiting
work still shows on the start page in two places: the waiting workspace's card ("Waiting on you") and
the Review Queue badge.

## Goals

- **No sidebar on the start page.** At every width, `#/home` renders without `.app-sidebar`, without the
  phone `.app-topbar` and without the "Open navigation" button. Every other route is unchanged.
- **A start-page top bar** (`<header class="start-topbar">`, a `banner` landmark), left to right:
  - The ARP lockup: a link named "ARP start" to `#/home`. The landing header's inline lockup is
    extracted into `components/ArpLockup.tsx`, used by both `Landing.tsx` and the top bar. Its svg is
    `aria-hidden` and its apex uses `--brand-apex`. It is 28px high, 32px from the left edge and 24px
    from the top, exactly where the landing header puts it, so it stays in place after "Open ARP →".
  - A search button named "Search or jump to…", showing the shortcut hint (`⌘K` on Mac, `Ctrl K`
    elsewhere, as the sidebar does today) in a `<kbd aria-hidden="true">`, so the accessible name is
    exactly "Search or jump to…". It opens the existing command palette.
  - An **Ask ARP** button with the `⌘J` / `Ctrl J` hint (also an
    `aria-hidden` `kbd`; accessible name exactly "Ask ARP"), rendered only when Ask is available (today's
    `canAsk`). It opens the existing Ask panel. Closing the panel returns focus to this button.
  - Inside `<nav aria-label="Main">`:
    - A **Review Queue** link to `#/review`. When the review count is above 0, it carries the sidebar's
      badge: same text (`N item(s)`), same `title` and `aria-label`, from the same
      `waiting.review` number.
    - A **Reports** link to `#/reporting`.
    - A **user menu** button showing only an avatar initial. Its accessible name is `useMe().name`, or
      "Account" when there is none. The name is not shown visibly a second time, since the greeting
      already shows it.
- **User menu.** A disclosure popover, not `role="menu"`, holding today's components:
  - `ReviewerField` (the "Reviewing as" name);
  - `SignedInAs` (the signed-in line, with "Sign out" when signed in with a token);
  - `ThemeSwitch`;
  - a link "Arcade" to `#/arcade`.

  Keyboard behaviour:
  - Opening it moves focus to its first focusable element.
  - Esc or a click outside closes it and returns focus to the button.
  - Tab past the last element closes it and focus moves on.
- **Header.** It is the greeting alone: one `h1`, "Good morning|afternoon|evening[, name]." It keeps
  today's greeting typography: Geist, same size and weight as `.hub-hero-greet` today. The existing
  runs error message with Retry stays, between the header and the cards.
- **Removed from the page and the code:**
  - the stats row (`.hub-stats`);
  - the waiting link (`.hub-waiting`, `.hub-waiting-quiet`);
  - "What counts?" (`.hub-counts`);
  - the dot legend (`StateLegend`, `.hub-legend`);
  - the Now row (`.hub-now`, `.hub-chip`);
  - the card footer (`.hub-card-foot`, `CardView.footer`);
  - the old card icon box (`.hub-card-icon`);
  - the functions `waitingSentence`, `waitingLink`, `waitingStat`, `waitingTarget`, and
    `lib/useWaitingTotal.ts`.
- **Card grid.** `.hub-cards` is `display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 20px`.
  - Cards 1–3 use `grid-column: span 2`; cards 4–5 use `span 3`.
  - From 761px to 1100px, every card spans 3.
  - At 760px and below, it is one column.
- **Waiting card.** A card whose tone is `wait` keeps the class `.hub-card-await`. Its border becomes
  `var(--await-edge)` (DESIGN.md, the needs-you shape on cards).
- **Card content.** Each card is one link and holds, top to bottom:
  - a figure area (`.hub-card-fig`), at least 200px tall, with:
    - a mono caption "Fig 0n · N process" or "N processes" (n = the card's position, N = its process
      count);
    - the workspace drawing;
  - the name;
  - the purpose;
  - a status line (`.hub-card-status`):
    - one 8×8px square per process (`.hub-mark-<state>`);
    - the status word;
    - when there is a detail, " · " and the detail.
- **Status.** `cardStatus` gives the word, its tone and the detail. The first match wins:

  | Process states | Word | Tone | Detail | Word colour |
  |---|---|---|---|---|
  | any waits | "Waiting on you" | `wait` | the waiting process's title | `--hi-ink` |
  | else any runs | "Running" | `now` | the running process's title | `--run` |
  | else any failed | "Last run failed" | `failed` | the failed process's title | `--low` |
  | else any finished | "Up to date" | `done` | "Last run … ago" (today's `cardView().now`) | `--muted` |
  | else | "No runs yet" | `idle` | none | `--muted` |
  | runs unknown | "Status unknown" | `unknown` | none | `--muted` |

  Squares: `done` filled `--text`, `now` `--run`, `wait` `--hi`, `failed` `--low`, `idle` a 1px
  `--muted` outline, `unknown` a 1px dashed `--muted` outline.
- **Drawings.** Original isometric wireframes, one per workspace:
  - StewardIQ: stacked slabs.
  - Argus: a slab with rising data blocks.
  - Transition Intel: a rising fin array.
  - R&D Lab: grouped blocks of different heights.
  - Data Hub: stacked discs.

  Every stroke is 1px; faces fill with `--panel`; strokes are `--text` mixed to 20–30%. At most one
  shape is accented: `--hi` when the card's tone is `wait`, `--run` when it is `now`, none otherwise.

## Non-goals

- Colour tokens. The page uses today's tokens; "running" stays `--run`, the current blue. Palette work,
  including the mockup's neutral look, is a separate spec.
- The typeface. The owner compared five pairings and kept today's fonts: Geist for everything on the
  start page, including the greeting. The landing page keeps its serif headline. The mockup's Inter is
  not adopted.
- Any route other than `#/home`.
- Search behaviour. The button only opens the existing palette.

## Anti-goals

- A fact shown twice on the start page.
- The reviewer name, theme switch or Sign out becoming unreachable from the start page.
- Amber used for anything but waiting (DESIGN.md, The One Signal Rule).
- A keyboard user who can't open, use and close the user menu.

## Approaches

1. **Start-page top bar plus sidebar elsewhere (chosen).** Smallest change; other pages stay familiar.
2. A global top bar for all pages. Bigger, touches every screen. Rejected for now.
3. Keep the sidebar but collapse it on the start page. Keeps the duplication. Rejected.

## Decided

- **App shell.**
  - `App.tsx` renders `<StartTopbar />` instead of the phone top bar and the sidebar when the route is
    `home`.
  - Below 760px the search button shows only a search icon and the hint, keeping its accessible name.
    The user menu button shows only its avatar initial, with the name as its accessible name.
  - Ask ARP stays visible at every width when available.
  - `closeAsk` returns focus to the start top bar's Ask button when the route is `home`.
- **Logic.**
  - `lib/workspaceCard.ts` gains
    `export function cardStatus(states: (StepState | "unknown")[] | null, titles: string[], lastLine: string): { word: string; tone: StepState | "unknown"; detail: string }`.
    `cardView` drops `footer` and adds `status`.
  - `lib/workspaceCard.ts` also gains
    `export function reviewBadge(count: number): { text: string; title: string } | null`.
    The sidebar uses it too, so both show the same text.
- **Drawings.**
  - `lib/workspaceDrawing.ts` exports
    `export function drawing(id: WorkspaceId, accent: "wait" | "now" | null): { d: string; part: "face" | "top"; accent: boolean }[]`.
    It holds the geometry only, with no colours.
  - `components/WorkspaceDrawing.tsx` renders the shapes as SVG paths with classes. The CSS reads
    `--panel`, `--text`, `--hi` and `--run`.
- **Amber lines added** (for `ac13_amber_usage_unchanged`'s allow-list):
  - `.hub-status-wait` (`color: var(--hi-ink)`);
  - `.hub-mark-wait` (`background: var(--hi)`);
  - `.ws-accent-wait` (`stroke: var(--hi)`);
  - `.hub-card-await {` (`border-color: var(--await-edge)`).

  The top bar badge reuses `.nav-count`, which is already allowed.
- **DESIGN.md is updated in this change.**
  - Process Card: drawing, caption, status line, no "Open →".
  - Layout: the start page has no sidebar; it is greeting, then cards in 3 + 2.
  - "Needs you" count: shown in the sidebar and the start top bar.
  - Theme switch: it lives in the sidebar and in the start page's user menu.
  - The Icon Accent Rule now reads: one element lights `--hi` when the workspace waits, or `--run` when
    it runs.
  - The phrase checked by `workspaceCard.test.ts` "AC-20" stays absent.

## Supersedes

- **`2026-11-03-start-page-cards-as-navigation`:**
  - AC-1, AC-2, AC-3, AC-16 (footer "Open →");
  - AC-18 (stats row);
  - AC-24 (Now row);
  - AC-25 (legend);
  - AC-15 (no status words inside cards): cards now carry a status word;
  - AC-22 (restated over `.hub-mark-wait` as AC-13d below).
- **`2026-11-09-night-desk-start-page`:**
  - AC-1 to AC-9, AC-8b, AC-8c (waiting sentence, link and stat);
  - AC-10, AC-10b (`.hub-card-icon`);
  - AC-10c (footer);
  - AC-11, AC-11b, AC-11c;
  - AC-13a, AC-13b, AC-13c;
  - AC-14, AC-15.
- **`2026-11-09-night-desk-waiting-link`:** AC-1 to AC-11 (`waitingTarget`, the link and its
  destination).
- **`2026-11-14-landing-brand-refresh`:** AC-23 (`.app-sidebar` after Open ARP), restated as AC-17 below.
- **Tests retired in `frontend/tests/workspaceCard.test.ts`:**
  - "AC-1/2/3: every card's footer is 'Open →'";
  - `r4_ac1` to `r4_ac7`, `r4_ac8`, `r4_ac8b`, `r4_ac8c` (the loop), `r4_ac9`;
  - `r4_runs_error_wins`, `r4_nan_is_no_link`;
  - `r6_ac1` to `r6_ac8`.
- **Tests in `frontend/tests/nightDeskTokens.test.ts`:**
  - retired: `r4_ac10`, `r4_ac10b`, `r4_ac10c`, `r4_ac11`, `r4_ac11b`, `r4_ac11c`,
    `r4_waiting_link_wraps`;
  - `ac13_amber_usage_unchanged`: the allow-list drops `.hub-waiting` and
    `.hub-card-await .hub-card-icon`, and adds the four selectors above. The `.hub-card-await .hub-ico`
    rules (`index.css` lines 1729–1730) are deleted with the old icons. The test matches line by line,
    so each of the four new rules is written on one line, for example
    `.hub-card-await { border-color: var(--await-edge); }`.
- **Tests edited in `backend/tests/e2e/test_app_smoke.py`:**
  - `test_opening_arp_lands_on_the_landing_page` expects `.start-topbar` (count 1) instead of
    `.app-sidebar` after "Open ARP →".
  - `test_start_page_signs_in_and_loads_without_errors` opens the user menu before asserting "Signed in
    as dev (approver)".
  - `test_navigating_to_the_review_queue_loads_it_from_the_api` is unchanged: its link is now the top
    bar's, still inside a `navigation` landmark.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1a | The running app at `/#/home`, 1440×900 | The page loads | There is no `.app-sidebar` element | evaluator |
| AC-1b | The same | The page loads | There is exactly one `.start-topbar`, with role `banner` | evaluator |
| AC-1d | `/#/home`, 1440×900 | The lockup is measured | Its rendered height is 28px, its left edge is 32px (±1) from the viewport and its top is 24px (±1), the same as `.landing-mark` on `#/welcome` | evaluator |
| AC-1e | `/#/home` | The `h1` is read | Its computed `font-family` starts with `"Geist"`, and its font-size and font-weight equal `main`'s `.hub-hero-greet` | evaluator |
| AC-1c | `/#/home` at 1440×900 and at 390×844 | The page loads | There is no `.app-topbar` and no button named "Open navigation" | evaluator |
| AC-2 | `/#/review`, 1440×900 | The page loads | `.app-sidebar` is present | evaluator |
| AC-3 | `/#/home`, 1440×900, the e2e stack's approver `dev` | The top bar's controls are read in DOM order | Their accessible names are "ARP start", "Search or jump to…", "Ask ARP", "Review Queue" (plus its badge's name when there is one), "Reports" and "dev" | evaluator |
| AC-3b | `StartTopbar.tsx` | Read | The Ask ARP button is rendered only inside a `canAsk &&` condition, and `canAsk` is passed from `App.tsx`'s existing `canAsk` | unit |
| AC-4 | `reviewBadge` | Called with 0, 1 and 15 | Returns `null`, `{ text: "1 item", title: "1 review item waiting on you" }` and `{ text: "15 items", title: "15 review items waiting on you" }` | unit |
| AC-5 | `App.tsx` and `StartTopbar.tsx` | Read | Both build the Review Queue badge with `reviewBadge(` from the same `waiting.review` value | unit |

Accepted exceptions to "observable": AC-3b and AC-5 are source checks. The e2e stack's dev auth always signs in the approver `dev` (no viewer), its seed has 0 Review Queue items, and the frontend has no render-test harness. AC-4 covers the badge's visible text.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-6 | `/#/home` | The search button is clicked | The command palette dialog is visible | evaluator |
| AC-6b | `/#/home`, approver `dev` | "Ask ARP" is clicked | The Ask panel opens | evaluator |
| AC-6c | The Ask panel opened from the top bar | The panel is closed | Focus is on the "Ask ARP" button | evaluator |
| AC-7a | `/#/home` | The user menu button is clicked | It has `aria-expanded="true"` | evaluator |
| AC-7b | The same | The popover is read | It contains the "Reviewing as" field, the theme switch and a link "Arcade" to `#/arcade` | evaluator |
| AC-7c | The e2e stack (dev sign-in) | The user menu is opened | The text "Signed in as dev (approver)" is visible | evaluator |
| AC-8a | The user menu is open | Esc is pressed | The popover is hidden | evaluator |
| AC-8b | The same | Esc is pressed | `document.activeElement` is the user menu button | evaluator |
| AC-8c | The user menu button has focus | Enter is pressed | Focus is on the popover's first focusable element | evaluator |
| AC-8d | The user menu is open | A click lands outside it | The popover is hidden | evaluator |
| AC-8e | The same | A click lands outside it | Focus is on the user menu button | evaluator |
| AC-8f | The user menu is open with focus on its last focusable element | Tab is pressed | The popover is hidden and focus is on the element after the user menu button in DOM order | evaluator |
| AC-9a | `/#/home` | The main content is read | It holds exactly one `h1`, whose text matches `^Good (morning\|afternoon\|evening)(, .+)?\.$` | evaluator |
| AC-9b | The same | The DOM is searched | None of `.hub-stats`, `.hub-waiting`, `.hub-counts`, `.hub-legend`, `.hub-now`, `.hub-card-foot` or `.hub-card-icon` exists | evaluator |
| AC-10 | `index.css` | Read | `.hub-cards` sets `grid-template-columns: repeat(6, minmax(0, 1fr))` and `gap: 20px`; cards 1–3 span 2 and 4–5 span 3; under `max-width: 1100px` each card spans 3; under `max-width: 760px` the grid is one column | unit |
| AC-11a | `/#/home`, 1440×900 | Each card is read | Its `.hub-card-fig` is at least 200px tall and holds an `svg` | evaluator |
| AC-11b | The same | Each card's caption is read | It matches `^Fig 0[1-5] · \d+ process(es)?$`, with the card's position and process count | evaluator |
| AC-11c | The same | Each card's `.hub-card-status` is read | It holds one 8×8px `.hub-mark-*` element per process | evaluator |
| AC-11d | The same | Each card's `.hub-card-status` text is read | It matches `^(Waiting on you\|Running\|Last run failed\|Up to date\|No runs yet\|Status unknown)( · .+)?$` | evaluator |
| AC-12 | `cardStatus` | Called with states `[done, wait, idle]`, `[now, idle]`, `[failed, done]`, `[done, done]` (last line "Last run 2 h ago"), `[idle]`, and `null` | Returns (word, tone, detail): ("Waiting on you", `wait`, the 2nd title), ("Running", `now`, the 1st title), ("Last run failed", `failed`, the 1st title), ("Up to date", `done`, "Last run 2 h ago"), ("No runs yet", `idle`, ""), ("Status unknown", `unknown`, "") | unit |
| AC-12b | `cardStatus`, every case in AC-12 | Its result is read | `detail` never equals `word` | unit |
| AC-12c | `index.css` | Read | `.hub-status-wait` sets `color: var(--hi-ink)`; `.hub-status-now` `var(--run)`; `.hub-status-failed` `var(--low)`; `.hub-status-done`, `.hub-status-idle` and `.hub-status-unknown` `var(--muted)` | unit |
| AC-12d | `index.css` | Read | `.hub-mark-*` are 8px squares; `.hub-mark-done` fills `var(--text)`, `-now` `var(--run)`, `-wait` `var(--hi)`, `-failed` `var(--low)`; `-idle` has a 1px solid `var(--muted)` outline and `-unknown` a 1px dashed one | unit |
| AC-12e | `index.css` | Read | No rule whose selector starts with `.hub-status-now`, `.hub-mark-now`, `.ws-accent-now` or `.hub-card` and contains `-now` uses `var(--hi` or `var(--await`; `.hub-mark-now` and `.ws-accent-now` use `var(--run)` | unit |
| AC-13a | `drawing` | Called for each of the five ids with accent `null`, `"wait"` and `"now"` | Exactly 0, 1 and 1 shapes have `accent: true` | unit |
| AC-13b | `drawing` | Called for the five ids with accent `null` | The five shape lists are pairwise different | unit |
| AC-13c | `index.css` | Read | `.ws-drawing path` sets `stroke-width: 1px`; `.ws-face` sets `fill: var(--panel)`; the drawing stroke is a `color-mix` of `var(--text)` between 20% and 30% | unit |
| AC-13d | `/#/home` on the e2e seed, StewardIQ waiting on its open stewardship decisions (a stack without them counts as a fail) | The cards are read | Every card holding a `.hub-mark-wait` has the class `hub-card-await`; no other card does | evaluator |
| AC-14 | `WorkspaceDrawing.tsx` and `workspaceDrawing.ts` | Read | Neither contains a hex, `rgb(`, `rgba(`, `hsl(` or `oklch(` literal, or a CSS named colour | unit |
| AC-15 | `/#/home` with the backend stopped | The page loads | No element except the lockup's apex (which uses `--brand-apex`) has a computed colour, background, fill, stroke or border colour equal to the computed `--hi` or `--hi-ink` | evaluator |
| AC-16a | `/#/home`, 390×844 | The page loads | `document.documentElement.scrollWidth` ≤ 390 | evaluator |
| AC-16b | The same | The top bar is read | It shows the lockup, the search button, "Ask ARP" (approver), "Review Queue", "Reports" and the user menu button | evaluator |
| AC-17a | The landing page | "Open ARP →" is clicked | The hash becomes `#/home` | evaluator |
| AC-17b | The same | "Open ARP →" is clicked | `.start-topbar` is present | evaluator |
| AC-17c | The same | "Open ARP →" is clicked | The landing `h1` is gone | evaluator |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-18 | Any card on `/#/home` | It is clicked | The hash becomes that workspace's route (`#/stewardiq`, `#/argus`, `#/transitionIntel`, `#/rdLab`, `#/dataHub`) | evaluator |
| AC-19 | `cardView`, today's fixtures (busy, calm, down) | `label` is read | It equals today's value for every workspace (cards-as-navigation AC-14 and AC-21 unchanged) | unit |
| AC-20 | `/#/home` with runs failing to load | The page loads | The "Runs could not be loaded…" message with Retry shows above the cards | evaluator |
| AC-21 | The branch | `npm test` and `pytest -m e2e tests/e2e` run | Both pass; the only existing tests edited or retired are those listed under Supersedes | unit |
