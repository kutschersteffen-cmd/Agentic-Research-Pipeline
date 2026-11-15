# Stewardship: the owner's decisions, round 2

Slug: stewardship-decisions-round-2

Risk: per PR, below. Size L in total, 5 small PRs, one per area.

Status: draft, round 2 of the findings clean-up the owner asked for on 15 Nov 2026 ("clean up further bugs and
findings"). The owner decided each item by button on 15 Nov 2026 (quoted below). Checked against `origin/main`
`5df84c4`.

## Why

The triage of tonight's findings left questions only the owner could answer. He answered them; this spec turns
each answer into the smallest change. None of them is visible in the showcase data except item 1.

## The five areas

| PR | Area | Risk | Waits for |
|----|------|------|-----------|
| 1 | Demo label on triggers | `risk:high` (a new field on stored triggers) | The `stewardship-priority-worklist` PR4 to PR6 builds: they rewrite `ledger_rows` and `vote_items`, and PR6 adds a triggers tab that needs the label too |
| 2 | Found-commitment quote | `risk:normal` (frontend only) | The build of `commitment-loop-review-fixes` (spec PR #501): it edits the same card |
| 3 | Workbench Confirm drops companies no longer held | `risk:high` (writes selection events; changes the API response) | The `stewardship-priority-worklist` PR4 to PR6 builds and `workbench-review-fixes`: all change `SelectionLog` in `worklist.py` and the workbench page |
| 4 | Concentration alerts without cash lines | `risk:high` (portfolio weights) | Nothing. The alerts follow-up (spec PR #497) edits another function of `evaluator.py`; merge `main` before the holdout run |
| 5 | One meeting per listing | `risk:high` (meeting keys and a repair of stored keys) | Nothing. `vote-abstain-and-seed-fixes` (spec PR #499) does not change `intake.py` |

Each PR carries `Spec: stewardship-decisions-round-2` and a `Rows:` line with its rows; the last to merge drops it.

## 1. Demo label on triggers

**Owner:** "Keep, label 'Demo data'": demo votes from the ETF filings keep counting and keep raising triggers; each
trigger raised by demo votes carries a `Demo data` label wherever triggers are shown.

**Today.** `vote_items()` (`stewardship/process.py`) merges ledger rows with no source filter, and `ledger_rows()`
(`vote_ledger_feed.py`) drops the meeting's and decision's `source`. The monitoring rule `vote_against_management`
fires on the per-company count of against-management votes, so a trigger cannot tell whether demo votes raised it.
Demo sources are `npx_urth_demo`, `cockpit_demo` and `mock_voice_seed` (`DEMO_SOURCES`, `cockpit.py`).

**Change.** `ledger_rows` keeps a `demo` flag per row (meeting or decision source in `DEMO_SOURCES`). The company
fields count non-demo against-management votes next to the total. A `vote_against_management` trigger gets
`demo: true` when that non-demo count is 0. `UnifiedTrigger` gains `demo: bool = False`, kept when stored. The
frontend shows a `Demo data` chip next to the reason in the "Triggers raised" table (`studios.tsx`, Monitoring
stage), in the stored-trigger table (`ProfileActionStrip.tsx`) and in PR6's triggers tab.

**Author's call:** a company with both demo and real against-management votes gets no label, because the real
votes alone raise the trigger.

## 2. Found-commitment quote

**Owner:** "Only if it matches": a found commitment's quote is shown only when it is found word for word in the
document; otherwise the card shows the commitment without a quote and a link to the document.

**Today (corrects the triage).** Found commitments are already checked against the note when they are created
(`commitment_suggestions`, `watch_check.py`); those that match nothing are dropped. But the check accepts a near
match (92 % of the characters, `grounding_fuzzy_threshold`), and the card shows the model's wording
(`<blockquote>"{s.quote}"</blockquote>`, `FoundCommitment` in `EngagementWatch.tsx`). The "document" is the note
itself: the issue's correspondence entry whose `entry_id` is the suggestion's `activity_id`.

**Change, frontend only.** The card shows the quote only when it appears in the note's `summary` after both are
lowercased, with runs of whitespace collapsed and curly quotes and dashes made straight. Otherwise, and when the
note is not in the issue, the card shows no quote and a `Show the note` button that scrolls to that correspondence
entry and moves focus to it. Nothing stored changes; near matches stay suggested.

**Author's calls:** differences of case, spacing and typographic quotes count as word for word (they come from
how a PDF is turned into text, not from the wording). Checking in the frontend was chosen over a new stored field,
which would need a database change and a new uniqueness key for suggestions without a quote.

## 3. Workbench Confirm drops companies no longer held

**Owner:** "Skip and drop them": Confirm confirms only companies still held, removes proposed companies that left
the universe from the proposal, and names them in a message.

**Today.** `SelectionLog.confirm` (`worklist.py`) writes `confirmed` for every `proposed` row. The route
`POST /api/stewardship/selection/confirm` already computes the scope's companies (`_in_scope`) and discards them.

**Change.** The route passes that set to `confirm`, which, under the same lock, confirms proposed rows in the set and
writes a `removed` event for proposed rows outside it. The response `Confirmed` gains `dropped: list[str]` (company
names, sorted); regenerate the OpenAPI types. The workbench's success message adds
`Not confirmed, no longer held: <names>.` when `dropped` is not empty.

## 4. Concentration alerts without cash lines

**Owner:** "Only non-cash lines": cash and currency lines are left out of a company's weight.

**Today.** `evaluator.py` (concentration rules) skips companies held only through cash, but a company's weight
still sums its cash lines: weight = the company's market value over the total, both over all holdings.

**Change.** The company's market value (the numerator) sums only lines that are not cash (`_is_cash`, the existing
helper: asset class `cash` or a `_CURRENCY` security id or ISIN). The total (NAV, the denominator) stays all lines,
cash included. The cash-only skip then follows by itself.

## 5. One meeting per listing

**Owner:** "One meeting per listing": when one shareholder meeting is voted through two listings of a company
(share and ADR), each listing gets its own meeting record and the upload goes through.

**Today.** Vote intake (`stewardship/intake.py`) names a meeting by the known `company_id`, else by `isin`, else by
`cusip`, plus the meeting date. Two rows for one known company with different ISINs land on one meeting, and the
second is rejected with `isin differs from the meeting's <ISIN>`; the whole batch is refused (422).

**Change.** A meeting is named by its listing first: `isin`, else `cusip`, else `company_id`, plus the date. The
meeting's `company_id` is the row's `company_id` when that company has a `stw_companies` row, else `isin_<ISIN>`
when that has one, else null (the rule the owner confirmed below). A repair step in `postgres_schema.py` (the `_vote_meeting_key_repair`
pattern) re-keys stored meetings named by `company_id` that carry an ISIN or CUSIP, so re-uploading an old file
updates instead of duplicating. The `differs from the meeting's` rejection can then only come from a `company_id`
conflict on one listing, and stays for that.

**Superseded in the parent spec** (`2026-11-12-stewardship-data-foundation-design.md`): the sentence "A meeting is
named by the row's `company_id` when it is in the registry or `stw_companies`, else by its `isin`, else by its
`cusip`" and the ISIN and CUSIP part of the conflict rule. Tests that change (list in the PR):
`backend/tests/test_stewardship_vote_intake.py` around lines 234 and 315.

**Spec correction, no code change** (owner: a meeting gets its company only when the company is already known).
The parent spec's rule "A vote row that carries `isin` or `cusip` and whose company matches nothing is stored with
`company_id` null" reads as if a registry match were enough. The code, and the parent's own earlier sentence, set
it only when the company has a `stw_companies` row. The correct reading: a vote's meeting gets a `company_id` only
when that company already has a `stw_companies` row; otherwise it is null.

## Decided as no change

The demo seed and the demo vote loader get no guard against non-demo databases (owner: "Leave as is"). A
high-severity trigger still goes straight to the chair meeting, as the tiers spec says.

## Non-goals

Filtering demo votes out; showing near-match quotes differently; a database field for verified quotes; changes to
the confirm dialog's wording beyond the dropped names; other alert rule types; merging the two listings' meetings
into one view.

## Acceptance

`unit` rows use the repo's test fixtures (Postgres where the code needs it). `holdout` rows drive the app started by
`backend/scripts/e2e_stack.sh up` through the API.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Company `SYN01` whose only against-management vote is on a meeting with `source` `npx_urth_demo` | Monitoring evaluates (`GET /api/stewardship/studio/monitoring/triggers`) | Its trigger with `rule` `vote_against_management` has `demo` `true` | unit |
| AC-2 | AC-1 plus one against-management vote for `SYN01` on a meeting with `source` `api` | The same call | That trigger has `demo` `false` | unit |
| AC-3 | AC-1 | The monthly run stores triggers, then `GET /api/stewardship/triggers` | The stored trigger has `demo` `true` | unit |
| AC-4 | AC-1 | The Monitoring stage renders the "Triggers raised" table | `SYN01`'s `vote_against_management` row shows a chip `Demo data` | unit |
| AC-5 | AC-2 | The same table | That row shows no `Demo data` chip (must not change) | unit |
| AC-6 | A pending `new_commitment` suggestion with quote `We will publish a transition plan by 2026.`, its note's `summary` containing `we will  publish a transition plan by 2026.` | The issue panel renders | The card shows the quote `"We will publish a transition plan by 2026."` | unit |
| AC-7 | The same suggestion, the note's `summary` containing `We shall publish a transition plan by 2026.` | The issue panel renders | The card shows no quote and a button `Show the note` | unit |
| AC-8 | AC-7 | The user presses `Show the note` | Focus is on the note's correspondence entry | unit |
| AC-9 | The suggestion's `activity_id` is not among the issue's correspondence | The issue panel renders | The card shows no quote and no `Show the note` button | unit |
| AC-10 | A house selection for the open cycle with `SYN01` and `SYN02` proposed; `SYN02` no longer in the house universe | `POST /api/stewardship/selection/confirm` `{}` | Status 200, body `{"confirmed": 1, "dropped": ["<SYN02's name>"]}` | unit |
| AC-11 | AC-10 done | `GET /api/stewardship/selection` | `SYN01` has status `confirmed`; `SYN02` is not listed | unit |
| AC-12 | A selection with `SYN01` proposed and still in the universe | The same confirm | Status 200, body `{"confirmed": 1, "dropped": []}` (must not change apart from the new field) | unit |
| AC-13 | The workbench page; `api` confirm resolves `{"confirmed": 1, "dropped": ["Beta plc"]}` | The user confirms | The message contains `Not confirmed, no longer held: Beta plc.` | unit |
| AC-14 | One portfolio, NAV 1000 EUR: company `C1` with an equity line of 50 EUR and a cash line (asset class `cash`) of 30 EUR; other holdings make up the rest; a concentration rule `above 6%` | `POST /api/portfolio/monitoring/evaluate-now` | No alert for `C1` (5.00 %) | unit |
| AC-15 | AC-14 with `C1`'s equity line 70 EUR | The same call | One alert for `C1` with `observed_value` `0.07` | unit |
| AC-16 | AC-14 with a company `C2` held only through a `_CURRENCYUSD` line of 200 EUR | The same call | No alert for `C2` (must not change) | unit |
| AC-17 | Company `SYN01` with a `stw_companies` row | `POST /api/stewardship/intake/votes` with two rows for meeting date `2026-05-01`, both `company_id` `SYN01`: one `isin` `US0000000001`, item `1`; one `isin` `US0000000002`, item `1` | Status 200, `rejected` `[]`, `created` `2` | holdout |
| AC-18 | AC-17 done | Read `vote_meetings` | Two meetings for `2026-05-01`, both `company_id` `SYN01`, one with each ISIN | unit |
| AC-19 | A stored meeting named `cid:SYN01:2026-05-01` with `isin` `US0000000001` (as written by `main` today) | The repair step runs, then the AC-17 batch is sent again | `created` `0`; still exactly two meetings for `2026-05-01` | unit |
| AC-20 | AC-17's company | One batch with two rows on one listing (`isin` `US0000000001`, date `2026-05-01`), one with `company_id` `SYN01` and one with `company_id` `SYN09` (also with a `stw_companies` row) | Status 422, one `rejected` entry with `field` `company_id` (must not change) | unit |

Must not change: no label on a trigger real votes raise (AC-5); confirm without leavers (AC-12); cash-only companies
never alert (AC-16); a company conflict on one listing is still refused (AC-20).
