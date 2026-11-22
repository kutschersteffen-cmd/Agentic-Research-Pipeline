# Annual report summary fields: business, risks and outlook as cited, reviewed facts

Status: Draft, for owner approval
Slug: `annual-report-summary-fields`
Risk: `risk:normal` (a new extraction preset; no database schema change, no new table)
Size: S, one slice

## Why

On 19 Nov 2026 Steffen asked where ARP could store what a 10-K says in words: the business overview,
the main risks and management's outlook. ARP already reads annual reports and has every table needed
to keep such text with its source: `field_observations` holds any value (the `value` column is JSONB),
`value_citations` holds the quote and page, and `company_facts` holds the current value after review.
What is missing is a set of fields that ask for this text. Steffen chose this route over reusing the
`doc_tree` section summaries, which have no citations and no review step.

## What the user can do afterwards that they cannot do today

- In Argus, pick the preset "Annual report summary", run it on companies whose annual report is in
  ARP, and get three text values per company and fiscal year: a business overview, the principal
  risks and the outlook. Each value links to the page it came from ("How was this found?").
- Review each value in the Review queue and, once approved, see it on the company page next to the
  company's other facts.

## What exists today

- `backend/arp/schemas/datapoints.py`: `FieldDefinition` with `data_type` `string`, `document_routing`
  (document types and section-heading substrings) and `high_risk`.
- `backend/arp/presets/`: seven presets (`green`, `eu_taxonomy`, `remuneration`, `transition_plan`,
  `transition_capex`, `transition_plan_actions`, `transition_delivery_kpis`), registered in
  `backend/arp/presets/registry.py` `PRESETS`. `GET /api/extraction/presets` lists them, Argus step 1
  offers them as `<name> · <n> fields`, `POST /api/extraction/presets/{id}/install` saves one.
- `backend/arp/research/stock_inference/profile.py`: a one-field `business_description` string schema
  ("Summarize the business as the company itself describes it, in 2-4 sentences") run through the
  normal extraction pipeline. It shows that a model-written summary with a grounded citation works with
  today's pipeline; it is not a preset and is not stored as a company fact.
- `backend/arp/ingestion/parsing.py:111`: a 10-K's `ITEM`/`PART` lines become chunk section names, which
  `document_routing.sections` matches (case-insensitive substring).
- `backend/arp/extraction/routing.py` `route()`: a row of a field whose version is not released, or whose
  first audit has not passed, always goes to review (`unreleased_version`, `first_audit_pending`). A row
  with no grounded citation goes to review with `not_grounded`.
- `backend/arp/db/observations.py`: run results become `field_observations` plus `value_citations`;
  each becomes a `company_facts` row with status `pending_review` until a reviewer approves it
  (`approved`). The company page Facts table (`frontend/src/pages/company/FactsTable.tsx`) shows any
  fact's value as text and already wraps long values.

## Goals

1. A preset `sch_annual_report_summary`, named "Annual report summary", with three `string` fields:
   `ar_business_overview`, `ar_principal_risks`, `ar_mda_outlook`.
2. Each field reads annual reports first (`10-K`, which in ARP means every annual report, US or not) and
   the sections where that content sits in a 10-K and in a European annual report.
3. Each value is one per fiscal year, under the `period_end` of the fiscal year the report covers.
4. Every value carries a grounded citation and goes to the Review queue; nothing reaches the company
   page as approved without a person.

## Non-goals

- No new table and no database migration.
- No change to the extraction pipeline, the verifier, grounding, routing or the review flow.
- No change to the company page or the Facts table.
- No other summary fields (strategy, segments, governance). They can be added to the preset later.
- Not added to the showcase loader (`backend/scripts/load_showcase_pack.py`).
- No exact-value golden cases for the summaries: the golden runner compares strings exactly, which a
  model-written summary never matches. Quality is checked by the evaluator on real reports instead.

## Anti-goals

- The summary must not be presented as the company's own words: the `description` says it is a summary
  written from the report.
- No value from the `doc_tree` summaries (they are never evidence).

## Design

New file `backend/arp/presets/annual_report_summary.py`, in the style of `remuneration.py`, with
`SCHEMA_ID = "sch_annual_report_summary"` and `build_annual_report_summary_schema()`, registered in
`PRESETS` after the existing seven.

Schema: `name` "Annual report summary", `description` "Business overview, principal risks and outlook,
summarised from the annual report with the page each comes from."

Settings on all three fields: `data_type` `string`, `required` False, `unit` None, `high_risk` False,
`status` draft (the default), `source_doc_types` `["10-K"]`. `document_routing.doc_types` `["10-K"]`,
`fallback` True. Every `extraction_instructions` starts with this common text:

> Read the annual report (Form 10-K, or the annual or integrated report of a non-US company). Write in
> English, in your own plain words, from what the report states; never add facts the report does not
> state. Report the value under the period_end of the fiscal year the report covers. Cite the passage
> each statement comes from. If the report has no such section, the value is not disclosed.

| field_id | name | description | own instructions (after the common text) | sections | seed_keywords |
|---|---|---|---|---|---|
| `ar_business_overview` | Business overview | Summary, written from the annual report, of what the company does: its main products or services, segments and markets. | 2 to 4 sentences on what the company does, its main segments and where it sells. | `item 1. business`, `business overview`, `business model`, `our business`, `fundamentals of the group`, `geschäftsmodell`, `grundlagen des konzerns` | business overview, business model, segments, products, services, markets |
| `ar_principal_risks` | Principal risks | The main risks the annual report names, as short phrases. | The 1 to 8 risks the report treats as most important, each as a phrase of at most 12 words, separated by "; ". | `item 1a`, `risk factors`, `principal risks`, `risk report`, `risks and opportunities`, `risikobericht`, `chancen- und risikobericht` | risk factors, principal risks, risk report, material risks |
| `ar_mda_outlook` | Outlook | Summary, written from the annual report, of management's outlook or guidance for the next fiscal year. | 1 to 4 sentences on what management expects for the next fiscal year, with any guidance figures as printed. | `item 7`, `management's discussion`, `outlook`, `forecast report`, `guidance`, `prognosebericht`, `ausblick` | outlook, guidance, forecast, expected, next fiscal year |

Review: the fields stay draft, so every row goes to review with `unreleased_version` (existing routing).
Releasing and auditing them later is the normal schema flow and is out of scope here.

## Defaults taken

- Field ids carry the prefix `ar_` like other presets (`tc_`, `rem_`), so they cannot collide with
  field ids of other schemas in the shared `fields` table.
- Three fields, the three named in the thread; more later.
- `ar_principal_risks` is a "; "-separated list, not prose, so a reviewer can check it item by item.
- English output, also for German reports.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The app | `GET /api/extraction/presets` | the list holds `{"preset_id": "sch_annual_report_summary", "name": "Annual report summary", "field_count": 3}` as its last entry | holdout |
| AC-2 | The app | `GET /api/extraction/presets/sch_annual_report_summary` | `fields[*].field_id` is exactly `["ar_business_overview", "ar_principal_risks", "ar_mda_outlook"]` | holdout |
| AC-3 | The response of AC-2 | each field is read | `data_type` is `string`, `required` is false, `high_risk` is false, `status` is `draft`, `source_doc_types` is `["10-K"]` | holdout |
| AC-4 | The response of AC-2 | each field's `document_routing` is read | `doc_types` is `["10-K"]`, `fallback` is true, and `sections` equals that field's list in the Design table, in that order | holdout |
| AC-5 | The response of AC-2 | each field's `extraction_instructions` is read | it starts with the common text of the Design section, character for character | holdout |
| AC-6 | The app | `POST /api/extraction/presets/sch_annual_report_summary/install` twice, as an analyst | both responses are 200, both `schema_id` are `sch_annual_report_summary`, and the second `version` equals the first | holdout |
| AC-7 | The preset installed; company C with one `10-K` document whose text holds `Item 1. Business` followed by `We generate and sell electricity.`; a stand-in model that returns for `ar_business_overview` the value `The company generates and sells electricity.`, period_end `2025-12-31`, confidence 0.95, citing the quote `We generate and sell electricity.` | an extraction run with the preset completes | C's result row for `ar_business_overview` has `value_state` `found`, `grounded` true, and route `review`, and its reasons include `unreleased_version` and `first_audit_pending` | unit |
| AC-8 | The run of AC-7 | the run's results are imported | `field_observations` holds one row for C, `ar_business_overview`, `period_end` 2025-12-31, value `The company generates and sells electricity.` | unit |
| AC-9 | The run of AC-7 | the run's results are imported | `value_citations` holds one row for the observation of AC-8, with `quote` `We generate and sell electricity.` | unit |
| AC-10 | The run of AC-7 | C's facts are read (`GET /api/companies/{C}/facts`) | the `ar_business_overview` fact has status `pending_review` | unit |
| AC-11 | As AC-7, but the stand-in cites `We build ships.`, which is not in the document | the run completes | the row has `grounded` false and its reasons include `not_grounded` | unit |
| AC-12 | The run of AC-11, imported | C's `company_facts` rows for `ar_business_overview` are read | none has status `approved` or `auto_accepted` | unit |
| AC-13 | The e2e stack started with `ARP_ANTHROPIC_API_KEY` exported and `ARP_STANDINS_DIR` unset; `RWE_annual_report_2025.pdf` and `NEE_annual_report_2025.pdf` saved into `demo/showcase/documents/` (downloaded by the owner from the sources `demo/showcase/documents.csv` names); `load_showcase_pack.py --only companies`, then `--only documents`, run with the stack's `ARP_POSTGRES_DSN` | a user starts an Argus extraction for RWE and NEE with the preset "Annual report summary", reporting year 2025, and opens step 5 | 6 rows are listed: each of the 3 fields once per company, every row with a value (none `not disclosed`) | evaluator |
| AC-14 | The step 5 of AC-13 | each row's period is read | it is 2025-12-31 | evaluator |
| AC-15 | The step 5 of AC-13 | each `ar_business_overview` value is read | it has 2 to 4 sentences and is in English | evaluator |
| AC-16 | The step 5 of AC-13 | each `ar_mda_outlook` value is read | it has 1 to 4 sentences and is in English | evaluator |
| AC-17 | The step 5 of AC-13 | each `ar_principal_risks` value is read | it is 1 to 8 items separated by `; `, each item at most 12 words | evaluator |
| AC-18 | The step 5 of AC-13 | "How was this found?" is clicked on each of the 6 rows | each opens a page of that company's 2025 annual report, and the cited passage on that page states what the value says | evaluator |
| AC-19 | The state of AC-13 | the user approves NEE's `ar_business_overview` on the Review Queue page and opens NEE's company page | the Facts table has a row whose Field cell reads `ar_business_overview`, Period `2025-12-31`, the approved text as Value and the status pill `approved` | evaluator |
| AC-20 | The response of AC-2 | the schema and each field are read | the schema's `name` is `Annual report summary` and its `description` equals the Design text; each field's `name` and `description` equal its Design table cells, character for character | holdout |
| AC-21 | The response of AC-2 | each field's `seed_keywords` is read | it equals that field's list in the Design table, in that order | holdout |
| AC-22 | Must not change | `GET /api/extraction/presets` | the seven earlier presets are listed first, in their earlier order, with their earlier `name` and `field_count` | holdout |

Must not change: the seven existing presets (AC-22).

## Slices

One `S` PR: the preset file, its registration and its tests. Rows: AC-1 to AC-22.

## Wiki

After merge, the weekly `/context-refresh` should list the new preset on the extraction presets page of
`openwiki/`. No hand edit.
