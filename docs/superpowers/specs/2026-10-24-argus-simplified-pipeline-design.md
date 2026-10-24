# A simplified Argus: one start page, five steps, no duplicates

Date: 2026-10-24
Status: draft, awaiting owner approval
Source: evaluator review of Argus on `main` at `ca652a3` (findings F1 to F5, layout and copy), and the
owner's brainstorming answers of 2026-10-24
Mockups: https://claude.ai/artifact/PTXrSNwBokToBVfSnfWw4P (start page plus five steps)
Builds on: `2026-10-21-retire-transition-plan-pipeline-design.md` (Transition Plan is the preset only)

## Intent

Argus is hard to use. A user who wants "extract schema X for universe Y" meets 11 screens, two step
lists that don't match, Run/Review and Manual/Automatic/Skip choices on every step, four places to
review, and a reload that loses their companies. Most pieces exist two to four times.

The typical user doesn't know what was extracted before, wants one schema run over one universe, and
rarely tunes anything. Settings stay available but out of the way.

This change rebuilds Argus as **one start page and five steps**, reusing the components and endpoints
that already exist, and deletes every duplicate screen. Screens come first; the data rules the owner
set follow in their own PRs.

## What the owner decided

- **Start page first.** Clicking Argus opens a start page with a live process flow (the five steps,
  each with the number of runs in it, clickable to filter), the runs list, what is waiting, and a
  **Start new extraction** button.
- **All runs.** The start page shows every run of the team, each with who started it.
- **Five steps:** 1 Companies, 2 Documents, 3 Schema, 4 Extract, 5 Results.
- **Step 1 shows what is already there**, per company: every identifier, the sector, whether it was
  extracted before, with which schema and version, and from which documents.
- **One central company ID.** Every company has exactly one central ID (`companies.id`). LEI, ISIN,
  CIK, ticker and the ids in a user's own list are additional identifiers on it.
- **Documents have four sources:** (1) the user uploads per company, with checks; (2) import from the
  shared import folder, mapped to companies, with checks; (3) SEC and ESEF filings; (4) filings plus a
  web crawl. Files open in a side panel and show a preview on hover. The user keeps or removes single
  files or the whole set.
- **Remove leaves a file out of this extraction only.** The file stays on the company.
- **The import folder is a shared drive** mounted on the server, with one subfolder per company under a
  defined naming convention. The app copies imported files into its own, separate folder.
- **Schema creation gets a visible structure**: saved schemas, templates, or "describe it in words",
  shown as a plain field table.
- **Extract shows, in plain words, where each company stands**, with its error.
- **Repeat runs are flagged, not decided.** When a company was already extracted with the same schema
  version from the same documents, the app says so and the user decides per company. If documents were
  added since, there is no warning; the row says how many are new.
- **Accepted results are never overwritten.** This covers values a person approved or edited and
  values the app accepted on its own. A re-run appends. A different value for an accepted field lands
  in the review list as a conflict.
- **XBRL facts stays a separate pipeline** with its own screen.
- **Build order: screens first**, then the data rules, and the duplicates are deleted as part of the
  plan.

## Calls made by the spec author (owner to check)

- **Waiting for you** shows the whole team's Argus items; **Only mine** filters both the runs list and
  Waiting for you to runs the signed-in user started.
- **Flows not yet started** (steps 1 to 3) are stored as draft runs and listed in Runs with status
  `Draft`. Any signed-in analyst can open and continue a draft.
- A run's status leaves `Needs you` and reads `Finished` once nothing in it waits for a decision.
- A new value that is itself routed to review or hold against an accepted fact creates one conflict
  item, not a conflict plus a review item.
- After **keep** on a conflict, the same new value for that fact does not raise the conflict again; a
  different value does.
- "The same documents" means the set of file contents the earlier run used for that company equals the
  set chosen now. Runs stored before this change have no such record and never trigger the warning.
- **Expected year** for the document check is a `Reporting year` field in step 2, defaulting to the
  previous calendar year.
- **Until the new steps exist** (slices 1 to 5), the start page's buttons open the old Extraction
  screens for steps not yet built, so nothing dead-ends. The old screens are removed in slice 6.

## Goals

1. A user goes from **Start new extraction** to results in five steps with one step bar and no
   sub-tabs.
2. Every Argus duplicate listed below is gone, and every link to a removed screen lands on its
   replacement.
3. A reload, or the same link opened by a teammate, returns to the same step with the same companies,
   documents and schema.
4. Before extraction starts, the user sees what each company already has.
5. No accepted value is replaced without a person deciding.

## Non-goals

- Changing the extraction engine, its graph or its models.
- Rebuilding Financials or TNFD as field schemas (parked by the 2026-10-21 spec).
- Merging the security master's JSONL store into the database (see "Left out").
- Changing XBRL Facts beyond using the shared company picker.
- Changing the Run History, Decision Studio or Security Master screens themselves.

## Anti-goals

- **A second way to do a step.** If any step can still be done from two Argus screens after this, it
  failed even if everything works.
- **A wizard that hides state.** Every step shows its result and lets the user go back.
- **Silent decisions.** Skipping a repeat, replacing a fact or matching a folder to a company never
  happens without the user seeing it.

## Constraints

- One PR per slice against `main`; at most three agent PRs in flight (`steward` skill).
- Stored runs of every type stay readable.
- Other workspaces that hand a universe to Argus (Thematic Universe, Risk Monitoring, Data Hub) keep
  working: their hand-over lands on step 1.
- After any change to a request or response model: `export_openapi.py`, `npm run gen:api`, commit both.

## Duplicates removed

| Today | After |
|---|---|
| Company list upload on Universe, Extraction › Companies, saved-universe pickers in Identify and Documents, XBRL Fetch | One company picker (step 1). XBRL Facts mounts the same component |
| Pipeline drawn 4 times: hub's 9 cards, 5 Extraction tabs, overview flow diagram, Extract tab step diagram | The start page's flow and the step bar |
| Identify and Documents as steps and as screens (`#/identity`, `#/discovery`) | Identify runs inside step 1; Documents is step 2 |
| Review in Documents › Review, Extract › Review, Review Queue, Tape Reader | Step 5 for the current run; Review Queue for everything (Tape Reader stays as a keyboard view of the same queue) |
| "What is stored" on Universe columns, Companies "ready / to onboard", document readiness | Step 1's table |
| Run status in Current runs, Extract › Run, Run History, "Needs you" | Step 4 for the current run; start page for Argus; Run History for all workspaces |
| `#/transitionPlan`, a second entry to the Extraction page | Transition Plan is a template in step 3 |
| Profile checkboxes plus a Schema tab | Step 3's single picker |

Removed: the 9-card hub content on `#/argus`, the screens at `#/argusUniverse`, `#/transitionPlan`,
`#/identity`, `#/discovery` and `#/extraction` with their tabs, the overview flow diagram, and the
Extract tab's step diagram (`PipelineEditor`'s canvas). Per-step settings the step diagram held
(models, evidence count, thresholds) move into step 3's **Settings (optional)** panel.

Old routes redirect (any sub-path included):

| Old route | Lands on |
|---|---|
| `#/extraction`, `#/extraction/...` | `#/argus` (start page) |
| `#/argusUniverse`, `#/identity` | step 1 of a new flow |
| `#/discovery` | step 1 of a new flow |
| `#/transitionPlan` | step 1 of a new flow with the `Transition plan` template preselected for step 3 |

## The screens

Mockups: https://claude.ai/artifact/PTXrSNwBokToBVfSnfWw4P. Values shown as `[value]` there are
placeholders, not real figures. Quoted strings below are the exact UI copy.

### Every step

- One step bar with five items `1 Companies` … `5 Results`; the current one is marked, finished ones
  show `✓`. Clicking an earlier item goes back to it with its data unchanged. No tab lists inside a
  step.
- The flow's id is in the URL. A reload, or a teammate opening the URL, shows the same step and data.

### Start page (`#/argus`)

- **Start new extraction** opens step 1 of a new draft flow with an empty list.
- **Process** region: five tiles, one per step, each with the number of runs in that step and, when
  something waits there, a line like `2 files need you` in the warning (orange) style. Clicking a tile
  filters Runs to that step; clicking it again clears the filter.
- **Runs** table: every Argus run (extraction runs of any profile and drafts), newest first. Columns:
  run (`<schema> v<n>`, plus who started it and when), companies (`<N>`), step (`<n> <Step name>`),
  status (one of `Draft`, `Running`, `Needs you`, `Stopped`, `Failed`, `Finished`), and an **Open** link that
  opens the run at its current step. **Only mine**, off by default.
- **Waiting for you** region: the count of open Argus items, grouped as `Conflicts`, `Values to review`,
  `Documents to check`, `Errors`, with a link to `#/review`. Items from other workspaces are not
  counted.
- A link to XBRL Facts.

### Step 1: Companies

- Pick a saved universe or index, add one company (name, ticker, ISIN, LEI or CIK), or upload a list.
- One row per company: central ID, every identifier, sector, country, **Extracted before** and
  **Documents on file**.
  - Extracted before: `<schema> v<n> · <YYYY-MM-DD> · <a> approved · <w> waiting`, or `Never`.
  - Documents on file: `<count> (<types, comma separated>)`, or `None`.
- A company the app can't match is in the warning style with `No identifier: add an ISIN, LEI or CIK`.
- A user's own id column (for example `company_id`) becomes an additional identifier of scheme `USER`
  on the matched company; it never creates a second company.
- **Resolve identities** starts one identity run for the unmatched companies only. Nothing runs before
  the click.
- **Continue with N companies** goes to step 2.

### Step 2: Documents

- `Reporting year` field (default: previous calendar year).
- Choose one source: `I upload them`, `From the import folder`, `Official filings`,
  `Filings + company websites`.
- Every file shows type, year, source and its check: `✓ name, year`, or in the warning style
  `Company not found in document`, `Year <found>, expected <reporting year>`, `Year unclear`.
- Per file: **Keep** or **Remove**. For the set: **Keep all that pass** and **Remove all**. Remove
  leaves the file out of this flow; it stays on the company.
- Hovering a file name shows an image of its first page. Clicking it opens the file in the side panel.
- **Continue with N files for M companies** goes to step 3.

### Step 3: Schema

- Left: saved schemas (each with `v<n>` and `released` or `draft`), templates (the installable presets
  including `Transition plan`, plus `Financials` and `TNFD` as built-in fixed profiles), and
  `Describe it in words` with **Draft fields**.
- Right: the chosen schema as a table with columns `Field`, `Type`, `Unit`, `What it means`, `Look in`;
  **Add field**; **Edit as v<n+1>**; **Release** for approvers.
- **Settings (optional)**, collapsed on open: quality mode, batch, the per-step settings, and an
  optional Decision Studio scoring template.
- Repeat warning: see "The repeat rule" below.
- Start button: `Extract <schema> v<n> for <N> companies` for a released schema, or
  `Try <schema> on 1 company` for a draft. A trial writes no facts.

### Step 4: Extract

- Header: `Started <HH:MM> · <done> of <N> done · about <m> minutes left · $<cost> so far` and **Stop**.
- One row per company: status (one of `Waiting`, `Reading documents`, `Extracting`,
  `Checking the answers`, `Done`, `Stopped`, `Failed`), a progress bar, what needs you, and for a failure
  the reason in words with **Retry** and, for a document problem, **Replace file**. For a document with
  no text the reason reads `No text could be read from <file name>`.
- The user can leave; the start page shows the run.

### Step 5: Results

- One row per value: company, field, value, source page, decision. Rows that need a person come first
  with **Approve** / **Edit** / **Reject**, or for a not-found value **Confirm not disclosed** /
  **Enter value**.
- A conflict row shows `Accepted: <old>` and `New: <new>`, each with its source, and **Keep accepted** /
  **Accept new**.
- Clicking a source opens the cited page in the side panel with the quote highlighted.
- **Only what needs me** (off: all rows, needing-me first; on: only those) and **Download CSV**.

## The repeat rule (slice 4)

When a run starts, it records per company the set of document content keys it used. In step 3, for
each company the app compares the chosen schema version and that company's kept files with the most
recent run of that company:
- **Same schema version and same set of file contents:** an orange box lists the company with the
  earlier run's date and its counts, and **Skip, keep earlier results** / **Run again** /
  **See earlier results**. Nothing is pre-chosen; Start is disabled until each listed company has a
  choice. Skipped companies are left out of the run.
- **Files added since** (the earlier set is contained in the current one, plus more): no warning; step 1
  and the step 3 list show `1 new document since the last run`, or `<k> new documents since the last run`
  for more than one.
- **Any other difference** (another version, a file changed or removed): no warning.

## The data rules (later slices)

1. **Accepted values are never overwritten** (`decide()` in `backend/arp/db/observations.py`). When the
   current fact is accepted (status `auto_accepted`, `approved` or `edited`):
   - an identical value changes nothing and stores no new observation row;
   - a different value is stored as an observation and creates one review item of kind `conflict`
     linking the current fact and the new observation; the current fact is unchanged;
   - deciding `keep` closes the item with decision `keep`; the fact stays; the same value is not raised
     again for that fact;
   - deciding `accept` closes the old fact (it keeps its row with `valid_to` set) and makes the new
     value the current fact with status `approved`.
   A pending or held current fact follows today's rules.
2. **One review list.** Document flags (discovery, import) and conflicts appear in the Review Queue next
   to field items, each with its kind (`document`, `conflict`, `field`). Tape Reader reads the same
   queue.
3. **Import from the shared folder, with copies.** The folder is a path set in config
   (`ARP_IMPORT_DIR`), mounted from the team's shared drive. Layout:

   ```
   <import folder>/
     Apple-Inc__LEI-HWUPKR0MPOU8FGXBT394/
       annual/2025_10-K.pdf
       sustainability/2025_Environmental-Progress-Report.pdf
   ```

   - Company folder: `<Readable-Name>__<SCHEME>-<value>`, scheme one of `LEI`, `ISIN`, `CIK`, `ID`
     (central id). Only the part after `__` is matched; the name is for people.
   - Type subfolders: `annual`, `sustainability`, `proxy`, `transcript`, `presentation`,
     `transition-plan`, `other`.
   - Files: `<year>_<anything>.<ext>`. No year: read from the document, else `Year unclear`.
   - **From the import folder** in step 2 first lists each subfolder for the flow's companies with its
     matched company, plus the folders it could not match, before anything is copied. On **Import**, it
     copies each file into the app's document folder. Unmatched folders never create companies. A file
     whose content names another company gets `Company not found in document`. An exact duplicate
     (same content hash) is skipped and listed as `Duplicate of <file name>, skipped`.
4. **Documents filed by central ID.** The app's document folder is keyed by `companies.id`, so one
   company's files stay together whichever identifier a list used. A one-time migration moves existing
   folders; running it twice changes nothing.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| A | Replace the Extraction page in place | No duplicate code, but the old flow is in pieces mid-change |
| **B (chosen)** | Build the start page and steps next to the old page, switch over, then delete the old | Safest, can be compared side by side; two ways to run an extraction for a few weeks |
| C | Fix the current flow only | Cheapest, keeps the nesting that makes it complicated |

The owner chose B, screens first, with the duplicates removed as part of the plan.

## Slices (one PR each, in order)

1. Start page on `#/argus`. Buttons for steps not yet built open the old screens.
2. Step 1 Companies, draft flows, flow id in the URL.
3. Step 2 Documents: upload, filings, filings plus web; checks; keep/remove; hover preview and side panel.
4. Step 3 Schema: picker, field table, release, settings panel, repeat rule.
5. Steps 4 and 5: per-company progress with errors, results with in-place review.
6. Switch-over: hand-overs land on step 1, old routes redirect, XBRL Facts uses the step 1 picker, every
   removed screen and diagram is deleted.
7. Data rule: accepted values never overwritten, conflicts to review.
8. Data rule: one review list.
9. Data rule: import from the shared folder (switches on `From the import folder` in step 2).
10. Data rule: documents filed by central ID, with migration.

## Left out, on purpose

- **Security master merge.** Identifiers live both in `company_identifiers` (database) and in the JSONL
  `IdentifierMapStore`. Moving the JSONL map into `company_identifiers` touches StewardIQ and Risk
  Monitoring too, so it gets its own spec. Until then step 1 shows the database central ID and the
  master identifiers beside it.
- Financials and TNFD as field schemas.
- A design pass beyond the app's existing rules.

## Left to the builder

- Component and file names, and how draft runs are stored (a run with status `draft` or a separate
  record), as long as the start page and Run History behave as specified.
- Which existing components to reuse where (`ArgusUniverse` table, `DocumentUpload`, `SourcePanel`,
  `SchemaPanel`/`SchemaFieldsEditor`, `JobRun`, `ExtractionResults`, `ReviewQueue`).
- Adding a "started by" field to runs (none exists today).

## Acceptance

Rows checked by `holdout` are owed as `unit` until `HOLDOUT_TOKEN` is set; the PR lists them.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | the app is open | **Argus** is clicked in the sidebar | the hash is `#/argus` and the page has a button `Start new extraction`, a region `Process` with exactly 5 links whose labels start `1 Companies`, `2 Documents`, `3 Schema`, `4 Extract`, `5 Results`, a `Runs` table and a `Waiting for you` region | evaluator |
| AC-2 | run R1 (step 4, started by user A) created before run R2 (step 5, started by user B) | the start page opens | the `Runs` table's first row is R2 and the second R1; each shows `<schema> v<n>`, `<N> companies`, its starter's name, its step (`5 Results`, `4 Extract`) and a status from `Draft`, `Running`, `Needs you`, `Stopped`, `Failed`, `Finished` | evaluator |
| AC-3 | the runs of AC-2 | **Open** is clicked on R1 | step 4 of R1 opens | evaluator |
| AC-4 | the runs of AC-2 | the `4 Extract` tile is clicked, then clicked again | first only R1 is listed; after the second click both are | evaluator |
| AC-5 | the runs of AC-2, signed in as user A | the start page opens | `Only mine` is off and both runs are listed | evaluator |
| AC-6 | the state of AC-5 | `Only mine` is switched on | only R1 is listed and `Waiting for you` counts only R1's items | evaluator |
| AC-7 | R2 has 2 values waiting for review, and a StewardIQ run has 1 item waiting | the start page opens | `Waiting for you` reads `2` with `Values to review: 2` and links to `#/review`; the `5 Results` tile is in the warning style and reads `2 values need you`; the other 4 tiles are not in the warning style | evaluator |
| AC-8 | the start page | `Start new extraction` is clicked | step 1 opens with an empty company list and the step bar shows 5 items with `1 Companies` current | evaluator |
| AC-9 | any of steps 1 to 5 | the page is inspected | it has exactly one step bar with 5 items and no element with `role="tablist"` | evaluator |
| AC-10 | step 1 with a CSV of 4 rows: Apple (LEI HWUPKR0MPOU8FGXBT394, ISIN US0378331005, CIK 0000320193, sector `Information Technology`, country `US`), Microsoft (ISIN US5949181045, sector `Information Technology`, country `US`), SAP (LEI 529900D6BF99LW9R2E68, sector `Information Technology`, country `DE`), Acme (name only) | the CSV is uploaded | the table has 4 rows; Apple, Microsoft and SAP each show a central ID, the identifiers given, and the sector and country given; Acme's row is in the warning style and reads `No identifier: add an ISIN, LEI or CIK` | evaluator |
| AC-11 | Apple already in `companies` with its LEI | a list with Apple's LEI and `company_id` `AAPL-X` is uploaded in step 1 | the number of rows in `companies` is unchanged and `company_identifiers` has a row with scheme `USER`, value `AAPL-X` on Apple's `companies.id` | holdout |
| AC-12 | a company with a run of schema S v2 on 2026-10-01 with 3 approved and 1 waiting field, and 2 documents (annual, sustainability) | it is loaded in step 1 | `Extracted before` reads `S v2 · 2026-10-01 · 3 approved · 1 waiting` and `Documents on file` reads `2 (annual, sustainability)` | evaluator |
| AC-13 | step 1 with 3 matched and 1 unmatched company | the page is shown, then `Resolve identities` is clicked | no identity run exists before the click; after it exactly one identity run exists, with 1 company | evaluator |
| AC-14 | step 1 with 4 companies loaded | the page is reloaded | step 1 shows the same 4 companies | evaluator |
| AC-15 | a flow at step 3 with 3 companies, 5 kept files and schema S chosen | the page is reloaded, then steps 1 and 2 are opened from the step bar | step 3 shows S chosen; step 1 shows the same 3 companies; step 2 shows the same 5 files as `Kept` | evaluator |
| AC-16 | the flow of AC-15, started by user A | user B opens its URL | user B sees step 3 with the same companies, files and schema | evaluator |
| AC-17 | the flow of AC-15 at step 3 | `1 Companies` in the step bar is clicked, then `3 Schema` | step 1 shows the same 3 companies; back on step 3, S is still chosen | evaluator |
| AC-18 | step 2 with files for 3 companies | one file is removed | that file is gone after a reload, the continue button's file count is 1 lower, and that company's `Documents on file` in step 1 is unchanged | evaluator |
| AC-19 | step 2 with 9 files, 2 failing their check | `Keep all that pass` is clicked | 7 rows show `Kept`, the 2 failing rows show neither `Kept` nor `Removed`, and the button reads `Continue with 7 files for <M> companies` | evaluator |
| AC-20 | a PDF uploaded for Apple whose text names only Microsoft | the upload finishes | its check reads `Company not found in document` and its row is in the warning style | evaluator |
| AC-21 | `Reporting year` 2025 | a file named `2023_report.pdf` whose text gives 2023 is uploaded | its check reads `Year 2023, expected 2025` and its row is in the warning style | evaluator |
| AC-22 | step 2 with a kept PDF | the pointer rests on its name | an image of its first page appears | evaluator |
| AC-23 | step 2 with a kept PDF | its name is clicked | the side panel opens showing that file | evaluator |
| AC-24 | the same PDF uploaded twice for one company | the second upload finishes | the company's document list in the API has 1 entry for it, and the UI row reads `Duplicate of <file name>, skipped` | holdout |
| AC-25 | step 3 | it opens | the picker lists saved schemas each with `v<n>` and `released` or `draft`, templates including `Transition plan`, `Financials` and `TNFD`, and a `Describe it in words` box; `Settings (optional)` is collapsed | evaluator |
| AC-26 | saved schema S with 4 fields | S is chosen | a table with columns `Field`, `Type`, `Unit`, `What it means`, `Look in` and 4 rows is shown | evaluator |
| AC-27 | the model replaced by a stand-in returning 3 fields | `Draft fields` is clicked with a description | the table shows those 3 fields | unit |
| AC-28 | `Settings (optional)` opened and evidence passages set to 3 | the run starts | the started run's stored settings have evidence passages 3 | unit |
| AC-29 | a draft schema chosen | step 3 shows its start button | the button reads `Try <schema> on 1 company` | evaluator |
| AC-30 | a trial run of a draft schema finishes with values | `company_facts` is read | it has 0 rows from that run | holdout |
| AC-31 | a run of a released schema finishes with auto-accepted values | `company_facts` is read | it has at least 1 row from that run | holdout |
| AC-32 | Apple's last run used schema S v2 and files F, and S v2 and the same F are chosen | step 3 opens | a warning lists Apple with that run's date, and the start button is disabled until Apple has `Skip, keep earlier results` or `Run again` chosen | evaluator |
| AC-33 | the same as AC-32 but one file in F has different content | step 3 opens | no warning lists Apple | holdout |
| AC-34 | the same as AC-32 but F plus one new file is chosen | step 3 opens | no warning lists Apple, and Apple's row reads `1 new document since the last run` | evaluator |
| AC-35 | the same as AC-32 but S v3 is chosen | step 3 opens | no warning lists Apple | holdout |
| AC-36 | Apple set to `Skip, keep earlier results` | the run starts | the run's company list does not contain Apple | holdout |
| AC-37 | a run where one company fails because its document has no text | step 4 shows | that row's status is `Failed`, it reads `No text could be read from <file name>`, and it has `Retry` and `Replace file`; every other row has a status from the fixed list and a progress bar | evaluator |
| AC-38 | that failed company | `Retry` is clicked | that row leaves `Failed` and shows `Waiting` or `Reading documents`; every other row's status is unchanged | evaluator |
| AC-39 | a running extraction | step 4 shows | the header reads `Started <HH:MM> · <done> of <N> done · about <m> minutes left · $<cost> so far` and has a `Stop` button | evaluator |
| AC-40 | a finished run with 2 values to review and 5 accepted | step 5 opens with `Only what needs me` off | all 7 rows are listed, the 2 to review first, each with `Approve`, `Edit`, `Reject` | evaluator |
| AC-41 | the run of AC-40 | `Only what needs me` is switched on | exactly 2 rows are listed | evaluator |
| AC-42 | a value recorded as not found and routed to review | step 5 shows it | its row has `Confirm not disclosed` and `Enter value` | evaluator |
| AC-43 | a step 5 row citing page 37 | its source is clicked | the side panel shows page 37 with the quote highlighted | evaluator |
| AC-44 | the run of AC-40 | `Download CSV` is clicked | a CSV with a header and 7 data rows is saved | evaluator |
| AC-45 | a fact with status `approved`, value 12 | a new run extracts 14 routed auto-accept | the current fact is 12 `approved`, a new observation with 14 exists, and one open review item of kind `conflict` links both | holdout |
| AC-46 | a fact with status `edited`, value 12 | a new run extracts 14 | as AC-45 | holdout |
| AC-47 | a fact with status `auto_accepted`, value 12 | a new run extracts 14 | as AC-45 | holdout |
| AC-48 | a fact with status `approved`, value 12 | a new run extracts 14 routed to review | the current fact is 12 and exactly one new review item exists for that field, of kind `conflict` | holdout |
| AC-49 | a fact with status `approved`, value 12 | a new run extracts 12 | the fact is unchanged, no review item is created and no new observation row is stored | holdout |
| AC-50 | the conflict of AC-45 | it is decided `keep` | the current fact is 12 `approved`, the item is closed with decision `keep`, and the 14 observation remains | holdout |
| AC-51 | after AC-50 | another run extracts 14 again | no new conflict item is created | holdout |
| AC-52 | the conflict of AC-45 | it is decided `accept` | the current fact is 14 `approved`; the 12 fact row still exists with `valid_to` set | holdout |
| AC-53 | a conflict, a document flag and a field review item | the Review Queue opens | it lists 3 items with kinds `conflict`, `document`, `field` | evaluator |
| AC-54 | the items of AC-53 | Tape Reader opens | it steps through the same 3 items | evaluator |
| AC-55 | step 5 shows the conflict of AC-45 | the row is shown | it reads `Accepted: 12` and `New: 14` with `Keep accepted` and `Accept new` | evaluator |
| AC-56 | `ARP_IMPORT_DIR` holds `Apple-Inc__LEI-HWUPKR0MPOU8FGXBT394/annual/2025_10-K.pdf` | the import runs for Apple | the file is in the app's document folder under Apple's `companies.id`, with type `annual` and year 2025 | holdout |
| AC-57 | `ARP_IMPORT_DIR` also holds `Unknown__ISIN-XX0000000000/annual/2025_a.pdf` | the import runs | the result lists `Unknown__ISIN-XX0000000000` as unmatched and the number of rows in `companies` is unchanged | holdout |
| AC-58 | the folder of AC-56 | `From the import folder` is chosen in step 2 | before anything is copied, each subfolder is listed with its matched company or `unmatched` | evaluator |
| AC-59 | an imported file | it is deleted from the import folder | the company's document list still has it and it opens | holdout |
| AC-60 | `annual/report.pdf` with no year in its name or text | it is imported | its check reads `Year unclear` | holdout |
| AC-61 | documents stored under a folder named by an ISIN | the migration runs, then runs again | each document sits under `<companies.id>/` and opens; the second run changes nothing | holdout |
| AC-62 | slice 6 is merged | `#/extraction/companies/auto` is opened | the hash becomes `#/argus` | evaluator |
| AC-63 | slice 6 is merged | each of `#/argusUniverse`, `#/identity` and `#/discovery` is opened in turn | each one opens step 1 of a new flow | evaluator |
| AC-64 | slice 6 is merged | `#/transitionPlan` is opened | step 1 of a new flow opens, and step 3 has `Transition plan` preselected | evaluator |
| AC-65 | slice 6 is merged | the hand-over to Argus is used from Thematic Universe, Risk Monitoring and Data Hub in turn | each time step 1 opens with the handed-over companies listed | evaluator |
| AC-66 | slice 6 is merged | every route in the sidebar and in `All screens` is opened | a company universe upload appears only on step 1 and XBRL Facts; a document upload only on step 2; no page shows the 9-card hub, the overview flow diagram or the `PipelineEditor` canvas | evaluator |
| AC-67 | slice 6 is merged | XBRL Facts opens | its company picker has the same controls and labels as step 1 | evaluator |
| AC-68 | slice 6 is merged | an XBRL fetch for CIK 0000320193 is run | it finishes with status `completed` and more than 0 facts | evaluator |
| AC-69 | stored runs of types `extraction`, `transition_plan`, `financials`, `tnfd`, `identity` and `discovery` with known result and review counts | each is opened from Run History | each shows the same number of result rows and review items as before the change | evaluator |
| AC-70 | a run started from step 3 | Run History opens | the run is listed | evaluator |
| AC-71 | the slice 6 PR's build | `arp golden-set run` is run on it (by hand if CI skips it) | it exits 0 | golden |
| AC-72 | a running extraction with 3 companies not yet started | `Stop` is clicked | those 3 rows read `Stopped`, no company starts afterwards, and the start page shows the run with status `Stopped` | evaluator |
| AC-73 | the flow of AC-8 | `#/argus` is opened | `Runs` has a row for it with status `Draft` and step `1 Companies` | evaluator |
| AC-74 | step 2 with 9 files | `Remove all` is clicked | all 9 rows show `Removed`, the continue button is disabled, and each company's `Documents on file` in step 1 is unchanged | evaluator |
| AC-75 | `ARP_IMPORT_DIR` holds an Apple file whose text names only Microsoft | the import runs for Apple | the file's check reads `Company not found in document` | holdout |
| AC-76 | `ARP_IMPORT_DIR` holds the same content twice under Apple | the import runs | Apple has 1 document for that content and the result lists 1 as `Duplicate of <file name>, skipped` | holdout |
| AC-77 | scoring template T chosen in `Settings (optional)` | the run starts | the started run has T attached | unit |

Must not change: stored runs stay readable (AC-69); XBRL fetch works (AC-68); hand-overs work (AC-65);
trial runs write no facts (AC-30); new runs appear in Run History (AC-70); Tape Reader reads the queue
(AC-54); the engine's results (AC-71).
