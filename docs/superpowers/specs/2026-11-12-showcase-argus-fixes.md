# Showcase fixes for the Argus extraction flow (review of 11 Nov 2026)

## Intent

The Argus review of 11 Nov 2026 (https://claude.ai/artifact/GmfDKzVGneUBnVkbbBfgc7) found 43 defects in
the five-step extraction flow. PR #413 (merged) fixed the 8 high ones in their smallest form and 8 of the
17 medium ones. This spec fixes what is left, so the flow can be shown live next week without a dead end,
a silent drop or internal text on screen:

- the 8 medium findings still open,
- 4 high findings #413 only half fixed,
- all 18 low findings,
- 6 defects from a second rehearsal of the same flow,
- 2 items handed over by the `showcase-stewardship-fixes` spec (PR #416) because they sit in Argus files.

Every fix comes with a test that failed before it. No existing test is changed, removed or weakened.

## Build order and PRs

Three implementing PRs, each on `main` (which has #413), each with `Spec: showcase-argus-fixes`.

| PR | What | Rows (`Rows:` line) |
|----|------|---------------------|
| 1 | Backend: company keys, ticker, edit/remove/discard endpoints, identity result, step 2 rules, start flag, progress, units | AC-1 to AC-55, AC-123 to AC-125, AC-134 to AC-146, AC-154, AC-155, AC-157 |
| 2 | Start page and steps 1 to 3 in the browser | AC-56 to AC-106, AC-147 to AC-149 |
| 3 | Steps 4 and 5, Results, walkthrough, company link, XBRL | AC-107 to AC-122, AC-126 to AC-133, AC-150 to AC-153, AC-156; last slice, no `Rows:` line |

PR 2 and PR 3 need PR 1's API. They can be built in parallel after PR 1 is merged.

Risk: PR 1 is `risk:high` (it writes to the central company register in `arp/argus/companies.py` and adds
a call that deletes stored flows). PRs 2 and 3 touch no high-risk path, but the intake rated the feature
`high` and the steward rule forbids a label below the intake's, so they are `risk:high` too unless the owner
lowers them.

PR 1 does not change `arp/db/fields.py`, although the intake listed it: the "Add field" clash is cured in
the browser (item 14), because field ids shared between schemas are intended for template fields.

## Causes (read in code on `main` 3fff505; none was re-run)

| # | Item | Source | Cause |
|---|------|--------|-------|
| 1 | Unmatched rows share a key | medium | `arp/argus/companies.py:75`: a row without a central id is keyed `own_id or name`, and a list's own id (`1`, `2`, …) repeats across lists. Documents, earlier runs and the repeat rule are looked up by this key. |
| 2 | Ticker is ignored | rehearsal | `register()` matches on LEI, ISIN, CIK only. A ticker-only row stays unmatched, and "Official filings" needs a CIK (`discovery/pipeline.py:49`). A ticker-to-CIK lookup exists (`EdgarDocumentSource.resolve_cik`, `ingestion/edgar.py:329`) but step 1 never calls it. |
| 3 | A row cannot be edited or removed | high leftover | No endpoint changes or removes a flow company; `add_companies` only appends. |
| 4 | An identity run changes nothing | medium | `identity_run_id` is stored and its status shown (#413), but nothing reads the run's result (`enriched_universe`, `discovery/identity_pipeline.py:136`) back into the flow's companies. |
| 5 | Broken list gives a 500 | low | `routers/argus.py:463` catches `ValueError` and `UnicodeDecodeError`; `csv.Error` is neither. The upload is read with no size cap. |
| 6 | Step 1 small things | low | The central id is printed under the name with no label (`ArgusFlow.tsx:120`). Saved universes with the same name read the same in the picker. |
| 7 | Drafts pile up and cannot be deleted | medium, #416 | `ArgusStart.tsx:101` and `openNewFlow` create a stored flow on every click or visit. `DELETE /flows/{id}` only removes a flow with no companies at step 1. Draft rows all read `New extraction` with a date. |
| 8 | Start page reads wrong when filtered | low | `ArgusStart.tsx:163` shows "No runs yet" whenever the filtered list is empty. Tiles filter the table but nothing says so. The run-name cell does not wrap, and stacked cells have no labels. No link to the Walkthrough. |
| 9 | Uploads are not kept | medium | The upload handler never sets a decision, so a file that passes its check still counts as "0 files". Undecided files show no state. |
| 10 | Type shows the stored code | medium, #416 | `ArgusDocuments.tsx:190` prints `f.doc_type` (`10-K`, `sustainability_report`); the dropdown shows labels. |
| 11 | Re-upload of a removed file is lost | low | `store_upload` reports a duplicate and the handler leaves the file's `removed` decision (`documents.py:158`, `routers/argus.py:256`). |
| 12 | Stale document check | low | The check cache is named by content, company key and file name (`documents.py:71`), not by the name, LEI and ISIN the check depends on; a failed read (`no_text`) is cached too. |
| 13 | Saved-schema view breaks the layout | medium | `index.css:2271-2279`: the left column has no `min-width: 0`, and the read-only field table has no column widths, so `Look in` wraps at about six words. |
| 14 | "Add field" ids clash | medium | `ArgusSchema.tsx:21`: `field_${n}` from the field count. Field definitions are keyed by `(field_id, version)` across all schemas (`db/fields.py:122-139`, `:180`). Fields drafted by the model get the default unique id and are not affected. |
| 15 | Release has no confirmation | high leftover | `ArgusSchema.tsx:300` releases on the click. |
| 16 | An unsaved draft is lost on reload | high leftover | The drafted fields and the typed description live in page state only. |
| 17 | Step 3 small things | low | Batch and the evidence field are not disabled while a save is in flight (`ArgusSchema.tsx:333-339`). A chosen schema that no longer exists leaves the button on `Loading schema…`. |
| 18 | Step in the URL | low | `App.tsx:396` passes any number; `/7` or `/2.5` renders step 1 with no step marked. |
| 19 | Step bar after a run ends | low | `ArgusExtract` gets no `refresh`, so `flow.step` stays 4 until a reload. |
| 20 | Status code in error banners | low | `api/client.ts:177` builds `"<status>: <detail>"`, and the Argus pages print it as is. |
| 21 | A flow can stay "starting" | low | `routers/argus.py:310-324`: the flag is cleared only around `start_extraction`; the two file writes after it are outside the `try`, and nothing treats an old flag as stale. |
| 22 | A conflicting company reads "Stopped" | medium | `save_companies` drops a company whose identifiers conflict and writes an error row with `company_id` but no `key` (`universe.py:80`); `flow_progress` maps errors by `key` (`routers/argus.py:345`). |
| 23 | Header undercounts | low | `done = completed_count + failed_count` (`routers/argus.py:358`); a company stopped for review is in neither. `test_progress_mixes_statuses` asserts this number, so `done` stays. |
| 24 | Stopped rows flip to Waiting during a Retry | low | `company_status` returns `Waiting` for every never-started company while the run is active (`progress.py:47-52`). |
| 25 | Stop gives no feedback | low | `FlowProgress` has no field for `cancel_requested`. |
| 26 | Little feedback while extracting | rehearsal | `minutes_left` is `None` until one company has finished (`progress.py:57`). Cost is added to the manifest when a company finishes (`batch_runner.py:185-192`). Why the Progress column looked empty is **not established**: the bar is driven by an in-process step tally (`step_tally.py:202`). |
| 27 | No "How was this found?" on most rows | medium | `ArgusResults.tsx` renders the link only inside `ReviewControls`, so only for rows with an open review item. |
| 28 | A skipped company's values are a link | high leftover | `ArgusResults` reads one run; #413 added a note with a link. |
| 29 | No period on Results | rehearsal | The table has no column for `period_end`, so two years of one field read as a duplicate. |
| 30 | Emissions flagged "check failed" | rehearsal | `normalise/tables/units_v1.csv` has no "metric tons" spelling of tCO2e; `value.py:127` raises `cannot convert … (unknown_unit)`. |
| 31 | Raw codes in the review detail | low, rehearsal | `ReviewControls.tsx:467` prints `route_reasons` joined by commas, and the check's note as stored. |
| 32 | Empty blind-verify step | low | `ArgusWalkthrough.tsx:201-202` returns nothing when the answer is null, although the verdict's note is in the trace. |
| 33 | Company link opens a wrong record | rehearsal | `companyHref` (`pages/company/companyQuery.ts:24`) always builds `UNIVERSE:<run company_id>`. For a company keyed by its central id that reference can name another, empty record. |
| 34 | XBRL "Add one company" replaces the list | rehearsal | `XbrlFetchArea.tsx:211` saves a one-company universe and swaps it in for the picked one. |

## Goals

1. Two different companies never share documents or run history because their lists reuse an id.
2. A company added by name and ticker is matched through its CIK, and "Official filings" finds its filings.
3. A wrong row, a wrong pick or an abandoned draft can be corrected or removed before a run starts.
4. "Resolve identities" changes the rows it resolved.
5. Steps 2 and 3 need no extra click that the page does not ask for, and lose no typed work on reload.
6. Step 4 says what each company is doing, how long is left and what it has cost so far.
7. Step 5 shows every value the user chose to keep, its period, and how it was found.
8. No internal code, status number or stored type name is shown where a sentence or label exists.

## Non-goals

- Anything #413 already fixed.
- Building the import folder (pipeline slice 9), filing documents by central id or any migration (slice 10),
  the one review list (slice 8), check-digit validation of identifiers.
- The two-reviewer rule and its wording (the review's 17th medium finding, "a solo user can never finish
  a review"). The intake left it out.
- One definition of "waiting on you" across the home page, the sidebar and Argus (needs slice 8). The Argus
  page only says what its own numbers count.
- A flow-level CSV. `Download CSV` stays the current run's export; a kept company's CSV is on its earlier
  run, which the existing note links to.
- Naming an extraction. A draft row shows its first companies and its time instead.
- `How was this found?` on Financials and TNFD runs: their values are not listed on step 5.
- Renaming the `Review` button to `Details`: two existing browser tests find it by that name.
- A second identity run started when the click's follow-up save fails (the review's last sentence on that
  finding). Rare, and no data is damaged.

## Anti-goals

- A ticker used to match or create a company in the register.
- A fix that changes the key of a company already stored in a flow, or moves stored documents.
- A fix that changes an existing test.
- An identity result or an edit that strands files already added to the flow.

## Approaches

1. **Three PRs by layer and risk (chosen).** The register and delete paths are reviewed alone as
   `risk:high`; the two browser PRs can be built in parallel and checked by the evaluator per screen.
2. One PR per finding: about 40 PRs for a showcase next week, and at most three agent PRs may be in flight.
3. One PR for everything: every browser change would wait on the high-risk review, and the diff is too
   large to read.

For the identity result (item 4) and row edits (item 3), two ways were considered for a row whose match
changes its storage key after files were added: copy the files to the new key, or refuse the change. Copying
moves documents between companies, which is slice 10's migration. **Refusing is chosen**: the row keeps its
state and the user removes and re-adds the company.

## Decided

Numbers match the causes table. Exact texts are in the acceptance rows.

**1. Unmatched keys.** A row without a central id that has a list id is keyed by its name and that id
together, not by the id alone. A row with only a name keeps today's key. Matched rows and companies
already stored in a flow are untouched.

**2. Ticker.** When a row has a ticker and no valid ISIN, LEI or CIK, step 1 looks the ticker up in the
SEC ticker list and, if found, treats the CIK as the row's identifier. The ticker itself is never passed
to matching. A row that already has an identifier is not looked up (a wrong-exchange ticker must not add a
second company's CIK to it). A miss or an unreachable list leaves the row unmatched with a reason; the add
still succeeds.

**3. Edit and remove.** Until the flow has a run, each step 1 row has `Edit` (name, ticker, ISIN, LEI,
CIK) and `Remove`. An edit registers the row again by the rules of adding and replaces it in place; fields the form does not
show (sector, country, website and any other list column) are kept.
Remove drops the row and its file choices in this flow at once, with no dialog (adding the company again
brings its files back); documents stay on the company. Once the flow has a run, or a Start is being
dispatched (`starting`), both answer 409 and the buttons are gone. An edit never changes the key of a row
that stays unmatched, so changing only the name keeps the key. The key changes only when the row becomes
matched to a company already stored under another key; if the flow lists files for the row, that edit is
refused. A row with files that is matched to a company new to the register keeps its key.

**4. Identity result.** The browser still starts exactly one identity run per click. When the flow is read
after that run has ended, each still-unmatched company the run resolved (not flagged for review) is
registered with the identifiers found and becomes matched. It is applied once per run. The key rule
of item 3 applies: a row with files whose match would change its key is left unmatched; otherwise it keeps
its key. While the run is `pending` or
`running`, step 1 reads the flow again every 4 seconds.

**5, 6. Lists and step 1.** A list the CSV reader rejects is a 400 with the existing wording; an oversized
list is a 413. The central id keeps its place under the name (the pipeline spec requires it) with the label
`Central ID`. Saved universes with the same label get their saved time appended.

**7. Drafts.** The start page lists a draft only once it has a company, which also hides drafts made by a
visit to `#/transitionPlan`. A listed draft shows its time and first two company names. `Delete` on a Draft
row, after a confirmation, removes the flow through a new call, `POST /flows/{id}/discard`, allowed for any
flow without a run that is not being started. A `starting` flag older than 60 seconds counts as not
starting, here and for Edit and Remove, as it does for Start. Plain `DELETE` keeps its rule (an existing test pins it).

**8. Start page.** An empty filtered list says so and offers `Show all`. The Process region says what the
tiles count and, when one is pressed, which step is shown. Long run names wrap. `Walkthrough` is linked.

**9 to 12. Step 2.** A file uploaded through the flow that passes its check is kept at once; one that fails
stays undecided and reads `Not decided`. Files found by a search stay undecided as today. The Type cell
uses the dropdown's labels. Uploading again a file removed in this flow keeps it when its check passes and
leaves it undecided when it fails. The check cache follows
the company's name, LEI and ISIN, and a failed read is not cached. The import option reads
`From the import folder (not available yet)`.

**13 to 17. Step 3.** The saved-schema table gives `What it means` and `Look in` real width and clamps
`Look in` to three lines with `Show more`. An added field gets a unique id. Release asks first
(`window.confirm`, as elsewhere in the app). An unsaved draft and its description are kept per flow in the
tab's session storage until saved or replaced. Batch and the evidence field are disabled during a save. A
chosen schema that no longer exists is cleared with a message.

**18 to 21. Flow shell.** A step in the URL that is not 1 to 5 goes to the flow's furthest step. A valid
step the flow has not reached still opens (an existing test opens step 3 of a new flow). The step bar
updates when the run ends. Argus banners drop the leading status number. A `starting` flag older than
60 seconds no longer blocks Start. The launched run is linked to the flow before the kept-file records are
written, so a failed write leaves the flow pointing at its run with `starting` false.

**22 to 26. Step 4.** A company dropped for conflicting identifiers reads `Failed` with the reason and has
no Retry. `FlowProgress` gains `finished` (rows that read `Done` or `Failed`; a company stopped for review reads
`Done`, so it counts), `stopping`, and per company
`retryable`; `done` keeps its meaning. The header shows `finished`. Never-started rows stay `Stopped`
during a Retry. Before any company has finished, time left is estimated from the stages reached:
`elapsed / p * (total - p)` in minutes, rounded up, with `p` the sum of the companies' percent / 100, once
`p >= 0.25`. Cost
includes finished model calls of companies still in progress, counted once.

**27 to 32. Step 5 and walkthrough.** Every value row has `How was this found?`. Values of a company set to
`Skip, keep earlier results` are listed as rows from the kept run, marked as kept, and reviewed in place
against that run; #413's note stays. A `Period` column follows `Field` and shows the period end date.
"Metric tons" spellings convert to tCO2e; plain `tons` stays unknown (US short tons). Route reasons and the
unit note are shown as sentences; a code with no sentence reads `Reason: <code with spaces>.` A failed blind re-extraction shows its note.

**33, 34. Elsewhere.** A run result's company link opens the record of the row's central id when it has
one. XBRL `Add one company` makes a new list of the picked companies plus the new one and picks it; the saved
universe picked before is not changed. Uploading or picking a saved universe still replaces.

## Pinned interfaces

- `PUT /api/argus/flows/{flow_id}/companies/{company_id}`, body `{name, ticker?, isin?, lei?, cik?}`,
  returns the flow view. Role `analyst`.
- `DELETE /api/argus/flows/{flow_id}/companies/{company_id}`, returns the flow view. Role `analyst`.
- `POST /api/argus/flows/{flow_id}/discard`, returns 204. Role `analyst`.
- `GET /api/argus/flows/{flow_id}/progress` gains `finished: int`, `stopping: bool` and, per company,
  `retryable: bool`.
- After a request or response model changes: export the OpenAPI file and regenerate the client types, as
  `.claude/CLAUDE.md` says.

## Shared files with showcase-stewardship-fixes

That spec (merged, PR #416) changes other functions in the same files. Whoever merges second merges `main`
first. Its table says this feature decides "which identifiers are accepted" in
`discovery/identity_agents.py`; this spec does that in `arp/argus/companies.py` instead (item 2) and does
not change `identity_agents.py`.

| File | This feature owns | showcase-stewardship-fixes owns |
|---|---|---|
| `backend/arp/discovery/identity_agents.py` | nothing | `gather_signals` failure handling, `lookup_errors`, the prompt line for a failed lookup |
| `frontend/src/pages/ArgusDocuments.tsx` | `DOC_TYPES`, the Keep block and `Not decided`, the Type cell (all types), the import note | nothing; its status text is `searchStatusText` in `lib/argusFlow.ts` |
| `frontend/src/pages/ArgusStart.tsx` | `start()`, hiding and deleting drafts, drafts made by `openNewFlow`, the filter texts, the Runs table | nothing |
| `frontend/src/pages/ArgusResults.tsx` | `How was this found?`, kept companies' rows, the `Period` column | the question in the Field cell for the transition-plan template, the walk and talk line, the Scoring panel |
| `frontend/src/pages/ArgusSchema.tsx` | saved-schema layout, field ids, Release confirmation, the unsaved draft, disabled settings, the missing-schema message | the estimate sentence by the start button, `64 indicators + 8 supporting figures` |
| `backend/arp/argus/companies.py` | keys of unmatched rows, the ticker lookup, registering an edited row or an identity result | `isic_code` in `_FIELDS` and the fill on an existing company |
| `backend/arp/argus/documents.py` | the check cache name, re-upload of a removed file | the year of an EDGAR filing |
| `backend/arp/api/routers/argus.py` | the new company and discard endpoints, upload kept by default, list upload errors, the start flag, progress | nothing |

## Existing tests that pin behaviour (none may change)

- `e2e/test_argus_step1.py::test_resolve_identities_starts_one_run_for_the_unmatched` (pipeline AC-13): one
  POST to `/api/identity/runs` per click with only the unmatched companies; `Identity run started.` and the
  link `Open identity runs`; after a reload no `Resolve identities` button while the run's record is
  unreadable. So the result is applied on the server, and polling runs only for `pending` or `running`.
- `e2e` `test_suggest_again_disabled_while_a_new_draft_runs`: the `Draft fields` button keeps its text.
- `test_argus_flows.py::test_only_an_empty_unstarted_draft_can_be_deleted`: plain `DELETE` answers 409 for a
  flow at step 2. Hence the separate `discard` call.
- `test_argus_progress.py::test_progress_mixes_statuses`: `done == 2` with two Done rows and one Failed.
  Hence the new `finished` field.
- `e2e/test_argus_switchover.py::test_transition_plan_opens_step_1_with_the_template_preselected`: opens
  `/3` on a flow at step 1 and expects step 3. Hence item 18 redirects only invalid steps.
- `e2e/test_argus_steps45.py` and `test_argus_switchover.py` click a button named `Review`.
- `test_argus_companies.py`: a matched row with a list id keeps that id as its key; a name-only row is
  keyed by its safe name; the three `No identifier: add an ISIN, LEI or CIK` assertions.
- `frontend/tests/argusFlow.test.ts`: `progressHeader`, `notInRun`, `identityStatus`, `searchStatusText`
  with today's arguments and outputs.

If a fix cannot be made without changing one of these, that is a spec question (steward rule 3).

## Notes for the builder

- AC-18, AC-31 and AC-32 are `unit` because the test stack has no model, so a hidden test cannot start a
  run through the API.
- Item 26, Progress column: reproduce it first on the showcase setup (one uvicorn process, a real run of
  two companies). Write the failing test from what you find. If AC-112 and AC-151 already pass on `main`, or it
  does not reproduce, post a spec question
  with what you saw; do not guess a cause.
- Item 2: use `EdgarDocumentSource.resolve_cik`. Tests replace the SEC list with a stand-in; no test calls
  the SEC.
- Item 4: `enriched_universe()` already leaves out flagged and unresolved companies.
- Item 3 and 4: the key would change only when the matched company is already stored under a key other
  than the row's. In every other case the row keeps its current `company_id`, whatever `register()`
  proposes. Roll the register transaction back when refusing.
- Item 31: the four sentences in AC-114 are fixed. Write the others from what each code means in
  `schemas/review.py` and `extraction/routing.py`.
- Each PR description pastes the failing-before output per fix and lists every test added.
- After PR 1 and PR 3, `openwiki/` needs an update for the key rule, the ticker rule, the discard call and
  the progress fields. Leave it to `/context-refresh`.

## Left to the builder

- The exact key format for an unmatched row with a list id, and the id format of an added field.
- Where the identity result is applied in the code, and how "applied once" is recorded.
- How running cost is recorded without counting a call twice.
- Component structure, CSS, and the wording of route-reason sentences beyond AC-114.

## Acceptance

"Flow" is an Argus flow. API paths are under `/api/argus`. Holdout rows do not depend on each other or on
test order: a test may replace a row's company name or identifier by another valid one of the same kind
that its database does not hold yet. "pipeline AC-n" is a row of
`2026-10-24-argus-simplified-pipeline-design.md`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | two CSV lists with columns `company_id,name`: list A `1,Acme`, list B `1,Foo Corp`; no ISIN, LEI or CIK | A is uploaded to flow 1 and B to flow 2 | the two rows' `company_id` values are different | holdout |
| AC-2 | one CSV with the rows `1,Acme` and `1,Foo Corp` | it is uploaded to a flow | the flow has 2 companies, named `Acme` and `Foo Corp` | holdout |
| AC-3 | the flows of AC-1, and a PDF uploaded for Acme in flow 1 | flow 2 is read | `files` of flow 2 is empty | holdout |
| AC-4 | a CSV row `7,Acme` with no identifier | it is uploaded to two different flows | both rows have the same `company_id` | holdout |
| AC-5 | a row with only `name` `Siemens AG` | it is added | its `company_id` equals `safe_key("Siemens AG")`, as on `main` | unit |
| AC-6 | a row `company_id` `AAPL`, `name` `Apple`, ISIN `US0378331005` | it is added to a flow | its `company_id` is `AAPL`, as on `main` | unit |
| AC-7 | the SEC ticker list replaced by a stand-in that maps `MSFT` to CIK `789019`; an empty register | `{name: "Microsoft", ticker: "MSFT"}` is added | the row has an `entity_id`, `problem` is null, and its `cik` is `789019` (leading zeros allowed) | unit |
| AC-8 | a stand-in list without `ZZZZ`; the register holds one company whose only identifier is ticker `ZZZZ` | `{name: "Zed", ticker: "ZZZZ"}` is added | the row's `entity_id` is null and the number of companies in the register is unchanged | unit |
| AC-9 | the state of AC-8 | the row is read | its `problem` is `Ticker ZZZZ is not listed at the SEC: add an ISIN, LEI or CIK` | unit |
| AC-10 | a stand-in list that raises when read | `{name: "Microsoft", ticker: "MSFT"}` is added | the response is 200 and the row's `problem` is `The SEC ticker list could not be read: add an ISIN, LEI or CIK` | unit |
| AC-11 | a stand-in that maps `MSFT` to `789019` | `{name: "Microsoft", ticker: "MSFT", isin: "US5949181045"}` is added | the row's `cik` is null | unit |
| AC-12 | a row with a name and no ticker or identifier | it is added | its `problem` is `No identifier: add an ISIN, LEI or CIK` | holdout |
| AC-13 | a flow without a run holding `Apple`, unmatched `Borealis` (name only, no files) and `Microsoft`, in that order | `PUT …/companies/<Borealis's id>` with `{name: "Borealis", isin: "DE000A1EWWW0"}` | 200; the second company is `Borealis` with an `entity_id`, `isin` `DE000A1EWWW0` and `problem` null | holdout |
| AC-14 | a flow with `Apple` matched by ISIN `US0378331005` and unmatched `Acme` | `PUT` for Acme with `isin` `US0378331005` | 400 with detail `Apple is already in this extraction.` | holdout |
| AC-15 | the state after AC-14 | the flow is read | it still has 2 companies and Acme has no `entity_id` | holdout |
| AC-16 | a flow without a run with 3 companies, one of them with a kept file | `DELETE …/companies/<that id>` | 200; the flow has 2 companies and `decisions` has no entry for that file | holdout |
| AC-17 | the state after AC-16 | the same company is added again | `files` lists that file again | holdout |
| AC-18 | a flow whose `run_id` is set | `PUT` or `DELETE` on one of its companies | 409 with detail `Companies cannot be changed once the extraction has started.` | unit |
| AC-19 | a flow without a run | `PUT` or `DELETE` with a company id not in the flow | 400 with detail `That company is not in this extraction.` | holdout |
| AC-20 | a signed-in user with role `viewer` | `PUT`, `DELETE` on a company, or `POST …/discard` | 403 each | unit |
| AC-21 | flow 1 added `{company_id: "CEDAR-X", name: "Cedar", isin: "FR0000120271"}`; flow 2 has unmatched `Cedar` (name only) with one uploaded file | `PUT` in flow 2 for Cedar with `isin` `FR0000120271` | 409 with detail `Cedar has files in this extraction. Remove the company and add it again with the identifier.` | holdout |
| AC-22 | the state after AC-21 | flow 2 is read | Cedar has no `entity_id` and `files` still lists its file | holdout |
| AC-23 | a flow with unmatched `Acme`; the flow's identity run has status `completed` and resolved Acme to CIK `1234567`, not flagged | `GET …/flows/<id>` | Acme has an `entity_id`, `problem` null and `cik` `1234567` | unit |
| AC-24 | as AC-23, but the run's result for Acme is flagged for review | `GET …/flows/<id>` | Acme has no `entity_id` | unit |
| AC-25 | the flow of AC-23 | it is read a second time | the register holds the same number of companies and identifiers as after the first read | unit |
| AC-26 | as AC-23, but the run's status is `running` | `GET …/flows/<id>` | Acme has no `entity_id` | unit |
| AC-27 | as AC-23, but Acme has a file in this flow and CIK `1234567` belongs to a company stored under another key | `GET …/flows/<id>` | Acme has no `entity_id` and `files` still lists its file | unit |
| AC-28 | a file `x.csv` with the body `name,isin`, a new line, one `"` and 200,000 times `x` | it is uploaded as a company list | 400, and the detail starts with `Could not read the list:` | holdout |
| AC-29 | `max_upload_bytes` set to 1,000,000 | a 1.5 MB company list is uploaded | 413 with detail `File is larger than the 1 MB upload limit.` | unit |
| AC-30 | a draft flow at step 2 with 2 companies and no run | `POST …/discard` | 204, and `GET` of the flow answers 404 | holdout |
| AC-31 | a flow whose `run_id` is set | `POST …/discard` | 409 with detail `An extraction that has started cannot be deleted.` | unit |
| AC-32 | the flow of AC-31 after the 409 | `GET` of the flow | 200 | unit |
| AC-33 | a flow at step 2 with no companies | `DELETE …/flows/<id>` | 409 with detail `Only an empty draft can be deleted.`, as on `main` | unit |
| AC-34 | a draft with a PDF uploaded for Apple (ISIN `US0378331005`) is discarded | a new flow adds Apple by the same ISIN | the new flow's `files` lists that PDF | holdout |
| AC-35 | reporting year 2025 | a PDF whose text names Apple and 2025 is uploaded for Apple through `…/documents/upload` | in the response that file's `state` is `kept` | holdout |
| AC-36 | reporting year 2025 | a PDF whose text names only Microsoft is uploaded for Apple | that file's `state` is null | holdout |
| AC-37 | a file whose check passes, kept, then removed in this flow | the same bytes are uploaded again for the same company | that file's `state` is `kept` | holdout |
| AC-38 | the state after AC-37 | the flow is read | `skipped_uploads` has no entry for that file | holdout |
| AC-39 | a kept file, not removed | the same bytes are uploaded again | the flow lists one row `Duplicate of <file name>, skipped`, as pipeline AC-24 | holdout |
| AC-40 | company key K named `Appel` with a PDF that names `Apple`; its check was read once (`Company not found in document`) | the company's name under key K becomes `Apple` and the flow is read | the file's check starts with `✓` | unit |
| AC-41 | a PDF whose first check fails to read the file (`no_text`) | the file becomes readable and the flow is read again | the check is the readable file's result, not the stored failure | unit |
| AC-42 | a flow file with `starting` true and `updated_at` 2 minutes ago | Start is called | the answer is 200 and the flow's `run_id` is set | unit |
| AC-43 | a flow file with `starting` true and `updated_at` 5 seconds ago | Start is called | 409 with detail `This extraction is already starting.` | unit |
| AC-44 | writing the run's kept-file record fails after the run was launched | the flow is read | `starting` is false and `run_id` is the launched run's id | unit |
| AC-45 | a finished run of `Apple`, `Microsoft` and `Mixed`, where Mixed was dropped for conflicting identifiers | `GET …/progress` | Mixed's `status` is `Failed` and its `reason` is `Identifiers match more than one company. Correct them in a new extraction.` | unit |
| AC-46 | the run of AC-45 | `GET …/progress` | Mixed's `retryable` is false | unit |
| AC-47 | the run of AC-45 | `GET …/progress` | `finished` is 3 and `total` is 3 | unit |
| AC-48 | a running run with one company with a result (reads `Done`), one `Failed`, one stopped for review (reads `Done`) and one in progress | `GET …/progress` | `finished` is 3 | unit |
| AC-49 | the run of AC-48 | `GET …/progress` | `done` is 2, as on `main` | unit |
| AC-50 | a stopped run with 3 never-started companies and 1 failed; Retry was clicked on the failed one and the run is active | `GET …/progress` | the 3 never-started rows read `Stopped` | unit |
| AC-51 | a running run on which Stop was requested | `GET …/progress` | `stopping` is true | unit |
| AC-52 | a run started 4 minutes ago with 2 companies: one at `Extracting` (50), one `Waiting` (0), none finished | `GET …/progress` | `minutes_left` is 12 | unit |
| AC-53 | as AC-52, but both companies are `Waiting` | `GET …/progress` | `minutes_left` is null | unit |
| AC-54 | a run with a stand-in model that reports cost; one company's first model call has finished and the company has not | `GET …/progress` | `cost_usd` equals the stand-in's cost of that one call | unit |
| AC-55 | the run of AC-54 after it finished | `GET …/progress` | `cost_usd` equals the sum of the calls' costs, each counted once | unit |
| AC-56 | step 1 of a flow without a run, with companies | the page is shown | every row has an `Edit` and a `Remove` button | evaluator |
| AC-57 | step 1 as in AC-56 | `Edit` is clicked on a row | fields `Name`, `Ticker`, `ISIN`, `LEI`, `CIK` appear filled with the row's values, with `Save` and `Cancel` | evaluator |
| AC-58 | the form of AC-57 on an unmatched row | a valid ISIN is typed and `Save` is clicked | the row is no longer in the warning style and shows that ISIN | evaluator |
| AC-59 | step 1 of a flow that has a run | the page is shown | no row has `Edit` or `Remove` | evaluator |
| AC-60 | step 1 with a matched company | the row is shown | the id under the name reads `Central ID <id>` | evaluator |
| AC-61 | two saved universes with the same name and company count, saved on the same day | the saved-universe picker is opened | the two entries differ: each ends with its saved time as `HH:MM` | evaluator |
| AC-62 | step 1 open while the flow's identity run has status `running` (a run record written into the runs folder by hand) | the record is changed to `completed` with the unmatched company resolved | within 10 seconds, without a reload, the row leaves the warning style | evaluator |
| AC-63 | the state after AC-62 with no unmatched row left | step 1 is shown | the status line reads `Identities resolved.` | evaluator |
| AC-64 | the app on `main` plus this change | the existing test `test_resolve_identities_starts_one_run_for_the_unmatched` runs unchanged | it passes | unit |
| AC-65 | the start page with N rows in Runs | `Start new extraction` is clicked, then the browser's Back | Runs has N rows | evaluator |
| AC-66 | the start page with N rows in Runs | `#/transitionPlan` is opened, then `#/argus` | Runs has N rows | evaluator |
| AC-67 | a draft with `Apple`, `Microsoft` and 13 more companies | the start page is shown | its row reads `New extraction` and, beneath, `<starter> · <date> <HH:MM> · Apple, Microsoft +13` | evaluator |
| AC-68 | a row with status `Draft`, signed in as analyst | `Delete` is clicked | a dialog reads `Delete this draft? Its company list and file choices are removed. Documents stay on the companies.` | evaluator |
| AC-69 | the dialog of AC-68 | it is cancelled | the row is still listed | evaluator |
| AC-70 | the dialog of AC-68 | it is confirmed | the row is gone from Runs | evaluator |
| AC-71 | rows with a status other than `Draft` | the start page is shown | none has a `Delete` button | evaluator |
| AC-72 | the start page with at least one run | a Process tile with count 0 is clicked | the table reads `No run matches this filter.` with a `Show all` button | evaluator |
| AC-73 | the state of AC-72, with `Only mine` ticked | `Show all` is clicked | every run is listed, no tile is pressed and `Only mine` is unticked | evaluator |
| AC-74 | no runs and no drafts with companies | the start page is shown | the table reads `No runs yet.` with `Start one` | evaluator |
| AC-75 | the start page | it is shown | the Process region shows `Extractions at each step. Click a step to list only its extractions.` | evaluator |
| AC-76 | the start page | tile `3 Schema` is clicked | a line above the table reads `Showing step 3 Schema only.` | evaluator |
| AC-77 | a run whose schema name is 60 letters without a space; window 1280 px wide | the start page is shown | the `Open` link of that row is fully visible | evaluator |
| AC-78 | the run of AC-77; window 390 px wide | the start page is shown | the page does not scroll sideways | evaluator |
| AC-79 | window 390 px wide | the start page is shown | each stacked cell of a Runs row is preceded by its column name | evaluator |
| AC-80 | the start page | it is shown | the head has a link `Walkthrough` to `#/argusWalkthrough` | evaluator |
| AC-81 | step 2, reporting year 2025, source `I upload them`, 2 companies | one passing PDF is uploaded for each, and nothing else is clicked | the button reads `Continue with 2 files for 2 companies` and is enabled | evaluator |
| AC-82 | step 2 with an uploaded file whose check fails | the file's row is shown | its `In this extraction` cell reads `Not decided` with `Keep` and `Remove` | evaluator |
| AC-83 | step 2, Type `Annual report` chosen | a file is uploaded | its Type cell reads `Annual report` | evaluator |
| AC-84 | step 2 with a file of stored type `sustainability_report` | its row is shown | its Type cell reads `Sustainability report` | evaluator |
| AC-85 | a file whose stored type is `20-F` | the type label is computed | it is `20-F` | unit |
| AC-86 | step 2 | the sources are shown | the second option reads `From the import folder (not available yet)` on one line and is disabled | evaluator |
| AC-87 | a saved draft schema with 4 fields whose `Look in` texts are 600 characters each; window 1280 × 800 | the schema is chosen in step 3 | the `What it means` and `Look in` columns are each at least 240 px wide | evaluator |
| AC-88 | the state of AC-87 | the table is shown | each `Look in` cell shows at most 3 lines and a `Show more` button | evaluator |
| AC-89 | the state of AC-87 | `Show more` is clicked in one cell | that cell shows its full text and a `Show less` button | evaluator |
| AC-90 | a saved schema with 4 fields whose name is 60 letters without a space; window 1280 px wide | step 3 is shown | in the saved-schemas dropdown (`#argus-saved-schema`) the schema's option text holds the whole name and `4 fields`, and the dropdown fits inside its card | evaluator |
| AC-91 | saved schemas A and B with 2 fields each; in A `Add field` named `Revenue` was saved and released | in B `Add field` named `Capex` is saved | B is saved with 3 fields and no error is shown | evaluator |
| AC-92 | the state after AC-91 | schema A is opened | its third field is named `Revenue` | evaluator |
| AC-93 | 1,000 field ids made by `Add field` | they are compared | all differ and none matches `field_<number>` | unit |
| AC-94 | a schema where two fields were added, the first left blank, and saved; then `Edit`, `Add field` named `X`, saved | the schema is read from `GET /api/extraction/schemas/<id>` | all `field_id` values differ | evaluator |
| AC-95 | a draft schema `S` v1 chosen, signed in as approver, 3 companies with kept files | `Release` is clicked | a dialog reads `Release S v1? A released version cannot be changed or withdrawn. It then extracts all 3 companies.` | evaluator |
| AC-96 | the dialog of AC-95 | it is cancelled | the start button still reads `Try S on 1 company` | evaluator |
| AC-97 | the dialog of AC-95 | it is confirmed | the start button reads `Extract S v1 for 3 companies` | evaluator |
| AC-98 | step 3 with a typed description and drafted fields marked `not saved` | the page is reloaded | the same description and the same fields are shown, marked `not saved` | evaluator |
| AC-99 | the state of AC-98, then `Save as a draft schema` | the page is reloaded | the saved schema is shown and no field is marked `not saved` | evaluator |
| AC-100 | an unsaved draft in flow 1 | step 3 of flow 2 is opened in the same tab | no unsaved field is shown | evaluator |
| AC-101 | step 3 Settings open, the server's answer to a settings save delayed by 3 seconds (a delayed route in the browser driver) | `Batch` is ticked | until the answer arrives the `Batch` checkbox and the evidence field are disabled | evaluator |
| AC-102 | a flow whose chosen schema's rows were deleted in the database by hand | step 3 is opened | the page shows `The schema chosen earlier no longer exists. Choose another.` and the start button reads `Choose what to extract` | evaluator |
| AC-103 | the state after AC-102 | the flow is read from the API | `schema_choice` is null | evaluator |
| AC-104 | a flow at step 2 | `#/argus/<id>/7`, `#/argus/<id>/2.5` and `#/argus/<id>/-1` are opened in turn | each time the address becomes `#/argus/<id>/2` and step 2 is shown | evaluator |
| AC-105 | a new flow at step 1 | `#/argus/<id>/3` is opened | step 3 is shown, as on `main` | evaluator |
| AC-106 | step 2 of a flow with no companies, source `Official filings` | `Find documents` is clicked | the error reads `Add companies in step 1 first.` with no number before it | evaluator |
| AC-107 | step 4 open on a running extraction | the run finishes, with no reload | `5 Results` in the step bar is a link | evaluator |
| AC-108 | step 4 open on a running extraction | `Stop` is clicked | the button reads `Stopping…` and is disabled | evaluator |
| AC-109 | the state of AC-108 | the page is shown | a line reads `Stopping: companies already running will finish.` | evaluator |
| AC-110 | a flow with `Apple` (LEI), `Microsoft` (ISIN) and a third row with Apple's LEI and Microsoft's ISIN, uploaded as one list (step 1 shows the third row with `Identifiers match more than one company`), a kept file each, run to the end | step 4 is shown | the third row reads `Failed` with `Identifiers match more than one company. Correct them in a new extraction.` and has no `Retry` button | evaluator |
| AC-111 | the run of AC-110 | step 4 is shown | the header reads `3 of 3 done` | evaluator |
| AC-112 | a real extraction of 2 companies in progress | step 4 is shown while a company reads `Reading documents`, `Extracting` or `Checking the answers` | that row's bar is filled to a quarter, a half or three quarters of its width, in that order of statuses | evaluator |
| AC-113 | a finished run with an auto-accepted value | step 5 is shown | that row has a link `How was this found?` that opens the walkthrough of that run, company and field | evaluator |
| AC-114 | a review detail whose reasons are `unreleased_version`, `check_failed`, `first_audit_pending`, `below_auto_accept_min` | the reasons are turned into text | they read `The schema is a draft, so every value is reviewed.`, `A check on this value failed.`, `The first values of a new schema version are always reviewed.`, `Confidence is below the level for automatic acceptance.` | unit |
| AC-115 | every value of `ReasonCode` and every reason literal in `extraction/routing.py` | each is turned into text | each text ends with a full stop, has no `_`, and does not start with `Reason:` | unit |
| AC-116 | the note `cannot convert 'short tons' to 'tCO2e' (unknown_unit)` | it is turned into text | it reads `The unit "short tons" could not be converted to tCO2e.` | unit |
| AC-117 | step 5 with a value waiting for review | `Review` is clicked on its row | the detail shows sentences and none of the codes `unreleased_version`, `check_failed`, `first_audit_pending`, `below_auto_accept_min` | evaluator |
| AC-118 | a flow where Microsoft is set to `Skip, keep earlier results` (earlier run of 2026-11-10 with 4 values) and the new run covers Apple | step 5 is shown | the table lists Apple's values and Microsoft's 4 values, and each Microsoft row's Company cell reads `Microsoft` and `kept from the extraction of 2026-11-10` | evaluator |
| AC-119 | the state of AC-118, one Microsoft value waiting for review | it is approved in place | the earlier run's review page shows that approval | evaluator |
| AC-120 | the state of AC-118 | step 5 is shown | the note `This run covers 1 of 2 companies. Not in it: Microsoft (kept from the extraction of 2026-11-10, open).` is still shown, as on `main` | evaluator |
| AC-121 | a run with `Revenue` for the period ends 2026-06-30 and 2025-06-30 of one company | step 5 is shown | a `Period` column follows `Field`; the two rows read `2026-06-30` and `2025-06-30`, the 2026 row first | evaluator |
| AC-122 | a value with no period end | its Period text is computed | it is `—` | unit |
| AC-123 | a field with unit `tCO2e` | each of `metric tons CO2e`, `metric tonnes CO2e`, `metric tons of CO2e`, `metric tonnes of CO2e`, `metric tons of CO2 equivalent`, `metric tonnes of CO2 equivalent` is normalised with the value 12.5 | each gives 12.5 tCO2e with no `check_failed` reason | unit |
| AC-124 | a field with unit `tCO2e` | `12.5` with the unit `thousand metric tons CO2e` is normalised | the canonical value is 12500 tCO2e | unit |
| AC-125 | a field with unit `tCO2e` | a value with the unit `tons CO2e` is normalised | it has the `check_failed` reason, as on `main` | unit |
| AC-126 | a recorded walkthrough of a field whose blind re-extraction failed | the body of the step `Verify, blind` is computed | it contains `Blind re-extraction failed: the answer did not fit the field type.` | unit |
| AC-127 | a finished run for Apple, matched to central id X | in the Data Library the run's results are opened and Apple's company link is clicked | the company page opens with the heading `Apple` and shows Apple's ISIN | evaluator |
| AC-128 | a company id `AAPL` with no central id known | `companyHref("AAPL")` is called | it returns `#/companies/UNIVERSE%3AAAPL`, as on `main` | unit |
| AC-129 | XBRL Facts with a list of 1 company picked | `Add one company` is submitted with Name `Microsoft` and CIK `789019` | the picker reports 2 companies | evaluator |
| AC-130 | the state after AC-129 | the fetch is started | the run covers 2 companies | evaluator |
| AC-131 | XBRL Facts with nothing picked | `Add one company` is submitted | the picker reports 1 company | evaluator |
| AC-132 | the state after AC-129 | the same company is added again | the picker still reports 2 companies | evaluator |
| AC-133 | the state after AC-129 | a list file with 3 companies is uploaded | the picker reports 3 companies, as on `main` | evaluator |
| AC-134 | a flow file as `main` stores it, with an unmatched company whose `company_id` is `1` and a file under that key | the flow is read | the company's `company_id` is `1` and `files` lists the file | unit |
| AC-135 | a flow without a run with unmatched `Dune` (name only) and one uploaded file for it | `PUT` for Dune with `{name: "Dune Corp"}` | 200; the row is named `Dune Corp`, has the same `company_id` as before, and `files` still lists the file | holdout |
| AC-136 | a flow without a run with unmatched `Elm` (name only) and one uploaded file for it; ISIN `NL0000009165` is not in the register | `PUT` for Elm with `{name: "Elm", isin: "NL0000009165"}` | 200; Elm has an `entity_id`, the same `company_id` as before, and `files` still lists the file | holdout |
| AC-137 | as AC-23, but Acme has an uploaded file in this flow and CIK `1234567` is not in the register | `GET …/flows/<id>` | Acme has an `entity_id`, the same `company_id` as before, and `files` still lists the file | unit |
| AC-138 | a flow file with `starting` true, `updated_at` 5 seconds ago and no `run_id` | `PUT` or `DELETE` on one of its companies | 409 with detail `Companies cannot be changed once the extraction has started.` | unit |
| AC-139 | the flow of AC-138 | `POST …/discard` | 409 with detail `An extraction that has started cannot be deleted.` | unit |
| AC-140 | the matched row of AC-7 in a flow with source `Official filings` | `Find documents` is called | the discovery run's stored company list has Microsoft with `cik` `789019` (leading zeros allowed) | unit |
| AC-141 | a finished run with a company that failed because its document has no text | `GET …/progress` | that company's `retryable` is true | unit |
| AC-142 | a running run on which Stop was not requested | `GET …/progress` | `stopping` is false | unit |
| AC-143 | a file whose check fails, kept by hand, then removed in this flow | the same bytes are uploaded again for the same company | that file's `state` is null | holdout |
| AC-144 | a stand-in that maps `MSFT` to `789019` | `{name: "Microsoft", ticker: "MSFT", isin: "XX"}` is added | the row's `cik` is `789019` (leading zeros allowed) and its `isin` is null | unit |
| AC-145 | a flow whose discovery run found a filing that passes its check | the flow is read | that file's `state` is null, as on `main` | unit |
| AC-146 | a run started 5 minutes ago with 2 companies: one at `Checking the answers` (75), one `Waiting`, none finished | `GET …/progress` | `minutes_left` is 9 | unit |
| AC-147 | the identity run statuses `pending`, `running`, `completed`, `failed` and an unreadable record (null) | the rule that decides whether step 1 reads the flow again every 4 seconds is evaluated for each | it is true for `pending` and `running` only | unit |
| AC-148 | a flow whose identity run ended `completed` with 1 company still unmatched | step 1's status line is computed | it reads `The identity run ended (completed): 1 company still has no identifier. Add an ISIN, LEI or CIK for it, or try again.`, as on `main` | unit |
| AC-149 | step 1 of a flow without a run, with 3 companies | `Remove` is clicked on a row | no dialog opens, the row is gone and the button reads `Continue with 2 companies` | evaluator |
| AC-150 | the state of AC-118 | `How was this found?` is clicked on a Microsoft row | the walkthrough of the 2026-11-10 run opens for Microsoft and that field | evaluator |
| AC-151 | the run of AC-112 | a row reads `Done` | its progress bar is filled to its full width | evaluator |
| AC-152 | the state after AC-129, where the first list was a saved universe with 1 company | XBRL Facts is opened again and that saved universe is picked | the picker reports 1 company | evaluator |
| AC-153 | the state after AC-129 | a saved universe with 5 companies is picked | the picker reports 5 companies, as on `main` | evaluator |
| AC-154 | the state after AC-44, the launched run still running | Start is called again | 409 with detail `This extraction is already running.` | unit |
| AC-155 | three flow files with `starting` true, `updated_at` 2 minutes ago, no `run_id` and one company each | `PUT` on the first's company, `DELETE` on the second's, `POST …/discard` on the third | 200, 200 and 204 | unit |
| AC-156 | a reason code `some_new_code` that has no sentence | it is turned into text | it reads `Reason: some new code.` | unit |
| AC-157 | a list row `name` `Fir`, `sector` `Software`, `country` `DE`, no identifier, uploaded to a flow | `PUT` for Fir with `{name: "Fir", isin: "SE0000108656"}` | 200; Fir has an `entity_id` and its `sector` is still `Software` and `country` still `DE` | holdout |

Must not change (each also a row above): a name-only row's key (AC-5); a matched row's key (AC-6); the
`No identifier` text (AC-12); one identity run per click (AC-64); plain `DELETE` of a flow (AC-33); the
duplicate-upload row (AC-39); a fresh `starting` flag blocks Start (AC-43); `done` in progress (AC-49);
`No runs yet.` (AC-74); an unreached step still opens (AC-105); the `Review` button's name (AC-117); the
"not in this run" note (AC-120); plain `tons CO2e` stays unknown (AC-125); `companyHref` (AC-128); an
uploaded XBRL list replaces the picked one (AC-133); a stored flow's keys (AC-134); a searched file stays
undecided (AC-145); the identity status line (AC-148); picking a saved XBRL universe replaces (AC-153).
