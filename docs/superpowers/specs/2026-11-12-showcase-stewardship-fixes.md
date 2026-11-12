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
   `in_scope: false`, `reason: "No ISIC code"`. The column `isic_code` already exists. Rows without a valid
   LEI, ISIN or CIK create no registry company, so they have nowhere to keep the code.
2. **Identity lookup dies on a failed lookup.** `backend/arp/discovery/identity_agents.py` `gather_signals`
   awaits `edgar.search_by_name` and then `search_client.search` with no guard; GLEIF comes last. Either
   failure ends the company's step. The run itself survives (`batch_runner.py` writes an error row), but
   `str(httpx.ConnectTimeout(""))` is `""`, so the reason is empty, and `FailureDetails.tsx` prints "No
   traceback was recorded for this run." whenever the run-level traceback is null, although each company
   error carries its own traceback.
3. **Barrier derivation gives "Not rated" without warning.** With `transition_barrier_refresh_enabled` off,
   `derivation.py` fetches nothing and notes "Sources not fetched: refresh is disabled". A cell with facts
   entered by hand is still rated; a cell without facts is "Not rated". No API tells the page whether the
   switch is on. Refusing the run is not possible: `test_tb_derivation.py` pins a run with the switch off.
   The rehearsal also saw "Nothing is waiting for review" after such a run; the code queues one item per cell,
   so the cause is not known from reading and the behaviour is pinned by AC-22.
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
    `interval_hours: 0` with `enabled` makes the scheduler run back to back. The live region `#announcer` is
    never cleared, so "14 tiers confirmed." stays in the page text.

## Goals

- G1. A company added through an Argus list keeps its `isic_code`, and an existing company without one gets it.
- G2. Identity lookup survives a failed EDGAR or web-search lookup, still asks GLEIF, and records the reason.
  A failure reason is never empty, and a company's traceback is shown.
- G3. Before a barrier derivation starts, the page says what it will use when the refresh is switched off.
- G4. The Calibration Agent compares against a document date and shows names.
- G5. Engagement: verifying asks for evidence; a resolved issue cannot be escalated; a repeated "Log outreach
  sent" adds nothing and never moves the milestone back; "Commitments met" follows from that.
- G6. The trigger-scan form starts empty and the scan reports signals for companies not in its list.
- G7. Drafting a dossier with no documents says that documents must be loaded first, without a model call.
- G8. Voting wording matches what happens; the routine sweep leaves out say-on-pay, low-confidence,
  model-judged and redomiciliation proposals; a run in progress says so; an override needs a reason.
- G9. An annual report's year is its period of report; the search status stops saying "Searching…" once files
  are listed.
- G10. Transition plan: a file uploaded for a company passes the entity check; results show the question, the
  walk and talk counts, and score and tier where a scoring template is attached; time and cost of the last
  run are stated before starting.
- G11. Everything shown from placeholder scores carries a "Sample data" mark; planned parts carry "Not built yet".
- G12. Where four-eyes blocks the signed-in person, the page says in plain text that a second person is needed.
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

## Anti-goals

- An existing test is changed, weakened or deleted.
- A guard that only hides a button while the API still accepts the bad request from the screen's own call.
- Wording that still claims a vote is sent to a platform.
- A "Sample data" mark on live data, or live data losing its source label.

## Constraints

- Build on `main` once #413 is merged; if it is not, branch from `fix/showcase` and merge `main`. The PR base
  is `main` either way.
- Owner's rules: every fix has a test that failed before, with its output in the PR description; no existing
  test changes; two PRs.
- Request or response models that change (`VerifyCommitmentRequest`, `CommitmentStatusRequest`, the schedule
  configs if validated in the model) need `export_openapi.py` and `npm run gen:api`, both files committed.
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
  of Tn` (computed from the values, no model call) and the existing Scoring panel (score and tier when a
  scoring template is attached, the template picker otherwise). No verdict label. This is the recommended
  option put to the owner with the spec; AC-49 to AC-51.

## Builder's calls (not asked; the owner may overrule at approval)

- **B1.** The empty flow per Transition Plan visit is not fixed here. The Argus switch-over spec requires
  every such visit to open a new flow (`test_argus_switchover.py`, AC-63 and AC-64 there, pinned). What the
  presenter sees is a start page filling with empty drafts, which is showcase-argus-fixes item 7
  (`ArgusStart.tsx`). That feature is asked to treat drafts made by `openNewFlow` the same way.
- **B2.** Evidence on verify. The screens always ask for it. The API refuses a blank `evidence`, and refuses a
  missing one when the commitment's target date is after today. A missing `evidence` on a commitment that is
  due or has no date is still accepted, because `test_actor_from_principal.py` posts exactly that.
- **B3.** Calibration date: `published_at`; without it, `fetched_at` only when it is earlier than the moment
  the check started (a stored time, not one stamped by the check). A document with neither is ignored. This
  keeps the two pinned tests green.
- **B4.** A recommendation the model judged (no `policy_rule_id`) is never "routine", whatever its confidence.
  The low-confidence line is 0.6, the same number as `confidence_review_threshold`.
- **B5.** Voting buttons keep the verb "Cast"; the dialog, the result banner, the per-proposal line and the
  co-sign warning say what is recorded.
- **B6.** EDGAR lookup failure is tolerated like web-search failure: both can be blocked in the bank setup.
- **B7.** A file uploaded or crawled into a company's own folder passes the entity check unless the document
  names another company (foreign LEI or legal name: still a mismatch). Step 2 already checked the name.
- **B8.** The estimate before a run is the last finished run of the same template, stated as it was, not
  scaled to the number of companies.
- **B9.** Barrier derivation is never refused; the page says beforehand what it will use.
- **B10.** Escalating a resolved or closed issue answers 409; missing evidence, no documents and a bad email
  answer 422; a missing override reason answers 400 like the checks next to it.
- **B11.** Schedules accept whole or fractional hours from 1 upward; 0.5 is refused.
- **B12.** Universe errors name the first bad row only.

## Shared files with showcase-argus-fixes

Different functions in each file; whoever merges second merges `main` first.

| File | This feature owns | showcase-argus-fixes owns |
|---|---|---|
| `backend/arp/discovery/identity_agents.py` | `gather_signals` failure handling, `lookup_errors`, the prompt line for a failed lookup | which identifiers are accepted (ticker alone) |
| `frontend/src/pages/ArgusDocuments.tsx` | nothing; the status text is `searchStatusText` in `lib/argusFlow.ts` | `DOC_TYPES`, the Keep block, the Type cell (all types) |
| `frontend/src/pages/ArgusStart.tsx` | nothing | `start()`, removing drafts, drafts made by `openNewFlow` (B1) |
| `frontend/src/pages/ArgusResults.tsx` | question in the Field cell for the transition-plan template, the walk and talk line, the Scoring panel | "How was this found?", skipped companies, the period column |
| `frontend/src/pages/ArgusSchema.tsx` | the estimate sentence by the start button, "64 indicators + 8 supporting figures" | saved-schema layout, field ids |
| `backend/arp/argus/companies.py` | `isic_code` in `_FIELDS` and the fill on an existing company | keys of unmatched rows, conflict handling |
| `backend/arp/argus/documents.py`, `backend/arp/ingestion/edgar.py` | the year of an EDGAR annual report | uploads counted before "Keep" |

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

Checked by. `holdout`: hidden test against the app started by `backend/scripts/e2e_stack.sh up` (dev sign-in,
no model key, barrier refresh off, `ARP_FUND_NAME` unset). `HOLDOUT_TOKEN` status is not known to the author;
if it is unset, the PR lists its `holdout` rows as owed and covers them with its own tests. `evaluator`: the
same stack, used through the browser. `unit`: the implementer's test; "unit (browser)" is a Playwright test in
`backend/tests/e2e` with the named API routes stubbed, as `test_rfp_page.py` does. Every `unit` row's test is
shown failing before the fix in the PR description.

Fixtures. `L1`, `L2`: valid LEIs the registry does not hold yet. A "list" is a CSV uploaded to
`POST /api/argus/flows/{flow}/companies/upload`; `E` is the `entity_id` of its row in the response. An
"engagement issue" is made with `POST /api/engagement/records` and `POST /api/engagement/records/{c}/issues`;
a commitment with `POST /api/stewardship/tracking/commitments`; "resolved" through
`POST /api/stewardship/tracking/close`. `verify` is
`POST /api/engagement/records/{c}/issues/{i}/verify-commitment`; `track-verify` is
`POST /api/stewardship/tracking/commitments/{id}` with `status: "verified"`. `EVIDENCE_MSG` is exactly
`Evidence is required to verify a commitment.` `NOTE_OFF` is exactly `Re-checking sources is switched off on
this server, so a derivation uses only facts entered by hand and documents already stored. Cells without
facts come out as Not rated.` Times are ISO strings with offset `+00:00` unless written otherwise.

### PR A: transition side (`Rows: AC-1` to `AC-61`)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | a new flow; no company with `L1` | upload the list `name,lei,isic_code` / `Acme Power AG,L1,3510` | `GET /api/companies/E` has `isic_code` `"3510"` | holdout |
| AC-2 | after AC-1 | `GET /api/companies/E/transition` | `in_scope` is `true` and `sector` is `"Power & Utilities"` | holdout |
| AC-3 | a company created by the list `name,lei` / `Acme Steel AG,L2` (its `isic_code` is null) | upload the list `name,lei,isic_code` / `Acme Steel AG,L2,2410` to any flow | `GET /api/companies/E` has `isic_code` `"2410"` | holdout |
| AC-4 | the company of AC-1 (`isic_code` `"3510"`) | upload the list `name,lei,isic_code` / `Acme Power AG,L1,2410` | `GET /api/companies/E` still has `isic_code` `"3510"` | holdout |
| AC-5 | a company created by a list without an `isic_code` column | `GET /api/companies/E/transition` | `in_scope` is `false` and `reason` is `"No ISIC code"` (must not change) | holdout |
| AC-6 | `gather_signals` with a web-search client that raises `httpx.ConnectTimeout("")` and a GLEIF client that returns one match | call it | it returns; `gleif_matches` has that one match and `search_results` is `[]` | unit |
| AC-7 | same | same | `lookup_errors` is exactly `["web search: ConnectTimeout"]` | unit |
| AC-8 | `gather_signals` with an EDGAR source that raises `httpx.ConnectError("boom")` | call it | it returns; `edgar_matches` is `[]` and `lookup_errors` is exactly `["EDGAR: ConnectError: boom"]` | unit |
| AC-9 | same | same | the web-search client received both queries and the GLEIF client was asked | unit |
| AC-10 | the signals of AC-7 | the adjudication prompt is built | it contains the line `Web search results: not available (ConnectTimeout)` and not `Web search results: none found` | unit |
| AC-11 | a web search that succeeds with no hits | the adjudication prompt is built | it contains `Web search results: none found` (must not change) | unit |
| AC-12 | all lookups succeed | `gather_signals` | `lookup_errors` is `[]`; an `IdentitySignals` stored without that key still loads | unit |
| AC-13 | a batch run where one company's step raises `httpx.ReadTimeout("")` | read the run's error rows | that row's `error` is `"ReadTimeout"` | unit |
| AC-14 | a batch run where one company's step raises `RuntimeError("boom")` | read the run's error rows | that row's `error` is `"boom"` (must not change) | unit |
| AC-15 | `GET /api/runs/{id}/failure` stubbed: `traceback` null, one `company_errors` entry `{key: "acme", error: "ReadTimeout", traceback: "Traceback (most recent call last): X"}` | open Run History, Details of that run | the text `Traceback (most recent call last): X` is on the page under `acme`, and `No traceback was recorded for this run.` is not | unit (browser) |
| AC-16 | same stub with no traceback on the run or on any company | open Details | `No traceback was recorded for this run.` is shown (must not change) | unit (browser) |
| AC-17 | the e2e stack | `GET /api/transition-barrier/matrix` | the body has `refresh_enabled` `false` | holdout |
| AC-18 | the e2e stack; any cell of the matrix | `GET /api/transition-barrier/cells/{code}/{region}` | the body has `refresh_enabled` `false` | holdout |
| AC-19 | `transition_barrier_refresh_enabled` true | both requests of AC-17 and AC-18 | `refresh_enabled` is `true` in both | unit |
| AC-20 | the e2e stack | open Transition Barriers | `NOTE_OFF` is visible next to "Derive all regions" before anything is clicked | evaluator |
| AC-21 | the e2e stack | open any cell's page | `NOTE_OFF` is visible next to "Derive this cell" before anything is clicked | evaluator |
| AC-22 | the e2e stack; a cell with no facts | click "Derive this cell", then "Review the result" | the review page lists exactly 1 open item, for that cell, and does not show `Nothing is waiting for review in this run.` | evaluator |
| AC-23 | matrix and cell responses stubbed with `refresh_enabled` true | open both pages | `NOTE_OFF` appears on neither | unit (browser) |
| AC-24 | the e2e stack | `POST /api/transition-barrier/derive` for one cell | 200 with a `run_id` (never refused; must not change) | holdout |
| AC-25 | one document with `published_at` `2026-01-10T00:00:00+00:00` and `fetched_at` left to its default; one match with `generated_at` `2026-02-01T00:00:00+00:00` | `check_company_staleness` | returns `[]` | unit |
| AC-26 | one document with `published_at` `2026-03-01T00:00:00+00:00`; the same match | same | one flag; its `newest_document_at` is `2026-03-01T00:00:00+00:00` | unit |
| AC-27 | one document with no `published_at` and `fetched_at` stamped during the call | same | returns `[]` | unit |
| AC-28 | one document with no `published_at` and `fetched_at` `2026-02-01T00:00:00+00:00`; a match with `generated_at` `2026-01-01T00:00:00+00:00` | same | one flag; `newest_document_at` is `2026-02-01T00:00:00+00:00` (must not change) | unit |
| AC-29 | one document with `published_at` `2026-02-10T16:31:00.000Z`; a match with `generated_at` `2026-02-10T17:00:00+00:00` | same | returns `[]` (instants are compared, not strings) | unit |
| AC-30 | the flag of AC-26; the match has `name` `Coca-Cola Co` and `activity_name` `Soft drinks` | read the flag | `company_name` is `Coca-Cola Co` and `activity_name` is `Soft drinks` | unit |
| AC-31 | the flag of AC-26 | read the flag | `reason` is exactly `A disclosure dated after this verdict was generated exists -- re-running classification is recommended.` | unit |
| AC-32 | calibration results stubbed with one flag: `company_id` `ko`, `company_name` `Coca-Cola Co`, `activity_id` `act_dd5b90051fcd`, `activity_name` `Soft drinks` | open Background Agents, the run's results | the Company cell reads `Coca-Cola Co` and the Activity cell reads `Soft drinks`; each id appears only as small text under its name | unit (browser) |
| AC-33 | the same stub without the two name fields (a stored older result) | same | the cells read `ko` and `act_dd5b90051fcd` | unit (browser) |
| AC-34 | an EDGAR 10-K of `Acme Corp` with `filingDate` `2026-02-14` and `reportDate` `2025-12-31`, found by a new search of a flow whose expected year is 2025; the document names `Acme Corp` | `GET /api/argus/flows/{id}` | that file's `year` is `2025` | unit |
| AC-35 | same | same | that file's `passes` is `true` and its `check` is exactly `✓ Acme Corp, 2025` | unit |
| AC-36 | same | `POST /api/argus/flows/{id}/files` with `{"all_that_pass": true}` | that file has the state a hand-kept file has | unit |
| AC-37 | the same filing without a `reportDate` | `GET /api/argus/flows/{id}` | `year` is `2026` and `check` is exactly `Year 2026, expected 2025` (must not change) | unit |
| AC-38 | Argus step 2; the search run is `running` and 3 files are listed | read the status text | exactly `3 found so far, still checking other sources…`; `Searching…` is not shown | unit |
| AC-39 | Argus step 2; the search run is `running` and no file is listed | read the status text | exactly `Searching…` (must not change) | unit |
| AC-40 | a document with `local_path` set, no `source_url`, `company_id` equal to the company's, title `report.txt`, and text without the company's legal name, LEI or CIK | `confirm_entity` | the status is confirmed | unit |
| AC-41 | the same document with another company's `company_id` | same | the status is ambiguous (must not change) | unit |
| AC-42 | the document of AC-40 whose first 5,000 characters carry another company's LEI | same | the status is mismatch (must not change) | unit |
| AC-43 | a document with the company's `company_id`, no `local_path` and no name, LEI or CIK signal | same | the status is ambiguous (must not change) | unit |
| AC-44 | an extraction run over the document of AC-40 only | read the run's results | no field's `route_reasons` contains `check:consistency.entity` | unit |
| AC-45 | Argus step 3; the latest finished run of the chosen template had 1 company, ran 13 minutes from `created_at` to `updated_at` and has `estimated_cost_usd` 8.58 | read the text next to the start button | exactly `The last run of this template took 13 min and $8.58 for 1 company.` (`companies` for more than one) | unit |
| AC-46 | Argus step 3; no finished run of the chosen template | same | exactly `No earlier run of this template yet, so time and cost are not known. Try it on 1 company first: the run shows both.` | unit |
| AC-47 | the e2e stack; no finished transition-plan run | open Transition Plan, add one company, go to step 3 | the AC-46 sentence is visible next to the start button before a run is started | evaluator |
| AC-48 | step 5 stubbed with a run of the template `transition_plan_indicators`; one field with name `A_headline_1` and description `Has the company set a net-zero target?` | read the Field cell of that row | it reads `Has the company set a net-zero target?` with `A_headline_1` in small text under it | unit (browser) |
| AC-49 | the same stub with 5 indicators (3 walk, 2 talk) and the value Yes for 2 walk and 1 talk indicators of one company | read that company's summary line on step 5 | exactly `Disclosed 3 of 5 · Walk 2 of 3 · Talk 1 of 2` | unit (browser) |
| AC-50 | the same stub; `GET /api/decision/runs/{run}/decision` returns one entity with `score` 62.5 and `tier_name` `Tier 2` | open step 5 | a section headed `Scoring` shows `62.5` and `Tier 2` for that company | unit (browser) |
| AC-51 | the same stub; that request answers 404 `No scoring template is attached to this run.` | open step 5 | the `Scoring` section shows the scoring-template picker and no error text | unit (browser) |
| AC-52 | step 5 stubbed with a run of any other template; a field named `revenue` with a description | read the Field cell | it reads `revenue` (must not change) | unit (browser) |
| AC-53 | the e2e stack; viewport 1280 by 800 | on Transition Barriers click a criterion code in the first column | the detail heading `<code> — <criterion>` is inside the viewport and has keyboard focus | evaluator |
| AC-54 | the e2e stack | open Transition Plan, go to step 3, read the template's line | it reads `64 indicators + 8 supporting figures`; `72 fields` is not shown for it | evaluator |
| AC-55 | the e2e stack | `GET /api/extraction/presets` | the transition-plan preset's `field_count` is `72` (must not change) | holdout |
| AC-56 | a review item whose `route_reasons` are `unreleased_version`, `check_failed`, `check:consistency.entity` | read the review detail | the line reads exactly `Routed for review: the template is not released yet, a check failed` | unit |
| AC-57 | a review item whose `route_reasons` are `some_new_code` | same | the line reads exactly `Routed for review: some new code` | unit |
| AC-58 | a registry company named `3f2b8c1e-5d47-4a9b-8c21-0a1b2c3d4e5f` and one named `Acme 3f2b` | `GET /api/companies?q=` | the response holds `Acme 3f2b` and no entry with the UUID name | unit |
| AC-59 | the UUID-named company | `GET /api/companies/{its id}` | 200 with that record (nothing is deleted; must not change) | unit |
| AC-60 | a flow with the company of AC-1; no document of it registered | upload one file for it with `POST /api/argus/flows/{flow}/documents/upload` | `GET /api/companies/E` has `documents` `1` | holdout |
| AC-61 | after AC-60, a run reads and registers that same file | `GET /api/companies/E` | `documents` is still `1` | unit |

The words for AC-56, for every code: `unreleased_version` "the template is not released yet";
`not_applicable_by_rule` "a rule marks this field as not applicable"; `not_grounded` "the quote was not found
in the source"; `boolean_not_applicable` "a yes/no field was answered not applicable"; `first_audit_pending`
"the first audit of this field is not done yet"; `below_auto_accept_min` "confidence is below the auto-accept
level"; `high_risk_not_found` "a high-risk field was not found"; `check_failed` "a check failed";
`low_confidence` "low confidence"; `verifier_disagrees` "the verifier disagrees"; `conflict` "sources
conflict". Any other code is shown with underscores as spaces. Entries starting `check:` are left out of the
line: the failed checks are already listed in words above it.

### PR B: stewardship side (the last slice, no `Rows:` line)

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-62 | an open issue with one open commitment (no target date) | `verify` with `{"commitment_id": id, "evidence": "  "}` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-63 | after AC-62 | `GET /api/engagement/records/{c}` | the commitment's `status` is `open` and the issue's `status` is `open` | holdout |
| AC-64 | an open commitment whose `target_date` is after today | `verify` with `{"commitment_id": id}` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-65 | the commitment of AC-64 | `verify` with `{"commitment_id": id, "evidence": "Board minutes 2026-11-01, p. 3"}` | 200; the commitment's `status` is `verified` and its `evidence` is `Board minutes 2026-11-01, p. 3` | holdout |
| AC-66 | an open commitment with no target date | `verify` with `{"commitment_id": id}` | 200; `status` is `verified` (must not change, B2) | holdout |
| AC-67 | an open commitment whose `target_date` is after today | `track-verify` without `evidence` | 422; `detail` is `EVIDENCE_MSG` | holdout |
| AC-68 | same | `track-verify` with `"evidence": "Annual report 2026, p. 41"` | 200; the record's commitment has `status` `verified` and `evidence` `Annual report 2026, p. 41` | holdout |
| AC-69 | an open commitment | the same endpoint with `status: "missed"` and no `evidence` | 200; `status` is `missed` (must not change) | holdout |
| AC-70 | Engagement, an issue with an open commitment | click "Verify" on the commitment | a text field labelled `Evidence (required)` opens with a `Confirm verification` button that is disabled while the field is empty; the commitment is still open | evaluator |
| AC-71 | Stewardship, Tracking, an open commitment | click "Verified" | the same field and button appear; the commitment is still open until confirmed | evaluator |
| AC-72 | a resolved issue | `POST …/issues/{i}/escalate` with `{"stage": "written_escalation_to_board", "reason": ""}` | 409; `detail` is exactly `A resolved or closed issue cannot be escalated.` | holdout |
| AC-73 | after AC-72 | `GET /api/engagement/records/{c}` | the issue's `escalation_stage` and the length of its `escalation_history` are what they were before | holdout |
| AC-74 | an open issue | the same request | 200; the issue's `escalation_stage` is `written_escalation_to_board` (must not change) | holdout |
| AC-75 | Engagement, a resolved issue | open its panel | `Set escalation stage` is disabled and the sentence `A resolved or closed issue cannot be escalated.` is visible next to it | evaluator |
| AC-76 | a new issue | `POST …/log-outreach-sent` with `{"summary": "S"}` twice | both answer 200; the issue's `correspondence` has exactly 1 entry | holdout |
| AC-77 | after AC-76 | the same request with `{"summary": "T"}` | `correspondence` has exactly 2 entries | holdout |
| AC-78 | an issue whose only commitment was verified (milestone `commitment_verified`, status `resolved`) | `POST …/log-outreach-sent` with `{"summary": "U"}` | the issue's `milestone_stage` is still `commitment_verified` and its `status` still `resolved` | holdout |
| AC-79 | a new issue (milestone `identified`) | `POST …/log-outreach-sent` with `{"summary": "S"}` | `milestone_stage` is `contacted` (must not change) | holdout |
| AC-80 | an issue at milestone `commitment_verified` | `log_meeting_summary_validated` for it | `milestone_stage` is still `commitment_verified` | unit |
| AC-81 | "Commitments met" in the tracking stage of `GET /api/stewardship/streams/house/flow` is `n` | a `verify` that is refused (AC-62) | the value is still `n` | holdout |
| AC-82 | same | a `verify` that is accepted (AC-65) | the value is `n + 1` | holdout |
| AC-83 | the e2e stack | open Engagement and click "Run scan" without typing | the company and signal inputs were empty; the message `Add at least one company and one signal with a company ID/name and theme filled in.` shows; `GET /api/engagement/records` lists what it listed before | evaluator |
| AC-84 | the e2e stack | click `Load sample` on the trigger-scan form | one company row `AAPL`, `Apple Inc.` and one signal row `AAPL`, `executive_compensation`, `high` are filled in | evaluator |
| AC-85 | no record for `C2` | `POST /api/engagement/trigger-scan` with companies `[{"company_id": "C1", "name": "Acme"}]` and signals `[{"company_id": "C2", "theme": "climate"}]` | 200; `events` has no entry for `C2`; `unlisted_signals` is exactly `{"count": 1, "company_ids": ["C2"]}` | holdout |
| AC-86 | after AC-85 | `GET /api/engagement/records/C2` | 404 (must not change) | holdout |
| AC-87 | none | the same request with the signal's `company_id` `C1` | `unlisted_signals` is exactly `{"count": 0, "company_ids": []}` | holdout |
| AC-88 | the e2e stack | on the form enter company `C1`, `Acme` and one signal `C2`, `climate`; click "Run scan" | the result shows `1 signal skipped: its company is not in the list (C2).` | evaluator |
| AC-89 | an issue of company `NODOCS`, `No Docs AG`, with no documents, ticker or CIK | `POST …/issues/{i}/dossier` with `{"company_id": "NODOCS", "name": "No Docs AG"}` | 422; `detail` is exactly `No documents are loaded for No Docs AG (NODOCS). Upload them in Data Library, then draft the dossier.` | holdout |
| AC-90 | same, with model stand-ins recording calls | same | no model call is recorded | unit |
| AC-91 | Engagement, an issue of a company with no documents | start the dossier draft in the panel | the AC-89 sentence is shown in the panel | evaluator |
| AC-92 | a company with one document | `research_company_issue` | the model is called and a dossier is returned (must not change) | unit |
| AC-93 | a voting run stubbed with 5 decided votes | click the cast button and read the dialog | its text is exactly `This records 5 votes as voting instructions, one file per vote, to be entered on the ballot platform by hand. Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.` | unit (browser) |
| AC-94 | the same stub; the cast request answers with 5 cast votes by `Ana` | confirm the dialog | the banner starts `5 votes recorded as voting instructions by Ana at` and ends `The instruction reference is shown on each proposal below.` | unit (browser) |
| AC-95 | a cast vote with `confirmation_id` `conf_abc` | read its proposal | it shows `Recorded · instruction ref conf_abc` | unit (browser) |
| AC-96 | the states of AC-93 to AC-95 and an override without co-sign | read the whole page in each | none contains `This sends`, `Confirmation ID`, `confirmation conf_` or `refused by the platform` | unit (browser) |
| AC-97 | a `say_on_pay` proposal with a rule-based recommendation at confidence 1.0 and no alignment flag | the routine test | not routine | unit |
| AC-98 | a proposal of type `other`, rule `rule_routine_management_proposal`, confidence 1.0, text one of `Approve the redomiciliation of the Company to Delaware`, `Reincorporation in Nevada`, `Change of the jurisdiction of incorporation` | same | not routine, for each text | unit |
| AC-99 | a `capital_action` proposal with a rule-based recommendation, text `Routine item.`, confidence 0.59 and then 0.6 | same | not routine at 0.59; routine at 0.6 | unit |
| AC-100 | a `director_election` proposal whose recommendation has `policy_rule_id` null and confidence 0.95 | same | not routine | unit |
| AC-101 | a `capital_action` proposal, rule-based, confidence 1.0, text `Routine item.`, no alignment flag | same | routine (must not change) | unit |
| AC-102 | a run stubbed with the proposals of AC-97, AC-100, AC-101 and the first text of AC-98 | read the sweep button, confirm it | the button reads `Approve 1 routine…` and exactly 1 review request is sent | unit (browser) |
| AC-103 | `GET /api/runs/{id}` stubbed `running`, 2 of 5 companies done; ballots `[]` | open the run's page | it shows `This voting run is still in progress (2 of 5 companies done). Ballots appear here as they are ready.` and not `No ballots in this run yet` | unit (browser) |
| AC-104 | the run stubbed `completed`; ballots `[]` | same | it shows `No ballots in this run yet: none of its companies has a proxy statement for an upcoming meeting. Start a new voting run once one is filed.` (must not change) | unit (browser) |
| AC-105 | a voting run with a ballot item | `POST /api/voting/runs/{id}/review` with `decision` `edit`, a `vote`, and `comment` missing or `"  "` | 400; `detail` is exactly `An override needs a reason.`; nothing is recorded | unit |
| AC-106 | same | the same request with `comment` `Board lacks independence` | `{"status": "recorded"}` | unit |
| AC-107 | same | `decision` `approve` without `comment` | `{"status": "recorded"}` (must not change) | unit |
| AC-108 | a stubbed run; a proposal's override block is open | read it | a field labelled `Reason for the override (required)` is shown and `Record override` is disabled while it is empty | unit (browser) |
| AC-109 | the e2e stack (seeded demo data) | open Stewardship, Monitoring | every trigger row whose reason names a CLTI score shows a `Sample data` chip in that row | evaluator |
| AC-110 | the e2e stack | open the Stewardship overview and the client program page | the note about placeholder CLTI scores and the benchmark note each start with a `Sample data` chip, and every table or tile there that shows a CLTI value has the chip next to its heading | evaluator |
| AC-111 | the e2e stack | open Stewardship, Checkpoint and Reporting | every block that says `Designed in the operating model, not built yet.` has a `Not built yet` chip next to its heading | evaluator |
| AC-112 | the e2e stack | `GET /api/stewardship/universe` | `note` contains `placeholders` (must not change) | holdout |
| AC-113 | Stewardship, an outreach draft written by the signed-in person, waiting for approval | open it | next to the disabled `Approve for sending` the page shows, as text, `A second person is needed: this draft was written by <authors>, and someone who did not write it approves it.` | evaluator |
| AC-114 | RFP, signed in as an approver who edited an answer last; the answer is not approved | open the answer | where the Approve button would be, the page shows `A second person is needed: you edited this answer last, and another approver must approve it.` | evaluator |
| AC-115 | an outreach draft | its author approves it through the API | 422 whose text contains `Four-eyes` (the rule is unchanged; must not change) | unit |
| AC-116 | an engagement record | `POST /api/engagement/records/{c}/contacts` with `{"name": "A", "role": "IR", "email": "not-an-email"}` | 422; `detail` is exactly `Enter a valid email address, or leave it empty.` | holdout |
| AC-117 | after AC-116 | `GET /api/engagement/records/{c}` | `contacts` is what it was before | holdout |
| AC-118 | an engagement record | the same request with `email` `a@example.org`, and again with `email` null | 200 both times; the contact is in `contacts` (must not change) | holdout |
| AC-119 | a stored record that holds a contact with `email` `not-an-email` | `GET /api/engagement/records/{c}` | 200 with that contact (must not change) | unit |
| AC-120 | `fund_name` `Alpha Fund`; the model stand-in returns subject `Engagement request from [Fund name]` and a body containing `[Fund name]` | `POST …/outreach-letter` | subject and body contain `Alpha Fund` and no `[Fund name]`; `placeholders` is `[]` | unit |
| AC-121 | `fund_name` unset; the same stand-in | same | subject and body are unchanged and `placeholders` is exactly `["[Fund name]"]` | unit |
| AC-122 | `fund_name` unset; the dossier cites `doc_1`; the body contains `[doc_1]` and `[Date]` | same | `placeholders` is exactly `["[Date]"]` | unit |
| AC-123 | the letter response stubbed with `placeholders` `["[Fund name]"]` | read the letter in the panel | `Fill in before sending: [Fund name]` is shown above it | unit (browser) |
| AC-124 | the calibration schedule holds values `V` | `PUT /api/calibration/schedule` with `{"enabled": true, "interval_hours": 0}` | 422 | holdout |
| AC-125 | after AC-124 | `GET /api/calibration/schedule` | the values are `V` | holdout |
| AC-126 | the e2e stack | `PUT /api/taxonomy-researcher/schedule` with `interval_hours` `0`, and again with `0.5` | 422 both times | holdout |
| AC-127 | the e2e stack | `PUT /api/calibration/schedule` with `{"enabled": false, "interval_hours": 1}` | 200; `GET` returns `interval_hours` `1` (must not change) | holdout |
| AC-128 | the e2e stack | on Background Agents enter interval `0` and save | `Interval must be at least 1 hour.` is shown next to the field and `GET /api/calibration/schedule` is unchanged | evaluator |
| AC-129 | the e2e stack | enter interval `24` and save | `Saved.` appears next to the save button | evaluator |
| AC-130 | the e2e stack | click `Scan now` and do not press Refresh | within 10 seconds "Past runs" has one more row than before, and its status reaches a finished state without a reload | evaluator |
| AC-131 | the e2e stack | `POST /api/universe/upload` with a CSV `name` / `Acme` | 422; `detail` is exactly `Row 1: company_id is required.` | holdout |
| AC-132 | the e2e stack | the same upload with a JSON file `[{"company_id": "A", "name": 5}]` | 422; `detail` starts `Row 1: name is not valid` and contains none of `pydantic`, `input_value`, `validation error` | holdout |
| AC-133 | the e2e stack | upload a CSV `company_id,name` / `A,Acme` | 200 with `path`, `company_count` `1` and `sample` (must not change) | holdout |
| AC-134 | the e2e stack | on Proxy Voting upload `universe.csv` with 3 companies | the page shows `3 companies loaded from universe.csv` and no server path | evaluator |
| AC-135 | any screen whose action writes to the live region `#announcer` (stubbed if needed) | do the action, then open another screen | `#announcer` is empty | unit (browser) |
| AC-136 | same | do the action and stay on the screen | `#announcer` holds the announced text (must not change) | unit (browser) |

Must not change: AC-5, AC-11, AC-14, AC-16, AC-24, AC-28, AC-37, AC-39, AC-41, AC-42, AC-43, AC-52, AC-55,
AC-59, AC-66, AC-69, AC-74, AC-79, AC-86, AC-92, AC-101, AC-104, AC-107, AC-112, AC-115, AC-118, AC-119,
AC-127, AC-133, AC-136, and every existing test.

## Follow-ups (not in this change)

- Document type shown raw in Data Library, citation lists and the review source list.
- The tooltip-only four-eyes reason on "Activate" in the versions panel.
- The outreach author check compares user id with display name; they differ with real users.
- `arp voting review` (CLI) still accepts an override without a reason.
- A verdict label for walk versus talk, if the owner wants a rule for one.
