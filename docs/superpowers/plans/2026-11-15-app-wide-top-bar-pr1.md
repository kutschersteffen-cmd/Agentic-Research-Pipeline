# App-wide top bar, PR 1 (the shell) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One top bar on every page except the landing page. It adds a Workspaces menu and a workspace row,
and removes the sidebar, the drawer and the phone top bar.

**Architecture:**
- `StartTopbar` becomes `AppTopbar`, gaining a Workspaces disclosure. Both popovers share one hook.
- A pure `workspaceOfRoute(hash)` decides the workspace row. A pure `workspaceMenuItems(runs, flow, now)` gives
  the menu's links and tones.
- `App.tsx` drops the sidebar branch and renders the bar plus `WorkspaceRow` for every route.

**Tech Stack:** React 19 + TypeScript (Vite), `node --test --experimental-strip-types` (DOM-less source and CSS
checks), pytest + Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md`, PR 1 section, rows AC-1 to AC-24 and
AC-32. PR 2 and PR 3 get their own plans.

## Global Constraints

- Colours, tokens and fonts do not change. Use the existing tokens only (`--text`, `--muted`, `--panel-border`,
  `--run`, `--hi`, `--hi-ink`, `--await-edge`).
- Amber (`var(--hi…)`/`var(--await…)`) is added nowhere. `nightDeskTokens` ac13 compares amber lines with `main`.
- The landing page (`#/welcome`, `#/`) is untouched.
- Every former sidebar destination stays reachable:
  - Start: the lockup and the Workspaces menu;
  - workspaces: the Workspaces menu;
  - Review Queue and Reports: the top bar;
  - Arcade: the user menu.
- Phone (≤760px): the top bar has exactly two rows at ≥360px, every control is ≥44px tall, and no sideways scroll.
- Workspace row label: `` `${w.short ?? w.name} screens` ``. The menu uses `w.short ?? w.name` too.
- Never weaken a test to pass. Every retired or changed test is listed in the PR body, and the owner adds
  `tests-weakened-ok`.

## Review Focus

- **Navigating from inside the Workspaces menu.** A click on a link changes the hash; the menu must close and
  must not steal focus back. Test: Task 2, `pr1_menu_closes_on_hashchange`.
- **Tablet widths (761–1024px).** These used to get the drawer and now get the desktop bar. At 800px and 1024px
  no route may scroll sideways. Test: Task 3, e2e `test_top_bar_fits_tablet_widths`.
- **Routes with ids after the tab** (`#/argus/<flowId>`, `#/review/<kind>/<id>`). The row and `aria-current`
  must follow the tab, not the full hash. Test: Task 1 (`#/argus/abc123`), and Task 3's row check on
  `#/review/extraction/x` (no row).
- **The leave guard.** A screen with unsaved changes refuses navigation (`canLeave`). Top bar links go through
  the same `hashchange` path, and `test_authority_taxonomy_page.py` keeps asserting it. Test: Task 4.
- **Large Review Queue badge on 360px.** "123 items" must not create a third row. Test: Task 3, e2e
  `test_top_bar_two_rows_at_360` with the badge text forced long via route interception.

---

### Task 1: `workspaceOfRoute`

**Files:**
- Modify: `frontend/src/lib/processes.ts` (append after `workspaceOfProcess`, ~l.288)
- Test: `frontend/tests/workspaceRoute.test.ts` (new)

**Interfaces:**
- Produces: `workspaceOfRoute(hash: string): WorkspaceId | null` and
  `rowLinks(w: Workspace): [href: string, label: string][]` (name link first, then `w.screens`).

- [ ] **Step 1: Write the failing test** `pr1_ac10_workspace_of_route`:
  ```ts
  const cases: [string, string | null][] = [["#/argus","argus"],["#/argus/abc123","argus"],["#/argus/new","argus"],
    ["#/argus/new/transition_plan","transitionIntel"],["#/voting","stewardiq"],["#/library","dataHub"],["#/review",null],
    ["#/reporting",null],["#/home",null],["#/arcade",null],["#/nosuch",null],["#/review/extraction/x",null]];
  for (const [h, want] of cases) assert.equal(workspaceOfRoute(h), want, h);
  ```
  Also `pr1_row_links`: `rowLinks(Argus)[0]` is `["#/argus","Argus"]`, and the remaining entries deep-equal
  `Argus.screens`.
- [ ] **Step 2:** Run `cd frontend && node --test --experimental-strip-types tests/workspaceRoute.test.ts`.
  Expected: FAIL (not exported).
- [ ] **Step 3:** Implement both functions in `lib/processes.ts`. Rules in order, per the spec:
  0. the tab is in `["home","review","reporting","arcade"]` → null;
  1. the tab is a workspace id;
  2. longest `screens` href equal to the hash or a `/`-prefix of it;
  3. the tab is a step `tab` (first workspace in `WORKSPACES` order);
  4. otherwise null.

  The tab is `hash.replace(/^#\/?/, "").split("/")[0]`.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5:** Commit `feat(nav): workspaceOfRoute and rowLinks`.

### Task 2: `AppTopbar` with the Workspaces menu

**Files:**
- Rename: `frontend/src/components/StartTopbar.tsx` → `frontend/src/components/AppTopbar.tsx` (`git mv`)
- Create: `frontend/src/lib/useDisclosure.ts`
- Modify: `frontend/src/lib/workspaceCard.ts` (add `workspaceMenuItems`)
- Modify: `frontend/src/pages/ProcessHub.tsx` (export the existing `useRuns` and `useHouseFlow`)
- Modify: `frontend/src/index.css` (start-topbar block: menu popover, `aria-current` underline)
- Test: `frontend/tests/startTopbar.test.ts` (update paths), `frontend/tests/workspaceCard.test.ts` (add)

**Interfaces:**
- Consumes: `cardView` (existing), `WORKSPACES`.
- Produces:
  - `useDisclosure(): { open: boolean; setOpen(o: boolean): void; buttonRef; popRef; wrapRef }`. It owns #482's
    behaviour, moved verbatim from `StartTopbar`:
    - focus the first focusable on open;
    - Esc with focus inside the wrapper closes it and refocuses the button;
    - an outside pointerdown closes it, and a `setTimeout` refocuses the button only if nothing focusable took
      focus;
    - focusout of the wrapper closes it;
    - **new:** `hashchange` closes it without refocusing.
  - `workspaceMenuItems(runs: RunManifest[] | null, flow: StewardshipFlow | null, now: Date):
    { href: string; label: string; tone: "wait" | "now" | "failed" | null; word: string }[]`. It returns Start
    first, then the five workspaces. `tone` and `word` come from `cardView(w, runs, flow, now).status` when the
    tone is wait, now or failed; otherwise `null` and `""`.
  - `AppTopbar` props: `#482`'s, plus `active: string` (the route tab). The Workspaces popover content is a child
    component that calls `useRuns()` and `useHouseFlow()`, so polling runs only while the menu is open.

- [ ] **Step 1: Write failing tests.**
  - `pr1_menu_items`, in `workspaceCard.test.ts`:
    - `workspaceMenuItems(null, null, NOW).map(i => i.label)` deep-equals
      `["Start","StewardIQ","Argus","Transition Intel","R&D Lab","Data Hub"]`;
    - the hrefs are `["#/home","#/stewardiq","#/argus","#/transitionIntel","#/rdLab","#/dataHub"]`;
    - with `busy` (existing fixture), the StewardIQ item has `tone: "wait"` and `word: "Waiting on you"`;
    - with `null` runs, every tone is null.
  - In `startTopbar.test.ts`, change `bar()` to read `AppTopbar.tsx`. Add `pr1_workspaces_button_named`: the
    source contains `>Workspaces` inside a `<button` with `aria-expanded`. Add `pr1_menu_closes_on_hashchange`:
    `useDisclosure.ts` contains `addEventListener("hashchange"`.
- [ ] **Step 2:** Run `node --test --experimental-strip-types tests/workspaceCard.test.ts tests/startTopbar.test.ts`.
  Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `useDisclosure`, `workspaceMenuItems`, `AppTopbar`, and the CSS:
  - `useDisclosure` is used by both the user menu and the Workspaces menu.
  - Menu order in `<nav>`: Workspaces, Review Queue, Reports, user.
  - Each menu link: label, then (when a tone is set) `<span class="hub-mark hub-mark-{tone}" aria-hidden>` and
    `<span class="hub-status-{tone}">{word}</span>`.
  - `aria-current="page"` goes on the menu link whose href is `` `#/${workspaceOfRoute(location.hash) ?? (active === "home" ? "home" : "")}` ``.
    The Review Queue and Reports links get it when `active` is `review` or `reporting`.
  - The CSS reuses `.start-topbar-pop` for the new popover, and underlines `aria-current` links with
    `text-decoration-thickness: 2px; text-underline-offset: 6px`.
- [ ] **Step 4:** Run `npm test && npx tsc -b && npm run lint`. Expected: PASS. `App.tsx` still imports the old
  name until Task 3, so update that import in this task.
- [ ] **Step 5:** Commit `feat(nav): AppTopbar with the Workspaces menu`.

### Task 3: One shell: no sidebar, workspace row, phone layout

**Files:**
- Modify: `frontend/src/App.tsx`:
  - remove `ArpMark`, `navOpen`, `navRef`, `menuRef`, `askTopRef`, `askSideRef`, the sidebar/drawer/`app-topbar`
    JSX, the `nav-dot` logic, and `recentRuns`/`runsLoaded` if they become unused;
  - `closeAsk` always focuses `askRef`;
  - always render `<AppTopbar …/>` then `<WorkspaceRow active=… />`;
  - the shell class is `app-shell app-shell-start` on every route.
- Create: `frontend/src/components/WorkspaceRow.tsx`
- Modify: `frontend/src/lib/nav.ts`: delete `NAV_GROUPS` and `currentNavIds`, now unused. Keep `navCount`,
  `HUBS`, `redirectHash` and `entryTab`.
- Modify: `frontend/src/index.css`:
  - delete `.app-sidebar*`, `.app-topbar*`, `.nav-scrim`, `.nav-open`, `.nav-dot*` and the sidebar media blocks;
  - add `.ws-row` (44px, `overflow-x: auto`, `border-bottom: 1px solid var(--panel-border)`, current link
    underlined 2px `--text`);
  - the ≤760px start-topbar block puts the user menu on row 1 (lockup, search, Ask ARP, user; then Workspaces,
    Review Queue, Reports). Use `display: contents` on `.start-topbar-end` and `.start-topbar-nav` with `order`,
    plus a full-width `::after` break.
- Test:
  - `frontend/tests/nav.test.ts`: retire "the sidebar lists exactly the approved links…" and "currentNavIds marks
    a sidebar link…", with a comment naming this spec;
  - `frontend/tests/nightDeskTokens.test.ts`: retire the `.nav-dot-now/failed/done` entries in the r2 token list
    (~l.200), and remove `\.nav-dot-wait|` from the ac13 allow-list;
  - `frontend/tests/startTopbar.test.ts`: `sp_ac1_home_has_no_sidebar` becomes `pr1_no_sidebar_anywhere`
    (`App.tsx` has no `app-sidebar`, `app-topbar` or `Open navigation`, and renders `<AppTopbar` unconditionally,
    outside any `active ===` branch); `sp_ac5_same_badge_source` checks `App.tsx` passes
    `reviewCount={navCount("review", waiting)}`;
  - `backend/tests/e2e/test_app_smoke.py`: add the tests below, and retire
    `test_phone_drawer_takes_focus_on_a_screen_without_a_sidebar_link`.

**Interfaces:**
- Consumes: `workspaceOfRoute`, `rowLinks` (Task 1); `AppTopbar` (Task 2).
- Produces: `WorkspaceRow({ hash }: { hash: string })`. It renders `null`, or
  `<nav className="ws-row" aria-label={`${label} screens`}>`, with `aria-current="page"` on the matched link.
  That is the longest screens href that equals or `/`-prefixes the hash, else the name link.

- [ ] **Step 1: Write the failing tests.**
  - The unit source tests above.
  - e2e:
    - `test_every_route_has_one_banner_and_no_sidebar` (AC-1, AC-1b) over the spec's route list at 1440 and 390;
    - `test_workspace_row_on_argus` (AC-11 exact link list);
    - `test_no_row_on_review_detail` (`#/review/extraction/x` has no `.ws-row`);
    - `test_top_bar_fits_tablet_widths` (800 and 1024: `scrollWidth` ≤ width on `#/stewardiq` and `#/history`);
    - `test_top_bar_two_rows_at_360` (AC-16 on `#/stewardiq`). Intercept `**/api/review**` and
      `**/api/runs**` so the badge reads "123 items" if the badge comes from those endpoints; otherwise seed
      through the existing fixture helpers.
- [ ] **Step 2:** Run `cd frontend && npm test`. Expected: the new unit tests FAIL. Run the new e2e tests on the
  stack (`bash backend/scripts/e2e_stack.sh up`, then `pytest -m e2e tests/e2e/test_app_smoke.py`). Expected:
  FAIL.
- [ ] **Step 3: Implement** the App, `WorkspaceRow`, nav and CSS changes above.
- [ ] **Step 4:** Run `npm test && npx tsc -b && npm run lint`, rebuild (`vite build`), and run the e2e file.
  Expected: PASS.
- [ ] **Step 5:** Commit `feat(nav): one top bar on every page, workspace row, no sidebar`.

### Task 4: Overview clean-up, leave guard, DESIGN.md

**Files:**
- Modify: `frontend/src/pages/ProcessHub.tsx` (`WorkspaceOverview`): remove `p.hub-crumb` and `nav.hub-screens`.
  Delete their CSS if unused: `.hub-crumb`, `.hub-screens`, and `.hub-now-label`/`.hub-chip` only if nothing
  else uses them (grep first).
- Modify: `frontend/src/pages/ArgusStart.tsx` (~l.134): remove its `.hub-crumb`.
- Modify: `backend/tests/e2e/test_authority_taxonomy_page.py` (~l.273): click a top bar link (e.g. "Reports")
  instead of `a.nav-tab:not(.active)`. The leave-guard assertion is unchanged.
- Modify: `DESIGN.md`:
  - replace the `**Sidebar:**` and `**Mobile / tablet:**` component entries with `**Top bar:**` and
    `**Workspace row:**`;
  - Layout (l.~219): one top bar on every page, a workspace row inside workspaces, no sidebar;
  - the theme-switch line (l.~149): "in the user menu";
  - Signal Amber (l.~166): "Needs you" count in the top bar;
  - remove the sidebar-only bullets (l.~244, ~246).
- Test: `frontend/tests/designDoc.test.ts` (new) `pr1_ac24_design_md` per AC-24. e2e
  `test_overview_has_no_crumb_or_screens` (AC-14 on `#/stewardiq` and `#/argus`).

- [ ] **Step 1:** Write `pr1_ac24_design_md` and the e2e test. Run both. Expected: FAIL.
- [ ] **Step 2:** Make the code and DESIGN.md edits.
- [ ] **Step 3:** Run `npm test`, rebuild, run `pytest -m e2e tests/e2e/test_app_smoke.py
  tests/e2e/test_authority_taxonomy_page.py`. Expected: PASS.
- [ ] **Step 4:** Commit `feat(nav): drop overview breadcrumbs; DESIGN.md top bar`.

### Task 5: Verify and open the PR

- [ ] Full e2e suite on the stack. Expected: all pass (the retired drawer test is gone).
- [ ] Playwright check of every `evaluator` row AC-1 to AC-23 and AC-32, at 1440×900, 390×844 and 360×800,
  light and dark. Save screenshots.
- [ ] `/impeccable:impeccable audit`, then a fresh whole-branch review. Fix Critical/Important findings, each
  with a failing test first.
- [ ] Merge `origin/main`, push, and open the PR against `main`:
  - label `risk:normal`;
  - body: `Spec: app-wide-top-bar`, "PR 1 of 3", every retired or changed test, screenshots;
  - ask the owner for `tests-weakened-ok` (via the buttons).
