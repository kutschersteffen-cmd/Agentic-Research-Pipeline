# UI polish 1: the owner's picks from the new-UI critique

## Intent

The critique of the new top bar and start page (2026-11-15) left a list of observations. The owner ticked 12 of them on the "New UI
Observations" page. Two are the same problem (the badge's tight padding), so there are 11 fixes. They are small and independent,
and one spec and one PR keep them reviewable as a single polish item.

Not picked, so not here:
- the P1 phone-row fix;
- the phone start page;
- the weight of the "Accept" button;
- the PR #484 code-review minors.

The waiting count has its own spec.

## Fixes

- **F1 Who is deciding (critique P2).** While someone is signed in (`useMe()` returns a user):
  - The user menu shows "Signed in as {name} ({role})" (plus Sign out when a token is set), the theme switch and the Arcade link. It
    does not show the "Reviewing as" field.
  - `AppTopbar` keeps the typed reviewer name (`localStorage` key `arp.reviewer`) equal to `me.name`, writing it whenever it differs.
    Voting decisions send `reviewer` from that store, so they record the verified name.

  When nobody is signed in, everything stays as today.
- **F2 Argus duplicate links (P3).** The `#/argus` header (`.argus-head-actions`) drops its "Walkthrough" and "XBRL Facts" links,
  because the workspace row has both. "Start new extraction" stays.
- **F3 Row alignment (P3).**
  - Above 760px, the workspace row's first link starts at the same x as `main h1`: `max(var(--s-8), calc((100% - 1248px) / 2 + var(--s-8)))`.
  - At 760px and below, the gutter stays 16px.
- **F4 Closed menus (minor).** Tab never reaches either menu's contents while the menu is closed. This is a test first; `hidden`
  should already guarantee it. If the test fails, a closed popover's contents are not rendered.
- **F5 Process heading on a phone (minor).** At 760px and below, a process's `h2` on a workspace page takes the full line. The state
  and cadence chips sit on the next line.
- **F6 Hub titles (minor).** On pages with a hub strip (Runs: Run history, Research plans, Standing agents; Library: Data Library,
  Search):
  - the `.hub-nav` overrides in `index.css` (the rules around ~l.1026–1035 that make the strip display-size and hide the page's `h1`) are deleted;
  - the strip falls back to the standard `.sub-nav .nav-tab` style;
  - the page's own `h1` shows.
- **F7 Failed is not amber (minor).** In `lib/argusStart.ts`, `tiles()` gains a `tone`:
  - `"await"` when the note is "N values need you";
  - `"failed"` when the note is "N failed";
  - `null` when there is no note.

  `ArgusStart` uses the class `argus-tile-await` for `await` and the new class `argus-tile-failed` for `failed`. `.argus-tile-failed`
  uses `--low` for its edge and note text, and no amber.
- **F8 Badge padding (minor; also the detector's cramped-padding finding).** `.nav-count` gets `padding: 2px var(--s-1_5)`, and its
  rendered height stays at or below 24px.
- **F9 What each workspace is (minor).** In the Workspaces menu, each workspace shows its `purpose` from `lib/processes.ts` under its
  name, in `var(--text-xs)` and `var(--muted)`. Start shows "Every workspace at a glance".
- **F10 Labels (minor).**
  - The start-page card caption drops the figure number: "Fig 01 · 3 processes" becomes "3 processes".
  - On step cards, "Hands on:" (what a step passes to the next) becomes "Passes on:".
  - "re-entered by hand" keeps its existing tooltip.
- **F11 A way to a failed run (minor).**
  - A new helper, `failedProcesses(w: Workspace, runs: RunManifest[] | null, flow: StewardshipFlow | null, activity: Activity | null): string[]`
    in `lib/workspaceCard.ts`, returns the titles of `w`'s processes whose `processState` is `failed`.
  - `WorkspaceOverview` shows one line per title, above the processes: "Last run failed: <title>." followed by a link "Open Run
    history →" to `#/history`.
  - The line uses `--low`, not amber.

## Non-goals

- The picks the owner did not make, and the waiting count.
- Any colour token or font change.

## Supersedes

- `2026-11-15-start-page-simplified` AC-11b (caption `^Fig 0[1-5] · …`). That row is a holdout test, so the test-writer updates it to
  `^\d+ process(es)?$`.
- `backend/tests/e2e/test_argus_showcase_fixes.py` ~l.79 (`.argus-head` has a Walkthrough link) and
  `backend/tests/e2e/test_argus_start.py` ~l.40 (XBRL Facts in `.argus-head`). Both assert the link in the "Argus screens" row
  instead.
- Any frontend test that reads "Hands on:" or the hidden hub `h1`. The builder lists each in the PR.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The e2e stack (dev sign-in), any route | The user menu is opened | It contains "Signed in as dev (approver)", the theme switch and an "Arcade" link, and no input labelled "Reviewing as" | evaluator |
| AC-1b | The same, with `localStorage["arp.reviewer"]` preset to `Ana` before load | The page has loaded | `localStorage["arp.reviewer"]` is `dev` | evaluator |
| AC-1c | Playwright stubs `**/api/me` with 401 | The user menu is opened | The "Reviewing as" input is present | evaluator |
| AC-1d | AC-1b's setup on a voting run with an undecided ballot | A vote is decided | The recorded decision's `reviewer` is `dev` | evaluator |
| AC-2 | `#/argus` | The page loads | `.argus-head` has no link named "Walkthrough" or "XBRL Facts" and still has the "Start new extraction" button; the "Argus screens" row has both links | evaluator |
| AC-3 | `#/argus`, 1440×900 | The row's first link and `main h1` are measured | Their left edges differ by ≤ 1px | evaluator |
| AC-3b | `#/argus`, 390×844 | The row's first link is measured | Its left edge is 16px (±1) | evaluator |
| AC-4 | Any route, both menus closed | Tab is pressed from the lockup through all top-bar controls | Focus never lands inside a `.start-topbar-pop` | evaluator |
| AC-5 | `#/stewardiq`, 390×844 | Each process heading is measured | The state chip's top ≥ the `h2`'s bottom | evaluator |
| AC-6 | `#/history`, 1440×900 | The page loads | An `h1` "Run History" is visible, and the hub links' computed font-size equals a `.nav-tab` outside the hub (14px) | evaluator |
| AC-6b | `#/library`, 1440×900 | The page loads | An `h1` "Data Library" is visible, and the hub links are 14px | evaluator |
| AC-6c | `index.css` | Read | No rule selects `.hub-nav ~ .page > h1` | unit |
| AC-7 | `lib/argusStart.ts` | `tiles()` runs on a fixture with 2 failed step-4 runs and 3 values to review at step 5 | Step 4 has `tone: "failed"` and `needs: "2 failed"`; step 5 has `tone: "await"`; a step with no note has `tone: null` | unit |
| AC-7b | `index.css` | Read | `.argus-tile-failed` uses `var(--low)` and no `var(--hi`, `var(--hi-ink`, `var(--await` | unit |
| AC-7c | `#/argus` on the e2e seed with failed extractions | Step 4's tile is read | Its computed border-color is not the computed `--await-edge`, and its note's colour equals the computed `--low` | evaluator |
| AC-8 | Any route with a badge, 1440×900 | The badge is measured | Computed padding-top is 2px and height ≤ 24px | evaluator |
| AC-9 | Any route | The Workspaces menu is opened | Each workspace link contains its `purpose` text at the computed size of `--text-xs`, and the Start link contains "Every workspace at a glance" | evaluator |
| AC-10 | `#/home` | Each card caption is read | It matches `^\d+ process(es)?$` | evaluator |
| AC-10b | `#/stewardiq` | The step cards' text is read | None contains "Hands on:", and at least one contains "Passes on:" | evaluator |
| AC-11 | `lib/workspaceCard.ts` | `failedProcesses` is called with a fixture where exactly one of R&D Lab's processes is `failed` | It returns `[that process's title]`; with two failed processes, both titles in order | unit |
| AC-11b | `#/rdLab`, with Playwright stubbing `**/api/runs*` to add one failed run of a type one R&D Lab step watches | The page loads | One line "Last run failed: <title>." whose link "Open Run history →" goes to `#/history`, with text colour equal to the computed `--low` | evaluator |

Must not change: the top bar's two phone rows (PR #484 AC-16), and amber appearing only for waiting (AC-7c checks the one place
this fix touches).
