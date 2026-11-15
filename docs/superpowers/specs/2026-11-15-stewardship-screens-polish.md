# Stewardship screens: polish from the findings

Slug: stewardship-screens-polish

Risk: `risk:normal`. Size M, 3 PRs: two frontend, one small backend.

Status: **approved by the owner on 15 Nov 2026** (buttons in the spec session, after the spec-critic
rounds). Round 2 of the findings clean-up the owner asked for on 15 Nov 2026 ("clean up further bugs and
findings"). Checked against `origin/main` `5df84c4`.

## Why

Small faults on the stewardship screens that a manager would notice at the showcase (about 27 Nov 2026, laptop
screen): codes instead of words, a form that keeps its old choice, one meaning shown in two colours, buttons that
work when they should not, and actions a screen reader does not announce.

## PR split and order

- **PR A, tiers picks and checkpoint** (`frontend/src/pages/steward/studios.tsx`): build at once. Rows AC-1 to AC-10.
- **PR B, engagement watch and ballot review** (`frontend/src/components/EngagementWatch.tsx`,
  `EngagementIssuePanel.tsx`, `BallotReview.tsx`, `frontend/src/lib/engagement.ts`): build only **after the build
  of `commitment-loop-review-fixes` (spec PR #501) is merged**, because that build edits `EngagementWatch.tsx` too.
  Branch PR B from `main` after that merge. Rows AC-11 to AC-38 and AC-42 to AC-44.
- **PR C, programme step names** (`backend/arp/stewardship/program.py`, `backend/arp/api/routers/stewardship.py`):
  build at once, in parallel with PR A. It does not fit PR A: the step name is written by the backend. Rows AC-39
  to AC-41.

Each PR carries `Spec: stewardship-screens-polish` and a `Rows:` line with its own rows; the PR that merges last
drops the `Rows:` line.

## Owner decisions (15 Nov 2026, by button)

- Bulk approve: the "Approve N routine" dialog lists the ballots that carry a commitment warning before the owner
  approves; he can still approve all. Owner: "List flagged ballots".
- Old programme versions: versions approved before the step "joint engagement" was removed show the current step
  name on screen; the stored history is not touched. Owner: "New name on screen".

## Goals

PR A (Bilateral picks on `#/stewardship/selection`, Escalation recommendations on `#/stewardship/checkpoint`):

- (A1) After a successful pick, the Company select and the Reason are both empty. After a refused pick both keep
  what the user entered.
- (A2) A refused pick or withdrawal shows the server's sentence without the status code (`422: `), with the
  company's name in place of its issuer id: for a withdrawal the pick's own `name` (from `GET
  /api/stewardship/tiers`), for a pick the name in the Company select's list.
- (A3) A pick or withdrawal that succeeds is announced in one polite status line. Any action clears the earlier
  status line and the earlier alert first, so at most one of the two shows.
- (A4) The Escalation recommendations table shows `No tier yet` for a company with no tier, and the rule's reason
  without the rule key in brackets.

PR B (the issue panel on `#/engagement`, the dossier watch list, the ballot review):

- (B1) One colour per flag kind, the same on the ballot and in the dossier: overdue amber-brown (status "mid"),
  broken red (status "low").
- (B2) A due date is shown whole, unless it matches `^\d{4}-\d{2}-\d{2}T` (an ISO date with a time part), which
  shows its first 10 characters.
- (B3) When nobody is signed in, every `Record result`, `Add proof statement`, `Add watch topic` and `Close topic`
  button in the panel is disabled, and one sentence directly under the panel's access-token field
  (`SignedInAs compact`) reads `Sign in to record results, proof statements and watch topics.`
- (B4) `Add proof statement` is not offered when the engagement store is the file store, i.e. only once the
  suggestions load has failed with the 409 `Watch items need the Postgres engagement store.` While the load is
  running, and after any other error, the button shows.
- (B5) After `Confirm` on an evidence suggestion, keyboard focus stays in the item it acted on: on a watch topic,
  its `Check against documents: <item>` button; on a commitment (which the confirm closes as `verified` or
  `missed`, so its buttons go), the commitment's row, made focusable; on an objective, the `Result` select of the
  Record result form that opens (today's behaviour).
- (B6) Screen readers hear which item a button acts on: on an evidence suggestion, `Confirm evidence: <item>` and
  `Reject evidence: <item>`; on a found commitment, `Reject commitment: <commitment text>`.
- (B7) A confirmed suggestion is announced in a polite status line in the item's row (outside the suggestion card,
  which disappears): `Evidence confirmed: <item>`. Objectives, commitments and watch topics alike.
- (B8) On a collapsed ballot card, the watch banner comes before the `Approve: vote …` button.
- (B9) Objective statuses, results and the Result select's option texts show words (`in progress`,
  `not achieved`), not codes; the values sent to the API stay codes.
- (B10) The issue header shows a `Demo data` chip when the issue's `data_source` or any of its objectives'
  `source` is a demo source. The per-objective `Demo data` chip stays.
- (B11) The "Approve N routine" dialog lists every watch flag (commitment or objective, overdue or broken) of the
  companies among those N proposals, one line per flag, `<company>: <message>`, each flag once however many of the
  company's proposals are in N; `Approve N` still approves all N.

PR C:

- (C1) A client programme version approved before the six-step ladder shows `private engagement` where it stored
  `joint_engagement`: in the `planned step` column of "The approved program against today's data" on the Client
  program page, and in `GET …/program`'s `versions`. The stored version is not rewritten.

`<item>` is the item's own text: an objective's description, a commitment's text, a watch topic's question.

## Non-goals

Phone layouts; anything inside `commitment-loop-review-fixes` (suggestion errors, watch-flag dates, CLI dossier)
or `tiers-review-fixes` (`tiers.py`, `policies.py`); the cockpit; other tier labels (`bilateral`, `letter`,
`monitor` stay); new colours or tokens; the `Confirm rejection` button's name; topic statuses (`open`, `closed`
have no codes to translate); the commitment row's `target …` date in `EngagementIssuePanel.tsx` (shown whole today,
B2 covers only the objective, watch topic and dossier dates); other backend changes than C1.

## Approach

One sensible way for each item, inside the files named above.

- **(A2)** Strip a leading `NNN: ` (the pattern `lib/themeLayers.ts` uses), then replace the issuer id with the
  company's name from the list the panel already loads. A friendlier server message was dropped: `tiers.py` is out
  of scope, and `tiers-review-fixes` pins today's text (its AC-8).
- **(A4)** The rule's `reason` is a sentence a person wrote in the rule editor; the bracketed `rule` key adds
  nothing for a reader. A label map in the frontend was dropped: rules are editable, so it would go stale.
- **(B1)** Ballot: `banner banner-warning` for overdue, `banner banner-danger` for broken. Dossier: `badge
  badge-mid` for overdue, `badge badge-low` for broken. Today both kinds are `banner-warning` on the ballot and
  `badge-low` in the dossier. These are status colours, not the amber signal: a late or broken commitment is the
  company's state, not a person's to-do (`DESIGN.md`, "The Status Is Not The Signal Rule"). Red for a broken
  commitment is already used in the same panel: a `missed` commitment's badge is `badge-low`
  (`EngagementIssuePanel.tsx`).
- **(B3)** Add the signed-in name to `EngagementWatch.tsx`'s `Ctx` (the panel already reads it with `useMe()` as
  `actor`) and disable on an empty one, as the panel's own buttons do.
- **(B4)** Track the 409 explicitly (for example a `fileStore` flag set in `useSuggestions`' error branch when the
  message is that sentence). Inferring it from `available: false` and `error: null` would also hide the button
  while loading.
- **(B9)** Move the panel's private `fmt()` (underscores to spaces) to `lib/engagement.ts` and import it in both
  files (exporting it from the panel would make a circular import).
- **(B11)** Routine proposals already exclude alignment-flagged ones (`isRoutine`), but not those of a company with
  a watch flag. The dialog gets one list of those companies above its table. Disabling or splitting the batch was
  not the owner's choice.
- **(C1)** `monitor()` builds the `planned step` cell from the frozen version's `client_step`; it maps the value
  through `OLD_STAGES` (`arp/schemas/engagement.py`) before formatting, the read-time mapping the engagement store
  and the cockpit already use. `GET …/program` already maps old tier keys in `versions` on read; it maps
  `client_step` the same way. Rewriting stored versions was ruled out by the owner.

## Acceptance

PR A rows marked `evaluator` run on the app started by `backend/scripts/e2e_stack.sh up`, with the house universe it
loads. "Company C" is any company in the Bilateral picks Company select, and "N" its name as the select shows it.

Rows marked `holdout` are hidden browser tests (Playwright, like `backend/tests/e2e/test_stewardship_watch_flags_ui.py`)
on that app, with the API calls they name stubbed by `page.route`; the frontend's `npm test` runs `.ts` logic tests
only and renders no components. "Signed out" means `/api/me` is stubbed to answer 401; otherwise the page is
signed in as the dev user. AC-39 to AC-41 stay `unit`: they write the stream file directly.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `#/stewardship/selection`, no pick for Company C | The user chooses C, types reason `Board change`, presses `Pick for bilateral` | The pick list shows N; the Company select shows `Choose a company…`; the Reason field is empty | evaluator |
| AC-2 | AC-1 done | Read the Bilateral picks panel | An element with `role="status"` reads `N is picked for bilateral.` | evaluator |
| AC-3 | AC-1 done | The user chooses C again, types reason `Again`, presses `Pick for bilateral` | The alert reads exactly `N is already picked for bilateral` (no `422`, no issuer id) | evaluator |
| AC-4 | AC-3 done | Read the form | The Company select still shows N and the Reason field reads `Again` (must not change) | evaluator |
| AC-5 | AC-3 done | Read the panel | The `role="status"` element is empty | evaluator |
| AC-6 | AC-3 done (the alert is showing) | The user presses `Withdraw` on N's pick | N leaves the pick list; the `role="status"` element reads `The bilateral pick for N is withdrawn.`; no `role="alert"` element is shown | evaluator |
| AC-7 | The picks panel; `POST /api/stewardship/tiers/bilateral` stubbed to answer 422 `{"detail": "A bilateral pick reason has at most 500 characters"}` | The user picks a company | The alert reads exactly `A bilateral pick reason has at most 500 characters` | holdout |
| AC-8 | `GET /api/stewardship/tiers` stubbed with one pick `{"issuer_id": "SYN01", "name": "Alpha Corp", …}`; `POST /api/stewardship/tiers/bilateral/SYN01/withdraw` stubbed to answer 422 `{"detail": "SYN01 has no bilateral pick"}` | The user presses `Withdraw` | The alert reads exactly `Alpha Corp has no bilateral pick` | holdout |
| AC-9 | The checkpoint studio; one escalation recommendation with `tier` `null`, `reason` `No escalation trigger`, `rule` `hold` | The table renders | The row's `tier` cell reads `No tier yet` and its `why` cell reads exactly `No escalation trigger` | holdout |
| AC-10 | `#/stewardship/checkpoint` | Read the Escalation recommendations table | No cell in the `why` column ends with `)` | evaluator |
| AC-11 | A ballot whose `watch_flags` hold one `overdue` and one `broken` flag | The ballot card renders collapsed | The overdue banner has class `banner-warning`, the broken banner class `banner-danger` | holdout |
| AC-12 | AC-11 | The card is expanded | Same classes as AC-11 | holdout |
| AC-13 | `DossierWatchList` with one entry flagged `overdue` and one flagged `broken` | It renders | The `overdue` badge has class `badge-mid`, the `broken` badge class `badge-low` | holdout |
| AC-14 | An `in_progress` objective with `target_date` `end of FY2027` | The panel renders | Its row reads `due end of FY2027` | holdout |
| AC-15 | the watch-topics list stubbed with one `open` topic with `target_date` `2026-12-31T00:00:00` | The panel renders | Its row reads `due 2026-12-31` | holdout |
| AC-16 | `DossierWatchList` with an entry whose `target_date` is `2025-12-31 (approx.)` | It renders | The entry reads `due 2025-12-31 (approx.)` | holdout |
| AC-17 | Signed out; the issue has one `in_progress` objective `Set a 2030 target` without proof; the watch-topics list stubbed with one `open` topic `Board diversity` without proof; the suggestions list stubbed with `{"suggestions": []}` | The panel renders | Buttons named `Record result: Set a 2030 target`, `Add proof statement: Set a 2030 target`, `Add proof statement: Board diversity`, `Add watch topic` and `Close topic: Board diversity` are all disabled | holdout |
| AC-18 | AC-17 | The panel renders | The text `Sign in to record results, proof statements and watch topics.` appears exactly once, directly after the access-token field | holdout |
| AC-19 | AC-17 but signed in as `dev` | The panel renders | The five buttons of AC-17 are enabled and the AC-18 sentence is absent (must not change) | holdout |
| AC-20 | Signed in as `dev`; the issue's objective of AC-17; the suggestions list stubbed to answer 409 `{"detail": "Watch items need the Postgres engagement store."}` | The panel renders | No button whose accessible name starts with `Add proof statement` | holdout |
| AC-21 | AC-20 but the suggestions list stubbed to answer 500 `{"detail": "boom"}` | The panel renders | The button `Add proof statement: Set a 2030 target` is present (must not change) | holdout |
| AC-22 | Signed in as `dev`; topic `Board diversity` with one pending evidence suggestion; the confirm stubbed to answer 200; the reload returns no pending suggestion | The user presses `Confirm evidence: Board diversity` | Focus is on the button `Check against documents: Board diversity` | holdout |
| AC-23 | An open commitment `Publish a transition plan` with one pending evidence suggestion, verdict `found`; the confirm stubbed to answer 200; the refreshed record shows the commitment `verified` | The user presses `Confirm evidence: Publish a transition plan` | Focus is on that commitment's row, whose badge reads `verified` | holdout |
| AC-24 | Objective `Set a 2030 target` with one pending evidence suggestion; same stubs | The user presses `Confirm evidence: Set a 2030 target` | The Record result form is open and focus is on its `Result` select (must not change) | holdout |
| AC-25 | AC-22's Given | Read the suggestion's buttons | Their accessible names are `Confirm evidence: Board diversity` and `Reject evidence: Board diversity` | holdout |
| AC-26 | One pending `new_commitment` suggestion with text `Publish a transition plan` | Read its Reject button | Its accessible name is `Reject commitment: Publish a transition plan` | holdout |
| AC-27 | AC-22 | Confirm succeeds | An element with `role="status"` in the topic's row reads `Evidence confirmed: Board diversity` | holdout |
| AC-28 | AC-24 | Confirm succeeds | An element with `role="status"` in the objective's row reads `Evidence confirmed: Set a 2030 target` | holdout |
| AC-29 | A collapsed, undecided ballot card with one watch flag | The card renders | In document order, the flag banner comes before the `Approve: vote …` button | holdout |
| AC-30 | An objective with status `in_progress` and result `not_achieved` | The panel renders | Its badge reads `in progress` and its result reads `result: not achieved`; no text in the row contains `_` | holdout |
| AC-31 | AC-30, signed in | The user opens Record result | The Result select's options read `achieved`, `partially achieved`, `not achieved`, `deterioration`, `abandoned`; choosing `not achieved` and saving sends `result` `not_achieved` | holdout |
| AC-32 | An issue with `source` `manual`, `data_source` null, one objective with `source` `mock_voice_seed` | The panel renders | The issue header's chip row contains a chip `Demo data` | holdout |
| AC-33 | AC-32 | The panel renders | The objective's row still shows its own `Demo data` chip (must not change) | holdout |
| AC-34 | An issue with `data_source` `npx_urth_demo` and no objectives | The panel renders | The issue header's chip row contains a chip `Demo data` | holdout |
| AC-35 | An issue with `source` `manual`, `data_source` null, objectives with `source` null | The panel renders | The issue header has no `Demo data` chip (must not change) | holdout |
| AC-36 | Reviewer name `dev` entered; a run with 3 routine, undecided proposals: 2 for `Alpha Corp`, whose ballot has one watch flag with message `Commitment overdue: "Publish a transition plan" was due 2026-10-01.`, and 1 for `Beta plc` with none | The user presses `Approve 3 routine…` | The dialog shows the line `Alpha Corp: Commitment overdue: "Publish a transition plan" was due 2026-10-01.` once and no line for `Beta plc` | holdout |
| AC-37 | AC-36's dialog open | The user presses `Approve 3` | 3 review decisions `approve` are sent, one per proposal | holdout |
| AC-38 | AC-36 without any watch flag | The user presses `Approve 3 routine…` | The dialog shows no watch-flag list (must not change) | holdout |
| AC-39 | A client stream whose `program_versions` hold one version with a target whose `client_step` is `joint_engagement` (written to the stream file directly) | `GET /api/stewardship/streams/<stream>/program/monitor` | That target's row has `planned step` `private engagement` | unit |
| AC-40 | AC-39 | `GET /api/stewardship/streams/<stream>/program` | That target in `versions` has `client_step` `private_engagement` | unit |
| AC-41 | AC-39 | Both calls done | The stream file still holds `client_step` `joint_engagement` (unchanged bytes) | unit |

| AC-42 | AC-23 | Confirm succeeds | An element with `role="status"` in the commitment's row reads `Evidence confirmed: Publish a transition plan` | holdout |
| AC-43 | Signed in as `dev`; the objective of AC-17; the suggestions list stubbed never to answer | The panel renders | The button `Add proof statement: Set a 2030 target` is present (must not change) | holdout |
| AC-44 | AC-36, but `Alpha Corp`'s ballot has two watch flags (`Commitment overdue: …` and `Objective overdue: "Set a 2030 target" was due 2026-09-30.`) | The user presses `Approve 3 routine…` | The dialog shows exactly two `Alpha Corp: …` lines, one per flag | holdout |

Must not change: a refused pick keeps the form (AC-4); signed-in buttons (AC-19); the proof button on a non-409
error and while loading (AC-21, AC-43); the objective's confirm-to-record flow (AC-24); the per-objective demo chip and no chip on live data
(AC-33, AC-35); the bulk dialog without flags (AC-38); stored programme versions (AC-41).
