# Stewardship commitment loop: from a company's commitment to proof

Slug: `stewardship-commitment-loop`. Risk: PR 1 `risk:high` (a new table and a new column: the steward table rates
database schema changes high); PRs 2 and 3 `risk:normal`. Size M, 3 PRs.

Status: **draft for the owner's approval.**

Owner decisions (13 Nov 2026, buttons in the owner's session):

- Close the loop from a commitment to proof, after reviewing a paper on AI-native investment stewardship.
  "Start building now".
- Intake scope: a checkable proof statement and target date per commitment; Argus suggests met or not met when a
  new document arrives; Argus suggests commitments from call and meeting notes; overdue and broken commitments show
  as a banner on Proxy Voting ballot items and through one read function, `commitment_flags`.
- Banner placement: <!-- Q1 --> every ballot item of the company.
- Co-sign: <!-- Q2 --> the banner is information only; it does not require a second sign-off.
- Unclear verdicts: <!-- Q3 --> never stored as a suggestion; the check reports only how many there were.

## Why

Commitments are logged today (`stw_commitments`, the Commitments list on `#/engagement`), but nothing checks them.
A person has to remember the target date, find the report that proves or disproves the commitment, and type the
evidence into the Verify box. Commitments made on a call never become commitments unless someone re-types them. When
the house then votes at that company's meeting, the ballot screen says nothing about a commitment the company broke.

This feature closes that loop: the commitment says what would count as proof, Argus reads each new report and
suggests "met" or "not met" with a quote it has to back up, a person decides, and the decision shows up where the
house votes. A model never changes a commitment's status. It only drafts the suggestion, and code checks the quote
before anyone sees it.

## Goals

1. A commitment can carry a **proof statement**: one sentence saying what evidence would show it was met
   ("The 2026 annual report names a board climate committee"). `target_date` already exists.
2. When a new or updated document for a company arrives, Argus checks every open commitment of that company against
   it and stores a **suggestion** (met or not met, with a quote re-found in the document) that a person confirms or
   rejects. The same check runs on demand per commitment.
3. From a call or meeting note (`stw_activities.summary`), Argus suggests new commitments, each with a quote from the
   note and a due date. A person adds or rejects each one.
4. An overdue or broken commitment shows as a banner on the company's Proxy Voting ballot items.
5. `arp.stewardship.tracking.commitment_flags(...)` returns the same flags for other features (first user:
   `stewardship-priority-worklist`).

## Non-goals (later features)

- The company timeline and the scheduled prep pack.
- Closing an engagement, changing an escalation stage or raising a monitoring trigger because of a pending
  suggestion. Those keep reading the commitment status a person set. (Confirming `met` resolves an engagement
  exactly as Verify does today; see "Confirm and reject".)
- Looking for commitments in letters, emails or documents; only call and meeting notes.
- Running the find-commitments step automatically on intake (400 demo companies × activities would be thousands of
  model calls). It runs when a person presses the button.
- A commitments sheet in the Excel intake.
- Wiring the new golden set into the CI golden workflow (a `.github/workflows` change is its own `risk:high` PR).
  The PR 2 author runs it and pastes the output into the PR.

## Anti-goals

- **The model sets a status.** Only confirm sets `verified` or `missed` (AC-22, AC-32).
- **A suggestion without proof.** A met or not-met verdict whose quote is not re-found in the document is counted
  as unclear and never stored (AC-18). An unclear verdict is never stored (AC-19).
- **Losing a rejection.** Rejected suggestions are kept with who, when and why, and are never deleted (AC-9, AC-14).
- **Asking twice.** A document already checked for a commitment never produces a second suggestion for it, whether
  the first was confirmed, rejected or is still pending (AC-20, AC-21).
- **Changing how votes are cast.** The commitment banner adds no co-sign rule (AC-48).

## Constraints

- Postgres only for suggestions. `stw_commitments`, `PostgresEngagementStore` and `arp db init-postgres` are on
  `main` already (`stewardship-data-foundation` PR 1, #433). This feature needs nothing from that spec's PR 2 (#440,
  intake) or PR 3. It starts after #440 merges anyway, as the intake set, so the two PRs don't edit
  `postgres_engagement_store.py` and `stewardship.py` at the same time. With `engagement_store = file` the suggestion
  endpoints answer 409 (AC-5). `commitment_flags` reads through the `EngagementStore` interface, so it works on both
  stores (AC-53).
- Schema changes go through `ensure_schema` in `arp/storage/postgres_schema.py`: one new table, one additive column,
  nothing dropped, idempotent.
- No change under `arp/extraction`, `arp/llm`, `arp/golden_set` or `arp/grounding.py`. The check calls the existing
  LLM client (`build_llm_client(settings).complete_structured`) and the existing `arp.grounding.ground_citations`
  (a `Citation` per quote, so `grounded` and `page` come from code, never from the model).
- Request and response models change: `scripts/export_openapi.py` and `npm run gen:api` run, both generated files are
  committed, and new `request<T>()` calls get a line in `frontend/src/api/contract.ts`.
- Writes need role `analyst` or above, reads `viewer`, as for every `/api/stewardship` route.
- No existing test is changed.
- Model calls in tests go through the stand-ins (`ARP_STANDINS_DIR/model/<OutputModel>.json`), so every row except
  the golden rows is deterministic.

## Approaches considered

1. **Suggestions in their own table, confirmed through the existing status update (picked).** A suggestion is a row
   in `stw_commitment_proposals`; confirming it calls the same store method a person's Verify click calls today.
   The audit trail is the table itself plus `stw_events`. The commitment row only changes when a person confirms.
2. A `proposed_status` column on `stw_commitments`. Smaller, but one commitment can have several suggestions (two
   reports, a rejection then a new report), and a rejected one would be overwritten.
3. Suggestions as monitoring triggers. Reuses the triggers screen, but triggers are recomputed on every read and
   are never stored, so there is nothing to confirm, reject or keep for audit.

What counts as "a new report or filing arrives": `monitoring.py` only evaluates rules on a data sample and never
sees documents, so it is not the trigger. The existing hook is `ChangeDetector.diff_and_record`
(`arp/discovery/change_detector.py`), which emits `new_document` and `updated_document` events for discovery runs
and the extraction pre-step, and already drives event refresh (E20) through `on_events`. Plain uploads
(`POST /api/documents/upload`, Argus uploads) emit no event, so each open commitment also gets a
**Check against documents** button.

## Data model

`stw_commitments` gains `proof_statement text null`. `Commitment` (`arp/schemas/engagement.py`) gains
`proof_statement: str | None = None`, so the Postgres store can return it; the file store carries it unchanged
(AC-52).

New table `stw_commitment_proposals`, one row per suggestion. Column defaults: `source` `app`, `external_id`
null, `status` `pending`, `created_at` `now()`. Every other column is nullable unless marked.

| Column | Type | Meaning |
|---|---|---|
| `proposal_id` | text pk | `cpr_…` |
| `source`, `external_id` | text | as every `stw_*` table |
| `kind` | text not null | `verdict` (met / not met on an existing commitment) or `new_commitment` (from a note) |
| `company_id` | text not null, fk `stw_companies` | |
| `engagement_id` | text not null, fk `stw_engagements` | |
| `commitment_id` | text fk `stw_commitments`, null | set for `verdict` |
| `activity_id` | text fk `stw_activities`, null | set for `new_commitment` |
| `verdict` | text null | `met` or `not_met` for `verdict`; null for `new_commitment` |
| `text` | text null | `new_commitment`: the commitment as Argus words it |
| `proof_statement` | text null | `new_commitment`: suggested proof statement, may be null |
| `target_date` | text null | `new_commitment`: `YYYY-MM-DD` when the note states one, else null |
| `doc_id`, `doc_type`, `doc_title` | text null | `verdict`: the document checked |
| `quote` | text not null | the passage, re-found in the document or note before the row is written |
| `page` | int null | from grounding, never from the model |
| `reason` | text null | the model's one-line reason, shown under the quote |
| `status` | text | `pending`, `confirmed`, `rejected` |
| `created_at` | timestamptz | |
| `decided_by`, `decided_at`, `reject_reason` | | set on confirm or reject |
| `created_commitment_id` | text null | `new_commitment` once confirmed |

Unique index on (`commitment_id`, `doc_id`) where `kind = 'verdict'`, and on (`activity_id`, `quote`) where
`kind = 'new_commitment'`. These are the "asking twice" keys: a check that would write an existing key writes nothing
and counts the commitment as `skipped`.

`stw_events` gets one row per write: `commitment_proposed`, `commitment_proposal_confirmed`,
`commitment_proposal_rejected` (`detail` = `proposal_id`, `commitment_id` or `activity_id`, `verdict`).

## The check (PR 2)

**Model output** (stand-in file names follow the class names):

```python
class CommitmentVerdictDraft(BaseModel):
    commitment_id: str
    verdict: Literal["met", "not_met", "unclear"]
    quote: str = ""      # verbatim from the document; empty for unclear
    reason: str = ""     # one sentence

class CommitmentCheckDraft(BaseModel):
    results: list[CommitmentVerdictDraft]
```

The prompt gives the document text (how much of a long document, and whether through retrieval, is the builder's
call) and, per open commitment, its `commitment_id`, `text`, `proof_statement` and `target_date`. One model call per
document and company.

**Code, after the call**, per result:

1. A `commitment_id` that was not in the prompt is ignored.
2. `unclear`, or an empty quote → counted `unclear`, nothing stored.
3. `met`/`not_met` whose quote `is_grounded(quote, document.full_text)` is false → counted `unclear`, nothing stored.
4. Key (`commitment_id`, `doc_id`) already in `stw_commitment_proposals` → counted `skipped`, nothing stored.
5. Otherwise a `pending` `verdict` row is written, with `page` from the grounded `Citation`.

Grounding: each quote becomes a `Citation(doc_id, doc_type, quote)` and goes through `ground_citations` against the
document; `grounded` false means rule 3.

**Automatic run.** On every `new_document` or `updated_document` event from `ChangeDetector`, for a company that has
at least one `open` commitment on an `open` or `stalled` engagement, all those commitments are checked against the
event's document. The event carries a `DiscoveredDocument` (url, `local_path`, `sha256`), not the text, so the
document is read with the registry's `fetch_all` for the company and matched on `Path(local_path).resolve()`
equality (`sha256` is not compared: the event's is a file hash, the registry's a text hash). No match → that event
is skipped and logged; nothing is stored (AC-63).

Wiring: `refresh_hook` (`arp/discovery/refresh.py`) returns a hook whenever event refresh **or**
`commitment_check_on_new_documents` is on. The hook runs the commitment check first, then `refresh_on_events` when
refresh is on; a check failure is logged and does not stop the refresh. `arp/extraction/pre_steps.py` and
`arp/discovery/pipeline.py` stay unchanged. Setting `commitment_check_on_new_documents` (env `ARP_COMMITMENT_CHECK_ON_NEW_DOCUMENTS`, default
`true`) turns it off. It runs only when `engagement_store = postgres`. It runs whether or not event refresh is on,
and a failure is logged and never fails discovery, the same contract as `on_events` today. Event refresh still
runs on the same events when the check fails (AC-54).

**On demand.** `POST /api/stewardship/commitments/{commitment_id}/check`, body `{"company_id": "…"}`: checks that
one commitment against the company's 5 newest documents from the document registry (`build_registry(...).fetch_all`
with a `CompanyRef` built from the engagement record: `company_id` and `name` only, no `ticker`, `cik` or `lei`, so
only local and uploaded documents are read),
one model call per document. Sort key per document: `published_at` if set, else `fetched_at`, descending; ties by
`doc_id`. If any model call fails (error, timeout, output that doesn't parse), the request answers 502
`Argus could not check the documents.` and stores nothing from that request (AC-55). Response:
`{"documents": N, "proposals": P, "unclear": U, "skipped": S}`. 409 `Only open commitments can be checked.` when
the commitment's status is not `open`.

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
`activity_type` is `call` or `meeting` (or, when `activity_type` is null, whose `type` is `call` or `meeting`); any
other → 409 `Commitments are only looked for in call and meeting notes.` Code drops a found commitment whose quote
is not grounded in the activity's `summary` (counted `ungrounded`), and one whose (`activity_id`, `quote`) exists
(counted `skipped`). A `target_date` that is not a valid `YYYY-MM-DD` is stored as null. Response:
`{"proposals": P, "ungrounded": G, "skipped": S}`. No `stw_commitments` row is written until a person adds it.

## Confirm and reject (PR 1)

- `GET /api/stewardship/commitment-proposals?company_id=…&status=pending|confirmed|rejected` (`company_id`
  required, else 422; status default `pending`) → `{"proposals": [Proposal, …]}` newest first, each with every column
  above.
- Confirm or reject on an unknown `proposal_id` → 404 `Unknown suggestion.`
- "The user" below is the signed-in user's name (`dev` on the e2e stack, where dev auth signs in `dev_user`).
- `POST /api/stewardship/commitment-proposals/{proposal_id}/confirm`:
  - `verdict` + `met` → the commitment becomes `verified` through `log_commitment_verified`, so it does exactly what
    Verify does today: the milestone moves, and when every commitment of the engagement is verified the engagement
    becomes `resolved` (AC-57). A person confirmed it, so this is not the model closing an engagement; `validated_by` = the user, `evidence` = `<doc_title>, page <page>: "<quote>"` (`, page <page>` left
    out when `page` is null).
  - `verdict` + `not_met` → `update_commitment_status(..., missed, user, evidence)` with the same evidence text.
  - `new_commitment`, body `{"text"?, "proof_statement"?, "target_date"?}` (each overrides the suggestion) → a new
    commitment on the activity's engagement (`made_at` = the activity's `occurred_at`, `recorded_by` = the user),
    and `created_commitment_id` is set. Without a `target_date` in either the suggestion or the body → 422
    `A due date is required to add a commitment.`
  - The commitment is no longer `open` → 409 `Commitment is no longer open.`, the suggestion stays `pending`
    (AC-56). It can still be rejected.
- `POST /api/stewardship/commitment-proposals/{proposal_id}/reject`, body `{"reason": "…"}`. Blank reason → 422
  `A reason is required to reject a suggestion.`
- Confirm or reject on a suggestion that is not `pending` → 409 `Suggestion already confirmed.` or
  `Suggestion already rejected.`
- These five routes answer 409 `Commitment checks need the Postgres engagement store.` when
  `engagement_store = file`: `GET /api/stewardship/commitment-proposals`,
  `POST /api/stewardship/commitment-proposals/{id}/confirm`, `POST /api/stewardship/commitment-proposals/{id}/reject`,
  `POST /api/stewardship/commitments/{id}/check`, `POST /api/stewardship/activities/{id}/find-commitments`.

`POST /api/stewardship/tracking/commitments` accepts an optional `proof_statement`.

## What the user sees

On `#/engagement`, in the issue panel (`EngagementIssuePanel.tsx`), Commitments section. Dates are `YYYY-MM-DD`.

- A commitment with a proof statement shows the line `Proof: <proof_statement>` under its text.
- An `open` commitment has a button **Check against documents** next to **Verify**. After it runs, one line under
  the commitment: `Checked <N> document(s): <P> new suggestion(s), <U> unclear.`, with singular and plural spelled
  out (`Checked 1 document: 1 new suggestion, 0 unclear.`). With no documents: `No documents on file for this
  company.`
- A pending `verdict` suggestion, under its commitment:

  ```
  Argus suggests: met                      (or: Argus suggests: not met)
  "<quote>"
  <doc_title>, page <page>                 (page part left out when null)
  <reason>
  [Confirm]  [Reject]
  ```

- A pending `new_commitment` suggestion, at the top of the Commitments section:

  ```
  Argus found a commitment in the <call|meeting> of <occurred_at date>
  <text>
  Proof: <proof_statement>                 (line left out when null)
  "<quote>"
  Due date [YYYY-MM-DD input, prefilled from target_date]
  [Add commitment]  [Reject]
  ```

  **Add commitment** is disabled while the due date is empty; when the note stated none, the input is empty and its
  hint reads `Not stated in the note`.
- **Reject** opens an input `Why reject? (required)` and a button **Confirm rejection**, disabled while blank.
- After confirming, the suggestion disappears and the commitment row shows what it shows today for a person's
  decision: badge `verified` (met) or `missed` (not met), `verified by <user>`, and `evidence: <evidence text>`.
- Each call or meeting activity in the activity list has a button **Find commitments**. After it runs:
  `Found <P> suggestion(s).` (`Found 0 suggestions.` when none).

## Flags and the ballot banner (PR 3)

```python
class CommitmentFlag(BaseModel):          # arp/schemas/engagement.py
    commitment_id: str
    engagement_id: str
    kind: Literal["overdue", "broken"]
    text: str
    target_date: str | None               # YYYY-MM-DD
    since: str                            # YYYY-MM-DD: target_date (overdue) or validated_at's date (broken)
    message: str

def commitment_flags(store: EngagementStore, company_id: str, today: date | None = None) -> list[CommitmentFlag]:
    # arp/stewardship/tracking.py; today defaults to the UTC date

def commitment_flags_by_company(records: list[EngagementRecord], today: date | None = None) -> dict[str, list[CommitmentFlag]]:
    # the same flags for many companies from one store.list_all(); only companies with at least one flag are keys
```

`commitment_flags(store, c)` equals `commitment_flags_by_company([store.get(c)]).get(c, [])`. The bulk form exists so a
screen over the whole house universe (2,500 companies) reads the store once.

Rules, the same as `tracking.triggers` uses today: only engagements whose status is `open` or `stalled` count.
`broken` = status `missed`; `overdue` = status `open` with a `target_date` before `today`. A target date equal to
today is not overdue. No record, or no flags → `[]`. Order: `broken` first, then `overdue`, each by `target_date`
ascending (null last), then `commitment_id`.

`message`:

- overdue: `Commitment overdue: "<text>" was due <target_date>.`
- broken: `Commitment broken: "<text>" was marked not met on <since>.` (a `missed` commitment without
  `validated_at` uses its `target_date`, and failing that its `made_at` date, as `since`)

**Ballot.** `CompanyBallot` (`arp/schemas/voting.py`) gains `commitment_flags: list[CommitmentFlag] = []`, filled
when `GET /api/voting/runs/{run_id}/ballots` is read (not when the run ran), so a date that passes after the run
still shows. `BallotReview.tsx` shows each flag's `message` as a `banner banner-warning` on every ballot item of that
company, above the existing engagement-alignment banner. `engagement_alignment_flag`, its note and the co-sign rule
in `ballot_casting.py` stay as they are.

## Left to the builder

- Prompt wording, and how a long document is narrowed for the check (retrieval or truncation). The golden rows
  judge the result.
- Index choices beyond the two unique keys above.
- Where the hook sits relative to `refresh_hook` (both must run on the same events).
- PR split, in this order; each PR leaves the app working and names its rows in a `Rows:` line:
  1. Column, table, `Commitment.proof_statement`, the list/confirm/reject API and the generated contract (no
     UI yet: nothing creates suggestions until PR 2). Rows AC-1 to AC-5, AC-12, AC-13, AC-49, AC-51, AC-52, AC-60,
     AC-67. The confirm and reject holdout rows need suggestions, which only PR 2 can create, so they run from PR 2.
  2. The check (event hook and button), find-commitments, the golden set and command, and all suggestion UI.
     Rows AC-6 to AC-11, AC-14 to AC-39, AC-54 to AC-59, AC-61 to AC-66, AC-68 to AC-74.
  3. `commitment_flags`, `commitment_flags_by_company`, `CompanyBallot.commitment_flags` and the banner.
     Rows AC-40 to AC-48, AC-50, AC-53 (the last PR drops the `Rows:` line).

## Golden set (PR 2)

`backend/tests/golden/commitment_check/`: `cases.json` and `documents/`. At least 20 `check` cases (a document, one
commitment with a proof statement, the label `met`, `not_met` or `silent`), at least 6 of each label, from real
public reports; and at least 10 `find` cases (a note, the labelled commitments each as a key phrase). Command:

`arp stewardship commitment-golden --kind check|find --cases <file> --documents-dir <dir> --min-precision <x> --min-coverage <y>`

prints one line `precision <p>, coverage <c>` and exits 1 below either threshold. With no suggestions at all,
precision is 0.

- `check`: precision = stored suggestions whose verdict equals the label ÷ stored suggestions (a suggestion on a
  `silent` case is wrong); coverage = `met`/`not_met` cases with a correct suggestion ÷ `met`/`not_met` cases.
- `find`: a suggestion is correct when its quote contains a labelled key phrase (case-insensitive); precision =
  correct ÷ suggestions; coverage = key phrases matched ÷ key phrases.

## Acceptance

**Holdout and evaluator setup.** Rows run on the e2e stack (`ARP_ENGAGEMENT_STORE=postgres`), started with
`ARP_STANDINS_DIR=<dir>`. They drive the app through its API and pages only:

- Each test uses a new `company_id`, so uploaded documents from other tests never count.
- A company: `POST /api/engagement/records`. Engagements and activities, with their dates and types:
  `POST /api/stewardship/intake/engagements` (`stewardship-data-foundation` PR 2). Commitments:
  `POST /api/stewardship/tracking/commitments`; status changes: `POST /api/stewardship/tracking/commitments/{id}`;
  closing an engagement: `POST /api/stewardship/tracking/close`.
- "A document for the company": a `.txt` file `AR2026.txt` uploaded with `POST /api/documents/upload`
  (`doc_type` `other`), containing `The board formed a climate committee in March 2026.` Its `doc_title` is `AR2026.txt`.
- Model answers: the test writes `<dir>/model/CommitmentCheckDraft.json` or `CommitmentFindDraft.json` as
  `{"output": …}`. "The check stand-in returns met" means one result for the commitment, `verdict` `met`, quote
  `The board formed a climate committee in March 2026.`
- "A pending met suggestion on C" = the check stand-in returns met and `POST /api/stewardship/commitments/{C}/check`
  has run.
- "No suggestions" = `GET /api/stewardship/commitment-proposals?company_id=…&status=` `pending`, `confirmed` and
  `rejected` each return `{"proposals": []}`.
- "Today" is the UTC date the test runs. "The user" is the signed-in user, `dev` on the e2e stack.

`unit` rows use the implementer's tests with the same stand-ins and may write tables directly.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A database where `main`'s `arp db init-postgres` has run | `arp db init-postgres` runs twice | Both runs exit 0 | unit |
| AC-51 | AC-1 done | The schema is read | `stw_commitments` has a column `proof_statement`, and table `stw_commitment_proposals` exists | unit |
| AC-2 | AC-1 done once | `arp db init-postgres` runs again | Every `stw_*` table's column list and row count are the same as before the run | unit |
| AC-3 | A company with one engagement | `POST /api/stewardship/tracking/commitments` with `text`, `target_date` `2027-03-31`, `proof_statement` `The 2026 annual report names a board climate committee` | Status 200; `GET /api/engagement/records/{company_id}` shows that commitment with that `proof_statement` and `target_date` | holdout |
| AC-4 | As AC-3 | The same POST without `proof_statement` | Status 200; the commitment's `proof_statement` is null | holdout |
| AC-52 | A file `EngagementStore` | A commitment with a `proof_statement` is added, then the record is read back | The commitment has the same `proof_statement` | unit |
| AC-5 | `engagement_store = file` | `GET /api/stewardship/commitment-proposals?company_id=x` | Status 409, detail `Commitment checks need the Postgres engagement store.` | unit |
| AC-68 | `engagement_store = file`, an open commitment | `POST /api/stewardship/commitments/{id}/check` | Status 409, detail `Commitment checks need the Postgres engagement store.` | unit |
| AC-60 | — | `POST /api/stewardship/commitment-proposals/cpr_unknown/confirm` | Status 404, detail `Unknown suggestion.` | holdout |
| AC-12 | A `viewer` user (non-dev auth) | `POST .../commitment-proposals/{id}/confirm` | Status 403 | unit |
| AC-13 | Two pending suggestions on two commitments; one confirmed, one rejected | `stw_events` is read | One row `commitment_proposal_confirmed` and one `commitment_proposal_rejected`, each with its `proposal_id` in `detail` | unit |
| AC-67 | A pending `not_met` suggestion with `doc_title` `AR 2026.pdf`, `page` 4 | Confirm | The commitment's `evidence` is `AR 2026.pdf, page 4: "<quote>"` | unit |
| AC-17 | An open commitment C; a document for the company; the check stand-in returns met | `POST /api/stewardship/commitments/{C}/check` with the `company_id` | Status 200, body `{"documents": 1, "proposals": 1, "unclear": 0, "skipped": 0}` | holdout |
| AC-62 | AC-17 done | `GET .../commitment-proposals?company_id=…` | One suggestion: `kind` `verdict`, `verdict` `met`, `commitment_id` C, `doc_title` `AR2026.txt`, `quote` `The board formed a climate committee in March 2026.` | holdout |
| AC-18 | As AC-17 but the stand-in quote is `The board dissolved its climate committee.` (not in the document) | Check | Body `{"documents": 1, "proposals": 0, "unclear": 1, "skipped": 0}`; no suggestions | holdout |
| AC-19 | As AC-17 but the stand-in returns `unclear` with an empty quote | Check | Body `{"documents": 1, "proposals": 0, "unclear": 1, "skipped": 0}`; no suggestions | holdout |
| AC-20 | AC-17 done | Check again | Body `{"documents": 1, "proposals": 0, "unclear": 0, "skipped": 1}`; the pending list still holds 1 suggestion | holdout |
| AC-21 | AC-17 done, then that suggestion rejected | Check again | Body `{"documents": 1, "proposals": 0, "unclear": 0, "skipped": 1}` | holdout |
| AC-22 | AC-17 done | `GET /api/engagement/records/{company_id}` | C's `status` is `open` and its `validated_by` is null | holdout |
| AC-23 | A commitment set to `verified` (with evidence) | `POST .../commitments/{id}/check` | Status 409, detail `Only open commitments can be checked.` | holdout |
| AC-24 | An open commitment, no documents for the company | Check | Status 200, body `{"documents": 0, "proposals": 0, "unclear": 0, "skipped": 0}` | holdout |
| AC-55 | As AC-17 but `CommitmentCheckDraft.json` is not valid JSON | Check | Status 502, detail `Argus could not check the documents.`; no suggestions | holdout |
| AC-6 | A pending met suggestion on C, whose engagement has a second open commitment | `POST /api/stewardship/commitment-proposals/{id}/confirm` | Status 200; C's `status` is `verified`, `validated_by` is the user, `evidence` is `AR2026.txt: "The board formed a climate committee in March 2026."` | holdout |
| AC-7 | As AC-6 but the stand-in verdict is `not_met` | Confirm | C's `status` is `missed`, `evidence` is `AR2026.txt: "The board formed a climate committee in March 2026."` | holdout |
| AC-8 | AC-6 done | `GET .../commitment-proposals?company_id=…&status=confirmed` | One suggestion, `status` `confirmed`, `decided_by` the user, `decided_at` not null | holdout |
| AC-57 | A pending met suggestion on C, C the only commitment of its engagement | Confirm | `GET /api/engagement/records/{company_id}` shows that engagement's `status` `resolved` (as Verify does today) | holdout |
| AC-9 | A pending met suggestion on C | `POST .../commitment-proposals/{id}/reject` with `{"reason": "Quote is about the 2024 target"}` | Status 200; `GET …&status=rejected` returns it with that `reject_reason` | holdout |
| AC-58 | AC-9 done | `GET /api/engagement/records/{company_id}` | C's `status` is still `open` | holdout |
| AC-14 | AC-9 done | `GET .../commitment-proposals?company_id=…` (no status) | `{"proposals": []}` | holdout |
| AC-10 | A pending met suggestion on C | Reject with `{"reason": "  "}` | Status 422, detail `A reason is required to reject a suggestion.` | holdout |
| AC-11 | AC-9 done | Confirm the same suggestion | Status 409, detail `Suggestion already rejected.` | holdout |
| AC-59 | AC-6 done | Reject the same suggestion with a reason | Status 409, detail `Suggestion already confirmed.` | holdout |
| AC-56 | A pending met suggestion on C, then C set to `verified` through `POST /api/stewardship/tracking/commitments/{C}` with evidence | Confirm | Status 409, detail `Commitment is no longer open.`; the pending list still holds the suggestion | holdout |
| AC-28 | A `meeting` activity (`occurred_at` 2026-10-01) whose summary contains `The CFO committed to publish a transition plan by 31 March 2027.`; the find stand-in returns one commitment, text `Publish a transition plan`, that sentence as quote, `target_date` `2027-03-31` | `POST /api/stewardship/activities/{id}/find-commitments` | Status 200, body `{"proposals": 1, "ungrounded": 0, "skipped": 0}` | holdout |
| AC-64 | AC-28 done | `GET .../commitment-proposals?company_id=…` | One suggestion: `kind` `new_commitment`, `text` `Publish a transition plan`, `target_date` `2027-03-31`, that quote | holdout |
| AC-29 | As AC-28 but the stand-in quote is not in the summary | Find | Body `{"proposals": 0, "ungrounded": 1, "skipped": 0}` | holdout |
| AC-30 | An `email` activity | Find | Status 409, detail `Commitments are only looked for in call and meeting notes.` | holdout |
| AC-31 | AC-28 done | Find again | Body `{"proposals": 0, "ungrounded": 0, "skipped": 1}` | holdout |
| AC-32 | AC-28 done | `GET /api/engagement/records/{company_id}` | The engagement's commitment count is the same as before the find | holdout |
| AC-15 | AC-28 with the stand-in `target_date` null | Confirm the suggestion with `{"target_date": "2027-03-31"}` | Status 200; the engagement has a new commitment with text `Publish a transition plan`, `target_date` `2027-03-31`, `made_at` starting `2026-10-01`, `recorded_by` the user | holdout |
| AC-61 | AC-15 done | `GET …&status=confirmed` | The suggestion's `created_commitment_id` is the new commitment's `commitment_id` | holdout |
| AC-16 | As AC-15 | Confirm with `{}` | Status 422, detail `A due date is required to add a commitment.`; the engagement's commitment count is unchanged | holdout |
| AC-25 | A company with one open commitment on an open engagement and a registered document; `commitment_check_on_new_documents` true; check stand-in returns met with a quote from that document | `ChangeDetector.diff_and_record` gets that document (same `local_path`) as new | One pending `verdict` suggestion with that document's `doc_id` | unit |
| AC-69 | As AC-25, the document already in the manifest with a different `sha256` | Same (an `updated_document` event) | One pending `verdict` suggestion with that document's `doc_id` | unit |
| AC-26 | As AC-25 with `commitment_check_on_new_documents` false and event refresh off | Same | No suggestion, and `calls.jsonl` has no `CommitmentCheckDraft` call | unit |
| AC-27 | As AC-25 with a stand-in file that is not valid JSON | Same | `diff_and_record` returns its one `new_document` event; no suggestion | unit |
| AC-54 | As AC-27 with event refresh on (`event_refresh_enabled` true, one schema id) | Same | `refresh_on_events` still starts its extraction run | unit |
| AC-63 | As AC-25 but no registered document has that `local_path` | Same | No suggestion and no `CommitmentCheckDraft` call | unit |
| AC-33 | AC-17 done | A user opens the company's issue on `#/engagement` | Under C: `Argus suggests: met`, then `"The board formed a climate committee in March 2026."`, then `AR2026.txt`, then buttons `Confirm` and `Reject` | evaluator |
| AC-71 | As AC-33 with the stand-in verdict `not_met` | The user opens the issue | Under C: `Argus suggests: not met` | evaluator |
| AC-70 | AC-33 | The user clicks `Confirm` | The suggestion is no longer shown; C shows the badge `verified`, `verified by dev` and `evidence: AR2026.txt: "The board formed a climate committee in March 2026."` | evaluator |
| AC-34 | AC-33 | The user clicks `Reject` | An input labelled `Why reject? (required)` and a `Confirm rejection` button, disabled while the input is empty | evaluator |
| AC-65 | AC-34, a reason typed | The user clicks `Confirm rejection` | The suggestion is no longer shown; C still shows the badge `open` | evaluator |
| AC-37 | AC-17's Given | The user clicks `Check against documents` on C | The line `Checked 1 document: 1 new suggestion, 0 unclear.` | evaluator |
| AC-73 | An open commitment, no documents for the company | The user clicks `Check against documents` | The line `No documents on file for this company.` | evaluator |
| AC-72 | AC-28's Given | The user clicks `Find commitments` on that activity | The line `Found 1 suggestion.` | evaluator |
| AC-35 | AC-28 done with the stand-in `target_date` null | The user opens the issue | `Argus found a commitment in the meeting of 2026-10-01`, the text, the quote, and an empty `Due date` input with the hint `Not stated in the note` | evaluator |
| AC-66 | AC-35 | The user looks at `Add commitment`, then enters `2027-03-31` | It is disabled while the date is empty and enabled after | evaluator |
| AC-74 | AC-66 | The user clicks `Add commitment` | The suggestion is no longer shown; the Commitments list has `Publish a transition plan` with `target 2027-03-31` | evaluator |
| AC-36 | A commitment with proof statement `The 2026 annual report names a board climate committee` | The user opens the issue | The line `Proof: The 2026 annual report names a board climate committee` under the commitment text | evaluator |
| AC-38 | `ARP_ANTHROPIC_API_KEY` set | `arp stewardship commitment-golden --kind check --cases tests/golden/commitment_check/cases.json --documents-dir tests/golden/commitment_check/documents --min-precision 0.9 --min-coverage 0.6` | Exit 0 | golden |
| AC-39 | `ARP_ANTHROPIC_API_KEY` set | The same command with `--kind find --min-precision 0.8 --min-coverage 0.7` | Exit 0 | golden |
| AC-40 | An open engagement with an `open` commitment, `target_date` = yesterday, text `Publish a transition plan` | `commitment_flags(store, company_id)` | One flag: `kind` `overdue`, `target_date` and `since` = yesterday, `message` `Commitment overdue: "Publish a transition plan" was due <yesterday>.` | unit |
| AC-41 | An open engagement with a `missed` commitment, text `Name a climate committee`, `validated_at` 2026-10-02 | `commitment_flags` | One flag: `kind` `broken`, `since` `2026-10-02`, `message` `Commitment broken: "Name a climate committee" was marked not met on 2026-10-02.` | unit |
| AC-42 | One company with: a `verified` commitment; an `open` one without `target_date`; an `open` one due today; an `open` one due tomorrow; an overdue `open` one on a `closed` engagement | `commitment_flags` | `[]` | unit |
| AC-43 | Two overdue (due 2026-09-01 and 2026-08-01) and one broken commitment on open engagements | `commitment_flags` | Three flags in the order: broken, due 2026-08-01, due 2026-09-01 | unit |
| AC-44 | A company with no engagement record | `commitment_flags` | `[]` | unit |
| AC-50 | Three companies: AC-40's (one overdue), AC-41's (one broken), and one with no flags | `commitment_flags_by_company(store.list_all())` | A dict with exactly the first two `company_id`s as keys, each value equal to `commitment_flags(store, company_id)` | unit |
| AC-53 | AC-40's data on a file `EngagementStore` | `commitment_flags` | The same flag as AC-40 | unit |
| AC-45 | A `proxy_voting` run's ballots seeded through `RunStore`, one ballot for a company with AC-40's overdue commitment | `GET /api/voting/runs/{run_id}/ballots` | That ballot's `commitment_flags` equals `commitment_flags(store, company_id)` as JSON | unit |
| AC-46 | As AC-45, a second ballot for a company without flags | `GET .../ballots` | That ballot's `commitment_flags` is `[]` | unit |
| AC-47 | The ballots response for a run stubbed (as the existing e2e voting tests do with `page.route`): company A with two items and `commitment_flags` = AC-40's flag; company B with one item and `[]` | A user opens the run's ballot review | Both of A's items show a warning banner `Commitment overdue: "Publish a transition plan" was due <date>.`; B's item shows none | evaluator |
| AC-48 | A `VoteRecord` approved without co-sign, `engagement_alignment_flag` false, for a company with an overdue commitment | `cast_vote(platform, record)` | The returned record's `cast_confirmation.status` is `confirmed` | unit |
| AC-49 | An open commitment with a `target_date` after today | `POST /api/stewardship/tracking/commitments/{id}` with `status` `verified` and no `evidence` | Status 422, detail `Evidence is required to verify a commitment.` (unchanged) | holdout |

Must not change: the co-sign rule for `engagement_alignment_flag` items and the alignment check itself (AC-48 plus
the existing voting tests, unchanged); manual Verify and status updates (AC-49); adding a commitment without a proof
statement (AC-4); `init-postgres` idempotence (AC-2); event refresh on new documents (AC-54); commitment status
changes only through a person (AC-22, AC-32, AC-58).
