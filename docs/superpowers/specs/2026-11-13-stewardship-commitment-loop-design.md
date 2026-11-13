# Stewardship evidence loop: objectives, commitments and watch topics checked against new reports

Slug: `stewardship-commitment-loop` (the name the factory knows it by). Risk: PR 1 `risk:high` (new tables and
columns: the steward table rates database schema changes high); PRs 2 and 3 `risk:normal`. Size M+, 3 PRs.

Status: **draft for the owner's approval.**

## Owner decisions

Decided (13 Nov 2026, buttons in this session):

- Close the loop from what was agreed or asked to proof, after reviewing a paper on AI-native investment
  stewardship. "Start building now".
- **What Argus checks:** VOICE objectives, company commitments and topics a user adds, not only commitments.
  Topics from selection triggers (CLTI laggard, disclosure gap, controversies, UNGC, pay) come in a **second
  feature**, `stewardship-trigger-watch-topics`, which adds one fixed question per trigger rule to the same watch
  list. This spec builds the watch list it plugs into.
- **Objectives:** a confirmed suggestion is evidence only. A person records the result (VOICE result, influence
  level, outcome); nothing closes an objective automatically.
- **Ballot banner and flags:** commitments and objectives only. Watch topics never show on ballots.
- **Engagement brief:** the dossier (**Draft dossier** on the engagement panel) gets a **Watch list** section built
  by code, and the talking points and outreach letter drafted from the dossier receive it too.

Assumed on the recommended option while the owner was away (the owner can change any of them at approval):

- **Banner placement:** on every ballot item of the company. Alternatives: only items whose proposal type maps to
  the engagement's theme (most items would never show one), or director elections plus theme-matched items.
- **Co-sign:** banner only; casting rules unchanged. Alternative: a flagged item needs a second sign-off, like
  `engagement_alignment_flag`.
- **Unclear:** an "unclear" answer is never stored as a suggestion; the check reports a count only. Alternative:
  store an unclear answer that has a re-found quote as a suggestion a person can only dismiss.

## Why

Stewardship work asks companies for things (VOICE objectives, with target dates) and records what companies
promise (commitments). Nothing checks either against what the company later publishes. A person has to remember the
date, find the report, read it, and type the evidence in. Promises made on a call never become commitments unless
someone re-types them. And when the house votes at that company's meeting, the ballot screen says nothing about an
objective that failed or a promise the company broke.

This feature closes that loop. Every open objective, commitment and watch topic can say what would count as proof.
Argus reads each new report and suggests "evidence found" or "evidence against", with a quote that code finds again
in the report before anyone sees it. A person confirms or rejects. Overdue and failed objectives and commitments show
where the house votes. The model never changes a status.

## Terms

- **Watch item:** an open objective (`stw_objectives`, status `initiated` or `in_progress`), an open commitment
  (`stw_commitments`, status `open`) or an open watch topic (`stw_watch_topics`, status `open`), on an engagement
  whose status is `open` or `stalled`. Its **text** is the objective's `description`, the commitment's `text` or the
  topic's `question`. Its **due date** is `target_date` (optional everywhere).
- **Proof statement:** one sentence saying what evidence would show the item was met ("The 2026 annual report names
  a board climate committee"). Optional; the check uses the text alone when there is none.
- **Suggestion:** a stored, pending answer from Argus that a person confirms or rejects. Two kinds: `evidence` (on a
  watch item, from a document) and `new_commitment` (from a call or meeting note).

## Goals

1. Objectives, commitments and watch topics can carry a proof statement. A person can add watch topics (a question,
   a proof statement, an optional due date) to an engagement.
2. When a new or updated document for a company arrives, Argus checks every watch item of that company against it
   and stores `evidence` suggestions (found or against, with a re-found quote). The same check runs on demand per
   item.
3. Confirming a suggestion: on a commitment it sets `verified` (found) or `missed` (against), as Verify does today;
   on an objective it only records the evidence and opens the result form prefilled; on a topic it records the
   evidence.
4. A person records an objective's result (result, influence level, outcome), which closes it.
5. From a call or meeting note (`stw_activities.summary`), Argus suggests new commitments, each with a quote and a
   due date; a person adds or rejects each one.
6. Overdue and failed objectives and commitments show as a banner on the company's Proxy Voting ballot items, and
   `watch_flags` / `watch_flags_by_company` return the same flags for `stewardship-priority-worklist`.
7. The engagement dossier lists the engagement's watch list (items, due dates, flags, confirmed evidence), and the
   drafts made from the dossier receive it.

## Non-goals

- Trigger-rule topics (the second feature, above).
- The company timeline and the scheduled prep pack.
- Any status, result, escalation stage or monitoring trigger set from a pending suggestion.
- Looking for commitments in letters, emails or documents; only call and meeting notes. Looking for new objectives
  anywhere.
- Running find-commitments automatically on intake (400 demo companies × activities would be thousands of model
  calls).
- A proof-statement or watch-topic column in the Excel intake (it would change the intake template that
  `stewardship-data-foundation` fixed).
- Wiring the new golden set into the CI golden workflow (a `.github/workflows` change is its own `risk:high` PR). The
  PR 2 author runs it and pastes the output into the PR.

## Anti-goals

- **The model sets a status.** Only a person's confirm or result form changes an item (AC-26, AC-37, AC-60).
- **A suggestion without proof.** A found/against answer whose quote is not found again in the document counts as
  unclear and is never stored (AC-22); an unclear answer is never stored (AC-23).
- **Losing a rejection.** Rejected suggestions keep who, when and why, and are never deleted (AC-40, AC-46).
- **Asking twice.** A document already checked for an item never produces a second suggestion for it, whatever
  happened to the first (AC-24, AC-25).
- **Changing how votes are cast** (AC-95) **or the intake template** (AC-97).

## Constraints

- Postgres only for watch topics and suggestions. `stw_commitments`, `stw_objectives`, `PostgresEngagementStore` and
  `arp db init-postgres` are on `main` (`stewardship-data-foundation` PR 1, #433). This feature starts after that
  spec's PR 2 (#440, intake) merges: the holdout tests create objectives and activities through its intake, and the
  two PRs would otherwise edit `postgres_engagement_store.py` and `stewardship.py` at the same time. Its PR 3 is not
  needed for anything but the panel's objectives list: if it has merged when PR 1 starts, PR 1 extends its list;
  otherwise PR 1 adds the list (see "What the user sees") and that PR then only adds its `Demo data` label.
  With `engagement_store = file` the routes listed under "API" answer 409. `watch_flags` reads through the
  `EngagementStore` interface, so it works on both stores.
- Schema changes go through `ensure_schema` in `arp/storage/postgres_schema.py`: two new tables, two additive
  columns, nothing dropped, idempotent.
- No change under `arp/extraction`, `arp/llm`, `arp/golden_set` or `arp/grounding.py`. The check uses the existing
  LLM client (`build_llm_client(settings).complete_structured`) and `arp.grounding.ground_citations` (a `Citation`
  per quote, so `grounded` and `page` come from code, never from the model).
- Request and response models change: `scripts/export_openapi.py` and `npm run gen:api` run, both generated files are
  committed, and new `request<T>()` calls get a line in `frontend/src/api/contract.ts`.
- Writes need role `analyst` or above, reads `viewer`, as for every `/api/stewardship` route.
- No existing test is changed.
- Model calls in tests go through the stand-ins (`ARP_STANDINS_DIR/model/<OutputModel>.json`), so every row except
  the golden rows is deterministic.

## Approaches considered

1. **One watch list over the existing rows, plus a topics table and a suggestions table (picked).** Objectives and
   commitments stay where they are and gain a `proof_statement` column; user topics get `stw_watch_topics`; every
   suggestion, whatever it is about, is a row in `stw_evidence_suggestions` pointing at (`item_kind`, `item_id`).
   The second feature adds trigger topics to the same topics table without touching the rest.
2. A separate loop per kind (commitment proposals, objective proposals, topic proposals). Three copies of the same
   check, confirm and reject code.
3. Copy objectives and commitments into one new `watch_items` table. One shape to read, but two copies of the truth
   that drift.

What counts as "a new report or filing arrives": `monitoring.py` only evaluates rules on a data sample and never
sees documents, so it is not the trigger. The existing hook is `ChangeDetector.diff_and_record`
(`arp/discovery/change_detector.py`), which emits `new_document` and `updated_document` events for discovery runs
and the extraction pre-step and already drives event refresh (E20) through `on_events`. Plain uploads
(`POST /api/documents/upload`, Argus uploads) emit no event, so each watch item also has a **Check against
documents** button.

## Data model

Additive columns: `stw_objectives.proof_statement text null`, `stw_commitments.proof_statement text null`.
`Objective` and `Commitment` (`arp/schemas/engagement.py`) gain `proof_statement: str | None = None`; the file store
carries it unchanged (AC-13).

`stw_watch_topics`, one row per user topic. Defaults: `source` `app`, `external_id` null, `status` `open`,
`created_at` `now()`.

| Column | Type | Meaning |
|---|---|---|
| `topic_id` | text pk | `wtp_…` |
| `source`, `external_id` | text | as every `stw_*` table |
| `engagement_id` | text not null, fk `stw_engagements` | |
| `question` | text not null | what to look for, e.g. `Has the company named a board climate committee?` |
| `proof_statement`, `target_date` | text null | `target_date` is `YYYY-MM-DD` |
| `status` | text not null | `open` or `closed` |
| `created_by`, `created_at`, `closed_by`, `closed_at` | | |

`stw_evidence_suggestions`, one row per suggestion. Defaults: `source` `app`, `external_id` null, `status`
`pending`, `created_at` `now()`. Columns are nullable unless marked.

| Column | Type | Meaning |
|---|---|---|
| `suggestion_id` | text pk | `evs_…` |
| `source`, `external_id` | text | as every `stw_*` table |
| `kind` | text not null | `evidence` or `new_commitment` |
| `company_id` | text not null, fk `stw_companies` | |
| `engagement_id` | text not null, fk `stw_engagements` | |
| `item_kind`, `item_id` | text | `evidence`: `objective`, `commitment` or `topic`, and that row's id |
| `activity_id` | text fk `stw_activities` | `new_commitment`: the note it came from |
| `verdict` | text | `evidence`: `found` or `against` |
| `text`, `proof_statement`, `target_date` | text | `new_commitment`: as Argus worded them; `target_date` only when the note states a date |
| `doc_id`, `doc_type`, `doc_title` | text | `evidence`: the document; `doc_title` = `SourceDocument.title` (the file name for local and uploaded files) |
| `quote` | text not null | the model's quote as returned; grounding only decides whether the row is written |
| `page` | int | from the grounded `Citation`, never from the model |
| `reason` | text | the model's one-line reason |
| `status` | text not null | `pending`, `confirmed`, `rejected` |
| `decided_by`, `decided_at`, `reject_reason` | | set on confirm or reject |
| `created_commitment_id` | text | `new_commitment` once confirmed |

Unique keys: (`item_kind`, `item_id`, `doc_id`) where `kind = 'evidence'`; (`activity_id`, `quote`) where
`kind = 'new_commitment'`. A check that would write an existing key writes nothing and counts it `skipped`.

`stw_events` gets one row per write: `watch_topic_added`, `watch_topic_closed`, `proof_statement_set`,
`objective_result_recorded`, `evidence_suggested`, `evidence_suggestion_confirmed`, `evidence_suggestion_rejected`
(`detail` = the ids involved). A proof statement or an objective result writes exactly one event
(`proof_statement_set` or `objective_result_recorded`), never also `objective_updated` (AC-100).

**Evidence text.** Wherever a confirmed suggestion is written out (commitment `evidence`, the result form's
prefilled outcome, the UI), it is `<doc_title>, page <page>: "<quote>"`, with `, page <page>` left out when `page` is
null.

## The check (PR 2)

**Model output:**

```python
class WatchItemVerdict(BaseModel):
    item_id: str
    verdict: Literal["found", "against", "unclear"]
    quote: str = ""      # verbatim from the document; empty for unclear
    reason: str = ""     # one sentence

class WatchCheckDraft(BaseModel):
    results: list[WatchItemVerdict]
```

The prompt gives the document text (how much of a long document, and whether through retrieval, is the builder's
call) and, per watch item, its id, kind, text, proof statement and due date. One model call per document and
company, covering every item being checked.

**Code, after the call**, per result:

1. An `item_id` that was not in the prompt is ignored.
2. `unclear`, or an empty quote → counted `unclear`, nothing stored.
3. `found`/`against` whose quote does not ground (`ground_citations` against the document) → counted `unclear`.
4. Key (`item_kind`, `item_id`, `doc_id`) already present → counted `skipped`.
5. Otherwise a `pending` `evidence` row is written.

**Automatic run.** On every `new_document` or `updated_document` event from `ChangeDetector`, for a company with at
least one watch item, all its watch items are checked against the event's document. The event carries a
`DiscoveredDocument` (url, `local_path`, `sha256`), not the text, so the document is read with the registry's
`fetch_all` for the company and matched on `Path(local_path).resolve()` equality (`sha256` is not compared: the
event's is a file hash, the registry's a text hash). No match → the event is skipped and logged.
Setting `watch_check_on_new_documents` (env `ARP_WATCH_CHECK_ON_NEW_DOCUMENTS`, default `true`) turns it off; it runs
only when `engagement_store = postgres`.

Wiring: `refresh_hook` (`arp/discovery/refresh.py`) returns a hook whenever event refresh **or**
`watch_check_on_new_documents` is on. The hook runs the watch check first, then `refresh_on_events` when refresh is
on; a check failure is logged and stops neither the refresh nor discovery. `arp/extraction/pre_steps.py` and
`arp/discovery/pipeline.py` stay unchanged.

**On demand.** `POST /api/stewardship/watch-items/{item_kind}/{item_id}/check`, body `{"company_id": "…"}`: checks
that one item against the company's 5 newest documents from `build_registry(...).fetch_all`, with a `CompanyRef`
built from the engagement record (`company_id` and `name` only, no `ticker`, `cik` or `lei`, so only local and
uploaded documents are read). Sort key: `published_at` if set, else `fetched_at`, descending; ties by `doc_id`. One
model call per document. Response `{"documents": N, "suggestions": P, "unclear": U, "skipped": S}`. An item that is
not a watch item (closed, verified, on a closed engagement) → 409 `Only open items can be checked.` Any failed model
call (error, timeout, output that doesn't parse) → 502 `Argus could not check the documents.`, nothing stored from
that request.

## Finding commitments in notes (PR 2)

```python
class FoundCommitment(BaseModel):
    text: str
    proof_statement: str | None = None
    target_date: str | None = None   # YYYY-MM-DD, only when the note states a date
    quote: str                       # verbatim from the note

class CommitmentFindDraft(BaseModel):
    commitments: list[FoundCommitment]
```

`POST /api/stewardship/activities/{activity_id}/find-commitments`, no body. Only for activities whose
`activity_type` is `call` or `meeting` (or, when `activity_type` is null, whose `type` is); any other → 409
`Commitments are only looked for in call and meeting notes.` A found commitment whose quote does not ground in the
activity's `summary` is dropped (`ungrounded`); one whose (`activity_id`, `quote`) exists is dropped (`skipped`); a
`target_date` that is not `YYYY-MM-DD` is stored as null. Response `{"suggestions": P, "ungrounded": G,
"skipped": S}`. No commitment exists until a person adds it.

## API

All under `/api/stewardship`. "The user" is the signed-in user's name (`dev` on the e2e stack).

**Watch items (PR 1)**

- `POST /watch-items/{item_kind}/{item_id}/proof-statement`, body `{"company_id", "issue_id", "proof_statement"}`
  (`item_kind` = `objective`, `commitment` or `topic`) → 200 with the item. Blank → 422 `A proof statement cannot be
  blank.` Allowed on an item in any status. `POST /tracking/commitments` also accepts an optional `proof_statement`.
- Unknown ids, or an `issue_id` the item is not on, on any route in this section → 404 `Unknown objective.`,
  `Unknown commitment.`, `Unknown topic.` or `Unknown activity.`
- `POST /watch-topics`, body `{"company_id", "issue_id", "question", "proof_statement"?, "target_date"?}` → 200 with
  the topic. Blank question → 422 `A question is required.` A `target_date` that is not `YYYY-MM-DD` → 422
  `target_date must be an ISO date`. An engagement whose status is not `open` or `stalled` → 409 `Watch topics need
  an open engagement.`
- `GET /watch-topics?company_id=…` → `{"topics": [...]}`, open and closed, newest first.
- `POST /watch-topics/{topic_id}/close` → 200; `status` `closed`, `closed_by` the user, `closed_at` now. Already
  closed → 409 `This topic is already closed.`
- `POST /objectives/{objective_id}/result`, body `{"company_id", "issue_id", "result", "influence_level", "outcome"}`
  (`result` and `influence_level` are strings from the VOICE lists, e.g. `"achieved"`, `"3"`, `"4A"`). Sets `result`, `influence_level`, `outcome`,
  `closed_at` = now, and `status` = `abandoned` when `result` is `abandoned`, else `closed`. Blank `outcome` → 422
  `An outcome is required.` No `influence_level` with a result other than `abandoned` → 422 `An influence level is
  required to close an objective.` An objective that is not `initiated` or `in_progress` → 409 `This objective is
  already closed.`

**Suggestions (PR 1)**

- `GET /evidence-suggestions?company_id=…&status=pending|confirmed|rejected` (`company_id` required, else 422;
  `status` default `pending`) → `{"suggestions": [...]}`, newest first, every column above.
- `POST /evidence-suggestions/{id}/confirm`:
  - `evidence` on a commitment: `found` → `verified` through `log_commitment_verified` (so it does what Verify does
    today: the milestone moves, and when every commitment of the engagement is verified the engagement becomes
    `resolved`); `against` → `update_commitment_status(..., missed, user, evidence)`. `validated_by` = the user,
    `evidence` = the evidence text.
  - `evidence` on an objective or topic: the suggestion becomes `confirmed`; the item itself is not changed.
  - `new_commitment`, body `{"text"?, "proof_statement"?, "target_date"?}` (each overrides the suggestion): a new
    commitment on the activity's engagement, `made_at` = the activity's `occurred_at`, `recorded_by` = the user;
    `created_commitment_id` is set. No `target_date` in suggestion or body → 422 `A due date is required to add a
    commitment.`; a body `target_date` that is not `YYYY-MM-DD` → 422 `target_date must be an ISO date`. Both leave
    the suggestion `pending`.
  - The item is no longer a watch item → 409 `This item is no longer open.`, the suggestion stays `pending` (it can
    still be rejected).
- `POST /evidence-suggestions/{id}/reject`, body `{"reason"}`. Blank → 422 `A reason is required to reject a
  suggestion.`
- Confirm or reject on a suggestion that is not `pending` → 409 `Suggestion already confirmed.` or `Suggestion
  already rejected.`; unknown id → 404 `Unknown suggestion.`

**Check and find (PR 2):** `POST /watch-items/{item_kind}/{item_id}/check` and
`POST /activities/{activity_id}/find-commitments`, above.

With `engagement_store = file`, every route in this section except `POST /tracking/commitments` answers 409
`Watch items need the Postgres engagement store.`

## What the user sees

On `#/engagement`, in the issue panel (`EngagementIssuePanel.tsx`). Dates are the UTC date: the first 10 characters
of the stored ISO value, never converted to the browser's time zone.

- **Objectives.** An **Objectives** section above Commitments lists the engagement's objectives: description,
  `objective_type`, a status badge (`initiated`, `in_progress`, `closed`, `abandoned`) and the `result` when set, as
  raw values. (Built here unless `stewardship-data-foundation` PR 3 merged it first; see Constraints.)
- **Proof statements.** Each objective, commitment and topic with a proof statement shows `Proof: <proof_statement>`
  under its text; each open one without has a link **Add proof statement** (an input and **Save**).
- **Watch topics.** A new section **Watch topics** under Commitments lists the engagement's topics (question, proof,
  `due <date>`, badge `open` or `closed`) and has **Add watch topic** (inputs `Question`, `What counts as proof`,
  `Due date`; button **Add topic**). Each open topic has **Close topic**.
- **Record result.** Each open objective has **Record result**: selects `Result` and `Influence level`, a text box
  `Outcome`, and **Save result**. The selects list the raw values (`achieved`, `3`, `4A`, …). After saving, the
  objective row shows its new status badge and result.
- **Check.** Each watch item has **Check against documents**. After it runs, one line under the item:
  `Checked <N> document(s): <P> new suggestion(s), <U> unclear.` with singular and plural spelled out
  (`Checked 1 document: 1 new suggestion, 0 unclear.`). With no documents: `No documents on file for this company.`
- **A pending evidence suggestion**, under its item:

  ```
  Argus suggests: evidence found            (or: Argus suggests: evidence against)
  "<quote>"
  <doc_title>, page <page>                  (page part left out when null)
  <reason>
  [Confirm]  [Reject]
  ```

- **After Confirm:** the suggestion disappears. A commitment shows what it shows today for a person's decision
  (badge `verified` or `missed`, `verified by <user>`, `evidence: <evidence text>`). An objective or topic shows a
  line `Evidence: <evidence text> (confirmed by <user>)` (`Evidence against: …` for `against`). For an open
  objective, the Record result form opens with `Result` preselected (`achieved` for found, `not_achieved` for
  against) and `Outcome` prefilled with the evidence text; the person changes what they want and saves, or closes the
  form.
- **Reject** opens an input `Why reject? (required)` and **Confirm rejection**, disabled while blank.
- **Find commitments** on each call or meeting activity. After it runs: `Found <P> suggestion(s).` (`Found 0
  suggestions.` when none). A pending `new_commitment` suggestion shows at the top of Commitments:

  ```
  Argus found a commitment in the <call|meeting> of <occurred_at date>
  <text>
  Proof: <proof_statement>                  (line left out when null)
  "<quote>"
  Due date [YYYY-MM-DD input, prefilled from target_date]
  [Add commitment]  [Reject]
  ```

  **Add commitment** is disabled while the due date is empty; when the note stated none, the input is empty with the
  hint `Not stated in the note`.

## Flags and the ballot banner (PR 3)

```python
class WatchFlag(BaseModel):              # arp/schemas/engagement.py
    item_kind: Literal["commitment", "objective"]
    item_id: str
    engagement_id: str
    kind: Literal["overdue", "broken"]
    text: str                            # commitment text or objective description
    target_date: str | None              # YYYY-MM-DD
    since: str | None                    # YYYY-MM-DD, see below
    message: str

def watch_flags(store: EngagementStore, company_id: str, today: date | None = None) -> list[WatchFlag]: ...
def watch_flags_by_company(records: list[EngagementRecord], today: date | None = None) -> dict[str, list[WatchFlag]]: ...
# arp/stewardship/tracking.py; today defaults to the UTC date. by_company keys only companies with a flag.
```

`watch_flags(store, c)` equals `watch_flags_by_company([store.get(c)]).get(c, [])`; the bulk form lets a screen over
2,500 companies read the store once. Only engagements whose status is `open` or `stalled` count.

| Item | `overdue` when | `broken` when | `since` | `message` |
|---|---|---|---|---|
| Commitment | status `open`, `target_date` before today | status `missed` | overdue: `target_date`; broken: `validated_at` date, else `target_date`, else `made_at` date | `Commitment overdue: "<text>" was due <target_date>.` / `Commitment broken: "<text>" was marked not met on <since>.` |
| Objective | status `initiated` or `in_progress`, `target_date` before today | `result` `not_achieved` or `deterioration` | overdue: `target_date`; broken: `closed_at` date, else `target_date`, else null | `Objective overdue: "<text>" was due <target_date>.` / `Objective failed: "<text>" was closed as <not achieved \| deterioration> on <since>.` (` on <since>` left out when null) |

A due date equal to today is not overdue. A `target_date` that is not `YYYY-MM-DD` (intake stores it as free text)
counts as no date: no overdue flag, and it sorts as null. No record or no flags → `[]`. Order: `broken` before `overdue`; within
each, `target_date` ascending (null last), then commitments before objectives, then `item_id`.

**Ballot.** `CompanyBallot` (`arp/schemas/voting.py`) gains `watch_flags: list[WatchFlag] = []`, filled when
`GET /api/voting/runs/{run_id}/ballots` is read (not when the run ran), so a date that passes after the run still
shows. `BallotReview.tsx` shows each flag's `message` as a `banner banner-warning` on every ballot item of that
company, above the existing engagement-alignment banner. `engagement_alignment_flag`, its note and the co-sign rule
in `ballot_casting.py` stay as they are.

## The watch list in the dossier (PR 3)

```python
class WatchListEntry(BaseModel):         # arp/schemas/engagement.py
    item_kind: Literal["objective", "commitment", "topic"]
    item_id: str
    text: str
    proof_statement: str | None
    target_date: str | None
    status: str                          # the item's own status
    flag: Literal["overdue", "broken"] | None
    evidence: list[str]                  # confirmed evidence suggestions, oldest first, as the UI words them

def watch_list(store: EngagementStore, company_id: str, issue_id: str, today: date | None = None) -> list[WatchListEntry]:
    # arp/stewardship/tracking.py
```

Entries: the engagement's watch items, plus its commitments and objectives that carry a `broken` flag. Order:
flagged entries first in `watch_flags` order, then the rest by `target_date` ascending (null last), then objectives,
commitments, topics, then `item_id`. Each `evidence` line is `Evidence: <evidence text> (confirmed by <user>)` or
`Evidence against: <evidence text> (confirmed by <user>)`. On the file store there are no topics or evidence, so
entries come from objectives and commitments only.

`ResearchDossier` gains `watch_list: list[WatchListEntry] = []`. `POST /api/engagement/records/{company_id}/issues/
{issue_id}/dossier` fills it with code after the model call; the model never writes it. `_dossier_context`
(`arp/engagement/drafting_agent.py`) adds a `Watch list:` block, one line per entry, so talking points and the
outreach letter receive it.

In the panel, under the drafted dossier: heading **Watch list**, one row per entry: `Objective: <text>`,
`Commitment: <text>` or `Watch topic: <text>`, then `due <date>` when set, a badge `overdue` or `broken` when
flagged, `Proof: <proof_statement>` when set, and each evidence line. With no entries: `No open objectives,
commitments or watch topics.`

## Left to the builder

- Prompt wording, and how a long document is narrowed for the check. The golden rows judge the result.
- Index choices beyond the unique keys above.
- PR split, in this order; each PR leaves the app working and names its rows in a `Rows:` line:
  1. Columns, tables, schema fields, the watch-item, topic, objective-result and suggestion list/confirm/reject API,
     the generated contract, and the proof-statement, watch-topic and record-result UI.
     Rows AC-1 to AC-19, AC-47, AC-48, AC-74, AC-75, AC-80, AC-96 to AC-103.
  2. The check (event hook and button), find-commitments, the golden set and command, and the suggestion UI.
     Rows AC-20 to AC-46, AC-49 to AC-73, AC-76 to AC-79, AC-81, AC-82.
  3. `watch_flags`, `watch_flags_by_company`, `CompanyBallot.watch_flags`, the banner and the dossier watch list.
     Rows AC-83 to AC-95, AC-104 to AC-110 (the last PR drops the `Rows:` line).

## Golden set (PR 2)

`backend/tests/golden/watch_check/`: `cases.json` and `documents/`. At least 24 `check` cases (a document, one watch
item with text and proof statement, the label `found`, `against` or `silent`), at least 6 per label and at least 6
objectives among them, from real public reports; and at least 10 `find` cases (a note, the labelled commitments each
as a key phrase). Command:

`arp stewardship watch-golden --kind check|find --cases <file> --documents-dir <dir> --min-precision <x> --min-coverage <y>`

prints one line `precision <p>, coverage <c>` and exits 1 below either threshold.

- `check`: precision = stored suggestions whose verdict equals the label ÷ stored suggestions (a suggestion on a
  `silent` case is wrong); coverage = `found`/`against` cases with a correct suggestion ÷ `found`/`against` cases.
  With no suggestions at all, precision is 0.
- `find`: a suggestion is correct when its quote contains a labelled key phrase (case-insensitive); precision =
  correct ÷ suggestions; coverage = key phrases matched ÷ key phrases.

## Acceptance

**Holdout and evaluator setup.** Rows run on the e2e stack (`ARP_ENGAGEMENT_STORE=postgres`), started with
`ARP_STANDINS_DIR=<dir>`. They drive the app through its API and pages only:

- Each test uses a new `company_id`, so uploaded documents from other tests never count.
- A company: `POST /api/engagement/records` first. An engagement with no objectives or activities:
  `POST /api/engagement/records/{company_id}/issues?name=…` (on `main`; returns `issue_id`). An engagement with an
  objective or activity: `POST /api/stewardship/intake/engagements` (`stewardship-data-foundation` PR 2) with an
  `engagements` row (`external_id`, `company_id`, `theme`), `objectives` rows (`external_id`,
  `engagement_external_id`, `description`, `objective_type`, `status`, `target_date`) and `activities` rows
  (`external_id`, `engagement_external_id`, `occurred_at`, `activity_type`, `summary`). Every `external_id` starts
  with the test's `company_id`. Intake returns no ids; `GET /api/engagement/records/{company_id}` gives them
  (`issues[].issue_id`, `issues[].objectives[].objective_id`, `issues[].correspondence[].entry_id`).
- Commitments: `POST /api/stewardship/tracking/commitments`; their status: `POST /api/stewardship/tracking/commitments/{id}`;
  closing an engagement: `POST /api/stewardship/tracking/close`; topics and objective results: the routes under "API".
- "A document for the company": `AR2026.txt` uploaded with `POST /api/documents/upload` (`doc_type` `other`),
  containing `The board formed a climate committee in March 2026.` (below: **Q**). Its `doc_title` is `AR2026.txt`.
- Model answers: the test writes `<dir>/model/WatchCheckDraft.json` or `CommitmentFindDraft.json` as
  `{"output": …}`. "The stand-in says found on X" means one result for item X, `verdict` `found`, quote Q.
- "A pending found suggestion on X" = the stand-in says found on X and `POST .../watch-items/{kind}/{X}/check` ran.
- "No suggestions" = `GET /api/stewardship/evidence-suggestions?company_id=…&status=` `pending`, `confirmed` and
  `rejected` each return `{"suggestions": []}`.
- "Today" is the UTC date the test runs. "The user" is `dev`.

`unit` rows use the implementer's tests with the same stand-ins and may write tables directly.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A database where `main`'s `arp db init-postgres` has run | `arp db init-postgres` runs twice | Both runs exit 0 | unit |
| AC-2 | AC-1 done | The schema is read | `stw_objectives` and `stw_commitments` have a column `proof_statement`; tables `stw_watch_topics` and `stw_evidence_suggestions` exist | unit |
| AC-3 | AC-1 done once | `arp db init-postgres` runs again | Every `stw_*` table's column list and row count are the same as before the run | unit |
| AC-4 | A company with one engagement | `POST /api/stewardship/tracking/commitments` with `text`, `target_date` `2027-03-31`, `proof_statement` `The 2026 annual report names a board climate committee` | Status 200; `GET /api/engagement/records/{company_id}` shows that commitment with that `proof_statement` | holdout |
| AC-5 | As AC-4 | The same POST without `proof_statement` | Status 200; the commitment's `proof_statement` is null | holdout |
| AC-6 | An engagement with an objective O (status `in_progress`) | `POST /api/stewardship/watch-items/objective/{O}/proof-statement` with `proof_statement` `The 2026 annual report names a board climate committee` | Status 200; the record shows O with that `proof_statement` | holdout |
| AC-7 | As AC-6 | The same with `proof_statement` `"  "` | Status 422, detail `A proof statement cannot be blank.` | holdout |
| AC-8 | A company with one engagement | `POST /api/stewardship/watch-topics` with `question` `Has the company named a board climate committee?`, `target_date` `2027-06-30` | Status 200; body has a `topic_id` and `status` `open`; `GET /api/stewardship/watch-topics?company_id=…` lists it | holdout |
| AC-9 | As AC-8 | The same with `question` `""` | Status 422, detail `A question is required.` | holdout |
| AC-10 | AC-8 done | `POST /api/stewardship/watch-topics/{topic_id}/close` | Status 200; the topic's `status` is `closed`, `closed_by` `dev` | holdout |
| AC-11 | `engagement_store = file` | `GET /api/stewardship/watch-topics?company_id=x` | Status 409, detail `Watch items need the Postgres engagement store.` | unit |
| AC-12 | `engagement_store = file`, an open commitment | `POST /api/stewardship/watch-items/commitment/{id}/check` | Status 409, detail `Watch items need the Postgres engagement store.` | unit |
| AC-13 | A file `EngagementStore` | A commitment with a `proof_statement` is added and read back | Same `proof_statement` | unit |
| AC-14 | A `viewer` user (non-dev auth) | `POST /api/stewardship/evidence-suggestions/{id}/confirm` | Status 403 | unit |
| AC-15 | — | `POST /api/stewardship/evidence-suggestions/evs_unknown/confirm` | Status 404, detail `Unknown suggestion.` | holdout |
| AC-16 | An objective O, status `in_progress` | `POST /api/stewardship/objectives/{O}/result` with `result` `achieved`, `influence_level` `"3"`, `outcome` `Committee named in the 2026 annual report` | Status 200; the record shows O with `status` `closed`, `result` `achieved`, `influence_level` `"3"`, that `outcome`, and `closed_at` starting with today | holdout |
| AC-17 | As AC-16 | The same without `influence_level` | Status 422, detail `An influence level is required to close an objective.` | holdout |
| AC-18 | As AC-16 | `result` `abandoned`, no `influence_level`, an `outcome` | Status 200; O's `status` is `abandoned` | holdout |
| AC-19 | As AC-16 | `outcome` `"  "` | Status 422, detail `An outcome is required.` | holdout |
| AC-20 | An open commitment C; a document for the company; the stand-in says found on C | `POST /api/stewardship/watch-items/commitment/{C}/check` with the `company_id` | Status 200, body `{"documents": 1, "suggestions": 1, "unclear": 0, "skipped": 0}` | holdout |
| AC-21 | AC-20 done | `GET .../evidence-suggestions?company_id=…` | One suggestion: `kind` `evidence`, `item_kind` `commitment`, `item_id` C, `verdict` `found`, `doc_title` `AR2026.txt`, `quote` Q | holdout |
| AC-22 | As AC-20 but the stand-in quote is `The board dissolved its climate committee.` | Check | Body `{"documents": 1, "suggestions": 0, "unclear": 1, "skipped": 0}`; no suggestions | holdout |
| AC-23 | As AC-20 but the stand-in returns `unclear` with an empty quote | Check | Body `{"documents": 1, "suggestions": 0, "unclear": 1, "skipped": 0}`; no suggestions | holdout |
| AC-24 | AC-20 done | Check again | Body `{"documents": 1, "suggestions": 0, "unclear": 0, "skipped": 1}`; the pending list still holds 1 suggestion | holdout |
| AC-25 | AC-20 done, then that suggestion rejected | Check again | Body `{"documents": 1, "suggestions": 0, "unclear": 0, "skipped": 1}` | holdout |
| AC-26 | AC-20 done | `GET /api/engagement/records/{company_id}` | C's `status` is `open` and `validated_by` is null | holdout |
| AC-27 | A commitment set to `verified` (with evidence) | Check it | Status 409, detail `Only open items can be checked.` | holdout |
| AC-28 | An open commitment, no documents for the company | Check | Status 200, body `{"documents": 0, "suggestions": 0, "unclear": 0, "skipped": 0}` | holdout |
| AC-29 | As AC-20 but `WatchCheckDraft.json` is not valid JSON | Check | Status 502, detail `Argus could not check the documents.`; no suggestions | holdout |
| AC-30 | An objective O (status `in_progress`); a document; the stand-in says found on O | `POST .../watch-items/objective/{O}/check` | Body `{"documents": 1, "suggestions": 1, "unclear": 0, "skipped": 0}`; the pending list holds one with `item_kind` `objective`, `item_id` O | holdout |
| AC-31 | An open topic T; a document; the stand-in says `against` on T with quote Q | `POST .../watch-items/topic/{T}/check` | Body has `"suggestions": 1`; the pending list holds one with `item_kind` `topic`, `verdict` `against` | holdout |
| AC-32 | An objective closed through `POST .../objectives/{O}/result` | Check it | Status 409, detail `Only open items can be checked.` | holdout |
| AC-33 | A pending found suggestion on commitment C, whose engagement has a second open commitment | `POST .../evidence-suggestions/{id}/confirm` | Status 200; C's `status` is `verified`, `validated_by` `dev`, `evidence` `AR2026.txt: "The board formed a climate committee in March 2026."` | holdout |
| AC-34 | As AC-33 but the stand-in verdict is `against` | Confirm | C's `status` is `missed`, `evidence` `AR2026.txt: "The board formed a climate committee in March 2026."` | holdout |
| AC-35 | AC-33 done | `GET …&status=confirmed` | One suggestion, `status` `confirmed`, `decided_by` `dev`, `decided_at` not null | holdout |
| AC-36 | A pending found suggestion on C, C the only commitment of its engagement | Confirm | The record shows that engagement's `status` `resolved` (as Verify does today) | holdout |
| AC-37 | A pending found suggestion on objective O | Confirm | Status 200; the record shows O with the same `status`, `result` and `outcome` as before | holdout |
| AC-38 | AC-37 done | `GET …&status=confirmed` | One suggestion with `item_kind` `objective`, `item_id` O | holdout |
| AC-39 | A pending found suggestion on topic T | Confirm | `GET .../watch-topics` shows T with `status` `open` | holdout |
| AC-40 | A pending found suggestion on C | `POST .../evidence-suggestions/{id}/reject` with `{"reason": "Quote is about the 2024 target"}` | Status 200; `GET …&status=rejected` returns it with that `reject_reason` | holdout |
| AC-41 | AC-40 done | `GET /api/engagement/records/{company_id}` | C's `status` is `open` | holdout |
| AC-42 | A pending found suggestion on C | Reject with `{"reason": "  "}` | Status 422, detail `A reason is required to reject a suggestion.` | holdout |
| AC-43 | AC-40 done | Confirm it | Status 409, detail `Suggestion already rejected.` | holdout |
| AC-44 | AC-33 done | Reject it with a reason | Status 409, detail `Suggestion already confirmed.` | holdout |
| AC-45 | A pending found suggestion on C, then C set to `verified` through `POST /api/stewardship/tracking/commitments/{C}` with evidence | Confirm | Status 409, detail `This item is no longer open.`; the pending list still holds it | holdout |
| AC-46 | AC-40 done | `GET .../evidence-suggestions?company_id=…` (no status) | `{"suggestions": []}` | holdout |
| AC-47 | Two pending suggestions; one confirmed, one rejected | `stw_events` is read | One `evidence_suggestion_confirmed` and one `evidence_suggestion_rejected` row, each with its `suggestion_id` in `detail` | unit |
| AC-48 | A pending `against` suggestion on a commitment, `doc_title` `AR 2026.pdf`, `page` 4 | Confirm | The commitment's `evidence` is `AR 2026.pdf, page 4: "<quote>"` | unit |
| AC-49 | A company with an open commitment and an open objective on an open engagement, a registered document; `watch_check_on_new_documents` true; the stand-in says found on both | `ChangeDetector.diff_and_record` gets that document (same `local_path`) as new | Two pending suggestions with that document's `doc_id`, one per item, from one `WatchCheckDraft` call | unit |
| AC-50 | As AC-49, the document already in the manifest with a different `sha256` | Same (an `updated_document` event) | Two pending suggestions | unit |
| AC-51 | As AC-49 with `watch_check_on_new_documents` false and event refresh off | Same | No suggestion; `calls.jsonl` has no `WatchCheckDraft` call | unit |
| AC-52 | As AC-49 with a stand-in that is not valid JSON | Same | `diff_and_record` returns its one `new_document` event; no suggestion | unit |
| AC-53 | As AC-52 with event refresh on (`event_refresh_enabled` true, one schema id) | Same | `refresh_on_events` still starts its extraction run | unit |
| AC-54 | As AC-49 but no registered document has that `local_path` | Same | No suggestion and no `WatchCheckDraft` call | unit |
| AC-55 | A `meeting` activity (`occurred_at` 2026-10-01) whose summary contains `The CFO committed to publish a transition plan by 31 March 2027.`; the find stand-in returns one commitment, text `Publish a transition plan`, that sentence as quote, `target_date` `2027-03-31` | `POST /api/stewardship/activities/{id}/find-commitments` | Status 200, body `{"suggestions": 1, "ungrounded": 0, "skipped": 0}` | holdout |
| AC-56 | AC-55 done | `GET .../evidence-suggestions?company_id=…` | One suggestion: `kind` `new_commitment`, `text` `Publish a transition plan`, `target_date` `2027-03-31`, that quote | holdout |
| AC-57 | As AC-55 but the stand-in quote is `The CEO promised a new climate policy.` | Find | Body `{"suggestions": 0, "ungrounded": 1, "skipped": 0}` | holdout |
| AC-58 | An `email` activity | Find | Status 409, detail `Commitments are only looked for in call and meeting notes.` | holdout |
| AC-59 | AC-55 done | Find again | Body `{"suggestions": 0, "ungrounded": 0, "skipped": 1}` | holdout |
| AC-60 | AC-55 done | `GET /api/engagement/records/{company_id}` | The engagement's commitment count is the same as before the find | holdout |
| AC-61 | AC-55 with the stand-in `target_date` null | Confirm with `{"target_date": "2027-03-31"}` | Status 200; the engagement has a new commitment, text `Publish a transition plan`, `target_date` `2027-03-31`, `made_at` starting `2026-10-01`, `recorded_by` `dev` | holdout |
| AC-62 | AC-61 done | `GET …&status=confirmed` | The suggestion's `created_commitment_id` is the new commitment's `commitment_id` | holdout |
| AC-63 | As AC-61 | Confirm with `{}` | Status 422, detail `A due date is required to add a commitment.`; the commitment count is unchanged | holdout |
| AC-64 | As AC-61 | Confirm with `{"target_date": "31.03.2027"}` | Status 422, detail `target_date must be an ISO date`; the pending list still holds it | holdout |
| AC-65 | AC-20 done | A user opens the company's issue on `#/engagement` | Under C: `Argus suggests: evidence found`, then `"The board formed a climate committee in March 2026."`, then `AR2026.txt`, then buttons `Confirm` and `Reject` | evaluator |
| AC-66 | As AC-65 with the stand-in verdict `against` | The user opens the issue | Under C: `Argus suggests: evidence against` | evaluator |
| AC-67 | AC-65 | The user clicks `Confirm` | The suggestion is gone; C shows the badge `verified`, `verified by dev` and `evidence: AR2026.txt: "The board formed a climate committee in March 2026."` | evaluator |
| AC-68 | AC-65 | The user clicks `Reject` | An input labelled `Why reject? (required)` and a `Confirm rejection` button, disabled while the input is empty | evaluator |
| AC-69 | AC-68, a reason typed | The user clicks `Confirm rejection` | The suggestion is gone; C still shows the badge `open` | evaluator |
| AC-70 | AC-20's Given | The user clicks `Check against documents` on C | The line `Checked 1 document: 1 new suggestion, 0 unclear.` | evaluator |
| AC-71 | An open commitment, no documents for the company | The user clicks `Check against documents` | The line `No documents on file for this company.` | evaluator |
| AC-72 | AC-30 done | The user clicks `Confirm` under O | The Record result form is open with `Result` `achieved` and `Outcome` `AR2026.txt: "The board formed a climate committee in March 2026."` | evaluator |
| AC-73 | AC-72 | The user closes the form without saving | O shows `Evidence: AR2026.txt: "The board formed a climate committee in March 2026." (confirmed by dev)` and its status is unchanged | evaluator |
| AC-74 | An objective with status `in_progress` | The user clicks `Record result`, picks `achieved` and influence level `3` (the value `"3"`), types an outcome, clicks `Save result` | The objective shows status `closed` and result `achieved` | evaluator |
| AC-75 | An engagement with no topics | The user clicks `Add watch topic`, types the question `Has the company named a board climate committee?`, the due date `2027-06-30`, and clicks `Add topic` | The Watch topics section lists that question with `due 2027-06-30` and the badge `open` | evaluator |
| AC-76 | AC-55's Given | The user clicks `Find commitments` on that activity | The line `Found 1 suggestion.` | evaluator |
| AC-77 | AC-55 done with the stand-in `target_date` null | The user opens the issue | `Argus found a commitment in the meeting of 2026-10-01`, the text, the quote, and an empty `Due date` input with the hint `Not stated in the note` | evaluator |
| AC-78 | AC-77 | The user looks at `Add commitment`, then enters `2027-03-31` | It is disabled while the date is empty and enabled after | evaluator |
| AC-79 | AC-78 | The user clicks `Add commitment` | The suggestion is gone; the Commitments list has `Publish a transition plan` with `target 2027-03-31` | evaluator |
| AC-80 | An objective and a commitment, each with proof statement `The 2026 annual report names a board climate committee` | The user opens the issue | Under each: `Proof: The 2026 annual report names a board climate committee` | evaluator |
| AC-81 | `ARP_ANTHROPIC_API_KEY` set | `arp stewardship watch-golden --kind check --cases tests/golden/watch_check/cases.json --documents-dir tests/golden/watch_check/documents --min-precision 0.9 --min-coverage 0.6` | Exit 0 | golden |
| AC-82 | `ARP_ANTHROPIC_API_KEY` set | The same with `--kind find --min-precision 0.8 --min-coverage 0.7` | Exit 0 | golden |
| AC-83 | An open engagement with an `open` commitment, `target_date` = yesterday, text `Publish a transition plan` | `watch_flags(store, company_id)` | One flag: `item_kind` `commitment`, `kind` `overdue`, `since` = yesterday, `message` `Commitment overdue: "Publish a transition plan" was due <yesterday>.` | unit |
| AC-84 | An open engagement with a `missed` commitment, text `Name a climate committee`, `validated_at` 2026-10-02 | `watch_flags` | One flag: `kind` `broken`, `since` `2026-10-02`, `message` `Commitment broken: "Name a climate committee" was marked not met on 2026-10-02.` | unit |
| AC-85 | An open engagement with an `in_progress` objective, `target_date` = yesterday, description `Set a 2030 science-based target` | `watch_flags` | One flag: `item_kind` `objective`, `kind` `overdue`, `message` `Objective overdue: "Set a 2030 science-based target" was due <yesterday>.` | unit |
| AC-86 | An open engagement with a `closed` objective, `result` `not_achieved`, `closed_at` 2026-10-02, description `Set a 2030 science-based target` | `watch_flags` | One flag: `kind` `broken`, `since` `2026-10-02`, `message` `Objective failed: "Set a 2030 science-based target" was closed as not achieved on 2026-10-02.` | unit |
| AC-87 | One company with: a `verified` commitment; an `achieved` objective; an `abandoned` objective; an `open` commitment and an `in_progress` objective without `target_date`; one of each due today; one of each due tomorrow; an overdue commitment on a `closed` engagement; an open topic due yesterday; an `in_progress` objective with `target_date` `31/12/2025` | `watch_flags` | `[]` | unit |
| AC-88 | Overdue commitments due 2026-09-01 and 2026-08-01, an overdue objective due 2026-08-01, a broken commitment | `watch_flags` | Four flags in the order: broken commitment, commitment due 2026-08-01, objective due 2026-08-01, commitment due 2026-09-01 | unit |
| AC-89 | A company with no engagement record | `watch_flags` | `[]` | unit |
| AC-90 | Three companies: AC-83's, AC-86's and one without flags | `watch_flags_by_company(store.list_all())` | A dict with exactly the first two `company_id`s as keys, each value equal to `watch_flags(store, company_id)` | unit |
| AC-91 | AC-83's data on a file `EngagementStore` | `watch_flags` | The same flag as AC-83 | unit |
| AC-92 | A `proxy_voting` run's ballots seeded through `RunStore`, one ballot for AC-83's company | `GET /api/voting/runs/{run_id}/ballots` | That ballot's `watch_flags` equals `watch_flags(store, company_id)` as JSON | unit |
| AC-93 | As AC-92, a second ballot for a company without flags | `GET .../ballots` | That ballot's `watch_flags` is `[]` | unit |
| AC-94 | The ballots response for a run stubbed (as the existing e2e voting tests do with `page.route`): company A with two items and one `watch_flags` entry (`item_kind` `objective`, `kind` `overdue`, `target_date` and `since` `2026-11-12`, `message` `Objective overdue: "Set a 2030 science-based target" was due 2026-11-12.`); company B with one item and `[]` | A user opens the run's ballot review | Both of A's items show a warning banner `Objective overdue: "Set a 2030 science-based target" was due 2026-11-12.`; B's item shows none | evaluator |
| AC-95 | A `VoteRecord` approved without co-sign, `engagement_alignment_flag` false, for a company with an overdue commitment | `cast_vote(platform, record)` | The returned record's `cast_confirmation.status` is `confirmed` | unit |
| AC-96 | An open commitment with a `target_date` after today | `POST /api/stewardship/tracking/commitments/{id}` with `status` `verified` and no `evidence` | Status 422, detail `Evidence is required to verify a commitment.` (unchanged) | holdout |
| AC-97 | — | `GET /api/stewardship/intake/template?kind=engagements` is opened in openpyxl | The `objectives` header row equals `stewardship-data-foundation`'s "Engagement batch" objectives list, in order (no `proof_statement` column) | holdout |
| AC-98 | A company with one engagement | `POST /api/stewardship/watch-topics` with a `question` and `proof_statement` `The 2026 annual report names a board climate committee` | `GET /api/stewardship/watch-topics?company_id=…` shows the topic with that `proof_statement` | holdout |
| AC-99 | An open topic T without a proof statement | `POST /api/stewardship/watch-items/topic/{T}/proof-statement` with a `proof_statement` | Status 200; `GET .../watch-topics` shows T with it | holdout |
| AC-100 | An objective | A proof statement is set, then a result recorded | `stw_events` gained exactly two rows, `proof_statement_set` then `objective_result_recorded`, and no `objective_updated` | unit |
| AC-101 | — | `POST /api/stewardship/objectives/obj_unknown/result` with a valid body and a real `company_id` and `issue_id` | Status 404, detail `Unknown objective.` | holdout |
| AC-102 | AC-10 done | Close the topic again | Status 409, detail `This topic is already closed.` | holdout |
| AC-103 | An engagement closed through `POST /api/stewardship/tracking/close` | `POST /api/stewardship/watch-topics` on it | Status 409, detail `Watch topics need an open engagement.` | holdout |
| AC-104 | An engagement with an `in_progress` objective (`target_date` = yesterday, description `Set a 2030 science-based target`) and an open topic (`question` `Has the company named a board climate committee?`, no due date); a document for the company; a stand-in `ResearchDossierDraft` with no citations | `POST /api/engagement/records/{company_id}/issues/{issue_id}/dossier` | The response's `dossier.watch_list` has 2 entries: first `item_kind` `objective`, `flag` `overdue`; then `item_kind` `topic`, `flag` null | holdout |
| AC-105 | AC-30 done, then the suggestion confirmed; the AC-104 dossier stand-in | Draft the dossier | O's entry has `evidence` `["Evidence: AR2026.txt: \"The board formed a climate committee in March 2026.\" (confirmed by dev)"]` | holdout |
| AC-106 | An engagement whose only commitment is `missed` and whose only objective is `achieved`; the AC-104 dossier stand-in | Draft the dossier | `watch_list` has 1 entry: the commitment, `flag` `broken` | holdout |
| AC-107 | An engagement with no objectives, commitments or topics; the AC-104 dossier stand-in | Draft the dossier | `watch_list` is `[]` | holdout |
| AC-108 | AC-104's dossier | `POST .../talking-points` with it | The `MeetingTalkingPoints` prompt in `calls.jsonl` contains `Set a 2030 science-based target` and `Has the company named a board climate committee?` | unit |
| AC-109 | AC-104's Given | The user clicks `Draft dossier` | Under the dossier: heading `Watch list`, then `Objective: Set a 2030 science-based target` with `due <yesterday>` and badge `overdue`, then `Watch topic: Has the company named a board climate committee?` | evaluator |
| AC-110 | AC-107's Given | The user clicks `Draft dossier` | Under the dossier: `No open objectives, commitments or watch topics.` | evaluator |

Must not change: the co-sign rule for `engagement_alignment_flag` items and the alignment check (AC-95 plus the
existing voting tests, unchanged); manual Verify and status updates (AC-96); adding a commitment without a proof
statement (AC-5); the intake template (AC-97); `init-postgres` idempotence (AC-3); event refresh on new documents
(AC-53); statuses change only through a person (AC-26, AC-37, AC-39, AC-41, AC-60).
