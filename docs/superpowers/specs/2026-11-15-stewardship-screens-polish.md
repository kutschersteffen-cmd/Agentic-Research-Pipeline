# Stewardship screens: polish from the findings

Slug: stewardship-screens-polish

Risk: `risk:normal`. Size M, 3 PRs: two frontend, one small backend.

Status: draft, round 2 of the findings clean-up the owner asked for on 15 Nov 2026 ("clean up further bugs and
findings"). Checked against `origin/main` `5df84c4`.

## Why

Small faults on the stewardship screens that a manager would notice at the showcase (about 27 Nov 2026, laptop
screen): codes instead of words, a form that keeps its old choice, one meaning shown in two colours, buttons that
work when they should not, and actions a screen reader does not announce.

## PR split and order

- **PR A, tiers picks and checkpoint** (`frontend/src/pages/steward/studios.tsx`): build at once. Its PR body
  carries `Rows: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7`.
- **PR B, engagement watch and ballot review** (`frontend/src/components/EngagementWatch.tsx`,
  `EngagementIssuePanel.tsx`, `BallotReview.tsx`): build only **after the build of
  `commitment-loop-review-fixes` (spec PR #501) is merged**, because that build edits `EngagementWatch.tsx` too.
  Branch PR B from `main` after that merge. Its PR body carries `Rows:` with AC-8 to AC-22 and AC-23 to AC-25.
- **PR C, programme step names** (`backend/arp/stewardship/program.py`): build at once, in parallel with PR A.
  It does not fit PR A: the step name is written by the backend. No `Rows:` line on whichever of B and C merges
  last; the other carries its rows.

## Owner decisions (15 Nov 2026, by button)

- Bulk approve: the "Approve N routine" dialog lists the ballots that carry a commitment warning before the owner
  approves; he can still approve all. Owner: "List flagged ballots".
- Old programme versions: versions approved before the step "joint engagement" was removed show the current step
  name on screen; the stored history is not touched. Owner: "New name on screen".

## Goals

PR A:

- (A1) After a successful bilateral pick, the Company select and the Reason are both empty again.
- (A2) A refused pick or withdrawal shows the server's sentence without the status code (`422: `), with the
  company's name in place of its id.
- (A3) A pick or a withdrawal that succeeds is announced in a polite status line.
- (A4) The checkpoint stage's "Escalation recommendations" table shows `No tier yet` for a company with no tier,
  and the rule's reason without the rule key in brackets.

PR B:

- (B1) One colour per flag kind, the same on the ballot and in the dossier: overdue amber-brown (status "mid"),
  broken red (status "low").
- (B2) A due date is shown whole, unless it is an ISO date with a time part, which shows the date only.
- (B3) Record result, Add proof statement, Add watch topic and Close topic are disabled when nobody is
  signed in, with the sidebar sign-in sentence shown once.
- (B4) "Add proof statement" is not offered on the file engagement store.
- (B5) After Confirm on a suggestion, keyboard focus stays in the item it acted on.
- (B6) Confirm and Reject name the item they act on for screen readers.
- (B7) On a collapsed ballot card, the watch banner comes before the Approve button.
- (B8) Objective and topic statuses show words (`in progress`), not codes (`in_progress`).
- (B9) The issue header shows the `Demo data` chip when any of its objectives is demo data.
- (B10) The "Approve N routine" dialog lists the companies among those N proposals whose ballot carries a watch
  flag, with the flag's message; the Approve button still approves all N.

PR C:

- (C1) A client programme version approved before the six-step ladder shows `private engagement` where it stored
  `joint_engagement`, on the Client program page's "The approved program against today's data" table
  (`planned step` column). The stored version is not rewritten.

## Non-goals

Phone layouts, the backend, anything inside `commitment-loop-review-fixes` (suggestion errors, watch-flag dates,
CLI dossier) or `tiers-review-fixes` (`tiers.py`, `policies.py`), the cockpit, other tier labels (`bilateral`,
`letter`, `monitor` stay as they are), new colours or tokens.

## Approach

One sensible way for each item, all inside the files named above; the alternatives are noted where one existed.

- **(A2)** The panel strips a leading `NNN: ` (the pattern `lib/themeLayers.ts` uses) and replaces the issuer id
  with the company's name from the list it already loads. A friendlier server message was dropped: `tiers.py` is
  out of scope (and `tiers-review-fixes` pins today's text, its AC-8).
- **(A4)** The rule's `reason` is already a sentence a person wrote in the rule editor; the bracketed `rule` key
  adds nothing for a reader. A label map in the frontend was dropped: rules are editable, so a map would go stale.
- **(B1)** Status colours, not the amber signal: an overdue or broken commitment is the company's state, not a
  person's to-do (`DESIGN.md`, "The Status Is Not The Signal Rule"). Ballot: `banner banner-warning` for overdue,
  `banner banner-danger` for broken. Dossier: `badge badge-mid` for overdue, `badge badge-low` for broken. Today
  both kinds are `banner-warning` on the ballot and `badge-low` in the dossier.
- **(B3)** Use `useMe()` the way `EngagementIssuePanel.tsx` already does for its other buttons (`!actor`), and
  `SIGN_IN_REQUIRED` from `lib/reviewer.ts` as the sentence.
- **(B4)** The file store is the one that answers the watch routes with 409 `Watch items need the Postgres
  engagement store.`; the panel already detects it (`STORE_409`, `useSuggestions`).
- **(B8)** Reuse the panel's `fmt()` (underscores to spaces) rather than a second helper.
- **(B10)** Routine proposals already exclude alignment-flagged ones (`isRoutine`), but not those of a company
  with a watch flag (`ballot.watch_flags`, the overdue or broken commitments). The dialog gets one list of those
  companies above its table; disabling or splitting the batch was not chosen by the owner.
- **(C1)** `monitor()` (`program.py`) builds the `planned step` cell from the frozen version's `client_step`. It
  maps the value through `OLD_STAGES` (`arp/schemas/engagement.py`) before formatting, the same read-time mapping
  the engagement store and the cockpit use. `GET …/program` already maps old tier keys this way on read; it maps
  `client_step` too. Rewriting the stored versions was ruled out by the owner.

## Acceptance

PR A rows run on the app started by `backend/scripts/e2e_stack.sh up`, on `#/stewardship/selection` (Bilateral
picks) and `#/stewardship/checkpoint`, with the house universe it loads. "Company C" is any company in the picks
list's Company select, and "N" is its name as the select shows it.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | No pick for Company C | The user chooses C, types reason `Board change`, presses `Pick for bilateral` | The pick list shows N; the Company select shows `Choose a company…`; the Reason field is empty | evaluator |
| AC-2 | AC-1 done | Read the picks panel | An element with `role="status"` reads `N is picked for bilateral.` | evaluator |
| AC-3 | AC-1 done | The user chooses C again, types reason `Again`, presses `Pick for bilateral` | The alert reads exactly `N is already picked for bilateral` (no `422`, no issuer id) | evaluator |
| AC-4 | AC-1 done | The user presses `Withdraw` on N's pick | N leaves the pick list; the `role="status"` element reads `The bilateral pick for N is withdrawn.` | evaluator |
| AC-5 | The picks panel rendered; `api.pickBilateral` rejects with `Error("422: A bilateral pick reason has at most 500 characters")` | The user picks a company | The alert reads exactly `A bilateral pick reason has at most 500 characters` | unit |
| AC-6 | The checkpoint studio rendered; `api` returns one escalation recommendation with `tier` `null`, `reason` `No escalation trigger`, `rule` `hold` | The table renders | Its row shows `No tier yet` in the `tier` column and exactly `No escalation trigger` in the `why` column | unit |
| AC-7 | The e2e app, `#/stewardship/checkpoint` | Read the "Escalation recommendations" table | No cell in the `why` column ends with `)`; no cell in the `tier` column reads `none` | evaluator |

PR B rows are frontend component tests or browser tests with the API stubbed by `page.route`, because the e2e
stack has no engagement data with these states. "Panel" is the issue panel on `#/engagement`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-8 | A ballot whose `watch_flags` hold one `overdue` and one `broken` flag | The ballot card renders, collapsed and then expanded | Each time, the overdue banner has class `banner-warning` and the broken banner has class `banner-danger` | unit |
| AC-9 | A dossier watch list with one entry flagged `overdue` and one flagged `broken` | The dossier watch list renders | The `overdue` badge has class `badge-mid`, the `broken` badge class `badge-low` | unit |
| AC-10 | An objective with `target_date` `end of FY2027`, a watch topic with `target_date` `2026-12-31T00:00:00`, a dossier entry with `target_date` `2025-12-31 (approx.)` | The panel renders | They read `due end of FY2027`, `due 2026-12-31` and `due 2025-12-31 (approx.)` | unit |
| AC-11 | `useMe()` returns null (signed out); an issue with one `in_progress` objective and one `open` watch topic, both without proof; the Postgres store | The panel renders | `Record result`, `Add proof statement` (both), `Add watch topic` and `Close topic` are disabled | unit |
| AC-12 | AC-11 | The panel renders | The text `Enter your access token in the sidebar first: every decision is recorded against the signed-in user.` appears exactly once | unit |
| AC-13 | AC-11 but signed in as `dev` | The panel renders | The same five buttons are enabled (must not change) | unit |
| AC-14 | `api.listSuggestions` and `api.listWatchTopics` reject with `Error("409: Watch items need the Postgres engagement store.")`; an issue with one `in_progress` objective without proof | The panel renders | No button named `Add proof statement` | unit |
| AC-15 | One pending evidence suggestion on an `open` watch topic with question `Board diversity`; stubs answer the confirm with 200 and the reload with no pending suggestion | A keyboard user presses `Confirm` on it | Focus is on the button named `Check against documents: Board diversity` | holdout |
| AC-16 | A pending evidence suggestion on an `in_progress` objective; same stubs | A keyboard user presses `Confirm` on it | The Record result form is open and focus is on its `Result` select (must not change) | holdout |
| AC-17 | AC-15's suggestion | Read its buttons | Their accessible names are `Confirm evidence: Board diversity` and `Reject evidence: Board diversity` | unit |
| AC-18 | AC-15 | Confirm succeeds | An element with `role="status"` reads `Evidence confirmed: Board diversity` | unit |
| AC-19 | A collapsed, undecided ballot card with one watch flag | The card renders | In document order, the flag banner comes before the `Approve: vote …` button | unit |
| AC-20 | An objective with status `in_progress` | The panel renders | Its status badge reads `in progress`; no text in the objective row reads `in_progress` | unit |
| AC-21 | An issue with `source` `manual`, `data_source` null, and one objective with `source` `mock_voice_seed` | The panel renders | The issue header's chip row contains a chip `Demo data` | unit |
| AC-22 | An issue with `source` `manual`, `data_source` null, and objectives with `source` null | The panel renders | The issue header shows no `Demo data` chip (must not change) | unit |
| AC-23 | A run with 3 routine, undecided proposals: 2 for company `Alpha Corp`, whose ballot has one watch flag with message `Commitment overdue: "Publish a transition plan" was due 2026-10-01.`, and 1 for `Beta plc` with none | The user presses `Approve 3 routine…` | The dialog shows the line `Alpha Corp: Commitment overdue: "Publish a transition plan" was due 2026-10-01.` once, and no line for `Beta plc` | unit |
| AC-24 | AC-23's dialog open | The user presses `Approve 3` | 3 review decisions `approve` are sent, one per proposal | unit |
| AC-25 | AC-23 without any watch flag | The user presses `Approve 3 routine…` | The dialog shows no commitment-warning list (must not change) | unit |
| AC-26 | PR C. A client stream whose `program_versions` hold one version with a target whose `client_step` is `joint_engagement` (written to the stream file directly) | `GET /api/stewardship/streams/<stream>/program/monitor` | The row for that target has `planned step` `private engagement` | unit |
| AC-27 | AC-26 | The stream file after that call | It still holds `client_step` `joint_engagement` (byte-identical) | unit |
| AC-28 | AC-26 | `GET /api/stewardship/streams/<stream>/program` | That target in `versions` has `client_step` `private_engagement` | unit |
