# The start page's style, app-wide

## Intent

PR #482 gave the start page (`#/home`) a new shell and a quieter look:
- a top bar instead of the sidebar;
- a user menu;
- wireframe drawings;
- 8px status squares with a word.

Every other page still has the old sidebar shell and round dots. The owner wants the same style on every page,
so the app has one shell and one way of showing state.

Visitors are the stewardship and research team. They work in five workspaces and their screens, often
screen-shared in committees and sometimes on a phone.

The mockup is `docs/superpowers/specs/assets/2026-11-15-app-wide-mockup.html` (artifact "App-wide Top Bar"). It
shows a workspace page with the Workspaces menu open, Run history, and the phone layout.

## Owner decisions (from the conversation)

- **Navigation.** One top bar on every page. Inside a workspace, a slim second row shows the workspace and its
  screens. A "Workspaces" menu in the top bar switches between the five. No sidebar anywhere.
- **Rollout.** One spec, two PRs: PR 1 is the shell, PR 2 the shared parts (squares instead of dots, run status,
  workspace header).
- **Colours and fonts stay as they are.** The paused Arctic foundation spec is a separate change.

## Goals

### PR 1: the shell

- **One top bar everywhere.** Every route except the landing page (`#/welcome`, `#/`) renders #482's top bar,
  `StartTopbar` renamed `AppTopbar` (class `.start-topbar` may be renamed; AC-1 checks the `banner` landmark).
  `App.tsx` no longer renders any of these:
  - `.app-sidebar`;
  - the phone `.app-topbar`;
  - the "Open navigation" button;
  - the drawer scrim.

  Their CSS is deleted, including the sidebar's `.nav-dot-*` workspace state dots.
- **Top bar contents.** From #482, in DOM order: lockup "ARP start", search, Ask ARP (when available), then
  `<nav aria-label="Main">` with **Workspaces**, Review Queue (+ badge), Reports and the user menu.
- **Workspaces menu.** A button named "Workspaces" opens a disclosure popover (not `role="menu"`) of six links:
  - Start `#/home`;
  - StewardIQ `#/stewardiq`;
  - Argus `#/argus`;
  - Transition Intel `#/transitionIntel` (the workspace's `short` name);
  - R&D Lab `#/rdLab`;
  - Data Hub `#/dataHub`.

  Behaviour:
  - A workspace whose start-page card tone (`cardView(...).status.tone`) is `wait`, `now` or `failed` shows,
    after its name, the same 8px `.hub-mark-<tone>` square and status word as its card. Other tones show nothing.
    This replaces the sidebar's state dots.
  - The link for the workspace the current route belongs to (Start on `#/home`) has `aria-current="page"`.
  - Opening moves focus to the first link.
  - Esc with focus inside the menu closes it and returns focus to the button.
  - A click outside closes it and returns focus to the button, unless the click focused another control.
  - Tab or Shift+Tab out of the menu and its button closes it.

  This is exactly #482's user-menu behaviour; the open/close logic is shared, not copied.
- **Current page.** The top bar's Review Queue and Reports links have `aria-current="page"` on `#/review` and
  `#/reporting`.
- **Which workspace a route belongs to.** A new helper, `workspaceOfRoute(hash)` in `lib/processes.ts`, returns
  a workspace id or null. The first rule that matches wins:
  0. The route id is one of `home`, `review`, `reporting`, `arcade`: null. These have their own place in the top
     bar.
  1. The route id (the first segment after `#/`) is a workspace id. This covers `#/argus`, `#/argus/<flowId>` and
     `#/stewardiq`.
  2. The hash equals, or starts with followed by `/`, a `screens` href of a workspace. The longest matching href
     wins, so `#/argus/new/transition_plan` → `transitionIntel` and `#/argus/new` → `argus`.
  3. The route id is the `tab` of a step in a workspace's processes. The first workspace in `WORKSPACES` order
     wins.
  4. Otherwise null.
- **The workspace row.** On a route where `workspaceOfRoute` is not null, a
  `<nav class="ws-row" aria-label="<workspace short ?? name> screens">` sits directly under the top bar. It holds:
  - the workspace's `short ?? name` as a link to `#/<id>`;
  - one link per `screens` entry, in list order. This includes Review Queue where a workspace lists it.

  Layout and state:
  - The current route's link has `aria-current="page"`. That is the screen whose href matched rule 2, or the
    name link when rule 1 or 3 matched.
  - The row is 44px high and not sticky.
  - Below 760px it scrolls sideways inside itself (`overflow-x: auto`) and never widens the page.
- **No duplicate navigation.** `WorkspaceOverview` removes these, because the row replaces them:
  - its "Screens" chip nav (`nav.hub-screens`);
  - its "Start › Name" line (`.hub-crumb`).

  `ArgusStart` (the `#/argus` overview) also removes its `.hub-crumb`.
- **Layout.** On every route, `main` is centred, at most 1248px wide, as on `#/home` today.
- **Focus and shortcuts.** Closing the Ask panel returns focus to the top bar's Ask button on every route.
  ⌘K / Ctrl K, ⌘J / Ctrl J and `?` work as today.
- **Phone (≤760px).** The top bar has exactly two rows at 360px and wider:
  - row 1: lockup, search (icon and hint, label visually hidden), Ask ARP, user menu;
  - row 2: Workspaces, Review Queue (+ badge), Reports.

  Every control in it is at least 44px tall, and no page scrolls sideways.
- **The step bar.** `ProcessBar` ("Step n of m · Next: …") is unchanged and renders under the workspace row.

### PR 2: the shared parts

- **Squares instead of dots.**
  - On workspace overviews, `.hub-process-state` shows one `.hub-mark hub-mark-<state>` square (8px) and the
    `STATE_LABEL` word, coloured by `.hub-status-<state>`. `.hub-dot` and all its CSS (including the
    `.hub-dots li…` selectors) go.
  - `.hub-step-status::before` (step cards) becomes an 8px square with no radius.
- **Run status as square and word.** `.status-pill` loses its border and pill radius, and shows an 8px
  `currentColor` square (`::before`) followed by its text.
  - `.status-running` (the colour rule at index.css ~695) uses `color: var(--run)` instead of `--accent`. Its
    other colours stay. The pipeline-card rule `.status-running { --edge: … }` (~1555) is unchanged.
  - `.status-pill` users that show a status get this look automatically. These are Run history, VotingRuns,
    ReportBuilder, EmergingThemesDetector, XbrlFetchArea, RunProgress, EngagementIssuePanel, ThemeDossiers and
    FactsTable. The builder lists any other user found in the PR.
  - The one user that is not a status, ThemeResearch's channel tag ("Economic"/"Financial", ThemeResearch.tsx
    ~285), switches to the existing `.chip` class.
- **Workspace header drawing.** `WorkspaceOverview` (all five overviews except `#/argus`) shows the workspace's
  `WorkspaceDrawing` at 120px wide, to the right of the `h1` and purpose. Its accent follows the start-page card
  rule: `wait`, `now` or none. Below 760px it is `display: none`.
- **Step card hover.** `.hub-step:hover` uses `border-color: var(--text)`.
- **DESIGN.md.** These change:
  - Layout: one top bar on every page, a workspace row inside workspaces, no sidebar.
  - The **Sidebar:** and **Mobile / tablet:** entries are replaced by **Top bar:** and **Workspace row:**.
  - Run status is described as square and word.

## Non-goals

- Colours, tokens, fonts (Arctic foundation spec).
- The landing page.
- In-page tab strips (`.nav-tab`), tables, forms and page copy, other than the removed breadcrumbs and Screens
  chips.
- A shortcut for the Workspaces menu.
- `ArgusStart`'s own layout beyond its breadcrumb.

## Anti-goals

- A page that scrolls sideways on a phone.
- A screen that can no longer be reached. Every former sidebar destination stays reachable:
  - Start: the lockup and the Workspaces menu;
  - the workspaces: the Workspaces menu;
  - Review Queue and Reports: the top bar;
  - Arcade: the user menu.
- Amber for anything but waiting on a person.
- Two shells again.

## Approaches

1. **Top bar plus a workspace row (chosen).** One shell, full width on every page, and a workspace's screens
   one click away. Switching workspace takes two clicks.
2. **Top bar with five workspace links.** Crowded, and it folds into a menu on phones anyway. Rejected.
3. **Restyled sidebar on inner pages.** Keeps two shells. Rejected.

For rollout, the owner chose two PRs, shell first.

## Decided (builder's calls)

- *Call:* the shared open/close logic is a small hook or a component; either is fine.
- *Call:* the row's links are plain text, with a 2px `--text` underline under the current one, as in the mockup.
- *Call:* how row 1 and row 2 are arranged on phones (DOM order or CSS). AC-3 still holds at desktop width, and
  AC-16 at phone width.

## Supersedes

**PR 1:**
- `backend/tests/e2e/test_app_smoke.py::test_phone_drawer_takes_focus_on_a_screen_without_a_sidebar_link`:
  retired, since there is no drawer.
- `backend/tests/e2e/test_authority_taxonomy_page.py` (~l.273): it clicks a sidebar `a.nav-tab`. It switches to
  a top bar link, keeping the same leave-guard assertion.
- `frontend/tests/nightDeskTokens.test.ts`: the release-2 checks requiring `.nav-dot-now`, `.nav-dot-failed` and
  `.nav-dot-done` rules (~l.199) are retired. `ac13`'s allow-list entry `.nav-dot-wait` is removed.
- Spec `2026-11-15-start-page-simplified` AC-2 (`/#/review` has `.app-sidebar`) is retired. AC-1a/AC-1c (no
  sidebar on home) still hold.
- Any other `frontend/tests` check that reads sidebar markup. The builder lists each one in the PR.

**PR 2:**
- Spec `2026-11-15-start-page-simplified` has no `.hub-dot` row.
- Any `frontend/tests` check of `.status-pill` borders or `.hub-dot`. The builder lists each one in the PR.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The running app, 1440×900, each of `#/home`, `#/review`, `#/stewardiq`, `#/argus`, `#/history`, `#/library`, `#/arcade` | The page loads | There is exactly one `banner` landmark, and it contains a link named "ARP start" | evaluator |
| AC-1b | The same routes, and the same routes at 390×844 | The page loads | There is no `.app-sidebar`, no `.app-topbar` and no button named "Open navigation" | evaluator |
| AC-2 | `#/welcome` | The page loads | The `h1` "Company research and stewardship at scale." is visible, and no button named "Workspaces" exists | evaluator |
| AC-3 | `#/review`, 1440×900, approver `dev` | The top bar's links and buttons are read in DOM order | Their accessible names are "ARP start", "Search or jump to…", "Ask ARP", "Workspaces", "Review Queue" (plus the badge name when shown), "Reports", "dev" | evaluator |
| AC-4 | `#/history` | "Workspaces" is clicked | It has `aria-expanded="true"`, and the popover holds exactly six links, in order: Start `#/home`, StewardIQ `#/stewardiq`, Argus `#/argus`, Transition Intel `#/transitionIntel`, R&D Lab `#/rdLab`, Data Hub `#/dataHub` | evaluator |
| AC-4b | The popover from AC-4 | Focus is read | It is on the "Start" link | evaluator |
| AC-5 | `#/argus/new` | The Workspaces popover is opened | The Argus link has `aria-current="page"`, and no other link does | evaluator |
| AC-5b | The e2e seed, with StewardIQ waiting on its open decisions | The Workspaces popover is opened | The StewardIQ link contains a `.hub-mark-wait` square and the text "Waiting on you" | evaluator |
| AC-6 | The Workspaces popover is open | Esc is pressed | The popover is hidden and focus is on the "Workspaces" button | evaluator |
| AC-7 | The Workspaces popover is open on `#/history` | The `h1` is clicked | The popover is hidden and focus is on the "Workspaces" button | evaluator |
| AC-8 | The Workspaces popover is open, focus on "Data Hub" | Tab is pressed | The popover is hidden and focus is on the "Review Queue" link | evaluator |
| AC-8b | The Workspaces popover is open, focus on "Start" | Shift+Tab is pressed twice | The popover is hidden and focus is on the "Ask ARP" button | evaluator |
| AC-9 | `#/review`; then `#/reporting` | The page loads | The top bar's "Review Queue" link (on `#/review`), then the "Reports" link (on `#/reporting`), has `aria-current="page"` | evaluator |
| AC-10 | `lib/processes.ts` | `workspaceOfRoute` is called with each hash: `#/argus`, `#/argus/abc123`, `#/argus/new`, `#/argus/new/transition_plan`, `#/voting`, `#/library`, `#/review`, `#/reporting`, `#/home`, `#/arcade`, `#/nosuch` | It returns, in order: `argus`, `argus`, `argus`, `transitionIntel`, `stewardiq`, `dataHub`, `null`, `null`, `null`, `null`, `null` | unit |
| AC-11 | `#/argus`, 1440×900 | The page loads | Exactly one `nav` named "Argus screens" exists, below the banner. Its links, in order: "Argus" `#/argus` (with `aria-current="page"`), "New extraction" `#/argus/new`, "Walkthrough" `#/argusWalkthrough`, "XBRL Facts" `#/xbrl`, "Review Queue" `#/review` | evaluator |
| AC-12 | `#/voting` | The page loads | Exactly one `nav` named "StewardIQ screens" exists, and its "Proxy Voting" link has `aria-current="page"` | evaluator |
| AC-12b | `#/transitionIntel` | The page loads | Exactly one `nav` named "Transition Intel screens" exists | evaluator |
| AC-13 | Each of `#/home`, `#/review`, `#/reporting`, `#/arcade` | The page loads | There is no `.ws-row` | evaluator |
| AC-14 | `#/stewardiq` and `#/argus` | The page loads | There is no `.hub-crumb`, no `nav.hub-screens`, and no visible text "Start ›" | evaluator |
| AC-15 | Each of `#/home`, `#/argus`, `#/stewardiq`, `#/review`, `#/history`, `#/voting` at 390×844 and at 360×800 | The page loads | `document.documentElement.scrollWidth` ≤ the viewport width | evaluator |
| AC-16 | `#/stewardiq` at 360×800, approver | The top bar is read | Every visible link and button in it is ≥ 44px tall, and their bounding boxes' `top` values take exactly two distinct values (±2px) | evaluator |
| AC-17 | `#/history`, approver | "Ask ARP" is clicked, then Esc closes the panel | Focus is on the top bar's "Ask ARP" button | evaluator |
| AC-18 | `#/stewardiq` | The first step card of the first process is clicked | The hash becomes that step's route, and a `nav` named "Process progress" shows "Step 1 of" followed by the process's step count | evaluator |
| AC-19 | `#/stewardiq`, the e2e seed with N > 0 review items | The page loads | The top bar's Review Queue link holds a badge with text `N items` (`1 item` when N = 1) and `aria-label` `N review items waiting on you` | evaluator |
| AC-20 | `#/voting`, 1440×900 | `main` is measured | It is at most 1248px wide, and its left and right offsets from the viewport differ by ≤ 1px | evaluator |
| AC-21 | `#/argus`, 1440×900 | The page scrolls down 400px | The workspace row has scrolled out of view (its bounding box `bottom` < the banner's `bottom`, or < 0) | evaluator |
| AC-22 | Any route except the landing page | Ctrl K is pressed | The command palette dialog is visible | evaluator |
| AC-22b | `#/history`, approver | Ctrl J is pressed | The Ask panel opens | evaluator |
| AC-23 | `#/library` | A second in-page tab (`.nav-tab`) is clicked | It gets the `active` class and the first one loses it | evaluator |
| AC-24 | `DESIGN.md` (PR 1) | Read | It contains `**Top bar:**` and `**Workspace row:**`, and no `**Sidebar:**` or `**Mobile / tablet:**` entry | unit |
| AC-25 | `#/stewardiq` (PR 2) | Each process heading's state is read | It holds exactly one 8×8px `.hub-mark-<state>` element and the matching `STATE_LABEL` word, and the page has no `.hub-dot` | evaluator |
| AC-26 | `index.css` (PR 2) | Read | It has no `.hub-dot` selector; `.hub-step-status::before` is 8px × 8px with no `border-radius` above 0; `.hub-step:hover` sets `border-color: var(--text)` | unit |
| AC-27 | `index.css` (PR 2) | Read | `.status-pill` has no `border` other than `0`/`none` and no `border-radius` above 0; `.status-pill::before` is 8px × 8px with `background: currentColor`; the `.status-running` rule that sets `color` uses `var(--run)` | unit |
| AC-28 | `#/history` with a run whose status is `running` (PR 2) | The status cell is read | It shows a square and the word, and its computed `color` equals the computed value of `--run` | evaluator |
| AC-29 | `ThemeResearch.tsx` (PR 2) | Read | The channel tag uses class `chip`, not `status-pill` | unit |
| AC-30 | `#/stewardiq`, 1440×900 (PR 2) | The header is read | There is one `svg.ws-drawing`, 120px wide, whose left edge is right of the `h1`'s right edge | evaluator |
| AC-30b | `#/stewardiq`, 390×844 (PR 2) | The header is read | The `svg.ws-drawing` has computed `display: none` | evaluator |
| AC-31 | `#/stewardiq` on the e2e seed, StewardIQ waiting on its open decisions (PR 2) | The header drawing is read | Exactly one of its shapes has the class `ws-accent-wait` | evaluator |
| AC-32 | `#/home` (PR 1 and PR 2) | The page loads | #482's acceptance rows that still hold pass unchanged: AC-1a, AC-1c, AC-3, AC-7a–AC-8f, AC-9a, AC-11a–AC-11d, AC-16a, AC-18 | evaluator |

Must not change:
- the landing page (AC-2);
- `ProcessBar` (AC-18);
- the palette and Ask shortcuts (AC-22, AC-22b);
- in-page tabs (AC-23);
- the start page (AC-32);
- every screen stays reachable (AC-3, AC-4, #482 AC-7b).
