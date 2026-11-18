# Night Desk, release 2: status lines, running colour, rounded cards, sidebar dots

## Intent

Release 1 (PR #367) brought Night Desk colours and fonts. Release 2 brings the mockups' status
language (`docs/design-directions.html`) into the real app: every workspace step says in one coloured
line what state it is in, "running" gets its own blue, cards get rounded corners, and the sidebar
shows a status dot per workspace. The owner wants to see at a glance where work is waiting, running
or failed, without opening each workspace.

## Goals

- Every non-planned step card on a workspace page (StewardIQ, Argus, Transition Intelligence
  Platform, R&D Lab, Data Hub) shows one status line under its title.
- "Running" has its own colour token, blue, in both themes.
- Start-page workspace cards, stat tiles and pipeline pills have rounded corners.
- Each workspace in the sidebar shows a status dot with an accessible label.

## Non-goals

- No start-page layout change (counts, "N things wait on you" link): a later release.
- No review-queue source excerpt, no landing page.
- No backend change; no new API calls.
- No change to how step or workspace state is computed (`lib/workspaceCard.ts` `stepState`,
  `processState` stay as they are).

## Anti-goals

- Amber used for anything other than "waiting on a person" (release 1's rule).
- A status that disagrees with the start page's step dots for the same step.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| **A (picked)** | One status line per step from the existing state, blue token, rounded cards, sidebar dots from the existing workspace state | Close to the mockups; CSS plus small changes in `ProcessHub.tsx` and `App.tsx` |
| B | CSS only: recolour borders and banners, round corners | Cheapest; no line on steps without a banner, no sidebar dots |
| C | Shared status-dot component for steps, start cards and sidebar | Most consistent; touches the working start-page dots |

The owner picked A.

## Decided

**Running colour.** New token `--run`: light `#2563c9`, dark `#6cb4ff` (both dark blocks).

**Step status line.** A pure function `stepStatusLine(state, waiting, decisions, lastUpdated)` in
`frontend/src/lib/workspaceCard.ts` returns `{ text, tone }`:

| Condition (first match wins) | text | tone |
|---|---|---|
| `waiting > 0` | `"<n> waiting on you"` (`"1 waiting on you"` for one) | `wait` |
| `decisions > 0` | `"<n> decisions open"` / `"1 decision open"` | `wait` |
| state `now` | `"Running"` | `now` |
| state `failed` | `"Last run failed"` | `failed` |
| state `done` and `lastUpdated` | `"Done · <d MMM>"` (e.g. `"Done · 8 Nov"`, `toLocaleDateString(undefined, {day:"numeric", month:"short"})`) | `done` |
| otherwise | `"No runs yet"` | `idle` |

The line replaces today's `hub-step-banner` span in `StepCard`, rendered as
`<span class="hub-step-status hub-step-status-<tone>">` with a leading dot. Colours: `wait` reuses the
existing banner styling (amber), `now` uses `--run`, `failed` uses `--low`, `done` and `idle` use
`--muted`. No new reference to `--hi`, `--hi-ink`, `--await` or `--await-edge` is added (release 1's
AC-13 test compares those references with `main`): the `wait` tone uses the existing
`.hub-step-banner` rule's declarations by keeping that class on the `wait` span.

**Rounded corners.** `.hub-card` gets `border-radius: var(--r-lg)`; `.dashboard-grid .stat-tile`
(`index.css` ~925) and `.pipeline-pill` (~1513) change `border-radius: 0` to `var(--r-md)`.
Arcade `.touchpad button`, `.grl-dn` and `.view-toggle button:last-child` stay as they are.

**Sidebar dots.** A pure function `workspaceState(w, runs)` in `workspaceCard.ts` returns the
highest-ranked `processState` of the workspace's processes, using the existing `RANK`
(`wait > now > failed > done > idle`), with `flow = null`. In `App.tsx`, each workspace nav item
(StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub) gets
`<span class="nav-dot nav-dot-<state>" aria-label="<name>: <STATE_LABEL[state]>">` after its label,
from the runs the app already loads. Dot colours: `wait` `var(--hi)` (one new rule, `.nav-dot-wait`),
`now` `--run`, `failed` `--low`, `done` `--muted`. For `idle`, and while runs are still loading, no
`.nav-dot` element is rendered. `STATE_LABEL` (unchanged): done "has a finished run", now "running",
wait "waiting on a person", failed "last run failed", idle "no activity yet".

**Amber references.** `.nav-dot-wait` is the one new reference to an amber token. Release 1's test
`ac13_amber_usage_unchanged` (`frontend/tests/nightDeskTokens.test.ts`) is extended to allow exactly
that one addition; the change is listed in the PR.

## Left to the builder

- Which runs list `App.tsx` passes to `workspaceState` (it loads runs for the command palette;
  if that list is capped, my call: use it anyway and note the cap in the PR).
- Dot size and spacing, within the mockup's look (6–8px circle).

## Known limitation

With `flow = null`, StewardIQ stages whose waiting state comes only from the stewardship flow (open
decisions) do not show `wait` in the sidebar dot. The step status line on the StewardIQ page does,
because `ProcessHub` loads the flow.

## Acceptance

The e2e seed may hold no waiting, running or failed runs, so AC-17, AC-17b and AC-18 check format and consistency only; tone coverage is in AC-3..13 and AC-16b.

Rows marked `unit` are owed as `holdout` once `HOLDOUT_TOKEN` is set; the PR lists them.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `index.css` | `--run` is read from `:root`, the dark media block and `[data-theme="dark"]` | Light `#2563c9`; both dark blocks `#6cb4ff` | unit |
| AC-2 | Each theme | Contrast of `--run` on `--panel` is computed | At least 4.5:1 in each theme | unit |
| AC-3 | `stepStatusLine("wait", 3, 0, null)` | Called | Returns `{ text: "3 waiting on you", tone: "wait" }` | unit |
| AC-4 | `stepStatusLine("idle", 1, 0, null)` | Called | Returns `{ text: "1 waiting on you", tone: "wait" }` | unit |
| AC-5 | `stepStatusLine("done", 0, 2, null)` | Called | Returns `{ text: "2 decisions open", tone: "wait" }` | unit |
| AC-6 | `stepStatusLine("done", 0, 1, null)` | Called | Returns `{ text: "1 decision open", tone: "wait" }` | unit |
| AC-7 | `stepStatusLine("now", 0, 0, null)` | Called | Returns `{ text: "Running", tone: "now" }` | unit |
| AC-8 | `stepStatusLine("failed", 0, 0, "2026-11-08T10:00:00Z")` | Called | Returns `{ text: "Last run failed", tone: "failed" }` | unit |
| AC-9 | `stepStatusLine("done", 0, 0, "2026-11-08T10:00:00Z")` with `TZ=UTC`, locale `en-GB` | Called | Returns `{ text: "Done · 8 Nov", tone: "done" }` | unit |
| AC-10 | `stepStatusLine("idle", 0, 0, null)` | Called | Returns `{ text: "No runs yet", tone: "idle" }` | unit |
| AC-11 | A workspace with 3 processes and run fixtures for which `processState(p, runs, null)` returns `done`, `now`, `wait` | `workspaceState(w, runs)` is called | Returns `"wait"` | unit |
| AC-12 | The same with `done`, `failed`, `idle` | `workspaceState(w, runs)` is called | Returns `"failed"` | unit |
| AC-13 | `runs = null` | `workspaceState(w, null)` is called | Returns `"idle"` | unit |
| AC-14 | `index.css` | The `.hub-card` rule is read | It contains `border-radius: var(--r-lg)` | unit |
| AC-15 | `index.css` | `.dashboard-grid .stat-tile` and `.pipeline-pill` are read | Each contains `border-radius: var(--r-md)` and not `border-radius: 0` | unit |
| AC-15b | `index.css` | `.touchpad button`, `.grl-dn` and `.view-toggle button:last-child` are read | Each is unchanged from `origin/main` | unit |
| AC-16 | The branch vs `origin/main` | Lines in `frontend/src` containing `var(--hi`, `var(--hi-ink`, `var(--await` or `var(--await-edge` are listed | The only added line is the `.nav-dot-wait` rule; no line is removed | unit |
| AC-16b | `index.css` | Colour declarations of `.hub-step-status-now`, `-failed`, `-done`, `-idle` and `.nav-dot-now`, `-failed`, `-done` are read | They reference `--run`, `--low`, `--muted`, `--muted`, `--run`, `--low`, `--muted` respectively; none references an amber token | unit |
| AC-17 | The running app from `e2e_stack.sh up` | Each of the 5 workspace pages opens | Every step card that is not `.hub-step-planned` has exactly one `.hub-step-status`, whose text matches one of `^\d+ waiting on you$`, `^\d+ decisions? open$`, `^Running$`, `^Last run failed$`, `^Done · \d{1,2} \w{3}$`, `^No runs yet$` | evaluator |
| AC-17b | The running app | For each step on the 5 workspace pages | The tone class of its `.hub-step-status` equals the state class of that step's dot on the start page, except that a step with waiting items or open decisions shows `wait` | evaluator |
| AC-18 | The running app, runs loaded | The sidebar renders | Each of the 5 workspace items has either no `.nav-dot` element (state idle) or one whose `aria-label` is `<workspace name>: <STATE_LABEL value>` | evaluator |
| AC-18b | The runs request still pending | The sidebar renders | No `.nav-dot` element exists | unit |
| AC-19 | The running app, light and dark | The start page opens | The computed `border-radius` of each `.hub-card` is `12px` | evaluator |
| AC-19b | Fixture runs | `WORKSPACES` and `cardView(w, runs, null, now)` are evaluated for each workspace | The 5 workspaces are, in order, StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub, and each card's `dots` equal `stepState` of its processes for those runs, exactly as on `origin/main` | unit |
| AC-20 | The branch vs `origin/main` | `git diff origin/main -- frontend/tests` is read; `npm test` runs | No test or assert is removed except the one allow-list extension in `ac13_amber_usage_unchanged`; `npm test` exits 0 | unit |

Must not change: start-page cards and dots (AC-19b), state computation and existing tests (AC-20), square arcade and graph controls
(AC-15b), where amber is used apart from the sidebar dot (AC-16).
