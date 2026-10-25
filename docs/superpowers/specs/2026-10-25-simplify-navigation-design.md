# Simplify navigation: a short sidebar and four screens fewer

Status: approved by the owner, 2026-10-25.

## Owner decisions, 2026-10-25

- The sidebar keeps only Start, the five workspaces, Presentations & Reports and Arcade, plus the
  **Needs you** group with Review Queue, because it carries the waiting count.
- Proxy Voting leaves the sidebar but stays as a screen, reached from StewardIQ and from Start's Needs you list.
- Four screens leave the UI: **Document Discovery**, **Identity Resolution**, **Dashboard** and **Tape Reader**.
- What the Dashboard shows that Start does not (the engagement counts) moves to Start.
- RFP Answers, which no page links to today, joins the StewardIQ screen links.

## Intent

The sidebar lists 14 items plus 23 under "All screens", and most of them repeat a link that a workspace page
already shows. Four screens duplicate another one: Document Discovery and Identity Resolution render the same
components as Extraction's Documents and Identify steps, the Dashboard's run list is Run history and its issue
list is Engagement, and Tape Reader is a second view of the Review Queue's items. Cutting them leaves one way
to each function and a sidebar that fits on a laptop screen without scrolling.

## Goals

- The sidebar shows exactly the items in **Sidebar (verbatim)** below, in that order, on desktop and in the
  phone drawer. The "All screens" group is gone.
- Every screen the sidebar drops stays reachable in two clicks or fewer: from a workspace page, a hub tab or
  Start. **Reachability** below lists each one.
- The four removed screens no longer render. Their old links land on the screen that now does the job.
- Start shows the three engagement counts the Dashboard showed today.

## Non-goals

- No backend change. The discovery schedule API, the identity and discovery runs, the engagement API and the
  review queue API stay as they are; only their screens go.
- Ask the Portfolio and Smart Search stay (the owner kept them).
- No change to the command palette's behaviour: it keeps listing every screen that still exists.
- No change to the five workspace pages beyond the RFP Answers link.

## Anti-goals

- No screen that stays in the app becomes unreachable without the command palette.
- No function is lost that has no other home: Extraction keeps its Identify and Documents steps, Review Queue
  keeps every decision Tape Reader could make.

## Sidebar (verbatim)

| Group label | Items, in order |
|-------------|-----------------|
| (none)      | Start |
| Needs you   | Review Queue |
| Workspaces  | StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub |
| Output      | Presentations & Reports |
| (none)      | Arcade |

Review Queue keeps its waiting-count badge. A sidebar link is marked current
(`aria-current="page"`) only when its own screen, or a tab of its hub, is open. A screen without a sidebar entry
(for example Universe) marks no sidebar link current. That includes hub tabs whose hub has no sidebar entry any
more: on `#/search` or `#/history`, no sidebar link is current.

"Screens links" below means the link row headed `Screens` at the foot of a workspace page.

## Reachability (screens leaving the sidebar)

Each screen is reached in one click from **each** source listed, unless the row says otherwise. Sources are
separated by semicolons; each source is one phrase.

| Screen (route) | Reached from |
|----------------|--------------|
| Universe (`#/argusUniverse`) | Argus page's Screens links |
| Data Library (`#/library`) | Data Hub page's Screens links |
| Search (`#/search`) | Data Hub page's Screens links; Data Library's `Search` hub tab |
| Run history (`#/history`) | Start's `All runs →` link |
| Background Agents (`#/backgroundAgents`) | Run history's `Standing agents` hub tab (from Start: `All runs →`, then `Standing agents`) |
| Feeds, Issues, Smart Search, Outputs, Security Master | Data Hub page's Screens links |
| Steward Workflow, Engagement, Proxy Voting | StewardIQ page's Screens links |
| Extraction, XBRL Facts | Argus page's Screens links |
| Risk Monitoring, Transition Barriers | Transition Intelligence Platform page's Screens links |
| Ask the Portfolio (`#/portfolio-monitoring/ask`) | Risk Monitoring's `Ask the Portfolio` tab |
| Theme dossiers, Emerging Themes, Taxonomy Library, Thematic Universe, Strategy Replication, Signals workbench, Value Chain Explorer, Decision Studio, Index Construction | R&D Lab page's Screens links |
| RFP Answers (`#/rfp`) | StewardIQ page's Screens links (new) |
| Company (`#/companies/<ref>`) | A company name in Extraction's Companies tab (checked by its own row, AC-28) |

## Removed screens and where their links go

An old route and every path under it (`#/dashboard/x`) land on the target, which replaces it in the address bar.

| Old route | Lands on |
|-----------|----------|
| `#/dashboard` | `#/home` (Start) |
| `#/tape` | `#/review` (Review Queue) |
| `#/identity` | `#/extraction/identify` |
| `#/discovery` | `#/extraction/documents` |

The "Onboard issuers" hub (Identity Resolution + Document Discovery tabs) goes with them; it had no route of its
own, so it needs no redirect. The one notice that links `Open identity runs` (shown in an Argus flow after it
starts an identity run) points to `#/history` instead.

Review Queue already offers every decision Tape Reader offered: Tape Reader had Approve, Reject and Escalate;
Review Queue items show `Accept`, `Correct…`, `Reject` and `Escalate`.

## Start: engagement line

Directly below the "Now" row, Start shows one line. Its text before the link is exactly:
`Engagement · <open> open · <stalled> stalled · <escalated> escalated` followed by a link `Open Engagement →`
to `#/engagement`. The counts use the Dashboard's definitions:

- **open:** issues whose status is `open` or `stalled`.
- **stalled:** issues whose status is `stalled`.
- **escalated:** issues whose escalation stage is not `private_engagement` and whose status is neither
  `resolved` nor `closed`.

While engagement records have not loaded, each count shows `—`, never `0`. If loading fails, the line reads
`Engagement · counts unavailable` with the same link.

## Constraints

- Deleting Tape Reader deletes its unit test `frontend/tests/tapeData.test.ts` with the code it tests. The
  "No tests removed" PR guard will fail on that; the owner applies the `tests-weakened-ok` label after reading
  the PR. No other test is removed or changed.
- `IdentityStage` and `DocumentsStage` stay: Extraction renders them.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The app at 1440×900 | `#/home`, `#/argusUniverse` and `#/rfp` are each opened | On each, the sidebar's links read, top to bottom: Start, Review Queue, StewardIQ, Argus, Transition Intelligence Platform, R&D Lab, Data Hub, Presentations & Reports, Arcade, and no other link | evaluator |
| AC-2 | The app at 1440×900, `#/home` open | The user reads the sidebar | Top to bottom: Start with no label above it; `Needs you` above Review Queue; `Workspaces` above StewardIQ to Data Hub; `Output` above Presentations & Reports; Arcade with no label above it. The text `All screens` appears nowhere in the sidebar | evaluator |
| AC-3 | The app at 390×844, `#/home` open | The menu button opens the drawer | The drawer shows the links and group labels of AC-2 in the same order, and no `All screens` text | evaluator |
| AC-4 | One review item waits on the user | `#/home` is open | Review Queue's sidebar link shows the badge `1` | unit |
| AC-5 | The app is running | `#/dashboard` is opened | Start renders and the address bar reads `#/home` | unit |
| AC-6 | The app is running | `#/tape` is opened | Review Queue renders and the address bar reads `#/review` | unit |
| AC-7 | The app is running | `#/identity` is opened | Extraction renders on its Identify tab and the address bar reads `#/extraction/identify` | unit |
| AC-8 | The app is running | `#/discovery` is opened | Extraction renders on its Documents tab and the address bar reads `#/extraction/documents` | unit |
| AC-9 | The app is running | `#/dashboard/x` is opened | Start renders and the address bar reads `#/home` | unit |
| AC-10 | The command palette is open | The user types each of `Dashboard`, `Tape`, `Identity`, `Discovery` and `Onboard` in turn | No item labelled `Dashboard`, `Tape Reader`, `Identity Resolution`, `Document Discovery` or `Onboard issuers` is listed | evaluator |
| AC-11 | The StewardIQ page is open | The user reads its Screens links | A link labelled `RFP Answers` to `#/rfp` is listed | evaluator |
| AC-12 | Each row of **Reachability** except Company | The user starts on each listed source | One click on a visible link opens that screen at its route (Background Agents: two clicks from Start) | evaluator |
| AC-13 | The Argus page is open | The user clicks `Universe` in its Screens links | Universe renders and no sidebar link has `aria-current="page"` | unit |
| AC-14 | Engagement records hold 5 issues: `open`@`private_engagement`, `open`@`joint_engagement`, `stalled`@`joint_engagement`, `resolved`@`joint_engagement`, `closed`@`joint_engagement` | Start is open | Directly below the Now row, the text before the link reads `Engagement · 3 open · 1 stalled · 2 escalated` | unit |
| AC-15 | The engagement API has not answered yet | Start is open | The text before the link reads `Engagement · — open · — stalled · — escalated` | unit |
| AC-16 | The engagement API returns an error | Start is open | The text before the link reads `Engagement · counts unavailable` | unit |
| AC-17 | The engagement API returns an error | Start is open | The engagement line still shows the link `Open Engagement →` to `#/engagement` | unit |
| AC-18 | Start is open | The user clicks `Open Engagement →` | Engagement renders at `#/engagement` | evaluator |
| AC-19 | An Argus flow has just started an identity run | Its notice shows | The notice's `Open identity runs` link points to `#/history` | unit |

Must not change:

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| ~~AC-20~~ | Retired 2026-10-25: Proxy Voting left the sidebar, so it has no badge there. See AC-32. | | | |
| AC-21 | Extraction is open with no companies loaded | The user opens the Identify tab | It shows the choices `Manual`, `Automatic` and `Skip` and a button whose label starts with `Resolve identity for` | evaluator |
| AC-22 | Extraction is open with no companies loaded | The user opens the Documents tab | It shows the choices `Manual`, `Automatic` and `Skip` and a button whose label starts with `Search for documents across` | evaluator |
| AC-23 | One extraction item waits in Review Queue | The user opens it | Its decision buttons read `Accept`, `Correct…`, `Reject` and `Escalate` | evaluator |
| AC-24 | The command palette is open | The user types `Run history`, `Universe` and `Value Chain Explorer` in turn | An item with that label is listed each time | evaluator |
| AC-25 | The command palette lists `Run history`, `Universe` and `Value Chain Explorer` | The user chooses each in turn | `#/history`, `#/argusUniverse` and `#/valueChain` open, in that order | evaluator |
| AC-26 | Data Library is open | The user clicks the `Search` hub tab | Search renders at `#/search` | evaluator |
| AC-28 | Extraction's Companies tab lists at least one company | The user clicks that company's name | The Company screen renders at `#/companies/<that company's ref>` | evaluator |
| AC-29 | The app is running | `#/argus` is open | Only the `Argus` sidebar link has `aria-current="page"` | unit |
| AC-30 | The app is running | `#/review` is open | Only the `Review Queue` sidebar link has `aria-current="page"` | unit |
| AC-31 | The app is running | `#/search` is open | No sidebar link has `aria-current="page"` | unit |
| AC-32 | One proxy voting run `pv-1` has 2 ballots waiting on the user | `#/home` is open | Start's Needs you list shows `Proxy voting run pv-1: 2 ballots to decide`, linking to `#/voting/pv-1` | unit |
| AC-27 | No discovery schedule has been saved and the server runs with default settings | `GET /api/discovery/schedule` is called | 200 with `enabled: false`, `interval_hours: 24.0`, `universe_path: null` | unit |

The other backend endpoints the Non-goals name (identity and discovery runs, review queue) get no row: this change
touches no backend file, and their existing backend tests stay as they are.
