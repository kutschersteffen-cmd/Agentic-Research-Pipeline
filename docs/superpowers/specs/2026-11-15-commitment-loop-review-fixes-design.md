# Commitment loop: review fixes

Slug: commitment-loop-review-fixes

Risk: `risk:normal`. Size S, 1 PR (touches `frontend/src`, so the PR gets a UI review).

Parent spec: [2026-11-13-stewardship-commitment-loop-design.md](2026-11-13-stewardship-commitment-loop-design.md).

Status: draft, waiting for the owner's approval.

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
4. **To prove:** an objective with an empty description once gave a 500 and stopped a company's watch checks. The
   crash site is gone; nothing tests it. `stw_objectives.description` is nullable and intake requires it, so such a
   row can only come from older data or a direct write.

## Goals

- (1) A non-409 error loading suggestions shows `Suggestions unavailable: <error text>` in the issue panel. The 409
  keeps today's silent fallback. The found-commitment card names no date when its note is unknown.
- (2) Watch flags read the date part (first 10 characters) of a due date, the same as `triggers()`.
- (3) The CLI dossier carries the same watch list as the API dossier.
- (4) One regression test per path that once crashed; code changes only if a test fails.

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

**(2) Due dates.** `_iso(value)` returns `value[:10]` when that is a valid `YYYY-MM-DD` date, else None. Free-text
due dates still count as none (parent AC-87). A flag's `target_date` and `since` hold the date part only, and its
`message` uses it.

**(3) CLI.** After `research_company_issue`, `dossier-draft` sets `watch_list` from
`watch_list(store, company_id, issue_id)` with the store it already opened, before writing `--out`.

**(4) Empty description.** `watch_items`, `watch_item` and the check treat an empty or null description as text
`""`. If the tests below pass on `main`, the PR adds only the tests.

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
| AC-1 | An engagement with an `open` commitment added through `POST /api/stewardship/tracking/commitments` with `text` `Publish a transition plan`, `target_date` `<yesterday>T10:00:00`; a document for the company; the AC-104 dossier stand-in | `POST /api/engagement/records/{company_id}/issues/{issue_id}/dossier` | The response's `dossier.watch_list` has 1 entry: `item_kind` `commitment`, `flag` `overdue` | holdout |
| AC-2 | An open engagement with an `open` commitment, text `Publish a transition plan`, `target_date` `<yesterday>T10:00:00` | `watch_flags(store, company_id)` | One flag: `item_kind` `commitment`, `kind` `overdue`, `target_date` and `since` = `<yesterday>`, `message` `Commitment overdue: "Publish a transition plan" was due <yesterday>.` | unit |
| AC-3 | An open engagement with an `in_progress` objective, description `Set a 2030 science-based target`, `target_date` `<yesterday>T10:00:00` | `watch_flags` | One flag: `item_kind` `objective`, `kind` `overdue`, `target_date` = `<yesterday>`, `message` `Objective overdue: "Set a 2030 science-based target" was due <yesterday>.` | unit |
| AC-4 | An open engagement with an `open` commitment, `target_date` `<today>T00:00:00` | `watch_flags` | `[]` | unit |
| AC-5 | AC-2's data | `triggers([record], sla_days)` and `watch_flags` | `triggers` holds one `commitment_missed` entry for that commitment and `watch_flags` one `overdue` flag for it | unit |
| AC-6 | AC-1's Given, the company in a universe file `U` | `arp engagement dossier-draft <company_id> <issue_id> --universe U --out F` | Exit 0; `F`'s `watch_list` equals `watch_list(store, company_id, issue_id)` as JSON, with 1 entry, `flag` `overdue` | unit |
| AC-7 | AC-6 done | `draft_talking_points` with `F`'s dossier | The `MeetingTalkingPoints` prompt in `calls.jsonl` contains `Publish a transition plan` and does not contain `Watch list:\n(none)` | unit |
| AC-8 | An open engagement with an `in_progress` objective whose `description` is `""`, and a second whose `description` is NULL (both written directly) | `PostgresEngagementStore.watch_items(company_id)` | Both objectives are returned, each with `text` `""` | unit |
| AC-9 | AC-8's first objective O; no documents for the company | `POST /api/stewardship/watch-items/objective/{O}/check` | Status 200, body `{"documents": 0, "suggestions": 0, "unclear": 0, "skipped": 0}` | unit |
| AC-10 | AC-49's Given plus AC-8's two objectives on the same engagement; the stand-in says found on the commitment only | `ChangeDetector.diff_and_record` gets the document as new | One pending suggestion, `item_kind` `commitment`, with that document's `doc_id` | unit |
| AC-11 | `GET /api/stewardship/evidence-suggestions*` stubbed with `page.route` to answer 500 `{"detail": "boom"}`; an engagement with an `open` commitment | A user opens the company's issue on `#/engagement` | The text `Suggestions unavailable: 500: boom` appears once; no `Check against documents` and no `Find commitments` button | evaluator |
| AC-12 | `ARP_ENGAGEMENT_STORE=file`; an engagement with an `open` commitment | A user opens the issue | No text starting `Suggestions unavailable`; no `Check against documents` button (unchanged) | evaluator |
| AC-13 | The suggestions list stubbed with `page.route`: one pending `new_commitment` suggestion on the issue, `activity_id` `act_unknown`, text `Publish a transition plan` | A user opens the issue | The card reads `Argus found a commitment in a note`, then `Publish a transition plan` | evaluator |
| AC-14 | AC-77's Given (parent spec) | A user opens the issue | The card reads `Argus found a commitment in the meeting of 2026-10-01` (unchanged) | evaluator |

Must not change: free-text due dates give no flag (parent AC-87, unchanged); the API dossier's watch list (parent
AC-104 to AC-107); the file store's silent fallback (AC-12); the found-commitment header with a known note (AC-14).

Owed while `HOLDOUT_TOKEN` is missing: none beyond AC-1; it is the only new `holdout` row. The CLI, store and
detector rows are `unit` because holdout tests drive the app only through its API and pages.
