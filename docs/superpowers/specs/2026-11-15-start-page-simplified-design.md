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

## Goals

- **No sidebar on the start page.** At widths of 1025px and up, `#/home` renders without
  `.app-sidebar`. Every other route keeps the sidebar exactly as today.
- **A start-page top bar** (`.start-topbar`, a `banner` landmark), left to right:
  - the ARP lockup, a link to `#/home`;
  - a search button labelled "Search or jump to…" with a `⌘K` hint, which opens the existing command
    palette;
  - an **Ask ARP** button with a `⌘J` hint, shown only when Ask is available (today's `canAsk`), which
    opens the existing Ask panel. The mockup merged Ask into the search label, but the palette has no
    Ask entry, so Ask keeps its own button.
  - inside a `nav` landmark labelled "Main":
    - a **Review Queue** link to `#/review`. When the review count is above 0, it shows the count as an
      amber badge: the same number and tooltip as today's sidebar badge.
    - a **Reports** link to `#/reporting`.
    - a **user menu** button showing the reviewer name.
- **User menu.** It holds everything the sidebar carried about the person, using today's components:
  - the "Reviewing as" name (`ReviewerField`) and the signed-in line with Sign out (`SignedInAs`);
  - the theme switch (`ThemeSwitch`);
  - a link to Arcade.
- **Header.** It is the greeting alone: an `h1` of "Good morning|afternoon|evening[, name]." Nothing else
  sits between the top bar and the cards apart from the existing runs error message, which stays.
- **Removed from the page:**
  - the stats row (`.hub-stats`);
  - the waiting link (`.hub-waiting`);
  - the "What counts?" disclosure (`.hub-counts`);
  - the dot legend (`StateLegend`);
  - the "Now" chip row (`.hub-now`);
  - the card footer "Open →" (`.hub-card-foot`).
- **Cards.** The five workspace cards sit on a 6-column grid: three cards span 2 columns, then two
  span 3. Each card is one link and holds, top to bottom:
  - a figure area at least 200px tall, with a mono caption "Fig 0n · N process(es)" and the workspace
    drawing;
  - the name;
  - the purpose;
  - a status line: one 8px square per process, then a status word, then " · " and the process that
    matters now (`cardView().now`) when there is one.
- **Status word.** Derived from the card's process states, the first match wins:
  1. "Waiting on you" (amber), if any process waits;
  2. "Running" (`--run`), if any runs;
  3. "Last run failed" (`--low`), if any failed;
  4. "Up to date", if any has a finished run;
  5. "No runs yet".

  While runs are unknown, the word is "Status unknown".
- **Drawings.** Each workspace gets an original isometric wireframe: thin 1px strokes, faces in the
  panel colour, a 30° projection.
  - StewardIQ: stacked slabs.
  - Argus: a slab with rising data blocks.
  - Transition Intel: a rising fin array.
  - R&D Lab: grouped blocks of different heights.
  - Data Hub: stacked discs.

  At most one element of a drawing is highlighted: amber when the card waits, `--run` when it runs,
  none otherwise (DESIGN.md, The Icon Accent Rule).

## Non-goals

- **Colour tokens.** This page uses today's tokens; the accent for "running" stays `--run`, the current
  blue. The palette work, including the neutral "instrument" look in the mockup, is a separate spec.
- **The typeface.** It stays Geist; the mockup's Inter is not adopted.
- **The phone layout of other routes, and their sidebar content.**
- **Search behaviour.** The search button only opens the existing command palette.

## Anti-goals

- A fact shown twice on the start page.
- The reviewer name, theme switch or Sign out becoming unreachable from the start page.
- Amber used for anything but waiting (DESIGN.md, The One Signal Rule).
- A keyboard user who can't reach and close the user menu.

## Approaches

1. **Start-page top bar plus sidebar elsewhere (chosen).** Smallest change; other pages stay familiar.
2. A global top bar for all pages, replacing the sidebar everywhere. Bigger, and it touches every
   screen. Rejected for now.
3. Keep the sidebar but collapse it on the start page. It keeps the duplication the owner wants gone.
   Rejected.

## Decided

- **App shell.**
  - `App.tsx` skips rendering `<aside className="app-sidebar">` and the phone top bar when the route
    is `home`, and renders `<StartTopbar />` instead.
  - The phone drawer button is not shown on `#/home`.
  - Below 760px the top bar hides the search text and keeps the `⌘K` button as an icon. It also hides
    the name in the user menu button.
- **User menu.** A button with `aria-expanded` and `aria-controls` opens a popover. Esc or a click
  outside closes it and returns focus to the button. The first focusable element inside gets focus on
  open.
- **Card status.**
  - `cardView` drops `footer` and gains `status: { word: string; tone: "wait" | "now" | "failed" | "done" | "idle" | "unknown" }`.
  - The card's `aria-label` stays as today: the name plus each process's state.
- **Drawings.** They live in a new `components/WorkspaceDrawing.tsx`, one SVG per workspace id, drawn
  with `currentColor`-free classes that read `--panel`, `--text` (strokes at 20–30% via
  `color-mix`), `--hi` and `--run`. There are no colour literals.
- **Count.** The Review Queue count is `App`'s existing `waiting.review`, the number today's sidebar
  badge shows.

## Supersedes

- In `frontend/tests/workspaceCard.test.ts`:
  - "AC-1/2/3: every card's footer is 'Open →'" is retired, because the footer is removed.
  - The waiting-link tests `r4_ac8`, `r4_ac8b`, `r4_nan_is_no_link`, `r4_runs_error_wins`, the loop at
    line 92 and `r6_ac4` to `r6_ac8` are retired. `waitingLink`, `waitingSentence` and `waitingStat`
    are removed with the headline link and stats.
- In `frontend/tests/nightDeskTokens.test.ts`: `r4_ac10c`, `r4_ac11`, `r4_ac11b`, `r4_ac11c` and
  `r4_waiting_link_wraps` (CSS for the removed elements) are retired. `ac13_amber_usage_unchanged`
  drops `.hub-waiting` from its allow-list.
- In `backend/tests/e2e/test_app_smoke.py`, `test_opening_arp_lands_on_the_landing_page`:
  - after "Open ARP →" it expects `.start-topbar` instead of `.app-sidebar` (count 1);
  - the Review Queue step clicks the top bar's "Review Queue" link (still inside a `navigation`
    landmark).
- From `2026-11-14-landing-brand-refresh`: AC-23 (".app-sidebar is present after Open ARP") becomes
  ".start-topbar is present" (AC-16 here).
- The night-desk start-page specs' rows for the stats row, the waiting link, the legend, "What
  counts?", the Now row and the card footer are superseded by this page. Their tests are listed above.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The running app at `/#/home`, 1440×900 | The page loads | There is no `.app-sidebar` element in the DOM and exactly one `.start-topbar` with role `banner` | evaluator |
| AC-2 | The running app at `/#/review`, 1440×900 | The page loads | `.app-sidebar` is present, as today | evaluator |
| AC-3 | `/#/home`, 1440×900 | The page loads | Inside `.start-topbar`, the visible link and button texts in order are: the ARP lockup (`svg[aria-label=ARP]`), "Search or jump to…", "Ask ARP" (when Ask is available), "Review Queue", "Reports", and the reviewer name | evaluator |
| AC-4 | `/#/home` with 15 reviewable items | The page loads | The Review Queue link's badge reads `15` with background `--hi`; the link's href is `#/review` | evaluator |
| AC-5 | `/#/home` with 0 reviewable items | The page loads | The Review Queue link shows no badge | evaluator |
| AC-6 | `/#/home` | The search button is clicked | The command palette opens (its dialog is visible) | evaluator |
| AC-6b | `/#/home` with Ask available | "Ask ARP" is clicked | The Ask panel opens, as the sidebar's Ask button does today | evaluator |
| AC-7 | `/#/home` | The user menu button is clicked | A menu opens holding the "Reviewing as" name field, the signed-in line with "Sign out", the theme switch and an "Arcade" link; the button has `aria-expanded="true"` | evaluator |
| AC-8 | The user menu is open | Esc is pressed | The menu closes and focus is on the user menu button | evaluator |
| AC-9 | `/#/home` | The page's main content is read | It holds exactly one `h1`, whose text matches `^Good (morning\|afternoon\|evening)(, .+)?\.$`, and none of `.hub-stats`, `.hub-waiting`, `.hub-counts`, `.hub-legend`, `.hub-now` or `.hub-card-foot` | evaluator |
| AC-10 | `/#/home`, 1440×900 | The cards are measured | Cards 1–3 share one row and cards 4–5 the next; card 4's width is 1.5× card 1's (±4px) | evaluator |
| AC-11 | `/#/home` | Each card is read | It contains a figure area at least 200px tall with an `svg`, a caption matching `^Fig 0[1-5] · \d+ process(es)?$`, the workspace name, its purpose and a status line | evaluator |
| AC-12 | `cardStatus` (in `lib/workspaceCard.ts`) | Called with process states `[done, wait, idle]`, `[now, idle]`, `[failed, done]`, `[done, done]`, `[idle]` and unknown runs | Returns the words "Waiting on you", "Running", "Last run failed", "Up to date", "No runs yet" and "Status unknown" with tones `wait`, `now`, `failed`, `done`, `idle`, `unknown` | unit |
| AC-13 | `WorkspaceDrawing.tsx` | Read | It contains no hex, `rgb(` or `oklch(` literal | unit |
| AC-14 | `/#/home` with StewardIQ waiting and Argus running | The drawings are read | StewardIQ's SVG has exactly one element using `--hi`, Argus's exactly one using `--run`, and Transition Intel's none of either | evaluator |
| AC-15 | `/#/home`, 390×844 | The page loads | No horizontal scroll; the top bar shows the lockup, a search icon button, Review Queue, Reports and the user menu button | evaluator |
| AC-16 | The landing page | "Open ARP →" is clicked | The hash becomes `#/home` and `.start-topbar` is present (replaces landing-brand-refresh AC-23) | evaluator |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-17 | Any card on `/#/home` | It is clicked | The hash becomes that workspace's route (`#/stewardiq`, `#/argus`, `#/transitionIntel`, `#/rdLab`, `#/dataHub`) | evaluator |
| AC-18 | Any card | Its `aria-label` is read | It equals today's `cardView().label` for the same data | unit |
| AC-19 | `/#/home` with runs failing to load | The page loads | The existing "Runs could not be loaded…" message with Retry shows above the cards | evaluator |
| AC-20 | `frontend/tests/` | `npm test` runs | Every test passes; the only existing tests edited or retired are those listed under Supersedes | unit |
