# Showcase fixes: transition plan and barriers, engagement, stewardship, voting

Slug: `showcase-stewardship-fixes`. Risk: `risk:normal`. Size: 2 PRs (PR A transition side, PR B stewardship
side), sliced with `Rows:`.

## Intent

A live rehearsal on 11 Nov 2026 (real model calls, bank JupyterLab setup) found 13 defects in the Transition
Plan, Transition Barriers, Engagement, Steward Workflow, Proxy Voting and Background Agents screens. The
showcase is next week. Each defect is fixed in the existing screens so that the presenter meets no surprise:
no dead end, no wrong state after an ordinary click, no wording that claims more than the code does.

The showcase runs with Gemini through Vertex AI, one uvicorn process, Postgres, dev sign-in or two local
users, and possibly no outbound web search.

## Evidence (read on `fix/showcase` 463ed94, the branch of PR #413)

Numbers follow the intake list. "Pinned" means an existing test fixes the behaviour; existing tests are never
changed.

1. **ISIC code lost on Argus list upload.** `backend/arp/argus/companies.py` `_FIELDS` has no `isic_code`, and
   only `sector` and `country` are passed to `resolve`, which uses them only when it creates a company.
   Nothing else writes `Company.isic_code`. `GET /api/companies/{ref}/transition` then answers
   `in_scope: false`, `reason: "No ISIC code"`. The column `isic_code` already exists. An upload makes no network lookup. Rows without a valid
   LEI, ISIN or CIK create no registry company, so they have nowhere to keep the code.
2. **Identity lookup dies on a failed lookup.** `backend/arp/discovery/identity_agents.py` `gather_signals`
   awaits `edgar.search_by_name` and then `search_client.search` with no guard; GLEIF comes last and already
   answers `[]` when it fails. An EDGAR or web-search failure ends the company's step. The run itself survives (`batch_runner.py` writes an error row), but
   `str(httpx.ConnectTimeout(""))` is `""`, so the reason is empty, and `FailureDetails.tsx` prints "No
   traceback was recorded for this run." whenever the run-level traceback is null, although each company
   error carries its own traceback.
3. **Barrier derivation gives "Not rated" without warning.** With `transition_barrier_refresh_enabled` off,
   `derivation.py` fetches nothing and notes "Sources not fetched: refresh is disabled". A cell with facts
   entered by hand is still rated; a cell without facts is "Not rated". No API tells the page whether the
   switch is on. Refusing the run is not possible: `test_tb_derivation.py` pins a run with the switch off.
   The rehearsal also saw "Nothing is waiting for review" after such a run; the code queues one item per cell,
   so the cause is not known from reading; AC-26 states what the presenter must see, and the builder finds
   the cause if that row fails. A derivation calls the model only for stored source documents whose facts are
   not extracted yet; a fresh stack stores none.
4. **Calibration flags everything.** `backend/arp/agents/calibration_agent.py` compares `max(d.fetched_at)`
   with the verdict time, as strings. No source sets `fetched_at`, so it is the time of the check itself.
   `SourceDocument.published_at` exists (EDGAR acceptance time, PDF creation date or `Last-Modified`).
   `CompanyMatch` already carries `name` and `activity_name`; `DriftFlag` drops them and the page prints ids.
   `test_calibration_agent.py` pins flags for documents that have only an explicit, older `fetched_at`.
5. **Engagement state.** `verify-commitment` takes only `commitment_id`; when all commitments are verified the
   issue becomes `resolved` and the milestone `commitment_verified`. `escalate` checks no status.
   `log_outreach_sent` always appends a letter entry and always sets the milestone to `contacted`;
   `log_meeting_summary_validated` also sets its stage unconditionally. The Steward Tracking screen has a
   second verify path (`POST /api/stewardship/tracking/commitments/{id}`), also without evidence. "Commitments
   met" counts commitments with status `verified`; it has no bug of its own.
   `test_actor_from_principal.py` posts `verify-commitment` with no evidence and expects 200.
6. **Trigger scan.** `EngagementDashboard.tsx` starts the form with Apple sample rows. `triggers.py` drops a
   signal whose `company_id` is not among the form's companies, and the response says nothing about it.
7. **Dossier without documents.** `research_agent.py` calls the model even when `registry.fetch_all` returns
   nothing; the "no evidence" sentence is model output.
8. **Voting.** `ManualInstructionBallotPlatform` only writes one instruction file per vote and returns a
   `conf_…` id; nothing is sent anywhere, and it is the only platform. `BallotReview.tsx` says "This sends N
   votes to the ballot platform", "Confirmation IDs", "refused by the platform". `isRoutine` there is only
   "has a recommendation and no alignment flag". An empty ballot list always shows "No ballots in this run
   yet…", whatever the run's status. `POST /api/voting/runs/{id}/review` accepts an override (`edit`) with no
   comment.
9. **Report year.** `backend/arp/argus/documents.py` takes the year from the title or `published_at`; the EDGAR
   title carries the filing date and `reportDate` is never read. `searchStatusText` (`lib/argusFlow.ts`)
   returns "Searching…" for every unfinished search, also when files are already listed.
10. **Transition-plan run.** No time or cost estimate exists anywhere. `confirm_entity`
    (`planning/entity_check.py`) looks for CIK, LEI or legal name in the document and never at whose folder
    the file is in, so an uploaded text file is "ambiguous" and every value gets `check:consistency.entity`.
    Step 5 shows the field name, which for this template is the indicator id; the question is the field's
    description. Score and tier come from Decision Studio (`GET /api/decision/runs/{run}/decision`) when a
    ratified scoring template is attached; `RunScoringPanel` shows them but has been mounted nowhere since
    36b4b11. A walk-versus-talk verdict does not exist in code; the walk and talk counts do
    (`decision/sources.py`).
11. **Placeholder data.** CLTI scores are a hash of the issuer id (`stewardship/benchmark.py`
    `placeholder_clti`), also for real holdings, and the rule "CLTI score below 30" raises high-severity
    triggers from them. The note saying so is shown only on the overview.
12. **Four-eyes.** `steward/drafting.tsx` gives the reason only as a tooltip. `RfpAnswers.tsx` renders no
    Approve block and no text when the signed-in approver edited the answer last.
13. **Smaller items.** Criterion detail opens below the table without scrolling. The template list says
    "72 fields" (64 indicators and 8 supporting figures; both counts are pinned). The review detail prints
    reason codes raw (`ReviewControls.tsx`). A bad universe file returns pydantic's text; Proxy Voting prints
    the server path. `GET /api/companies` lists records whose name is a UUID. The company page counts only
    registered documents, and an upload registers nothing until a run reads it. The letter's "[Fund name]" is
    model output; `fund_name` (`ARP_FUND_NAME`) exists. `Contact.email` is an unchecked string.
    `interval_hours: 0` with `enabled` makes the scheduler run back to back; the page
    shows no confirmation after a save and reloads "Past runs" only on "Refresh results". The live region `#announcer` is
    never cleared, so "14 tiers confirmed." stays in the page text.

## Goals

- G1. A company added through an Argus list keeps its `isic_code`, and an existing company without one gets it.
- G2. Identity lookup survives a failed EDGAR or web-search lookup, still asks GLEIF, and records the reason
  in the company's result (`signals.lookup_errors`, returned by the identity results API and given to the
  adjudication prompt). A company's failure reason is never empty, and its traceback is shown.
- G3. Before a barrier derivation starts, the page says what it will use when the refresh is switched off,
  and the review link after it lists the derived cells.
- G4. The Calibration Agent compares against a document date and shows names.
- G5. Engagement: verifying asks for evidence; a resolved issue cannot be escalated; a repeated "Log outreach
  sent" adds nothing and never moves the milestone back; "Commitments met" follows from that.
- G6. The trigger-scan form starts empty and the scan reports signals for companies not in its list.
- G7. Drafting a dossier with no documents says that documents must be loaded first, without a model call.
- G8. Voting wording matches what happens; the routine sweep leaves out say-on-pay, low-confidence,
  model-judged and redomiciliation proposals; a run in progress says so; an override needs a reason.
- G9. The year of an EDGAR filing (10-K, 20-F, 40-F and their amendments) is the year of its period of
  report when EDGAR gives one; the search status stops saying "Searching…" once files are listed.
- G10. Transition plan: a file uploaded for a company passes the entity check; results show the question, the
  walk and talk counts, and score and tier where a scoring template is attached; time and cost of the last
  run are stated before starting.
- G11. These carry a `Sample data` chip: each Monitoring trigger whose reason names a CLTI score; the
  overview's note on placeholder scores; on the client program page the score note and the `Weighted CLTI`
  tile. Each block for a part that is planned carries a `Not built yet` chip.
- G12. On an outreach draft and on an RFP answer, where four-eyes blocks the signed-in person, the page says
  in plain text that a second person is needed.
- G13. The smaller items in Evidence 13 are fixed as the acceptance rows state.

## Non-goals

- Anything PR #413 already fixes.
- Making a transition-plan run faster or cheaper. The header text "estimating time left" stays (pinned).
- Replacing placeholder CLTI or benchmark data. Building Checkpoint or Reporting. A real ballot platform.
- Changing the four-eyes rule. Database schema changes. Deleting any stored record.
- "Annual report shown as 10-K" and every other change to the Type cell on Argus step 2, including the raw
  `sustainability_report` (showcase-argus-fixes item 8, see Shared files).
- The empty Argus flow that a visit to Transition Plan creates (see Builder's calls, B1).
- A walk-versus-talk verdict label. The counts are shown; no rule turns them into a verdict.
- The server path shown in Taxonomy Library and Emerging Themes (R&D Lab screens, not in this rehearsal list).
- Fiscal years that end in January or February (the period of report then falls in the next calendar year).
- Checking that an `isic_code` is a real ISIC code (it is stored as typed, as text), and keeping a code for a
  list row without a valid LEI, ISIN or CIK (no registry company exists for it).
- A `Sample data` chip on other Stewardship tables (coverage tiers, votes, previews).
- An empty reason on a run-level failure (only company rows are in scope).

## Anti-goals

- An existing test is changed, weakened or deleted.
- A guard that only hides a button while the API still accepts the bad request from the screen's own call.
- Wording that still claims a vote is sent to a platform.
- A `Sample data` chip on a row that does not come from placeholder scores.

## Constraints

- Build on `main` once #413 is merged; if it is not, branch from `fix/showcase` and merge `main`. The PR base
  is `main` either way.
- Owner's rules: every fix has a test that failed before, with its output in the PR description; no existing
  test changes; two PRs.
- Request or response models that change (`VerifyCommitmentRequest`, `CommitmentStatusRequest`) need
  `export_openapi.py` and `npm run gen:api`, both files committed.
- The schedule interval is checked in the two `PUT` handlers, not in the stored config model, so a schedule
  file already holding 0 still loads (AC-172).
- `Contact` is the stored model: validate the email in the endpoint, not in the model, or stored records with
  a bad address stop loading.
- `email-validator` is not installed; no new dependency.
- Risk rises to `risk:high` only if the build turns out to need auth, schema or stored-data deletion. It
  should not: every fix above was checked against that.

## Approaches

1. **Fix each defect at its cause in the existing code, two PRs by area (chosen).** Backend guards where state
   can be corrupted, wording and visible notes in the frontend, one small helper per rule so it can be tested.
   Smallest change that holds under ordinary clicks; reviewable per area.
2. **Frontend-only guards.** Faster, but the API would still accept an evidence-free verify, an escalation of
   a resolved issue or interval 0, and nothing could be proven by an API test. Rejected (anti-goal).
3. **One PR.** About 60 files across both areas; a review that size is where regressions hide the week before
   a showcase. Rejected; the intake set two.

## Decided (owner)

- **O1, transition-plan results.** Step 5 shows per company the line `Disclosed D of N · Walk W of Wn · Talk T
  of Tn` (computed from the values, no model call; B16) and the existing Scoring panel (score and tier when a
  scoring template is attached, the template picker otherwise). No verdict label. The owner chose
  this on 12 Nov 2026 over a verdict label and over counts only; AC-58 to AC-60.
- **O2.** The owner approved this spec, with the builder's calls below, on 12 Nov 2026.

## Builder's calls (not asked; the owner may overrule at approval)

- **B1.** The empty flow per Transition Plan visit is not fixed here. The Argus switch-over spec requires
  every such visit to open a new flow (`test_argus_switchover.py`, AC-63 and AC-64 there, pinned). What the
  presenter sees is a start page filling with empty drafts, which is showcase-argus-fixes item 7
  (`ArgusStart.tsx`). That feature is asked to treat drafts made by `openNewFlow` the same way.
- **B2.** Evidence on verify, the same on both verify endpoints. The screens always ask for it. The API
  refuses a blank `evidence` (empty or only spaces), and refuses a missing one (`null` or no key) when the
  commitment's target date is after today's UTC date. A missing `evidence` on a commitment that is due or has
  no date is still accepted, because `test_actor_from_principal.py` and `test_stewardship_tracking.py` post
  exactly that.
- **B3.** Calibration date: `published_at` (read as UTC when it has no offset); without it, `fetched_at`
  only when it is earlier than the moment this check started (a time the source supplied, not one stamped
  while fetching). A document with neither is ignored. Every check fetches anew and stores no document, so
  a time stamped by one check never reaches the next. This keeps the two pinned tests green.
- **B4.** A recommendation the model judged (no `policy_rule_id`) is never "routine", whatever its confidence.
  The low-confidence line is a fixed 0.6 in the page (the default of `confidence_review_threshold`, which the
  page cannot read). Redomiciliation is recognised by the proposal text, case-insensitive, containing
  `redomicil`, `re-domicil`, `reincorporat`, `re-incorporat` or one of `jurisdiction`, `state`, `place`,
  `country` followed by ` of incorporation`.
- **B5.** Voting buttons keep the verb "Cast"; the dialog, the result banner, the per-proposal line and the
  co-sign warning say what is recorded.
- **B6.** EDGAR lookup failure is tolerated like web-search failure: both can be blocked in the bank setup.
  A GLEIF failure stays as today (an empty list, not recorded).
- **B7.** A file in a company's own folder (uploaded or crawled: `local_path` set, no `source_url`) is
  confirmed where the check would otherwise say "ambiguous". The existing mismatch rules run first and are
  unchanged. Step 2 already checked the name.
- **B8.** The estimate before a run is the latest run of the same template with status `completed` or
  `partially_completed`, stated as it was, not scaled to the number of companies. Minutes are `updated_at`
  minus `created_at`, rounded to the nearest minute, at least 1, never converted to hours.
- **B9.** Barrier derivation is never refused; the page says beforehand what it will use.
- **B10.** Escalating an issue with status `resolved` or `closed` answers 409; missing evidence, no documents and a bad email
  answer 422; a missing override reason answers 400 like the checks next to it.
- **B11.** Schedules accept whole or fractional hours from 1 upward; 0.5 is refused, enabled or not.
- **B12.** Universe errors name the first bad row only; rows are counted from 1 at the first data row.
- **B13.** A letter is "the same" when the issue already has a letter entry with the same `summary` and
  `doc_ref`, anywhere in its correspondence. The panel sends the same summary for the same draft.
- **B14.** A contact email is valid when it has no spaces, exactly one `@`, text before it, and after it a
  domain with a dot that neither starts nor ends with the dot. An empty string counts as no email.
- **B15.** A letter placeholder is every distinct `[...]` token (1 to 40 characters, one line) in the subject
  and then the body, in order of first appearance, except a token that is `[<doc id>]` of a dossier citation.
  `[Fund name]` is replaced with `fund_name`, matching that exact spelling.
- **B16.** `Disclosed` counts the indicators whose current value is Yes, reviewed or not. `N` is the number of
  indicators, without the 8 supporting figures. Walk or talk is each indicator's `walk_or_talk` from
  `GET /api/transition-plan/indicators`.

Supersedes: none. No earlier spec's acceptance row pins a behaviour this change alters (searched the specs
for the endpoints and strings above; the `No ISIC code` and `interval_hours` rows there stay true).

## Shared files with showcase-argus-fixes

Different functions in each file; whoever merges second merges `main` first.

| File | This feature owns | showcase-argus-fixes owns |
|---|---|---|
| `backend/arp/discovery/identity_agents.py` | `gather_signals` failure handling, `lookup_errors`, the prompt line for a failed lookup | which identifiers are accepted (ticker alone) |
| `frontend/src/pages/ArgusDocuments.tsx` | nothing; the status text is `searchStatusText` in `lib/argusFlow.ts` | `DOC_TYPES`, the Keep block, the Type cell (all types) |
| `frontend/src/pages/ArgusStart.tsx` | nothing | `start()`, removing drafts, drafts made by `openNewFlow` (B1) |
| `frontend/src/pages/ArgusResults.tsx` | question in the Field cell for the transition-plan template, the walk and talk line, the Scoring panel | "How was this found?", skipped companies, the period column |
| `frontend/src/pages/ArgusSchema.tsx` | the estimate sentence by the start button, "64 indicators + 8 supporting figures" | saved-schema layout, field ids |
| `backend/arp/argus/companies.py` | `isic_code` in `_FIELDS` and the fill on an existing company (an existing code wins, nothing is reported) | keys of unmatched rows, identifier conflicts |
| `backend/arp/argus/documents.py`, `backend/arp/ingestion/edgar.py` | the year of an EDGAR filing | uploads included in the flow's file list before "Keep" |
| `backend/arp/db/company_view.py` | the company page's `documents` count | nothing |

## What is left to the builder

How each rule is placed in the code (store, helper or endpoint), component structure, CSS for the chips, the
wording of the EDGAR line in the adjudication prompt, and how the company page counts unregistered uploads,
as long as the rows below hold.

## Showcase setup (no code)

- Score and tier appear on step 5 only with a ratified scoring template that matches the transition-plan
  template. Ratify one in Decision Studio before the showcase.
- Set `ARP_FUND_NAME` so outreach letters carry the fund's name.
- Barrier derivation fetches sources only with `ARP_TRANSITION_BARRIER_REFRESH_ENABLED=true`.

## Acceptance

Checked by. `holdout`: hidden test against a fresh app started by `backend/scripts/e2e_stack.sh up` (dev
sign-in, no model key, barrier refresh off, `ARP_FUND_NAME` unset, no stored barrier source documents). No
`holdout` or `evaluator` row needs a model call. `HOLDOUT_TOKEN` status is not known to the author; if it is
unset, the PR lists its `holdout` rows as owed and covers them with its own tests. `evaluator`: the same
stack, used through the browser. `unit`: the implementer's test; "unit (browser)" is a Playwright test in
`backend/tests/e2e` with the named API routes stubbed, as `test_rfp_page.py` does. Every `unit` row's test is
shown failing before the fix in the PR description.

Fixtures. `L1`, `L2`, `L3`: 20-character LEIs that pass the ISO 17442 checksum and that the registry does not
hold yet. A "list" is a CSV uploaded to `POST /api/argus/flows/{flow}/companies/upload`; `E` is the
`entity_id` of its row in the response. An "issue" is made with `POST /api/engagement/records` and
`POST /api/engagement/records/{c}/issues`, each test with its own company id; a commitment with
`POST /api/stewardship/tracking/commitments`; status `resolved` or `closed` through
`POST /api/stewardship/tracking/close` with `{"company_id", "issue_id", "status": "resolved"` or `"closed",
"outcome": "x"}`. `RECORD` is `GET /api/engagement/records/{c}`. `verify` is
`POST /api/engagement/records/{c}/issues/{i}/verify-commitment`; `track-verify` is
`POST /api/stewardship/tracking/commitments/{id}` with `status: "verified"`; `outreach` is
`POST /api/engagement/records/{c}/issues/{i}/log-outreach-sent`. "After today" and "yesterday" are UTC dates.
`EVIDENCE_MSG` is exactly `Evidence is required to verify a commitment.` `NOTE_OFF` is exactly `Re-checking
sources is switched off on this server, so a derivation uses only facts entered by hand and documents already
stored. Cells without facts come out as Not rated.` `MET` is, in `GET /api/stewardship/streams/house/flow`,
the `value` of the metric labelled `Commitments met` in the stage whose `id` is `tracking`; it counts every
company's verified commitments. Times are ISO strings with offset `+00:00` unless written otherwise. "Name
then id" means the cell holds the name, followed by the id in an element of its own.

### PR A: transition side (`Rows: AC-1` to `AC-71`)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | a new flow; no company with `L1` | upload the list `name,lei,isic_code` / `Acme Power AG,L1,3510` | `GET /api/companies/E` has `isic_code` `"3510"` | holdout |
| AC-2 | after AC-1 | `GET /api/companies/E/transition` | `in_scope` is `true` and `sector` is `"Power & Utilities"` | holdout |
| AC-3 | a company created by the list `name,lei` / `Acme Steel AG,L2` (its `isic_code` is null) | upload the list `name,lei,isic_code` / `Acme Steel AG,L2,2410` to any flow | `GET /api/companies/E` has `isic_code` `"2410"` | holdout |
| AC-4 | the company of AC-1 (`isic_code` `"3510"`) | upload the list `name,lei,isic_code` / `Acme Power AG,L1,2410` | the upload answers 200 and `GET /api/companies/E` still has `isic_code` `"3510"` | holdout |
| AC-5 | a new flow; no company with `L3` | upload the list `name,lei,isic_code` / `Acme Oil AG,L3,0610` | `GET /api/companies/E` has `isic_code` `"0610"` (text, the leading zero kept) | holdout |
| AC-6 | a company created by a list without an `isic_code` column | `GET /api/companies/E/transition` | `in_scope` is `false` and `reason` is `"No ISIC code"` (must not change) | holdout |
| AC-7 | `gather_signals` with a web-search client that raises `httpx.ConnectTimeout("")` and a GLEIF client that returns one match | call it | it returns; `gleif_matches` has that one match and `search_results` is `[]` | unit |
| AC-8 | same | same | `lookup_errors` is exactly `["web search: ConnectTimeout"]` | unit |
| AC-9 | `gather_signals` with an EDGAR source that raises `httpx.ConnectError("boom")` | call it | it returns; `edgar_matches` is `[]` and `lookup_errors` is exactly `["EDGAR: ConnectError: boom"]` | unit |
| AC-10 | same; the web search returns one hit and GLEIF one match | same | `search_results` has that hit and `gleif_matches` has that match | unit |
| AC-11 | EDGAR raises `httpx.ConnectError("boom")`, the web search raises `httpx.ConnectTimeout("")`, GLEIF returns one match | same | it returns; `lookup_errors` is exactly `["EDGAR: ConnectError: boom", "web search: ConnectTimeout"]` and `gleif_matches` has that match | unit |
| AC-12 | the signals of AC-8 | the adjudication prompt is built | it contains the line `Web search results: not available (ConnectTimeout)` and not `Web search results: none found` | unit |
| AC-13 | a web search that succeeds with no hits | the adjudication prompt is built | it contains `Web search results: none found` (must not change) | unit |
| AC-14 | all lookups succeed | `gather_signals` | `lookup_errors` is `[]` | unit |
| AC-15 | an `IdentitySignals` stored before this change (no `lookup_errors` key) | load it | it loads and its `lookup_errors` is `[]` | unit |
| AC-16 | an identity run of one company with the web-search client of AC-7 | `GET /api/identity/runs/{id}/results` | that company's `signals.lookup_errors` is `["web search: ConnectTimeout"]` | unit |
| AC-17 | a batch run where one company's step raises `httpx.ReadTimeout("")` | read the run's error rows | that row's `error` is `"ReadTimeout"` | unit |
| AC-18 | a batch run where one company's step raises `RuntimeError("boom")` | read the run's error rows | that row's `error` is `"boom"` (must not change) | unit |
| AC-19 | `GET /api/runs/{id}/failure` stubbed: `traceback` null, one `company_errors` entry `{key: "acme", error: "ReadTimeout", traceback: "Traceback (most recent call last): X"}` | open Run History, Details of that run | the text `Traceback (most recent call last): X` is on the page under `acme`, and `No traceback was recorded for this run.` is not | unit (browser) |
| AC-20 | same stub with no traceback on the run or on any company | open Details | `No traceback was recorded for this run.` is shown (must not change) | unit (browser) |
| AC-21 | the e2e stack | `GET /api/transition-barrier/matrix` | the body has `refresh_enabled` `false` | holdout |
| AC-22 | the e2e stack | `GET /api/transition-barrier/cells/STL-R1/European%20Union` | the body has `refresh_enabled` `false` | holdout |
| AC-23 | `transition_barrier_refresh_enabled` true | both requests of AC-21 and AC-22 | `refresh_enabled` is `true` in both | unit |
| AC-24 | the e2e stack | open Transition Barriers | `NOTE_OFF` is visible next to "Derive all regions" before anything is clicked | evaluator |
| AC-25 | the e2e stack | open the page of the cell `STL-R1`, `European Union` | `NOTE_OFF` is visible next to "Derive this cell" before anything is clicked | evaluator |
| AC-26 | the e2e stack; the cell `STL-R1`, `European Union` with no facts entered | click "Derive this cell", then "Review the result"; then do both again | each time the review page lists exactly 1 open item for that run, for that cell, and does not show `Nothing is waiting for review in this run.` (each derivation queues its own item) | evaluator |
| AC-27 | matrix and cell responses stubbed with `refresh_enabled` true | open both pages | `NOTE_OFF` appears on neither | unit (browser) |
| AC-28 | the e2e stack | `POST /api/transition-barrier/derive` with `{"cells": [{"code": "PWR-T1", "region": "European Union"}]}` | 200 with a `run_id` (never refused; must not change) | holdout |
| AC-29 | one document with `published_at` `2026-01-10T00:00:00+00:00` and `fetched_at` left to its default; one match with `generated_at` `2026-02-01T00:00:00+00:00` | `check_company_staleness` | returns `[]` | unit |
| AC-30 | one document with `published_at` `2026-03-01T00:00:00+00:00`; the same match | same | one flag; its `newest_document_at` is `2026-03-01T00:00:00+00:00` | unit |
| AC-31 | a source that returns one document with no `published_at` and `fetched_at` stamped while fetching | same | returns `[]` | unit |
| AC-32 | the source of AC-31, which stamps `fetched_at` anew on each call | run the check twice in a row | both return `[]` | unit |
| AC-33 | one document with no `published_at` and `fetched_at` `2026-02-01T00:00:00+00:00`; a match with `generated_at` `2026-01-01T00:00:00+00:00` | `check_company_staleness` | one flag; `newest_document_at` is `2026-02-01T00:00:00+00:00` (must not change) | unit |
| AC-34 | one document with `published_at` `2026-02-10T16:31:00.000Z`; a match with `generated_at` `2026-02-10T17:00:00+00:00` | same | returns `[]` (instants are compared, not strings) | unit |
| AC-35 | one document with `published_at` `2026-03-01T00:00:00` (no offset); a match with `generated_at` `2026-02-01T00:00:00+00:00` | same | one flag | unit |
| AC-36 | the flag of AC-30; the match has `name` `Coca-Cola Co` and `activity_name` `Soft drinks` | read the flag | `company_name` is `Coca-Cola Co` and `activity_name` is `Soft drinks` | unit |
| AC-37 | the flag of AC-30 | read the flag | `reason` is exactly `A disclosure dated after this verdict was generated exists -- re-running classification is recommended.` | unit |
| AC-38 | calibration results stubbed with one flag: `company_id` `ko`, `company_name` `Coca-Cola Co`, `activity_id` `act_dd5b90051fcd`, `activity_name` `Soft drinks` | open Background Agents, the run's results | the Company cell holds `Coca-Cola Co` then `ko`, and the Activity cell `Soft drinks` then `act_dd5b90051fcd` (name then id) | unit (browser) |
| AC-39 | the same stub without the two name fields (a stored older result) | same | the cells read `ko` and `act_dd5b90051fcd` | unit (browser) |
| AC-40 | an EDGAR 10-K of `Acme Corp` with `filingDate` `2026-02-14` and `reportDate` `2025-12-31`, found by a new search of a flow whose expected year is 2025; the document names `Acme Corp` | `GET /api/argus/flows/{id}` | that file's `year` is `2025` | unit |
| AC-41 | same | same | that file's `passes` is `true` and its `check` is exactly `✓ Acme Corp, 2025` | unit |
| AC-42 | same | `POST /api/argus/flows/{id}/files` with `{"all_that_pass": true}` | that file's `state` is `"kept"` | unit |
| AC-43 | an EDGAR 20-F with `filingDate` `2026-04-20` and `reportDate` `2025-12-31`, found the same way | `GET /api/argus/flows/{id}` | that file's `year` is `2025` | unit |
| AC-44 | the filing of AC-40 without a `reportDate` | same | `year` is `2026` and `check` is exactly `Year 2026, expected 2025` (must not change) | unit |
| AC-45 | Argus step 2; the search run is `running` and 3 files are listed | read the status text | exactly `3 found so far, still checking other sources…`; `Searching…` is not shown | unit |
| AC-46 | Argus step 2; the search run is `running` and no file is listed | read the status text | exactly `Searching…` (must not change) | unit |
| AC-47 | a document with `local_path` set, no `source_url`, `company_id` equal to the company's, title `report.txt`, and text without the company's legal name, LEI or CIK | `confirm_entity` | the status is confirmed | unit |
| AC-48 | the same document with another company's `company_id` | same | the status is ambiguous (must not change) | unit |
| AC-49 | the document of AC-47 whose first 5,000 characters carry another company's LEI | same | the status is mismatch (must not change) | unit |
| AC-50 | a document with the company's `company_id`, no `local_path` and no name, LEI or CIK signal | same | the status is ambiguous (must not change) | unit |
| AC-51 | an extraction run over the document of AC-47 only | read the run's results | no field's `route_reasons` contains `check:consistency.entity` | unit |
| AC-52 | Argus step 3; the latest `completed` run of the chosen template had 1 company, 13 minutes between `created_at` and `updated_at`, and `estimated_cost_usd` 8.58 | read the text next to the start button | exactly `The last run of this template took 13 min and $8.58 for 1 company.` | unit |
| AC-53 | the same with a `partially_completed` run of 2 companies, 75 minutes 20 seconds and cost 20 | same | exactly `The last run of this template took 75 min and $20.00 for 2 companies.` | unit |
| AC-54 | the run of AC-52 with `estimated_cost_usd` null | same | exactly `The last run of this template took 13 min for 1 company; its cost was not recorded.` | unit |
| AC-55 | no `completed` or `partially_completed` run of the chosen template (a `failed` one exists) | same | exactly `No earlier run of this template yet, so time and cost are not known. Try it on 1 company first: the run shows both.` | unit |
| AC-56 | step 3 stubbed: a flow with 1 company and the transition-plan template; the runs list empty | open step 3 | the AC-55 sentence is visible next to the start button before a run is started | unit (browser) |
| AC-57 | step 5 stubbed with a run of the template `transition_plan_indicators`; one field with name `A_headline_1` and description `Has the company set a net-zero target?` | read the Field cell of that row | it holds `Has the company set a net-zero target?` then `A_headline_1` (name then id) | unit (browser) |
| AC-58 | the same stub with 5 indicators (3 `walk`, 2 `talk`) and one supporting figure; one company with Yes for 2 walk and 1 talk indicators, No for 1 walk and not found for 1 talk | read that company's summary line on step 5 | exactly `Disclosed 3 of 5 · Walk 2 of 3 · Talk 1 of 2` | unit (browser) |
| AC-59 | the same stub; `GET /api/decision/runs/{run}/decision` returns one entity with `score` 62.5 and `tier_name` `Tier 2` | open step 5 | a section headed `Scoring` shows `62.5` and `Tier 2` for that company | unit (browser) |
| AC-60 | the same stub; that request answers 404 `No scoring template is attached to this run.` | open step 5 | the `Scoring` section shows the scoring-template picker and no error text | unit (browser) |
| AC-61 | step 5 stubbed with a run of any other template; a field named `revenue` with a description | read the Field cell | it reads `revenue` only (must not change) | unit (browser) |
| AC-62 | the e2e stack; viewport 1280 by 800 | on Transition Barriers click a criterion code in the first column | the detail heading `<code> — <criterion>` is inside the viewport and has keyboard focus | evaluator |
| AC-63 | the e2e stack | open `#/transitionPlan`, then step 3 of the flow it opened (`#/argus/<flow>/3`); read the template's line | it reads `64 indicators + 8 supporting figures`; `72 fields` is not shown for it | evaluator |
| AC-64 | the e2e stack | `GET /api/extraction/presets` | the transition-plan preset's `field_count` is `72` (must not change) | holdout |
| AC-65 | a review item whose `route_reasons` are `unreleased_version`, `check_failed`, `check:consistency.entity` | read the review detail | the line reads exactly `Routed for review: the template is not released yet, a check failed` | unit |
| AC-66 | a review item whose `route_reasons` are `some_new_code` | same | the line reads exactly `Routed for review: some new code` | unit |
| AC-67 | a review item whose `route_reasons` are only `check:consistency.entity` | same | no `Routed for review:` line is shown | unit |
| AC-68 | a registry company named `3f2b8c1e-5d47-4a9b-8c21-0a1b2c3d4e5f` and one named `Acme 3f2b` | `GET /api/companies?q=` | the response holds `Acme 3f2b` and no entry with the UUID name | unit |
| AC-69 | the UUID-named company | `GET /api/companies/{its id}` | 200 with that record (nothing is deleted; must not change) | unit |
| AC-70 | a flow with the company of AC-1; `GET /api/companies/E` has `documents` `0` | upload one file for it with `POST /api/argus/flows/{flow}/documents/upload` | `GET /api/companies/E` has `documents` `1` | holdout |
| AC-71 | after AC-70, a run reads and registers that same file | `GET /api/companies/E` | `documents` is still `1` | unit |

The words for AC-65, for every code: `unreleased_version` "the template is not released yet";
`not_applicable_by_rule` "a rule marks this field as not applicable"; `not_grounded` "the quote was not found
in the source"; `boolean_not_applicable` "a yes/no field was answered not applicable"; `first_audit_pending`
"the first audit of this field is not done yet"; `below_auto_accept_min` "confidence is below the auto-accept
level"; `high_risk_not_found` "a high-risk field was not found"; `check_failed` "a check failed";
`low_confidence` "low confidence"; `verifier_disagrees` "the verifier disagrees"; `conflict` "sources
conflict". Any other code is shown with underscores as spaces. Entries starting `check:` are left out of the
line: the failed checks are already listed in words above it.

### PR B: stewardship side, AC-72 to AC-172 (the last slice, no `Rows:` line)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-72 | an open issue with one open commitment (no target date) | `verify` with `{"commitment_id": id, "evidence": "  "}` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-73 | same | `verify` with `{"commitment_id": id, "evidence": ""}` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-74 | after AC-72 | `RECORD` | the commitment's `status` is `open` and the issue's `status` is `open` | holdout |
| AC-75 | an open commitment whose `target_date` is after today | `verify` with `{"commitment_id": id}` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-76 | same | `verify` with `{"commitment_id": id, "evidence": null}` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-77 | same | `verify` with `{"commitment_id": id, "evidence": "Board minutes 2026-11-01, p. 3"}` | 200; in `RECORD` the commitment's `status` is `verified` and its `evidence` is `Board minutes 2026-11-01, p. 3` | holdout |
| AC-78 | an open commitment with no target date | `verify` with `{"commitment_id": id}` | 200; in `RECORD` its `status` is `verified` (must not change, B2) | holdout |
| AC-79 | an open commitment whose `target_date` is yesterday | `verify` with `{"commitment_id": id}` | 200; in `RECORD` its `status` is `verified` (must not change, B2) | holdout |
| AC-80 | an open commitment whose `target_date` is after today | `track-verify` without `evidence` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-81 | an open commitment with no target date | `track-verify` with `"evidence": "  "` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-82 | an open commitment whose `target_date` is after today | `track-verify` with `"evidence": "Annual report 2026, p. 41"` | 200; in `RECORD` the commitment has `status` `verified` and `evidence` `Annual report 2026, p. 41` | holdout |
| AC-83 | an open commitment with no target date | `track-verify` without `evidence` | 200; in `RECORD` its `status` is `verified` (must not change, B2) | holdout |
| AC-84 | an open commitment | the same endpoint with `status: "missed"` and no `evidence` | 200; in `RECORD` its `status` is `missed` (must not change) | holdout |
| AC-85 | Engagement, an issue with an open commitment | click "Verify" on the commitment | a text field labelled `Evidence (required)` opens with a `Confirm verification` button that is disabled while the field is empty; in `RECORD` the commitment is still `open` | evaluator |
| AC-86 | after AC-85 | type `Board minutes p. 3` and click `Confirm verification` | the panel shows the commitment as verified, and in `RECORD` its `evidence` is `Board minutes p. 3` | evaluator |
| AC-87 | Stewardship, Tracking, an open commitment | click "Verified" | the same field and button appear; in `RECORD` the commitment is still `open` until confirmed | evaluator |
| AC-88 | an issue with status `resolved` | `POST …/issues/{i}/escalate` with `{"stage": "written_escalation_to_board", "reason": ""}` | 409; `detail` is exactly `A resolved or closed issue cannot be escalated.` | holdout |
| AC-89 | an issue with status `closed` | the same request | 409; the same `detail` | holdout |
| AC-90 | after AC-88 | `RECORD` | the issue's `escalation_stage` and the length of its `escalation_history` are what they were before | holdout |
| AC-91 | an open issue | the same request | 200; in `RECORD` the issue's `escalation_stage` is `written_escalation_to_board` (must not change) | holdout |
| AC-92 | Engagement, a resolved issue | open its panel | `Set escalation stage` is disabled and the sentence `A resolved or closed issue cannot be escalated.` is visible next to it | evaluator |
| AC-93 | a new issue | `outreach` with `{"summary": "S"}` twice | both answer 200; in `RECORD` the issue's `correspondence` has exactly 1 entry | holdout |
| AC-94 | after AC-93 | `outreach` with `{"summary": "T"}` | `correspondence` has exactly 2 entries | holdout |
| AC-95 | after AC-94 | `outreach` with `{"summary": "S"}` again | `correspondence` still has exactly 2 entries | holdout |
| AC-96 | an issue whose only commitment was verified (milestone `commitment_verified`, status `resolved`) | `outreach` with `{"summary": "U"}` | in `RECORD` the issue's `milestone_stage` is still `commitment_verified` and its `status` still `resolved` | holdout |
| AC-97 | a new issue (milestone `identified`) | `outreach` with `{"summary": "S"}` | `milestone_stage` is `contacted` (must not change) | holdout |
| AC-98 | an issue at milestone `dialogue_opened` | `log_outreach_sent` for it | `milestone_stage` is still `dialogue_opened` | unit |
| AC-99 | an issue at milestone `commitment_verified` | `log_meeting_summary_validated` for it | `milestone_stage` is still `commitment_verified` | unit |
| AC-100 | an issue at milestone `contacted` | `log_meeting_summary_validated` without commitments | `milestone_stage` is `response_received` (must not change) | unit |
| AC-101 | the issue panel stubbed with a drafted letter | click "Log outreach sent" twice | both requests carry the same `summary` | unit (browser) |
| AC-102 | `MET` read as `n`; an open commitment | a `verify` that is refused (AC-72), then read `MET` in the same test | it is still `n` | holdout |
| AC-103 | `MET` read as `n`; an open commitment | a `verify` that is accepted (AC-77), then read `MET` in the same test | it is `n + 1` | holdout |
| AC-104 | the e2e stack | open Engagement and click "Run scan" without typing | the company and signal inputs were empty; the message `Add at least one company and one signal with a company ID/name and theme filled in.` shows; `GET /api/engagement/records` lists what it listed before | evaluator |
| AC-105 | the e2e stack | click `Load sample` on the trigger-scan form | one company row `AAPL`, `Apple Inc.` and one signal row `AAPL`, `executive_compensation`, `high` are filled in | evaluator |
| AC-106 | no record for `C2` | `POST /api/engagement/trigger-scan` with companies `[{"company_id": "C1", "name": "Acme"}]` and signals `[{"company_id": "C2", "theme": "climate"}]` | 200; `events` has no entry for `C2`; `unlisted_signals` is exactly `{"count": 1, "company_ids": ["C2"]}` | holdout |
| AC-107 | after AC-106 | `GET /api/engagement/records/C2` | 404 (must not change) | holdout |
| AC-108 | none | the request of AC-106 with the signal's `company_id` `C1` | `unlisted_signals` is exactly `{"count": 0, "company_ids": []}` | holdout |
| AC-109 | none | the request of AC-106 with signals for `C3`, `C2`, `C2` (theme `climate` each) | `unlisted_signals` is exactly `{"count": 3, "company_ids": ["C2", "C3"]}` (every signal counted, ids distinct and sorted) | holdout |
| AC-110 | the e2e stack | on the form enter company `C1`, `Acme` and one signal `C2`, `climate`; click "Run scan" | the result shows `1 signal skipped: its company is not in the list (C2).` | evaluator |
| AC-111 | the scan response stubbed with `unlisted_signals` `{"count": 3, "company_ids": ["C2", "C3"]}` | run a scan | the result shows `3 signals skipped: their companies are not in the list (C2, C3).` | unit (browser) |
| AC-112 | an issue of company `NODOCS`, `No Docs AG`, with no documents, ticker or CIK | `POST …/issues/{i}/dossier` with `{"company_id": "NODOCS", "name": "No Docs AG"}` | 422; `detail` is exactly `No documents are loaded for No Docs AG (NODOCS). Upload them in Data Library, then draft the dossier.` | holdout |
| AC-113 | same, with model stand-ins recording calls | same | no model call is recorded | unit |
| AC-114 | Engagement, an issue of a company with no documents | start the dossier draft in the panel | the AC-112 sentence, with that company's name and id, is shown in the panel | evaluator |
| AC-115 | a company with one document | `research_company_issue` | the model is called and a dossier is returned (must not change) | unit |
| AC-116 | a voting run stubbed with 5 decided votes | click the cast button and read the dialog | its text is exactly `This records 5 votes as voting instructions, one file per vote, to be entered on the ballot platform by hand. Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.` | unit (browser) |
| AC-117 | the same with 1 decided vote | same | exactly `This records 1 vote as a voting instruction, in its own file, to be entered on the ballot platform by hand. Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.` | unit (browser) |
| AC-118 | the stub of AC-116; the cast request answers with 5 cast votes; signed in as `Ana` | confirm the dialog | the banner starts `5 votes recorded as voting instructions by Ana at` and ends `The instruction reference is shown on each proposal below.` | unit (browser) |
| AC-119 | a cast vote with `confirmation_id` `conf_abc` | read its proposal | it shows `Recorded · instruction ref conf_abc` | unit (browser) |
| AC-120 | 2 flagged votes without co-sign | read the warning in the cast dialog | exactly `2 flagged votes have no co-sign and will be refused when the votes are recorded.` (`1 flagged vote has` for one) | unit (browser) |
| AC-121 | the cast request answers 400 with detail `X` | confirm the dialog | the error reads exactly `Recording the votes failed: X. Nothing was recorded; try again.` | unit (browser) |
| AC-122 | the states of AC-116 to AC-121 | read the whole page in each | none contains `This sends`, `Confirmation ID`, `confirmation conf_`, `by the platform`, `submitted`, or `sent to` outside the sentence `Nothing is sent to a ballot platform from here.` (any letter case) | unit (browser) |
| AC-123 | a `say_on_pay` proposal with a rule-based recommendation at confidence 1.0 and no alignment flag | the routine test | not routine | unit |
| AC-124 | a proposal of type `other`, rule `rule_routine_management_proposal`, confidence 1.0, text one of `Approve the redomiciliation of the Company to Delaware`, `REINCORPORATION IN NEVADA`, `Change of the jurisdiction of incorporation`, `Re-domiciliation to Ireland` | same | not routine, for each text | unit |
| AC-125 | the same proposal with the text `Amend the articles of association` | same | routine | unit |
| AC-126 | a `capital_action` proposal with a rule-based recommendation, text `Routine item.`, confidence 0.59 and then 0.6 | same | not routine at 0.59; routine at 0.6 | unit |
| AC-127 | a `director_election` proposal whose recommendation has `policy_rule_id` null and confidence 0.95 | same | not routine | unit |
| AC-128 | a `capital_action` proposal, rule-based, confidence 1.0, text `Routine item.`, no alignment flag | same | routine (must not change) | unit |
| AC-129 | a run stubbed with the proposals of AC-123, AC-127, AC-128 and the first text of AC-124 | read the sweep button, confirm it | the button reads `Approve 1 routine…` and exactly 1 review request is sent | unit (browser) |
| AC-130 | `GET /api/runs/{id}` stubbed `running`, 2 of 5 companies done; ballots `[]` | open the run's page | it shows `This voting run is still in progress (2 of 5 companies done). Ballots appear here as they are ready.` and not `No ballots in this run yet` | unit (browser) |
| AC-131 | the same stubbed `pending`, 0 of 5 done | same | it shows `This voting run is still in progress (0 of 5 companies done). Ballots appear here as they are ready.` | unit (browser) |
| AC-132 | the same stubbed `failed`; ballots `[]` | same | it shows `This voting run stopped before any ballot was ready (status: failed). Run History shows why.` and not `No ballots in this run yet` (`cancelled` reads the same with its status) | unit (browser) |
| AC-133 | the run stubbed `completed`; ballots `[]` | same | it shows `No ballots in this run yet: none of its companies has a proxy statement for an upcoming meeting. Start a new voting run once one is filed.` (must not change) | unit (browser) |
| AC-134 | a voting run with a ballot item | `POST /api/voting/runs/{id}/review` with `decision` `edit`, a `vote`, and `comment` missing or `"  "` | 400; `detail` is exactly `An override needs a reason.`; the run's stored review decisions are unchanged | unit |
| AC-135 | same | the same request with `comment` `Board lacks independence` | `{"status": "recorded"}` | unit |
| AC-136 | same | `decision` `approve` without `comment` | `{"status": "recorded"}` (must not change) | unit |
| AC-137 | a stubbed run; a proposal's override block is open | read it | a field labelled `Reason for the override (required)` is shown and `Record override` is disabled while it is empty | unit (browser) |
| AC-138 | the e2e stack (seeded demo data) | open Stewardship, Monitoring | at least 1 trigger row has a reason containing `CLTI score`, and each such row shows a `Sample data` chip | evaluator |
| AC-139 | same | same | no trigger row whose reason does not contain `CLTI` shows the chip | evaluator |
| AC-140 | the e2e stack | open the Stewardship overview | the note containing `CLTI scores are placeholders` starts with a `Sample data` chip | evaluator |
| AC-141 | the client program page stubbed with a `score_note` and its figures | open it | the score note starts with a `Sample data` chip and the `Weighted CLTI` tile carries one; the `Active share` tile does not | unit (browser) |
| AC-142 | the e2e stack | open Stewardship, Checkpoint, and then Reporting | each of the two screens shows at least 1 block with the sentence `Designed in the operating model, not built yet.` and a `Not built yet` chip next to that block's heading | evaluator |
| AC-143 | the e2e stack | `GET /api/stewardship/universe` | `note` contains `placeholders` (must not change) | holdout |
| AC-144 | Stewardship stubbed with an outreach draft whose `authors` are `["Ana"]`, waiting for approval; signed in as `Ana` | open it | next to the disabled `Approve for sending` the page shows, as text, `A second person is needed: this draft was written by Ana, and someone who did not write it approves it.` | unit (browser) |
| AC-145 | RFP stubbed: signed in as an approver whose `user_id` is the answer's `last_editor`; the answer is not approved | open the answer | where the Approve button would be, the page shows `A second person is needed: you edited this answer last, and another approver must approve it.` | unit (browser) |
| AC-146 | an outreach draft | its author approves it through the API | 422 whose text contains `Four-eyes` (the rule is unchanged; must not change) | unit |
| AC-147 | an engagement record | `POST /api/engagement/records/{c}/contacts` with `{"name": "A", "role": "IR", "email": "not-an-email"}` | 422; `detail` is exactly `Enter a valid email address, or leave it empty.` | holdout |
| AC-148 | same | the same request with `email` `a@b`, and again with `a b@c.de` | 422 both times with the same `detail` | holdout |
| AC-149 | after AC-147 | `RECORD` | `contacts` is what it was before | holdout |
| AC-150 | an engagement record | the same request with `email` `a@example.org`, again with null, again with `""` | 200 each time; the contact is in `contacts` (must not change) | holdout |
| AC-151 | a stored record that holds a contact with `email` `not-an-email` | `RECORD` | 200 with that contact (must not change) | unit |
| AC-152 | `fund_name` `Alpha Fund`; the model stand-in returns subject `Engagement request from [Fund name]` and a body containing `[Fund name]` | `POST …/outreach-letter` | subject and body contain `Alpha Fund` and no `[Fund name]`; `placeholders` is `[]` | unit |
| AC-153 | `fund_name` unset; the same stand-in | same | subject and body are unchanged and `placeholders` is exactly `["[Fund name]"]` | unit |
| AC-154 | `fund_name` unset; the dossier cites `doc_1`; the body contains `[Date]`, `[doc_1]` and `[Date]` again, the subject `[Fund name]` | same | `placeholders` is exactly `["[Fund name]", "[Date]"]` | unit |
| AC-155 | the letter response stubbed with `placeholders` `["[Fund name]"]` | read the letter in the panel | `Fill in before sending: [Fund name]` is shown above it | unit (browser) |
| AC-156 | the calibration schedule holds values `V` | `PUT /api/calibration/schedule` with `{"enabled": true, "interval_hours": 0}` | 422 | holdout |
| AC-157 | same | the same request with `{"enabled": false, "interval_hours": 0}` | 422 | holdout |
| AC-158 | after AC-156 and AC-157 | `GET /api/calibration/schedule` | the values are `V` | holdout |
| AC-159 | the e2e stack | `PUT /api/taxonomy-researcher/schedule` with `enabled` true and `interval_hours` `0`, and again with `0.5` | 422 both times | holdout |
| AC-160 | the e2e stack | `PUT /api/calibration/schedule` with `{"enabled": false, "interval_hours": 1}`, and again with `1.5` | 200 both times; `GET` then returns the `interval_hours` just sent (must not change) | holdout |
| AC-161 | a schedule file stored earlier with `enabled` true and `interval_hours` 0 | start the scheduler and let one run finish | no second run starts within 3,600 seconds of the first | unit |
| AC-172 | the same stored file | `GET /api/calibration/schedule` | 200 with `interval_hours` `0` (the stored file is not rewritten; the scheduler reads anything below 1 as 1 hour) | unit |
| AC-162 | the e2e stack | on Background Agents enter interval `0` on the Calibration Agent and save | `Interval must be at least 1 hour.` is shown next to the field and `GET /api/calibration/schedule` is unchanged | evaluator |
| AC-163 | the e2e stack | enter interval `24` and save | `Saved.` appears next to the save button | evaluator |
| AC-164 | the e2e stack | on the Calibration Agent click `Scan now` and do not press "Refresh results" | within 10 seconds "Past runs" has 1 more row than before; within 60 seconds that row shows a finished status (`completed`, `partially_completed` or `failed`), without a reload | evaluator |
| AC-165 | the e2e stack | `POST /api/universe/upload` with a CSV `name` / `Acme` | 422; `detail` is exactly `Row 1: company_id is required.` | holdout |
| AC-166 | the e2e stack | the same upload with a CSV `company_id,name` whose rows are `A,Acme`, `,Beta`, `,Gamma` | 422; `detail` is exactly `Row 2: company_id is required.` | holdout |
| AC-167 | the e2e stack | the same upload with a JSON file `[{"company_id": "A", "name": 5}]` | 422; `detail` starts `Row 1: name is not valid` and contains none of `pydantic`, `input_value`, `validation error` | holdout |
| AC-168 | the e2e stack | upload a CSV `company_id,name` / `A,Acme` | 200 with `path`, `company_count` `1` and `sample` (must not change) | holdout |
| AC-169 | the e2e stack | on Proxy Voting upload `universe.csv` with 3 companies | the page shows `3 companies loaded from universe.csv` and no server path | evaluator |
| AC-170 | any screen whose action writes to the live region `#announcer` (stubbed if needed) | do the action, then open another screen | `#announcer` is empty | unit (browser) |
| AC-171 | same | do the action and stay on the screen | `#announcer` holds the announced text (must not change) | unit (browser) |

Must not change: AC-6, AC-13, AC-18, AC-20, AC-28, AC-33, AC-44, AC-46, AC-48, AC-49, AC-50, AC-61, AC-64,
AC-69, AC-78, AC-79, AC-83, AC-84, AC-91, AC-97, AC-100, AC-107, AC-115, AC-128, AC-133, AC-136, AC-143,
AC-146, AC-150, AC-151, AC-160, AC-168, AC-171, and every existing test.

## Follow-ups (not in this change)

- Document type shown raw in Data Library, citation lists and the review source list.
- The tooltip-only four-eyes reason on "Activate" in the versions panel.
- The outreach author check compares user id with display name; they differ with real users.
- `arp voting review` (CLI) still accepts an override without a reason.
- A verdict label for walk versus talk, if the owner wants a rule for one.
