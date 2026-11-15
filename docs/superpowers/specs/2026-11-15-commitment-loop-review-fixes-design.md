# Commitment loop: review fixes

Slug: commitment-loop-review-fixes

Risk: `risk:normal`. Size S, 1 PR (touches `frontend/src`, so the PR gets a UI review).

Parent spec: [2026-11-13-stewardship-commitment-loop-design.md](2026-11-13-stewardship-commitment-loop-design.md).

Status: **approved by the owner on 15 Nov 2026** (buttons in the spec session, after the spec-critic read
"Ready for approval").

## Why

On 15 Nov 2026 the owner asked to "fix all bugs" from the open review findings on the stewardship commitment loop.
Checked on `main` `b53ad65`, three are still present and one is probably fixed but unproven:

1. **Suggestions vanish on any error.** `useSuggestions` (`frontend/src/components/EngagementWatch.tsx`, the
   `catch` in `reload`) sets `available = false` for every error. Only the file store's 409 means "no suggestions
   here"; a 500 or a network error also hides every suggestion and the `Check against documents` and
   `Find commitments` buttons, with no message. Separately, the found-commitment card (`FoundCommitment`) reads
   `Argus found a commitment in the note of ` followed by nothing when the suggestion's note is not in the issue's
   activities.
2. **A due date with a time gives no watch flag.** `watch_flags_by_company` (`backend/arp/stewardship/tracking.py`)
   reads due dates with `_iso()`, which accepts only an exact `YYYY-MM-DD`. `POST /api/stewardship/tracking/commitments`
   accepts `2026-11-01T10:00:00` (any `datetime.fromisoformat` value) and stores it as given. Such a commitment, once
   past due, raises a `commitment_missed` trigger (`triggers()` reads `[:10]`) but no overdue watch flag, so it is
   missing from ballot banners, the dossier watch list's flag and the worklist.
3. **The CLI dossier has no watch list.** `arp engagement dossier-draft` (`backend/arp/cli/engagement.py`) never sets
   `watch_list`; the API route does (`routers/engagement.py`, `draft_dossier_endpoint`). Talking points drafted from
   a CLI dossier say `Watch list: (none)`.
4. **To prove:** an objective with an empty description once gave a 500 and stopped a company's watch checks.
   Nothing tests it. `stw_objectives.description` is nullable and intake requires it, so such a row can only come
   from older data or a direct write. A NULL description still crashes on `main`: `_cols` drops NULL columns and
   `Objective.description` is a required `str`, so `PostgresEngagementStore.get` fails for that company, and with it
   the record page, `watch_flags`, `watch_list` and the check route.

## Goals

- (1) A non-409 error loading suggestions shows `Suggestions unavailable: <error text>` in the issue panel. The 409
  keeps today's silent fallback. The found-commitment card names no date when its note is unknown.
- (2) Watch flags read the date part (first 10 characters) of a due date, the same as `triggers()`.
- (3) The CLI dossier carries the same watch list as the API dossier.
- (4) An objective with an empty or NULL description never breaks the record read or a watch check. Regression
  tests first; code changes only where a test fails (the NULL case will).

## Non-goals

No new features, no other watch UI, no retry button, no change to what counts as overdue (strictly before today,
UTC). Already fixed on `main` and out of scope: evidence text with a missing document title; confirming a found
commitment with no linked activity; refusing a suggestion on a closed engagement (owner's 14 Nov decision).

## Approaches

There is one sensible way for each item, so no alternatives were put to the owner:

- (1) Branch on the error in the existing `catch`: a message starting `409:` keeps `available = false` and no
  message; anything else also sets `available = false` and stores the error text. A retry button or keeping the
  buttons usable after an error were dropped: nothing asked for them, and Check and Find would fail the same way.
- (2) Fix `_iso()` to try `value[:10]` instead of `value`. One shared helper, so `watch_list`'s sort follows too.
  Changing callers one by one was dropped: it leaves two meanings of "due date" in one file.
- (3) The CLI calls `watch_list(store, company_id, issue_id)` and sets it on the dossier exactly as the route does.

## Design

**(1) Suggestions error.** `Suggestions` gains `error: string | null`. On a 409, `available` is false and `error`
is null (today's behaviour). On any other error, `available` is false and `error` is the thrown error's message
(the API client's `"<status>: <detail>"`, or the browser's text for a network error). A later successful reload
clears `error` and sets `available` true. The issue panel shows `Suggestions unavailable: <error>` once, as one
muted line, where the builder sees fit near the Commitments section.

**(1) Found-commitment header.** With the note found: unchanged, `Argus found a commitment in the <activity type>
of <YYYY-MM-DD>` (parent AC-77). Without it: `Argus found a commitment in a note`.

**(2) Due dates.** `_iso(value)` returns `value[:10]` when that is a valid `YYYY-MM-DD` date, else None, the same
reading as `triggers()`. A due date that starts with a valid date (`2025-12-31 (approx.)`) therefore counts as
`2025-12-31`; one that does not (`31/12/2025`) still counts as none (parent AC-87). A flag's `target_date` and
`since` hold the date part only, and its `message` uses it. Dossier watch list entries keep the stored
`target_date` unchanged; only their `flag` and sort order follow the date part.

**(3) CLI.** After `research_company_issue`, `dossier-draft` sets `watch_list` from
`watch_list(store, company_id, issue_id)` with the store it already opened, before writing `--out`.

**(4) Empty description.** The record read (`PostgresEngagementStore.get`), `watch_items`, `watch_item` and the
check treat a NULL description as `""`; an empty one stays `""`. Where a row below already passes on `main`, the PR
adds only its test.

**Builder's calls:** where the error line sits in the panel; its style class (reuse an existing muted or error class).

## Parent rows this extends

- (1) extends AC-65 to AC-79 (suggestions UI), in particular AC-77 (the found-commitment header).
- (2) extends AC-83, AC-85, AC-87, AC-90 (watch flags) and AC-104 (dossier watch list flag).
- (3) extends AC-104 to AC-108 (dossier watch list, talking points).
- (4) extends AC-30 (checking an objective) and AC-49 (the automatic check on new documents).

The parent's hidden tests are not changed or retired: no parent row's "Then" changes.

## Acceptance

Setup is the parent spec's ("Holdout and evaluator setup"): e2e stack with `ARP_ENGAGEMENT_STORE=postgres` and
`ARP_STANDINS_DIR=<dir>`, a new `company_id` per test, `AR2026.txt` as "a document for the company", the AC-104
dossier stand-in, "today" = the UTC date the test runs, user `dev`. `unit` rows may write tables directly.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | An engagement with an `open` commitment added through `POST /api/stewardship/tracking/commitments` with `text` `Publish a transition plan`, `target_date` `<yesterday>T10:00:00`; a document for the company; the AC-104 dossier stand-in | `POST /api/engagement/records/{company_id}/issues/{issue_id}/dossier` | The response's `dossier.watch_list` has 1 entry: `item_kind` `commitment`, `target_date` `<yesterday>T10:00:00`, `flag` `overdue` | holdout |
| AC-2 | An open engagement with an `open` commitment, text `Publish a transition plan`, `target_date` `<yesterday>T10:00:00` | `watch_flags(store, company_id)` | One flag: `item_kind` `commitment`, `kind` `overdue`, `target_date` and `since` = `<yesterday>`, `message` `Commitment overdue: "Publish a transition plan" was due <yesterday>.` | unit |
| AC-3 | An open engagement with an `in_progress` objective, description `Set a 2030 science-based target`, `target_date` `<yesterday>T10:00:00` | `watch_flags` | One flag: `item_kind` `objective`, `kind` `overdue`, `target_date` = `<yesterday>`, `message` `Objective overdue: "Set a 2030 science-based target" was due <yesterday>.` | unit |
| AC-4 | An open engagement with an `open` commitment, `target_date` `<today>T00:00:00` | `watch_flags` | `[]` | unit |
| AC-5 | AC-2's data | `triggers([record], sla_days)` | Exactly one `commitment_missed` entry, for that commitment (unchanged) | unit |
| AC-6 | An open engagement with an `in_progress` objective, description `Set a 2030 science-based target`, `target_date` `2025-12-31 (approx.)` | `watch_flags` | One flag: `kind` `overdue`, `target_date` `2025-12-31` | unit |
| AC-7 | AC-1's Given, the company in a universe file `U` | `arp engagement dossier-draft <company_id> <issue_id> --universe U --out F` | Exit 0; `F`'s `watch_list` equals `watch_list(store, company_id, issue_id)` as JSON, with 1 entry, `flag` `overdue` | unit |
| AC-8 | AC-7 done | `draft_talking_points` with `F`'s dossier | The `MeetingTalkingPoints` prompt in `calls.jsonl` contains `Publish a transition plan` and does not contain `Watch list:\n(none)` | unit |
| AC-9 | An open engagement with an `in_progress` objective whose `description` is `""`, and a second whose `description` is NULL (both written directly) | `PostgresEngagementStore.watch_items(company_id)` | Both objectives are returned, each with `text` `""` | unit |
| AC-10 | AC-9's data | `GET /api/engagement/records/{company_id}` | Status 200; both objectives are listed, each with `description` `""` | unit |
| AC-11 | AC-9's second objective O (NULL description); a document for the company; the stand-in returns `unclear` for O | `POST /api/stewardship/watch-items/objective/{O}/check` | Status 200, body `{"documents": 1, "suggestions": 0, "unclear": 1, "skipped": 0}` | unit |
| AC-12 | AC-49's Given plus AC-9's two objectives on the same engagement; the stand-in says found on the commitment only | `ChangeDetector.diff_and_record` gets the document as new | One pending suggestion, `item_kind` `commitment`, with that document's `doc_id` | unit |
| AC-13 | `GET /api/stewardship/evidence-suggestions*` stubbed with `page.route` to answer 500 `{"detail": "boom"}`; an engagement with an `open` commitment and a `meeting` activity (intake) | A user opens the company's issue on `#/engagement` | The text `Suggestions unavailable: 500: boom` appears once; no `Check against documents` button on the commitment and no `Find commitments` button on the meeting note | evaluator |
| AC-14 | `api.listSuggestions` rejects with `Error("409: Watch items need the Postgres engagement store.")`; an issue with an `open` commitment | The issue panel renders | No text starting `Suggestions unavailable`; no `Check against documents` button (unchanged) | unit (frontend) |
| AC-15 | `useSuggestions` rendered with `api.listSuggestions` rejecting `Error("500: boom")` on the first load, then resolving `{"suggestions": []}` | `result.current.reload()` resolves | `error` is null and `available` is true | unit (frontend) |
| AC-16 | The suggestions list stubbed with `page.route`: one pending `new_commitment` suggestion on the issue, `activity_id` `act_unknown`, text `Publish a transition plan` | A user opens the issue | The card reads `Argus found a commitment in a note`, then `Publish a transition plan` | evaluator |
| AC-17 | AC-77's Given (parent spec) | A user opens the issue | The card reads `Argus found a commitment in the meeting of 2026-10-01` (unchanged) | evaluator |

Must not change: free-text due dates give no flag (parent AC-87, unchanged); the API dossier's watch list (parent
AC-104 to AC-107); `triggers()` (AC-5); the file store's silent fallback (AC-14); the found-commitment header with a known note
(AC-17).

AC-1 is the only new `holdout` row. The CLI, store, detector and directly written rows are `unit`: holdout tests
drive the app only through its API and pages, intake refuses an objective without a description, and the e2e stack
always runs the Postgres store. The "must not change" line relies on the parent's AC-104 to AC-107 hidden tests
running in the holdout regression suite; the test-writer confirms they are there.
