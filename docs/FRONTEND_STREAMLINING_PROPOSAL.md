# Proposal: streamline the frontend and tie it to processes

Status: proposal, nothing implemented. Builds on `PROCESS_VIEW.md` (which stays the
source for the process list and the closed handoffs).

## What is there today

- **29 routes** in `App.tsx` (`TABS`) for 16 functions. The sidebar shows ~20 items in
  7 groups, with 4 two-tab hubs (Dashboard, Library, Onboard issuers, Runs) and a
  collapsed "More tools" group of 7.
- **Two process maps that disagree.**
  - Start page (`ProcessHub.tsx`): 4 boxes, StewardIQ, Theme Machine, Data Engineer,
    Design Studio. Each has its own step list, live status and overview page.
  - Processes screen (`Processes.tsx`): 7 processes (onboard, climate, engage, proxy,
    client, thematic, strategy), a different cut with different step lists.
  - Both are hand-maintained arrays. The same screen appears in several processes
    under different names ("Steward · Selection" vs "Selection").
- **Steward Workflow is one route with 6+ stages** that Processes treats as separate
  steps; Risk Monitoring has 5 sub-tabs; Extraction doubles as Transition Plan.
  Navigation depth varies: some steps are routes, some sub-routes, some sub-tabs.
- **Handoffs are partly solved.** Universe handoff exists as one piece of state in
  `App.tsx`; Decision Studio publications, voting feed and alerts flow as company
  fields. Open gap: Transition Barriers → Transition Plan (#7 in `PROCESS_VIEW.md`).
- The primary user (stewardship/ESG team) works from "what is waiting on me", not
  from a tool list. The sidebar's first group ("Needs you") already admits this, but
  it holds only two screens.

## Principles

1. **One registry, many views.** A process is data, defined once. Start page tiles,
   the Processes screen, the process bar and the palette all read it.
2. **Navigation by job, not by tool.** Fewer top-level items; specialist tools live
   inside a hub, not beside it.
3. **Every screen knows its process context** and offers the next step with its
   handoff named, without a stepper that locks order (unchanged from `PROCESS_VIEW.md`).
4. **Work that waits on a person is one list**, not a count per screen.
5. **No new state.** Status keeps coming from the run store and stewardship flow.

## Proposal

### 1. Merge the two process maps into one registry (small, do first)

Create `lib/processes.ts`: `{ id, name, purpose, cadence, doneWhen, steps[] }`, where a
step is `{ label, screen, href, handoff?, manual?, runTypes?, stage? }`.

- Keep the 7 processes from `PROCESS_VIEW.md` as the canonical set (they carry
  cadence, "done when" and manual handoffs).
- The 4 Start-page boxes become **workspaces** that group processes by owner:
  Stewardship (engage, proxy, client), Research (thematic, strategy),
  Data (onboard), Portfolio (climate). The box shows the workspace's live counts and
  lists its processes; it no longer has a private step list.
- Delete the duplicate `PROCESSES` array in `ProcessHub.tsx` and the per-box overview
  pages once the workspace view renders from the registry.

Result: one place to edit when a process changes; no contradictory step names.

### 2. Cut the sidebar to ~10 items by promoting hubs

Keep every route id (deep links, palette, ProcessBar stay valid). Only the sidebar
grouping and the tab strips change.

| Sidebar item | Tabs inside (existing routes) |
|---|---|
| **Today** | Overview, Processes, Needs you (new, see 3) |
| **Stewardship** | Steward Workflow, Engagement, Proxy Voting |
| **Issuer data** | Identity, Documents, Extraction, Transition Plan, Transition Barriers |
| **Research** | Thematic Universe, Taxonomy, Emerging Themes, Strategy Replication |
| **Portfolio** | Risk Monitoring (existing sub-tabs) |
| **Scoring & indices** | Decision Studio, Index Construction |
| **Review** | Review Queue, Run History, Standing agents |
| **Library** | Data Library, Search |
| **Reports** | Presentations & Reports |
| *Lab, Arcade* | folded under a footer "Experiments" link |

- Transition Plan gets its own tab label inside Issuer data instead of hiding behind
  Extraction's profile toggle. The toggle still works; the tab just preselects it.
- "More tools" disappears: its contents have a home by job.
- The existing `HUBS` mechanism already does this for 4 groups, so this is config
  plus a generalisation of the tab strip, not a new component.

### 3. One "Needs you" inbox (medium, highest user value)

Replace the per-screen waiting counts with one list on Today, sorted by deadline:
review-queue items, ballots to decide, stalled engagement issues, checkpoint
overrides, tier changes to confirm. Each row shows its **process** and links to the
exact item. Data already exists (`waitingCount`, `openCount`, `stageDecisions`); this
is aggregation, not new backend. Phone-first: this is the "check a pending vote away
from the desk" screen from `PRODUCT.md`.

### 4. Generalise the handoff (medium)

Today `UniverseHandoff` carries only a universe. Widen to
`Handoff = { kind: "universe" | "run" | "publication" | "issuer", ref, from, to }` and
render one standard **handoff chip** at the top of the receiving screen:
"From Risk Monitoring · 212 companies · [clear]". `ProcessBar` then shows, per step,
what passes on and whether the arrow is manual, from the registry's `handoff` and
`manual` fields.

Concrete additions this unlocks:
- Close gap #7: show sector × jurisdiction barrier cells beside the walk-vs-talk
  verdict in Transition Plan results.
- "Next step →" button on a finished run: the next step of the active process,
  prefilled with the run as input (extends the existing "Extraction →" button on
  Document Discovery to every run type).
- Remember the active process in the URL (`?p=climate`) so the bar survives
  navigation and Back; without it, screens used by several processes can't know
  which next step to offer.

### 5. Normalise navigation depth (small)

Pick one rule: **a process step is a route or a first-level sub-route, never a
tab-within-a-page.** Promote Steward stages (already `#/stewardship/<stage>`) and
Risk Monitoring tabs to registry steps, which `PALETTE_ITEMS` already treats this way.
Retire ad hoc `useState` tab switching on pages in favour of `resolveSubTab`.

### 6. Trim the page files (only where they block the above)

`IndexBuilder.tsx` (1542 lines) and `DecisionStudio.tsx` (1400) hold several tasks
each. Split by tab only when step 2 requires a tab to become its own route. No
refactor for its own sake.

## Phasing

| Phase | Work | Size | Depends on |
|---|---|---|---|
| A | Registry (1) + delete duplicate arrays | ~1 day | none |
| B | Sidebar and hubs (2) | ~1 day | A optional |
| C | Needs-you inbox (3) | ~2 days | A |
| D | Handoff chip + process in URL + next-step button (4) | ~2-3 days | A |
| E | Depth rule (5), gap #7 | ~1 day | D |

Ship A and B first: they remove the most confusion for the least code, and are
reversible config.

## What to measure

- Clicks from sign-in to the first pending decision (target: 1, from Today).
- Number of places a process's steps are written down (target: 1, now 2).
- Top-level sidebar items (target: ≤ 10, now ~20).
- Manual handoffs listed in `PROCESS_VIEW.md` (target: 0 open).

## Not proposed

- A process-instance object or stepper that locks order (reasons in `PROCESS_VIEW.md`).
- Removing any screen or route. Everything stays reachable by link and palette.
- Merging Decision Studio, Index Construction and Strategy Replication into one
  tool: they share a hub, not a codebase.

## Decisions for you

1. Is "Needs you" as the landing view right, or should Today stay a dashboard first?
2. OK to demote Lab and Arcade to a footer link?
3. Should workspaces (the 4 Start-page boxes) survive as a concept, or should the
   Start page just list the 7 processes?
