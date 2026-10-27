# Argus walkthrough: how one value was found

Status: draft for the owner, 2026-10-27.

## Why

The 2026-10-26 extraction test ended with a hand-made walkthrough (Caterpillar total capex, ArcelorMittal blast
furnace) that showed, stage by stage, what the models said and what the code checked. It explained in minutes
why a value landed in front of a reviewer. Building it took reading the run's model log by hand. The owner wants
the same view inside Argus, for any field of any run, so a reviewer (or a committee the screen is shared with) can
see why a value is what it is without asking an engineer.

## Owner decisions (2026-10-27)

1. **Any field of a real run**, not a fixed set of examples.
2. **Old runs are acceptable** with steps marked "not recorded".
3. **Save passage positions and the three model answers**, not the passage text.
4. **Two ways in:** a Walkthrough item in the Argus menu with Run → Company → Field pickers, and a
   "How was this found?" link on every result row and review item.
5. **All run types Argus runs:** data-point extraction (including the transition-plan schemas, which run as
   extraction runs), Financials and TNFD.
6. **Full answer depth:** every model step offers Summary, Full answer and JSON.
7. **Approach B:** a separate trace file per company in the run's folder.

## Goals

- During a run, keep what each field's models saw and said, at about 3 KB per field and company, with no extra
  model call.
- One screen in Argus that lays out every step one value went through, from document to route.
- Reach it from the Argus menu and from every result row and review item.

## Non-goals

- Changing extraction itself: models, prompts, retrieval, grounding, checks, routing, corrections.
- Back-filling traces for runs made before this change.
- Comparing traces across runs, searching traces, or exporting them.
- The golden set, research callers (`research/revenue_exposure/resolver.py`, `research/taxonomy_sources/empirical.py`)
  and any pipeline Argus does not run: they record nothing.

## Anti-goals (a failure even if it runs)

- A run, or one company in it, fails because its trace could not be written.
- A results page or export gets slower or larger because of traces.
- The walkthrough lets a reviewer tell a seeded known-answer item from a real one.
- The walkthrough shows another reviewer's decision (it shows model and code steps only).

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| A | A `trace` part on every stored result row | Least code, but every results page and export carries it, roughly 3× heavier for a 4,000-company run |
| **B** | **A trace file per company in the run's folder, read by its own endpoint** | **Chosen.** Results stay as they are; one more file per company and one endpoint. Fits how runs already keep `schema.json` and the step tally in the run folder |
| C | A Postgres table | Easy cross-run queries nobody asked for, at the price of a schema migration (a `risk:high` PR) |

## Design

### What a run records

For each company, the run writes one JSON file, `traces/<company_id>.json`, in the run's folder
(`run_store.run_dir(run_id)`), when it stores that company's result. Writing it is best effort: an error is logged,
the run records an event `trace_write_failed` with the company id (`run_store.append_event`), and the company's
result is stored as usual (anti-goal 1).

The file's top level has up to three keys, each present only when the run filled it: `fields` (data-point
fields), `plans` (transition-plan list fields) and `record` (Financials and TNFD). A plan-schema run can hold both
`fields` and `plans`.

**Data-point extraction runs** (`execute_extraction_run`, every schema): `fields` maps each field id this run
processed to one entry, always with every key below (`null` when unused):

```json
{"fields": {"tc_capex_total": {
  "field_id": "tc_capex_total",
  "grouped": false,
  "skipped": null,
  "passages": [{"doc_id": "doc_…", "char_start": 176348, "char_end": 179607, "section": "MD&A"}],
  "extractor":   {"model": "…", "prompt_version": "…", "answer": { /* ExtractionDraft as returned */ }},
  "verifier":    {"model": "…", "prompt_version": "…", "blind": false,
                  "answer": { /* VerifierOutput, or the blind draft */ }, "verdict": null},
  "adjudicator": {"model": "…", "prompt_version": "…", "answer": { /* AdjudicatorOutput */ }},
  "vision": null
}}}
```

- `passages`: the evidence chunks sent to the extractor, in the order sent. `char_end` is exclusive: the passage
  text is `document_text[char_start:char_end]`.
- `verifier` / `adjudicator`: `null` when that call did not happen in this run.
- **Blind verification** (high-risk field): the verifier model re-extracts into an `ExtractionDraft`, and code
  compares the two. `verifier.answer` is the model's draft as returned, and `verifier.verdict` is the
  `VerifierOutput` the code built from the comparison. For a non-blind verifier, `verifier.answer` is its
  `VerifierOutput` and `verifier.verdict` is `null`. *(Builder check; my call: decision 3 asks for what the model
  said, so the draft the code used to throw away is kept.)*
- **Vision check**: when the vision fallback ran for an ungrounded quote (`check_on_page`), its answer is kept as
  `vision: {"model", "prompt_version", "answer"}`, else `vision` is `null`. *(My call: it is a model call that can
  change grounding, so a full trace includes it.)*
- A field that did not reach the models records an entry with `skipped` set and `passages` `[]`, all answers
  `null`: `"skipped": "tagged"` (value from tagged data, `method` `tagged`), `"no_evidence"` (no passage matched),
  `"derived"` (a derived field computed by a rule) or `"documents_held"` (every document was held). Otherwise
  `skipped` is `null`. *(My call: a new run must never show the "before walkthroughs" note.)*
- A field extracted in a group call records `grouped: true`, the group's passages, and the group answer's values
  for this field only.
- A field reused from an earlier run (`reused_from_run` set) records nothing; the walkthrough reads the trace
  of the run the row was reused from.
- **Transition-plan list fields** (the plan actions schema's fields that `_extract_plans` fills with one
  `extract_plan` call per plan document): the file holds one entry per plan document under `plans`,
  `{"plans": {"<doc_id>": {"passages": […], "extractor": {…}}}}`; there is no verifier or adjudicator on that path.
  Their rows are told apart by `basis` as well as period. *(My call: decision 5 covers every schema.)*

**Financials and TNFD runs**: the file holds one entry for the whole company record (their extractor and verifier
cover every section in one call): `{"record": {"passages": […], "extractor": {…}, "verifier": {…}}}`. These
pipelines have no adjudicator.

**Seeded known-answer items** (`arp/review/quality.py`): the seeding writes a trace of the same shape for each
seeded field, at `run_dir(<the seeded run>)/traces/<seeded company_id>.json` (the seeded run is an ordinary
trial extraction run, so the walkthrough takes that run and company like any other): `passages` as below,
`extractor` = the seeded draft, `verifier` = the seeded verifier output, `adjudicator` `null`. A seeded
item's walkthrough is therefore built the same way as a real agreeing item's (anti-goal 3). Two details keep it
indistinguishable *(builder check; my calls)*: the passages come from running the real evidence selection
(`field_evidence`) over the seeded document, so the passage count is whatever real retrieval returns for it; and
for a high-risk seeded field `verifier.answer` is a draft (equal to the seeded draft) with `verifier.verdict` the
seeded output, as blind verification records. `model` and `prompt_version` are the values the real extractor and
verifier would record for that field (the same ones the seeded row's provenance already carries).

### The endpoint

`GET /api/walkthrough/runs/{run_id}/companies/{company_id}?item=<field_id or section>&period_end=<date or
unspecified>`, same sign-in as the run results endpoints (item names below). `period_end` is required for
data-point fields and plan list fields (with `basis` for the latter) and picks one stored row; Financials and TNFD
sections take no `period_end`. `trace_run_id`, `passages`, `extractor`, `verifier`, `adjudicator`, `vision` and
`skipped` all belong to that one row. Response:

```json
{
  "run_id": "…", "run_type": "extraction", "company_id": "…", "company_name": "Caterpillar",
  "item": "tc_capex_total", "item_name": "Total capex",
  "recorded": true,
  "trace_run_id": "…",
  "rows": [ /* the stored result rows for this field, every period; for Financials/TNFD the record's section */ ],
  "passages": [{"rank": 1, "doc_id": "…", "doc_title": "…", "section": "MD&A",
                "char_start": 176348, "char_end": 179607, "text": "…"}],
  "extractor": {…} | null, "verifier": {…} | null, "adjudicator": {…} | null, "vision": {…} | null,
  "skipped": null, "not_recorded_reason": null
}
```

- `passages[i].rank` is `i + 1`, in the order the passages were sent to the extractor.
- `rows` for a data-point field equals what the run results endpoint returns for that company and field, every
  period, in the same order (the picked row is the one whose `period_end` matches). Results rows carry no review
  decision data: decisions are stored separately and are not merged into results.
- Fields that did not reach the models still store a row, as today: `no_evidence` and `documents_held` a
  `not_found` row, `derived` the derived row. So the picker and the links reach them like any other row.
- Status codes: 401 without a session (as the results endpoints); 404 for an unknown run, an unknown company in
  the run, a field not in the run's schema, a schema field with neither a stored row nor a trace entry for the company, or a section name
  not listed below for that run type (a TNFD section on a Financials run, a Financials section on a TNFD run, any
  section name on a data-point run that is not one of its fields); 422 for a data-point or plan list field
  requested without `period_end`, or a plan list field without `basis`.
- `trace_run_id`: the run whose trace was read. For a reused row the endpoint follows `reused_from_run` from run
  to run (each run's stored row for the same field and period) until it reaches a row without `reused_from_run`;
  that run is `trace_run_id`. Stored rows are not changed. *(Builder check; my call: reuse overwrites
  `reused_from_run` with the latest run, so a run-3 row can point at a run-2 row that was itself reused.)*
- **Moved rows**: a row that R4 moved to a planned field (a `planned_move` correction with attribute `field_id`)
  reads the trace entry of the correction's `original` field, the field whose answer produced it. *(My call.)*
- `recorded`: `false` when no trace exists for this item; then `passages` is `[]` and every answer is `null`.
  `not_recorded_reason` says why, checked in this order: `"write_failed"` (the run has a `trace_write_failed`
  event for this company), `"expired"` (the run's `created_at` is more than `retention_runs_days` days ago) or
  `"before_traces"` (every other case: the run predates this change, or its file is missing). All three are
  checked against the `trace_run_id` run, so a reused row whose original run expired reads `expired`.
  `not_recorded_reason` is `null` when `recorded` is `true`. A skipped field (`skipped` set) has a trace and is
  `recorded: true`. *(Builder check; my call: traces expire with the run's other files, as today; the screen
  says so instead of claiming the run predates the feature.)*
- **Item names**: data-point runs use the field id; transition-plan list fields add `&basis=<basis>`; Financials
  sections are `segments`, `capex`, `rnd`; TNFD sections `disclosures`, `core_global_metrics`, `sector_metrics`,
  `general_requirements`, `sector_leap_considerations`. `rows` is always a list: a section that is one object
  (`capex`, `rnd`, `general_requirements`) comes back as a one-element list, `[]` when it is empty or `None`.
  *(My calls.)*
- `text`: cut from the cached document text (the same content store the review source view uses); `null` when the
  document text is not available.
- Unknown run, company or item: HTTP 404.
- The response never includes review decisions, reviewer names or cosigns (anti-goal 4).

### The screen

New Argus menu item **Walkthrough** (beside Universe). Route: `#/argusWalkthrough/<run_id>/<company_id>/<item>`
plus, for a data-point or plan list row, `/<period_end>` (the row's `period_end`, or `unspecified` when it has
none); Financials and TNFD sections have no period segment. The three pickers always show, prefilled from the route when it is full: Run (Argus run types,
newest first), Company (the run's companies), Field (data-point runs: each field and period with a stored row,
"Total capex · 2025"; plan list fields by basis; Financials: Segments, CapEx, R&D; TNFD: its five sections).
Choosing all three updates the route; a plan list row adds `?basis=<basis>` to it. Layout, as in the owner-reviewed mockup (https://claude.ai/artifact/U1chr5wCfgSQgXnHJ3qjFg):

1. **Result card:** stored value with unit, period, confidence, number of alternatives; the route and its
   reasons; for a row with an open review item, a link "Open in review queue".
2. **Steps**, in order, each with its number, name, `LLM · <model>` or `code`, and a short result label.

Data-point runs, ten steps:

| # | Step | Result label (examples) | Source |
|---|---|---|---|
| 1 | Tagged data first | `skipped` / `taken from XBRL tag` | row `method` |
| 2 | Find evidence | `12 passages` | trace `passages` |
| 3 | Extract | `2,821 · confidence 0.40` | trace `extractor` |
| 4 | Verify (`Verify, blind` for a high-risk field) | `agrees` / `disagrees` | trace `verifier`, row verifier confidence and notes |
| 5 | Adjudicate | `settled` / `unresolved` / `not needed` | trace `adjudicator` |
| 6 | Ground every quote | `1 of 2 grounded` | row citations |
| 7 | Combine into one record | `2.794 + 1 alternative` | row value, alternatives, confidence |
| 8 | Auto-corrections | `1 correction` / `none` | row `corrections`, lines as in the review panel |
| 9 | Checks | `6 passed` / `1 failed` | row `checks` |
| 10 | Route | `review` / `auto_accept` / `hold` | row `route`, `route_reasons` |

- **Skipped fields:** step 1 shows `taken from XBRL tag` for `skipped` `tagged`; for `no_evidence` step 2 shows
  `no passage matched` and steps 3–5 `not reached`; for `derived` step 1 shows `derived by rule` and steps 2–5
  `not reached`; for `documents_held` step 2 shows `documents held` and steps 3–5 `not reached`.
- **Vision check:** when `vision` is set, step 6 shows a line `Vision check · <model>` with its own Summary / Full
  answer / JSON tabs.
- **Blind verification:** step 4's Full answer shows the verifier's draft as a per-period table (like Extract)
  and, under it, the code's verdict (agrees, disagreement type, notes).

Financials and TNFD, six steps (five for TNFD):

| # | Step | Source |
|---|---|---|
| 1 | Find evidence | trace `record.passages` |
| 2 | Extract | trace `record.extractor` |
| 3 | Verify | trace `record.verifier`, the section's `verifier_notes` |
| 4 | Ground every quote | the section's citations and `grounded` |
| 5 | XBRL overlay (Financials only) | a value whose `raw_value_text` or any citation `quote` contains `SEC XBRL` (case-insensitive): `XBRL value used`, else `not used` |
| 6 | Combine | the section's confidence and the record's `needs_review` |

Transition-plan list fields, six steps: 1 Find evidence and 2 Extract plan (trace `plans.<doc_id>`, the plan
document the row cites), 3 Ground every quote, 4 Auto-corrections, 5 Checks, 6 Route (from the row, as for
data-point rows). Their Field picker lists each row by name and basis (`Actions · action:3`).

Steps a pipeline does not have are left out, not shown as "not recorded".

- **Find evidence** shows the passages ranked 1 and 2 with their document title, section and character range, and the
  quoted words of the row's citations marked inside them; the others behind "Show the other N passages".
  A passage whose `text` is `null` shows its position and "Text not available".
- **Model steps** (Extract, Verify, Adjudicate) each have three tabs: **Summary** (default: the plain line),
  **Full answer** (a table with one row per period: value, printed as, unit, state; then each quote with its
  passage and whether it was grounded; for the verifier and adjudicator, their fields as labelled lines) and
  **JSON** (the answer exactly as recorded, with a Copy button).
- **Not recorded** (`recorded: false`): a note above the result card. For `before_traces`: `This run is from
  before walkthroughs were recorded. Passages and model answers were not saved; the steps below show what the
  stored row holds.` For `expired`: `This run's walkthrough has expired: runs older than <retention_runs_days>
  days keep only their results. The steps below show what the stored row holds.` For `write_failed`: `The
  walkthrough for this company could not be saved during the run. The steps below show what the stored row
  holds.` In all three, steps 2, 3 and 5
  (Financials/TNFD: 1 and 2; plan list fields: 1 and 2) show `not recorded` in a dashed box. The verify step
  shows what the row holds: data-point step 4 the verifier confidence and notes; Financials/TNFD step 3 the
  section's `verifier_notes`. Code steps show as usual.
- **Reused:** when `trace_run_id` differs from the run, a line under the result card: `Reused from run
  <trace_run_id>; the steps show that run.`

### "How was this found?" links

The link opens the screen with run, company, item (and period) filled in. It appears on:

- each field in the extraction results (`frontend/src/components/ExtractionResults.tsx` field detail), which also
  covers the Data Library by-company view that reuses it;
- each review item's panel (`frontend/src/components/ReviewControls.tsx`);
- the TNFD results (`frontend/src/components/TnfdResults.tsx`) per section, and the Financials results per section
  (wherever they render today);
- each Financials and TNFD review item, opening the company with its first section picked.

### Size

About 3 KB per field and company: under 1 MB for a 10-company test, about 360 MB for 4,000 companies × 30 fields.
Traces live and are deleted with the run's folder.

## Left to the builder

- Module and component names, the exact Summary wording per step beyond the labels above, styling (follow the
  existing Argus pages and tokens).
- How the trace is threaded out of the field graph and the Financials/TNFD graph (the state already holds
  evidence, draft, verifier and adjudicator).
- How the API types are generated (run `scripts/export_openapi.py` and `npm run gen:api` per CLAUDE.md).

## Acceptance

"A run" below is an `arp extract run` (or the Financials/TNFD equivalent) with the stand-in model (`fake_llm`), so
answers are fixed. "The walkthrough" is the endpoint's response unless the row says the screen. "The same run on
`main`" means the same stand-in run on the `main` commit this branch starts from, compared with run ids and
timestamps ignored. The results CSV export is built in the browser from the results endpoint, so the results
endpoint rows cover it.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | A data-point run, one company, one non-high-risk field; the stand-in extractor returns 120 with one quote and the verifier agrees | the run completes | `traces/<company_id>.json` exists in the run folder; its top level has exactly the key `fields`; `fields` has exactly one key, the field id; that entry has `grouped` false, `skipped` null, `vision` null, `adjudicator` null, `verifier.blind` false, `verifier.verdict` null, `extractor.answer.values[0].value` 120, and `passages` equal in order to the chunks sent to the extractor, each with exactly the keys `doc_id`, `char_start`, `char_end`, `section` | holdout |
| AC-2 | As AC-1 but the field is high-risk; the stand-in extractor returns one value for the period ending 2025-12-31 with its quote in the rank-1 passage; evidence selection returns 12 passages; the stand-in blind verifier re-extracts 2.794, the comparison disagrees, the adjudicator returns `settled` false | the run completes | the entry has `verifier.blind` true, `verifier.answer.values[0].value` 2.794, `verifier.verdict.agrees` false, `adjudicator.answer.settled` false | holdout |
| AC-3 | The AC-1 run | the walkthrough is requested for that company, field and the row's `period_end` | HTTP 200; `recorded` true; `not_recorded_reason` null; `trace_run_id` equals `run_id`; for every i, `passages[i].rank` is i+1 and `passages[i].text` equals the document text `[char_start:char_end]` (end exclusive); `extractor.answer.values[0].value` 120 | holdout |
| AC-4 | A run created within `retention_runs_days`, whose folder has no `traces/` (made before this change) | the walkthrough is requested for a stored field | HTTP 200; `recorded` false; `not_recorded_reason` `before_traces`; `passages` `[]`; `extractor`, `verifier`, `adjudicator`, `vision` null; `rows` equals the results endpoint's rows for that company and field | holdout |
| AC-5 | Run 1 extracts the field; run 2, with unchanged inputs, reuses its row | the walkthrough is requested in run 2 for that row's field and `period_end` | `trace_run_id` is run 1's id; `recorded` true; `extractor` equals run 1's trace entry's `extractor` | holdout |
| AC-6 | A field whose value came from tagged data | the run completes | its trace entry has `skipped` `tagged`, `passages` `[]`, and `extractor`, `verifier`, `adjudicator`, `vision` null | holdout |
| AC-7 | The AC-6 run | the walkthrough is requested for that field | `recorded` true; `skipped` `tagged` | holdout |
| AC-8 | Fields A and B extracted in one group call; the stand-in group answer gives A one value 10 and B one value 20 | the run completes | both entries have `grouped` true and equal `passages`; A's `extractor.answer.values` has length 1 with value 10; B's has length 1 with value 20 | holdout |
| AC-9 | A Financials run for one company | the run completes | the trace file's top level has exactly the key `record`, holding `passages`, `extractor` and `verifier`, with no `adjudicator` key | holdout |
| AC-10 | The AC-9 run | the walkthrough is requested with `item=capex` | `recorded` true; `adjudicator` null; `rows` equals `[record.capex]` (one element) | holdout |
| AC-11 | A TNFD run for one company | the walkthrough is requested with `item=disclosures` | `recorded` true; `rows` equals `record.disclosures` | holdout |
| AC-12 | A TNFD run whose record has a `general_requirements` object | the walkthrough is requested with `item=general_requirements` | `rows` equals `[record.general_requirements]` | holdout |
| AC-13 | A TNFD run whose record's `general_requirements` is `None` | the walkthrough is requested with `item=general_requirements` | HTTP 200; `rows` `[]` | holdout |
| AC-14 | `traces` in the run folder is a regular file, not a folder, so creating `traces/<company_id>.json` fails | the run processes one company | run status `completed`; done count 1; the company's row is returned by the results endpoint; the run's events include `trace_write_failed` with that company id | holdout |
| AC-15 | The AC-14 run | the walkthrough is requested for that company's field | `recorded` false; `not_recorded_reason` `write_failed` | holdout |
| AC-16 | A completed data-point run, the AC-9 Financials run and a TNFD run | the walkthrough is requested with: an unknown run id; a company not in the run; a field not in the schema; a schema field with neither a stored row nor a trace entry for the company; `item=disclosures` on the Financials run; `item=capex` on the TNFD run; `item=capex` on the data-point run | HTTP 404 for each | holdout |
| AC-17 | A transition-plan actions run and the AC-1 run | the walkthrough is requested for a plan list field without `basis`, and for the AC-1 field without `period_end` | HTTP 422 for each | holdout |
| AC-18 | No session | the walkthrough is requested | the same status code as the results endpoint returns without a session (401) | holdout |
| AC-19 | A field whose review item has a decision with a note and a cosign | the walkthrough is requested | outside `rows` and the model `answer` objects, no key contains `decision`, `reviewer` or `cosign`; neither the reviewer's user id nor the decision note's text appears anywhere in the body | holdout |
| AC-20 | A seeded known-answer item (`seed_known_answers`) and a real trial-run item, both for the same non-high-risk field, the real verifier agreeing | both walkthroughs are requested | both have `recorded` true and `adjudicator` null; outside `rows`, the set of key paths (list indexes folded into `[]`) is equal between the two bodies; equal `extractor.model`, `extractor.prompt_version`, `verifier.model`, `verifier.prompt_version`; no key, and no value outside `passages[].text`, `rows[].citations` and the answers' `quote` fields, contains `seed` or `known` (case-insensitive) | holdout |
| AC-21 | The AC-20 seeded item | its walkthrough is requested | the list of `(doc_id, char_start, char_end, section)` from `passages`, in order, equals the same list from `field_evidence` for the seeded document and field | holdout |
| AC-22 | A seeded high-risk known-answer item | its walkthrough is requested | `verifier.blind` true; `verifier.answer` has the key `values`; `verifier.verdict` has the key `agrees` | holdout |
| AC-23 | The golden set runs | it completes | no file matching `**/traces/*.json` exists under the runs root or the golden-set output directory | holdout |
| AC-24 | Each research caller (`research/revenue_exposure/resolver.py`, `research/taxonomy_sources/empirical.py`) extracts for one company | it completes | no file matching `**/traces/*.json` exists under the runs root | holdout |
| AC-25 | The AC-1 run and the same run on `main` | the results endpoint is read for both | the response bodies are equal | holdout |
| AC-26 | The AC-1 and AC-2 runs and the same runs on `main` | their stored result rows are compared | every row's `value`, `confidence`, `route`, `route_reasons`, `checks` and `corrections` are equal | holdout |
| AC-27 | The AC-1 run, after which every `traces/*.json` is overwritten with the bytes `{not json` | the results endpoint is read | HTTP 200 with the same body as before | holdout |
| AC-28 | The AC-1 run | the model calls are counted | 1 extractor call and 1 verifier call | holdout |
| AC-29 | The AC-2 run | the model calls are counted | 1 extractor, 1 blind verifier and 1 adjudicator call | holdout |
| AC-30 | The AC-9 run | the model calls are counted | 1 extractor call and 1 verifier call | holdout |
| AC-31 | The AC-1 run | the trace file's size is read | at most 8,192 bytes | holdout |
| AC-32 | Runs 1, 2 and 3 with unchanged inputs: run 1 extracts the field, runs 2 and 3 reuse it | the walkthrough is requested in run 3 for that row's field and `period_end` | `trace_run_id` is run 1's id; `recorded` true | holdout |
| AC-33 | A field where no passage matches | the run completes | its trace entry has `skipped` `no_evidence` | holdout |
| AC-34 | A derived field | the run completes | its trace entry has `skipped` `derived` | holdout |
| AC-35 | A company whose documents are all held | the run completes | each field's trace entry has `skipped` `documents_held` | holdout |
| AC-36 | The AC-33 run | the walkthrough is requested for that field | `recorded` true; `not_recorded_reason` null | holdout |
| AC-37 | A row that R4 moved from `tc_capex_total` to `tc_capex_total_planned`, while `tc_capex_total_planned` also has its own trace entry | the walkthrough is requested for `tc_capex_total_planned` with the moved row's `period_end` | `extractor` equals the `extractor` of the `tc_capex_total` entry in the trace file | holdout |
| AC-38 | A run whose `created_at` is more than `retention_runs_days` days ago and whose trace files were deleted | the walkthrough is requested | `recorded` false; `not_recorded_reason` `expired` | holdout |
| AC-39 | Vision fallback on; a quote the text match cannot ground; the stand-in vision check answers | the run completes | the field's trace entry `vision.answer` equals the stand-in's answer | holdout |
| AC-40 | Vision fallback off | the run completes | every trace entry has `vision` null | holdout |
| AC-41 | A transition-plan actions run with one plan document | the run completes | the trace file has `plans.<doc_id>` holding `passages` and `extractor` | holdout |
| AC-42 | The AC-41 run | the walkthrough is requested for a list field with one of its rows' `period_end` and `basis` | `recorded` true; `rows` is non-empty and every row's `basis` equals the requested basis; `extractor` equals the trace file's `plans.<doc_id>.extractor` for the document the row's citation names; `verifier` and `adjudicator` null | holdout |
| AC-43 | The AC-2 run loaded in the running app | a reviewer opens Argus › Walkthrough and picks run, company and the field's 2025 row | the result card's value, unit, period and route equal the results endpoint's row; ten numbered steps show; the route reads `#/argusWalkthrough/<run>/<company>/<field>/2025-12-31` | evaluator |
| AC-44 | As AC-43 | the reviewer reads step 4 | its name is `Verify, blind` | evaluator |
| AC-45 | As AC-43 | the reviewer reads step 5 | its label is `unresolved` | evaluator |
| AC-46 | As AC-43 | the reviewer opens the Extract step's Full answer tab | a table with the columns value, printed as, unit, state and one row per value in the endpoint's `extractor.answer.values`, followed by the quotes | evaluator |
| AC-47 | As AC-43 | the reviewer opens the Extract step's JSON tab and clicks Copy | the clipboard text parses to JSON equal to the endpoint's `extractor.answer` | evaluator |
| AC-48 | As AC-43, with 12 passages | the reviewer looks at Find evidence | two passages show with document title, section and character range, the quoted words marked; a link reads `Show the other 10 passages` | evaluator |
| AC-49 | The AC-4 run in the running app | the reviewer opens a field's walkthrough | the note `This run is from before walkthroughs were recorded. Passages and model answers were not saved; the steps below show what the stored row holds.` shows; steps 2, 3 and 5 read `not recorded` | evaluator |
| AC-50 | The running app | the reviewer clicks `How was this found?` on a field's 2025 row in the extraction results | the route equals `#/argusWalkthrough/<run>/<company>/<field>/2025-12-31` for that row | evaluator |
| AC-51 | The running app | the reviewer clicks `How was this found?` on a review item | the route equals `#/argusWalkthrough/<run>/<company>/<field>/<period_end>` of the item's row | evaluator |
| AC-52 | The running app | the reviewer clicks `How was this found?` on a field in the Data Library by-company view | the route equals `#/argusWalkthrough/<run>/<company>/<field>/<period_end>` of that row | evaluator |
| AC-53 | The running app, a Financials run | the reviewer clicks `How was this found?` on CapEx in the results | the route equals `#/argusWalkthrough/<run>/<company>/capex`; 6 numbered steps show, none named Adjudicate | evaluator |
| AC-54 | The running app, a TNFD run | the reviewer clicks `How was this found?` on a TNFD review item | the route equals `#/argusWalkthrough/<run>/<company>/disclosures`; 5 numbered steps show, none named Adjudicate | evaluator |
| AC-55 | The running app, a Financials run whose capex total's `raw_value_text` contains `SEC XBRL` | the reviewer opens the CapEx walkthrough | step 5 `XBRL overlay` reads `XBRL value used` | evaluator |
| AC-56 | The running app at 390 px wide, the AC-43 walkthrough open with the Verify JSON tab shown | the page is measured | `document.documentElement.scrollWidth` ≤ 390; the three pickers sit one above another at the same left edge; the JSON block's `scrollWidth` exceeds its `clientWidth` | evaluator |
| AC-57 | The AC-5 reused row in the running app | the walkthrough opens | the line `Reused from run <run 1 id>; the steps show that run.` shows under the result card | evaluator |
| AC-58 | The AC-33 run in the running app | the reviewer opens that field's walkthrough | step 2 reads `no passage matched`; steps 3, 4 and 5 read `not reached` | evaluator |
| AC-59 | The running app, a TNFD run | the reviewer clicks `How was this found?` on Disclosures in the TNFD results | the route equals `#/argusWalkthrough/<run>/<company>/disclosures` | evaluator |
| AC-60 | The running app, a Financials run with a review item | the reviewer clicks `How was this found?` on that review item | the route equals `#/argusWalkthrough/<run>/<company>/segments` | evaluator |
| AC-61 | The running app, the AC-41 run | the reviewer clicks `How was this found?` on a plan list row | the route equals `#/argusWalkthrough/<run>/<company>/<field>/<period_end>?basis=<the row's basis>` | evaluator |
| AC-62 | `seed_known_answers` with the same inputs and seed, on this branch and on `main` | the created review items are compared | their bodies are equal | holdout |
| AC-63 | The AC-9 Financials run and a TNFD run, and the same runs on `main` | the results endpoint is read for each | the response bodies are equal | holdout |
| AC-64 | Run 1 created more than `retention_runs_days` days ago, its trace files deleted; run 2 reuses its row | the walkthrough is requested in run 2 for that row | `trace_run_id` is run 1's id; `recorded` false; `not_recorded_reason` `expired` | holdout |
| AC-65 | A TNFD run | the model calls are counted | 1 extractor call and 1 verifier call | holdout |
| AC-66 | The AC-41 run | the model calls are counted | 1 `extract_plan` call | holdout |
| AC-67 | The AC-39 run | the vision calls are counted | exactly 1 | holdout |
| AC-68 | A Financials run made with no `traces/` folder, created within `retention_runs_days` | the walkthrough is requested with `item=capex` | `recorded` false; `not_recorded_reason` `before_traces`; `rows` equals `[record.capex]` | holdout |
| AC-69 | The AC-68 run in the running app | the reviewer opens the CapEx walkthrough | steps 1 and 2 read `not recorded`; step 3 shows the section's `verifier_notes` | evaluator |

Must not change, each a row above: results endpoint bodies (AC-25, AC-63) and the CSV export built from them;
seeded review items (AC-62); stored
rows and routing (AC-26); results never read traces (AC-27); model call counts (AC-28, AC-29, AC-30, AC-65, AC-66, AC-67); the golden
set and research callers write no traces (AC-23, AC-24).
