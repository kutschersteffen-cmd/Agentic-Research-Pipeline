# Agent screen fixes: keep what you typed, show only the open thread

Status: Draft, for owner approval
Slug: `agent-screen-fixes`
Risk: `risk:normal` (frontend only; no auth, schema, money or workflow path; owes the UI review gate)
Size: `S`, one PR, no slices (bug-list bundle B = item 6)

## Decisions for the owner

1. **A result that answers after you opened another thread.** Asked in the spec thread. Specified here with
   the recommended answer, "Stay where I am": the screen stays on the thread you opened, the new thread shows
   up in the thread list, and the composer keeps what you sent (AC-22 to AC-28). If the owner picks "Jump to
   the new thread", those seven rows change before approval.

Every other choice is listed under "Defaults taken"; approving the spec approves them.

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`, IDs A24, A25, B2;
consolidated rows M19, M20, M21) found three faults on the Agent screen of the Agentic Research Platform that
still reproduce on `main` at `d8395c0`:

- **M19 (A24).** A failed Ask wipes the question you typed. Plan, Explore and Refine keep it.
- **M20 (A25).** A plan or exploration that answers late lands on the thread you opened after it, and the
  previous thread's plan or exploration stays on screen while the new one loads. An error from the previous
  thread stays on screen after you open another one.
- **M21 (B2).** The Antigravity patch's fix for the above compared the selection object by identity. `App.tsx`
  builds a new selection object on every render, so any App re-render while a request runs (a decision event,
  a count refresh) made the check fail and the new plan or exploration never opened. This is a rule for the
  fix here, not a bug on `main`.

The Antigravity patch is a hint only; this spec states the behaviour.

## What the user can do afterwards that they cannot do today

- Send an Ask while the model is down, see the error, and press Enter again without retyping the question.
- Click from one plan or exploration to another without the first one's brief, stream or stage showing under
  the second, however slowly the first one answers.
- Open another thread after an error and not see the old thread's error there.
- Start a plan, exploration or ask, open another thread while it runs, and stay on the thread you opened.

## Three versions

- **Safe:** move `setText("")` after a successful ask, wrap the two loads in `untilCancelled`, clear `error`
  on selection change. Misses the stale plan shown while the next one loads and the 3 s poll race.
- **Strong (specified here):** the safe version, plus: render only the plan or exploration whose id is the
  selection's id; drop any plan or exploration response (first load, poll, reload after an action) whose id is
  not the current selection's; one value comparison `sameThread` for every "is this thread still open" check;
  a result opens its new thread only if the user stayed where they sent it from.
- **Most ambitious:** the strong version plus a per-thread store (plan, exploration, asks, error keyed by
  thread) so switching back shows the last state at once. Next step up would need: a cache policy and a
  memory limit; not worth it for a screen that reloads in one request.

## What exists today

All paths under `frontend/src/`, at `main` `d8395c0`.

- `pages/Agent.tsx:312-315` `send()`: in Ask mode `setText("")` runs before `ask(t, false)`. `ask()`
  (`:275-298`) catches a failed `api.agentPost` and shows `e.message` in the page's error line (`:456`), but
  the question is gone. Plan and Explore (`:316-321`) clear inside `act` after the create succeeds; Refine
  (`:304-310`) clears only on `ok` and only if the same Refine thread is still open.
- `pages/Agent.tsx:119-126` `loadPlan` and `loadExploration` call `api.getPlan` / `api.getExploration` and set
  state with no cancel. `loadAsks` (`:128-131`) already uses `untilCancelled` (`lib/agent.ts:165`).
- The stream renders `exploration && explorationId` (`:466`) and `plan && planId` (`:478`); the stage's Board
  tab renders `plan ?` (`:415`) and the Script/Diff/Audit tabs `!plan` (`:422`), with no check that the loaded
  object's id is the selected one.
- The 3 s poll (`:240-245`) calls `loadPlan()` while the plan's status is in `ACTIVE`. `act()` (`:257-272`)
  calls `loadPlan()` and `loadExploration()` after every action.
- `error` (`:74`) is cleared only by `act()` and `ask()`; opening another thread leaves it.
- `ask()` (`:275-284`): a new-thread ask calls `onSelect(null)` first, then `onSelect({kind:"ask", id})` when
  it answers, whatever is open by then. Plan/Explore `send()` (`:316-321`) calls `onSelect(new)` after the
  create the same way. A follow-up ask (`:287`) and Refine (`:307`) compare `current.current` by `kind` and
  `id`.
- `App.tsx:324` passes `selected={agentSelection(route.params)}`: a new object on every App render.
  `App.tsx:188-194` re-renders App on every `arp:decided` window event without changing the route.
- `lib/agent.ts:92` `Selection = { kind: "plan" | "ask" | "exploration" | "refine"; id: string } | null`.

## Goals

1. A failed Ask leaves the question in the composer (M19).
2. The stream and stage show only the plan or exploration that is selected, never another thread's, at any
   moment: while it loads, after a late first load, after a late poll (M20).
3. An error line from one thread is gone once another thread is opened (M20).
4. Every "is the same thread still open" check compares `kind` and `id`; an App re-render during a request
   changes nothing (M21).
5. A plan, exploration or ask that answers after the user opened another thread does not take them away
   from it (owner decision 1).

## Non-goals

- A32 (a refused navigation keeps a queued Agent ask): fixed by bundle A.
- A26 (Accept on a failed exploration): done by bundle D.
- A loading indicator for a thread that is loading.
- The ask buttons inside an answer ("Draft a plan", "Explore" in `AskTurn`): unchanged.
- Refine threads: unchanged (they already behave as goal 1 and 4 ask).
- Any backend or API change. No generated API file changes.
- Every other bug-list item.

## Anti-goals

- An identity comparison (`===` on a `Selection` object) anywhere in the "same thread" checks (B2).
- A composer that empties while the request it sent is still running in Ask mode.

## Design

### Helper (pure, node-loadable)

| Export (file) | Behaviour |
|---|---|
| `sameThread(a: Selection, b: Selection): boolean` (`lib/agent.ts`) | `true` when both are `null`, or both are non-null with equal `kind` and equal `id`; else `false`. Never compares the objects themselves. |

`sameThread` adds no import to `lib/agent.ts`, so `npm test` still loads it under
`node --test --experimental-strip-types`.

### Agent screen (`pages/Agent.tsx`)

- **Where a request was sent from.** Each send records the selection it was sent from: the selection at send
  time for Plan, Explore and a follow-up Ask; `null` for a new-thread Ask (which first calls `onSelect(null)`,
  as today). "Still there" means `sameThread(current.current, sentFrom)`.
- **When the answer arrives.** Check `sameThread(current.current, sentFrom)` once, as soon as the response
  arrives and before calling `onSelect`. If it holds: open the new thread (new-thread Ask, Plan, Explore) or
  append the answer (follow-up Ask), and clear the composer. If not: do neither; the thread list reload
  (`loadList`, as today) shows the new thread. If the request fails and `sameThread(current.current,
  sentFrom)` does not hold, its error is not shown; the composer keeps the text.
- **Composer.** Ask mode no longer clears before sending. While the request runs the text stays in the
  (disabled) box, as Plan and Explore do today. On failure it keeps the text.
- **Loads.** `loadPlan` and `loadExploration` drop any response, value or error, whose requested id is not
  the selected `kind`/`id` at the moment it arrives (read through `current`, not the closure that sent it).
  This covers the first load on opening, the 3 s poll and the reload after `act()`. A response for the
  selected thread is applied as today. The reload after `act()` reads the selection through `current` when it
  runs: it loads the selected plan or exploration, and never clears `plan` or `exploration` while that
  thread is the one selected.
- **Render.** The stream, the stage's Board tab, its Script, Diff and Audit tabs, and its Mini-app tab use
  the loaded plan only when `plan.id === planId`, and the loaded exploration only when
  `exploration.id === explorationId`. Otherwise they render as if nothing were loaded (what a first open shows
  today before the response).
- **Error line.** `error` is set to `null` whenever the selection's `kind` or `id` changes; an App re-render
  that keeps `kind` and `id` (a new `Selection` object) leaves it. A failure that happens after that (for the
  newly opened thread) shows as today.

## Defaults taken

- The composer keeps the sent text when the user opened another thread before the answer came (as Refine
  does); it is cleared only where the answer lands.
- A new-thread Ask counts as sent from "no thread" (`#/agent`): it opens its thread only if nothing else was
  opened meanwhile.
- The error line clears on every change of thread, including a "Threads could not be loaded" or "The inbox
  could not be loaded" line; the next failure of those loads shows it again.
- A request that fails after the user opened another thread shows no error there (it belongs to the thread
  they left); the composer keeps the text.
- No loading line: a thread that is loading shows what a first open shows today.
- `sameThread` is the one comparison; the existing follow-up Ask and Refine checks move to it.

## Acceptance

**How the E2E rows run.** Against `backend/scripts/e2e_stack.sh up`, as a signed-in user who can ask, at a
1440 px wide viewport, with the named API routes answered by the test (Playwright `page.route`).

- "Delayed N s": the route is answered N s later **without blocking the test** (async Playwright with
  `asyncio.sleep`, or a delayed `fetch` installed with `add_init_script`). Every click and event a row names
  happens while that response is still pending. A `time.sleep` inside a sync route handler does not qualify.
- Plan A has brief `Alpha brief`, plan B `Bravo brief`, plan N `November brief`; exploration X has question
  `Xray question`, exploration Y `Yankee question`. Every plan's status is `draft` unless the row says
  otherwise. Every plan or exploration a row names answers `GET /api/plans/<id>` or
  `GET /api/agent/explorations/<id>` immediately unless the row says otherwise.
- The thread list routes (`/api/plans`, `/api/agent/ask-threads`, `/api/agent/explorations`) return the threads
  a row names. "Click B" means: as soon as B's button in the thread list is visible, click it. "Open
  `<address>`" means load that address.
- "The composer" is `#agent-brief`. "The stream" is `section.agent-stream`. "The stage" is `aside.agent-stage`.
- "Within N s" means the condition holds at some point no later than N s after the action.
- Error lines read `500: <detail>` (from `api/client.ts`), so "contains `boom`" matches
  `The plan could not be loaded: 500: boom.`

**The helper rows** (AC-1, AC-2) import `sameThread` from the PR checkout's `frontend/src/lib/agent.ts` with
`node --test --experimental-strip-types`, as `npm test` does.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | — | `sameThread({kind:"plan",id:"p1"}, {kind:"plan",id:"p1"})` (two separate objects) and `sameThread(null, null)` | `true` and `true` | holdout |
| AC-2 | — | `sameThread({kind:"plan",id:"p1"}, {kind:"exploration",id:"p1"})`, `sameThread({kind:"plan",id:"p1"}, {kind:"plan",id:"p2"})`, `sameThread({kind:"plan",id:"p1"}, null)` | `false`, `false`, `false` | holdout |
| AC-3 | Open `#/agent`; Ask mode; `POST /api/agent/asks` answers 500 `{"detail":"model down"}` | Type `Which sectors lead?`, press Enter | Once a `role="alert"` element containing `model down` is visible, the composer's value is exactly `Which sectors lead?` | holdout |
| AC-4 | Ask thread T open (`#/agent/ask/T`; `GET /api/agent/asks?thread_id=T` returns one answered ask); `POST /api/agent/asks` answers 500 `{"detail":"model down"}` | Type `And Europe?`, press Enter | Once the alert containing `model down` is visible, the composer's value is exactly `And Europe?` | holdout |
| AC-5 | Open `#/agent`; Ask mode; `POST /api/agent/asks` delayed 2 s, then answers an ask with `thread_id` `T2` | Type `Which sectors lead?`, press Enter | 0.5 s after Enter, the composer's value is exactly `Which sectors lead?` | holdout |
| AC-6 | Open `#/agent`; Ask mode; `POST /api/agent/asks` answers an ask with `thread_id` `T2` (must not change) | Type `Which sectors lead?`, press Enter | Within 5 s the address bar ends with `#/agent/ask/T2` | holdout |
| AC-7 | As AC-6 (must not change) | As AC-6 | Within 5 s the composer's value is `""` | holdout |
| AC-8 | Open `#/agent`; Explore mode; `POST /api/agent/explorations` answers 500 `{"detail":"sandbox down"}` (must not change) | Type `Which holdings lack a plan?`, press Enter | Once the alert containing `sandbox down` is visible, the composer's value is exactly `Which holdings lack a plan?` | holdout |
| AC-9 | Plans A and B in the list; `GET /api/plans/A` delayed 2 s | Open `#/agent/A`, click B | 3 s after the click, `#agent-brief-h` has text `Bravo brief` and the stream contains no text `Alpha brief` | holdout |
| AC-10 | Plans A and B; `GET /api/plans/B` delayed 2 s | Open `#/agent/A`, wait for `Alpha brief`, click B | 0.5 s after the click, the stream and the stage contain no text `Alpha brief` and the page has no `#agent-brief-h` element | holdout |
| AC-11 | Plan A with status `running` (first `GET /api/plans/A` immediate, every later one delayed 2 s); plan B | Open `#/agent/A`; wait until a second `GET /api/plans/A` request has been sent (Playwright request event); click B | 3 s after the click, `#agent-brief-h` has text `Bravo brief` and the stream contains no text `Alpha brief` | holdout |
| AC-12 | Explorations X and Y in the list; `GET /api/agent/explorations/X` delayed 2 s | Open `#/agent/exploration/X`, click Y | 3 s after the click, `#agent-exploration-h` has text `Yankee question` and the stream contains no text `Xray question` | holdout |
| AC-13 | Plan A and exploration Y in the list; `GET /api/plans/A` delayed 2 s | Open `#/agent/A`, click Y; 3 s later click the stage's `Script` tab | The stage's tab panel has text `An exploration has no script, changes or audit trail: its code and tool calls are in the stream.` | holdout |
| AC-14 | Plans A and B; `GET /api/plans/A` answers 500 `{"detail":"boom"}` | Open `#/agent/A`, wait for the alert containing `The plan could not be loaded`, click B | Within 2 s the page contains no text `The plan could not be loaded` | holdout |
| AC-15 | Plans A and B; `GET /api/plans/A` delayed 2 s, then 500 `{"detail":"boom"}` | Open `#/agent/A`, click B | 3 s after the click, the page contains no text `The plan could not be loaded` | holdout |
| AC-16 | Plans A and B; `GET /api/plans/B` answers 500 `{"detail":"boom"}` (must not change) | Open `#/agent/A`, wait for `Alpha brief`, click B | Within 2 s a `role="alert"` element contains `The plan could not be loaded:` and `boom` | holdout |
| AC-17 | Plan B; `GET /api/plans/B` answers 500 `{"detail":"boom"}` | Open `#/agent/B`, wait for the alert, run `window.dispatchEvent(new Event("arp:decided"))` | 1 s later a `role="alert"` element still contains `The plan could not be loaded:` | holdout |
| AC-18 | Plan A with status `running`: the first `GET /api/plans/A` returns `running`, every later one returns `done` (must not change) | Open `#/agent/A` | Within 8 s the stream's `.agent-meta .status-pill` reads `done` | holdout |
| AC-19 | Plan A open (`#/agent/A`); Plan mode; `POST /api/plans` delayed 2 s, then answers plan N | Type `November brief`, press Enter; 0.5 s later run `window.dispatchEvent(new Event("arp:decided"))` | Within 5 s of Enter, the address bar ends with `#/agent/N` | holdout |
| AC-20 | Ask thread T open as in AC-4; `POST /api/agent/asks` delayed 2 s, then answers an answered ask in thread T with question `And Europe?` | Type `And Europe?`, press Enter; 0.5 s later run `window.dispatchEvent(new Event("arp:decided"))` | Within 5 s of Enter, the stream has an `.ask-turn` whose `.ask-question` is `And Europe?` and the stream contains no text `Working…` | holdout |
| AC-21 | As AC-20 | As AC-20 | Within 5 s of Enter, the composer's value is `""` | holdout |
| AC-22 | Plans A and B in the list; plan A open; Plan mode; `POST /api/plans` delayed 2 s, then answers plan N; after that answer, `/api/plans` lists A, B and N | Type `November brief`, press Enter; 0.5 s later click B | 3 s after the click, the address bar ends with `#/agent/B` | holdout |
| AC-23 | As AC-22 | As AC-22 | 3 s after the click, the thread list has a button with text `November brief` | holdout |
| AC-24 | As AC-22 | As AC-22 | 3 s after the click, the composer's value is exactly `November brief` | holdout |
| AC-25 | Plan B in the list; open `#/agent`; Ask mode; `POST /api/agent/asks` delayed 2 s, then answers an ask with `thread_id` `T2` | Type `Which sectors lead?`, press Enter; 0.5 s later click B | 3 s after the click, the address bar ends with `#/agent/B` | holdout |
| AC-26 | Plan B in the list; open `#/agent`; Explore mode; `POST /api/agent/explorations` delayed 2 s, then answers exploration X | Type `Xray question`, press Enter; 0.5 s later click B | 3 s after the click, the address bar ends with `#/agent/B` | holdout |
| AC-27 | As AC-26 | As AC-26 | 3 s after the click, `#agent-brief-h` has text `Bravo brief` | holdout |
| AC-28 | Plans A and B in the list; plan A open; Plan mode; `POST /api/plans` delayed 2 s, then 500 `{"detail":"planner down"}` | Type `November brief`, press Enter; 0.5 s later click B | 3 s after the click, the page contains no text `planner down` | holdout |

Must not change: a successful new-thread Ask opens its thread and empties the composer (AC-6, AC-7); a failed
Explore keeps the composer text (AC-8); an error for the thread that is open still shows (AC-16); the 3 s poll
still updates the open plan (AC-18).
