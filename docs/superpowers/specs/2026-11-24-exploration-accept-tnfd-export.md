# Exploration accept rule and TNFD CSV export

Status: Draft, for owner approval
Slug: `exploration-accept-tnfd-export`
Risk: `risk:normal` (backend, plus one small frontend change in `frontend/src/lib/agent.ts` and
`frontend/src/components/ExplorationCard.tsx`, so it owes the UI review gate; no auth, schema, money or
workflow path)
Size: `S`, one PR, no slices

## Decisions for the owner

Both change acceptance rows. The rows below are written for the recommended option of each; approving
the spec approves both.

| # | Decision | Recommended | Alternatives |
|---|----------|-------------|--------------|
| D1 | Which explorations can be accepted, and which stay in the Agent inbox? | Only `done` ones can be accepted: Accept on a `failed` or `timeout` exploration answers 409, they leave the inbox, and their card shows no Accept button. | (b) Accept refused for them, but they stay in the inbox until a new Dismiss action removes them (adds a route, a column and a button). (c) Keep today's behaviour and drop item 8. |
| D2 | How does a TNFD run's CSV export look, and does it hold back unreviewed values? | One row per item (disclosure, core metric, sector metric, LEAP consideration, general requirements) with an `item_type` column and its own columns per type. A company's values are blank while its record still waits for review, was rejected or was escalated; a `review_status` column says which, as in the extraction export. | (b) Same rows, no review gate: every value is exported. (c) One summary row per company, no metric values. |

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`, old IDs A17, A26,
B3, A8; bug-list items 8 and 9, `all-findings.md` M14 and M11) found two faults that still reproduce on
`main` at `96759e7`:

- A failed or timed-out exploration can be accepted, which labels a result that does not exist as
  `accepted`. Nothing else accepts it under any sensible rule, so it sits in the Agent inbox for good.
- A TNFD run's CSV export falls into the discovery branch of `GET /api/runs/{run_id}/export.csv`. The
  file holds only the discovery header `company_id,name,homepage_used,doc_type,url,local_path` and no
  rows, because TNFD records have no `documents_found`.

## What the user can do afterwards that they cannot do today

- Treat the Agent inbox as a to-do list: every exploration row in it is a real result waiting for a
  person. Failed and timed-out explorations no longer pile up there, and the Accept button appears
  only where accepting means something.
- Download a TNFD run as a spreadsheet: one line per disclosure, metric, LEAP consideration and general
  requirements block, for every company, with the pillar, values, units, confidence and grounding.
- Trust that file: nothing a person still has to decide on, or turned down, leaves the app, and each
  line says why its values are blank.

## Three versions

- Safe: accept refuses non-`done`; the inbox filters on `status`; the TNFD export writes one row per
  disclosure only (recommendation, disclosed, summary), no review gate.
- Strong: the safe version plus all five TNFD item types in one file with type-specific columns, the
  review gate keyed on the company's whole-record review item, and the frontend card without Accept on
  failed and timed-out explorations.
- Most ambitious that still has exact rows (specified here): the strong version, plus a company with no
  extracted items still gets one `none` row (so it does not vanish from the file), a record that says
  `needs_review` but has no queue row is held back too, and the Accept rule lives in one frontend
  function (`canAccept`) that both the card and a hidden test read.

Next step up would need: an `.xlsx` export with one sheet per TNFD item type plus a citations sheet (as
the theme export has), and a Dismiss/Retry action for failed explorations; both need a design the owner
has not seen.

## What exists today

Explorations:

- `status` is `done`, `failed` or `timeout` (`backend/arp/agent/explorations.py`).
- `POST /api/agent/explorations/{id}/accept` (`backend/arp/api/routers/agent.py`,
  `accept_exploration`; store `ExplorationStore.accept`) accepts any exploration whatever its status; a
  second accept keeps the first one's `accepted_by` and `accepted_at`. Unknown id: `404 {"detail":
  "exploration not found"}`.
- `GET /api/agent/inbox` (`agent.py`, `inbox`) lists every exploration whose `accepted_at` is null.
- `frontend/src/components/ExplorationCard.tsx` shows Accept whenever the badge `Exploratory: not
  reviewed` shows (`explorationBadge` in `frontend/src/lib/agent.ts`), failed and timed-out cards
  included.
- Mini-app (`409 "only a done exploration can be shown as a mini-app"`) and Turn into a plan (`409 "only
  an accepted exploration can become a plan"`, needs `done` and accepted) already refuse non-`done`
  explorations.
- The status strip (`2026-11-22-agent-research-examples.md`, Part 4) already shows `Review —` for
  `failed` and `timeout` explorations and `Needs you` only for `done`, not accepted.

TNFD export:

- `export_run_csv` in `backend/arp/api/routers/runs.py` has branches for `theme`, `extraction`,
  `financials`, `transition_plan`, `transition_barrier_refresh` and an `else` for discovery; `tnfd` lands
  in the `else`.
- Record shape: `TNFDExtractionRecord` in `backend/arp/schemas/tnfd.py` (company_id, ticker, name,
  as_of, framework_version, disclosures, core_global_metrics, sector_metrics,
  sector_leap_considerations, general_requirements, overall_confidence, needs_review, …).
- Review: `tnfd` is a reviewable run type (`backend/arp/review/items.py`). A record with `needs_review`
  queues one whole-record review item whose `item_key` is the `company_id`
  (`extraction/tnfd_pipeline.py`, `orchestration/batch_runner.py`). Final decisions come from
  `effective_decisions` (`orchestration/review_queue.py`). The extraction export's `_reviewed_value`
  already holds back values awaiting review.
- Frontend: Run history (`frontend/src/pages/RunHistory.tsx`) shows a `CSV` link (`exportRunCsvUrl`) for
  every run, TNFD runs included, so no frontend change is needed for item 9.

## Goals

1. Only a `done` exploration can be accepted (D1).
2. The inbox lists only `done` explorations not yet accepted (D1).
3. The exploration card offers Accept only on a `done`, not accepted exploration (D1).
4. A TNFD run's CSV export has one row per item with the header below (D2).
5. A company's values are held back while its record waits for review, was rejected or was escalated,
   with `review_status` saying which (D2).

## Non-goals

- Any other bug-list item (the Agent screen itself is bundle B).
- A review gate for the `transition_plan` export (it has none today); not in this item unless the owner
  asks.
- Run types other than `tnfd` that also fall into the discovery `else` (for example `identity`,
  `holdings`): they keep today's behaviour.
- Changing explorations already accepted before this change: a `failed` or `timeout` row with
  `accepted_at` set keeps it. No migration.
- An `.xlsx` export for TNFD.

## Anti-goals

- Do not delete, hide or relabel failed or timed-out explorations anywhere except the inbox:
  `GET /api/agent/explorations` and `GET /api/agent/explorations/{id}` return them as today.
- Do not apply a whole-record correction to the TNFD export (no TNFD review screen writes one).

## Design

### Accept rule (goals 1 to 3)

- `POST /api/agent/explorations/{id}/accept`: unknown id → `404 {"detail": "exploration not found"}`
  (checked first). An exploration whose `status` is not `done` → `409 {"detail": "only a done exploration
  can be accepted"}`, and nothing is written, even when `accepted_at` is already set. A `done` exploration
  → 200 as today; a second accept keeps the first `accepted_by` and `accepted_at`.
- `GET /api/agent/inbox`: an `exploration` row only for an exploration with `status == "done"` and
  `accepted_at` null. Row shape and sort order unchanged.
- `frontend/src/lib/agent.ts` gets `export const canAccept = (e: Pick<Exploration, "status" |
  "accepted_at">): boolean`, true exactly when `e.status === "done"` and `e.accepted_at === null`.
  `ExplorationCard` shows the Accept button only when `canAccept(e)` is true. The badge `Exploratory: not
  reviewed` still shows on every exploration not accepted, failed and timed-out ones included (AC-49 of
  the code-mode spec is unchanged).

### What this supersedes in the code-mode spec

`docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md` is not edited (this PR holds only this
file). From the merge of this spec, these parts of it read as follows:

- Line 218, inbox kind `exploration`: "an exploration not yet accepted" becomes "a `done` exploration
  not yet accepted".
- Lines 277–278: "`POST /api/agent/explorations/{id}/accept` sets `accepted_by` and `accepted_at`" now
  holds for a `done` exploration only; any other answers `409 {"detail": "only a done exploration can be
  accepted"}`.
- Line 318, "the accept route is not changed": no longer true after this spec.
- Row AC-50: its Given narrows to "A `done` exploration E not yet accepted". Its hidden test uses a
  `done` exploration, so it stays as it is and keeps passing. AC-48 and AC-49 are unchanged.

### TNFD export (goals 4 and 5)

A new `elif manifest.run_type == "tnfd":` branch before the discovery `else`. Media type `text/csv` and
`Content-Disposition: attachment; filename=<run_id>.csv` as for every run type. Written with Python's
`csv.writer`, so booleans are `True`/`False`, `None` is an empty cell, and floats are written as Python
`str()` writes them (`12.5`, `3.0`).

Header, exactly these 36 columns in this order:

```
company_id,ticker,name,as_of,framework_version,item_type,pillar,recommendation_id,category,metric_kind,sector_name,sector_guidance_status,sector_guidance_version,metric_no,is_core_sector_metric,metric_name,leap_stage,disclosed,summary,consideration,materiality_basis,disclosure_scope,location_specificity,cross_framework_links,time_horizons,iplc_engagement_described,value,unit,baseline_year,confidence,grounded,verifier_notes,review_flags,overall_confidence,needs_review,review_status
```

Rows: records in the order `RunStore.read_results` returns them. Within a record: each disclosure in
list order, then each core global metric, each sector metric, each LEAP consideration, then the general
requirements block if present. A record with none of these writes one row with `item_type` `none`.

Every row carries the record columns `company_id`, `ticker`, `name`, `as_of`, `framework_version`,
`overall_confidence`, `needs_review` and `review_status`. The item columns per `item_type` (every other
item column empty):

| `item_type` | Columns filled, from the item |
|---|---|
| `disclosure` | `pillar` (from `PILLAR_BY_RECOMMENDATION`, e.g. `governance`), `recommendation_id`, `leap_stage` (`leap_stage_reference`), `disclosed`, `summary`, `materiality_basis`, `disclosure_scope`, `confidence`, `grounded`, `verifier_notes`, `review_flags` |
| `core_metric` | `category`, `metric_kind`, `metric_name`, `value`, `unit`, `baseline_year`, `confidence`, `grounded`, `verifier_notes`, `review_flags` |
| `sector_metric` | `sector_name`, `sector_guidance_status`, `sector_guidance_version`, `metric_no`, `is_core_sector_metric`, `metric_name`, `value`, `unit`, `baseline_year`, `confidence`, `grounded`, `verifier_notes`, `review_flags` |
| `leap_consideration` | `sector_name`, `leap_stage`, `consideration`, `review_flags` |
| `general_requirements` | `materiality_basis` (`materiality_approach`), `disclosure_scope`, `location_specificity`, `cross_framework_links`, `time_horizons` (`time_horizons_defined`), `iplc_engagement_described` |
| `none` | none |

Lists (`review_flags`, `cross_framework_links`) are joined with `"; "`; an empty list is an empty cell.
`time_horizons` is `key=value` pairs in the dict's order joined with `"; "`. Enum values are written as
their value (`governance.A`, `land_use_change`).

**Review gate.** A record is *gated* when its `needs_review` is true, or the run's review queue has a row
whose `item_key` is its `company_id`, or the run has a decision row with that `item_key`. For a record
that is not gated, every row has `review_status` empty and all cells filled as above. For a gated record,
the effective decision for `item_key` = `company_id` (from `effective_decisions`, the same reader the
extraction export uses) sets `review_status` on all its rows:

| Effective decision | `review_status` | Held back |
|---|---|---|
| none (no final decision, including an `escalate`) | `awaiting review` | yes |
| `approve` | `approve` | no |
| `reject` | `reject` | yes |
| `correct` | `correct` | yes |
| `edit` (legacy row) | `edit` | yes |

*Held back* means the 15 columns from `disclosed` to `verifier_notes` in header order (`disclosed`,
`summary`, `consideration`, `materiality_basis`, `disclosure_scope`, `location_specificity`,
`cross_framework_links`, `time_horizons`, `iplc_engagement_described`, `value`, `unit`, `baseline_year`,
`confidence`, `grounded`, `verifier_notes`) are empty on every row of that record. The other columns stay
filled, so a reader still sees which items wait.

## Fixtures

**Fixture X** (explorations). Postgres as the app uses it, with `agent_explorations` emptied first. Explorations written with
`ExplorationStore.add` (any question, code `return 1`, `tool_calls: []`, `model: "stand-in"`):
`D` with `status: "done"`, `result: 1`; `F` with `status: "failed"`, `error: "boom"`; `T` with
`status: "timeout"`, `error: "stopped after 30 s"`. None accepted. No draft plans and no calls awaiting
review.

**Fixture T** (TNFD export). Run `RT` with `run_type` `tnfd`, status `completed`. Results records in this
order, each written as `TNFDExtractionRecord(..., run_id="RT").model_dump(mode="json")`, the way the TNFD
pipeline writes them, so every field is present; the export may rely on that shape. Unless a row says otherwise, a record has `as_of` `2025-12-31`, `framework_version` left at its
default `v1.1 (October 2023, incl. Additional Guidance)`, `overall_confidence` 0.5, empty item lists and no
`general_requirements`. A queue row is `{"item_key": "<company_id>", ...the record's JSON}`. A decision row
is `{"item_key": "<company_id>", "decision": ..., "decided_at": ..., "user_id": "x"}` with no `step`, so
`approve`, `reject` and `correct` are final and `escalate` leaves the item open.

| `company_id` | `name` | `ticker` | `needs_review` | items | queue row | decision rows (oldest first) |
|---|---|---|---|---|---|---|
| `c1` | `Alpha` | `T1` | false | D1, M1, S1, L1, G1 (below); `overall_confidence` 0.85 | none | none |
| `c2` | `Beta` | null | true | disclosure D2 | yes | none |
| `c3` | `Gamma` | `T3` | true | core metric M3 | yes | `approve` |
| `c4` | `Delta` | `T4` | true | disclosure D4 | yes | `reject` |
| `c5` | `Epsilon` | `T5` | true | sector metric S5 | yes | `reject`, then `approve` |
| `c6` | `Zeta` | `T6` | true | disclosure D6 | yes | `escalate` |
| `c7` | `Eta` | `T7` | false | none | none | none |
| `c8` | `Theta` | `T8` | true | LEAP consideration L8 | none | none |

Items (fields not named take the schema default):

- D1: `recommendation_id` `governance.A`, `disclosed` true, `summary` `Board oversees nature risks`,
  `materiality_basis` `double`, `disclosure_scope` `full_value_chain`, `leap_stage_reference` `evaluate`,
  `confidence` 0.9, `grounded` true, `verifier_notes` `ok`.
- M1: `category` `land_use_change`, `metric_kind` `dependency_impact`, `metric_name` `Land converted`,
  `value` 12.5, `unit` `ha`, `baseline_year` 2020, `confidence` 0.8, `grounded` true.
- S1: `sector_name` `oil_and_gas`, `sector_guidance_status` `final`, `sector_guidance_version` `2024-06`,
  `metric_no` `OG.C2.0`, `is_core_sector_metric` true, `metric_name` `Hydrocarbon spills`, `value` 3.0,
  `unit` `bbl`, `confidence` 0.7, `grounded` false, `review_flags`
  `["metric_missing_unit_or_baseline", "metric_core_flag_mismatch"]`.
- L1: `sector_name` `oil_and_gas`, `leap_stage` `locate`, `consideration` `Screen upstream sites, then rank`.
- G1: `materiality_approach` `double`, `disclosure_scope` `direct_operations`, `location_specificity`
  `site level`, `cross_framework_links` `["TCFD", "GRI 101"]`, `time_horizons_defined`
  `{"short": "0-3y", "long": "10y+"}`, `iplc_engagement_described` true.
- D2: `recommendation_id` `strategy.A`, `disclosed` true, `summary` `Beta strategy`, `confidence` 0.6.
- M3: `category` `pollution`, `metric_kind` `risk_opportunity`, `metric_name` `Spills`, `value` 4.0, `unit`
  `t`, `baseline_year` 2021, `confidence` 0.7, `grounded` true.
- D4: `recommendation_id` `governance.B`, `disclosed` true, `summary` `Delta governance`, `confidence` 0.4.
- S5: `sector_name` `metals_and_mining`, `sector_guidance_status` `final`, `sector_guidance_version`
  `2024-06`, `metric_no` `MM.C23.0`, `is_core_sector_metric` true, `metric_name` `Area managed`, `value`
  7.5, `unit` `ha`, `confidence` 0.6, `grounded` true.
- D6: `recommendation_id` `risk.B`, `disclosed` true, `summary` `Zeta risk`, `confidence` 0.5.
- L8: `sector_name` `fishing`, `leap_stage` `assess`, `consideration` `Theta note`.

Read the export with Python's `csv.reader`; "row `<company_id>`/`<item_type>`" is the data row with that
`company_id` and `item_type`. "Empty" means the cell is `""`.

## Defaults taken

- The badge `Exploratory: not reviewed` stays on failed and timed-out explorations: their label is
  still `exploratory`. Only the Accept button goes.
- A failed or timed-out exploration accepted before this change keeps its acceptance; accepting it again
  answers 409.
- Accept on a non-`done` exploration answers 409 even when it was already accepted (status is checked
  before the idempotent path).
- No frontend change for the 409: the Agent screen's existing error line shows the `detail`, and the
  button no longer shows on such cards anyway.
- The TNFD review gate is per company, because TNFD queues one whole-record review item per company.
  A `correct` decision holds the record back: no TNFD review screen writes a whole-record correction, so
  the export has no corrected values to apply.
- An `escalate` with no later final decision reads `awaiting review`, like the extraction export.
- A record with `needs_review` true but no queue row and no decision is held back as `awaiting review`:
  nothing a person was meant to check leaves the app.
- `missing_recommendations`, `record_review_flags`, citations, `generated_at` and `provenance` are not in
  the CSV. A disclosure row's `disclosed` column shows what was found; citations belong in the `.xlsx`
  next step.
- `pillar`, `leap_stage`, `review_flags`, `metric_name` and the identity columns are not held back: they
  say which item waits, not what it found.
- `ticker` null writes an empty cell.

## Acceptance

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture X | `POST /api/agent/explorations/F/accept` as a signed-in user | HTTP 409, body `{"detail": "only a done exploration can be accepted"}` | holdout |
| AC-2 | AC-1 done | `GET /api/agent/explorations/F` | `accepted_at` null, `accepted_by` null, `label` `exploratory` | holdout |
| AC-3 | Fixture X | `POST /api/agent/explorations/T/accept` | HTTP 409, body `{"detail": "only a done exploration can be accepted"}` | holdout |
| AC-3b | AC-3 done | `GET /api/agent/explorations/T` | `accepted_at` null, `label` `exploratory` | holdout |
| AC-4 | Must not change. Fixture X | `POST /api/agent/explorations/D/accept` as the e2e app's user | HTTP 200; `label` `accepted`, `accepted_by` `dev`, `accepted_at` not null | holdout |
| AC-5 | Must not change. AC-4 done; its `accepted_at` noted as `A` | `POST /api/agent/explorations/D/accept` again | HTTP 200; `accepted_at` equals `A`, `accepted_by` `dev` | holdout |
| AC-6 | Must not change. Fixture X | `POST /api/agent/explorations/00000000-0000-0000-0000-000000000000/accept` | HTTP 404, body `{"detail": "exploration not found"}` | holdout |
| AC-7 | Exploration `FA` written with `ExplorationStore.add` with `status: "failed"`, then `accepted_by` set to `old` and `accepted_at` to `2026-11-01T09:00:00+00:00` directly in the `agent_explorations` table (SQL `UPDATE`) | `POST /api/agent/explorations/FA/accept` | HTTP 409, body `{"detail": "only a done exploration can be accepted"}` | holdout |
| AC-7b | AC-7 done | `GET /api/agent/explorations/FA` | `accepted_by` `old`, `accepted_at` parses to the instant 2026-11-01 09:00:00 UTC | holdout |
| AC-8 | Fixture X | `GET /api/agent/inbox` | exactly 1 row has `kind` `exploration`, and it equals `{kind: "exploration", plan_id: null, seq: null, exploration_id: D, title: <D's question, first 60 characters>, href: "#/agent/exploration/D"}`; no row has `exploration_id` `F` or `T` | holdout |
| AC-9 | Fixture X, then D accepted | `GET /api/agent/inbox` | no row has `kind` `exploration` | holdout |
| AC-10 | Must not change. Fixture X | `GET /api/agent/explorations` | 3 rows, with ids `D`, `F` and `T` and statuses `done`, `failed`, `timeout` | holdout |
| AC-10b | Must not change. Fixture X | `GET /api/agent/explorations/F` | HTTP 200; `status` `failed`, `error` `boom`, `label` `exploratory` | holdout |
| AC-11 | `frontend/src/lib/agent.ts` | `canAccept({status: "done", accepted_at: null})` | `true` | holdout |
| AC-12 | Same | `canAccept({status: "failed", accepted_at: null})` and `canAccept({status: "timeout", accepted_at: null})` | both `false` | holdout |
| AC-13 | Same | `canAccept({status: "done", accepted_at: "2026-11-24T09:00:00+00:00"})` | `false` | holdout |
| AC-14 | Frontend test: `ExplorationCard` rendered with an exploration `status: "failed"`, `label: "exploratory"`, `accepted_at: null` | the card is read | no button with the name `Accept` | unit |
| AC-14b | Must not change. Same as AC-14 | the card is read | the text `Exploratory: not reviewed` is shown | unit |
| AC-15 | Frontend test: same with `status: "done"`, `label: "exploratory"`, `accepted_at: null` | the card is read | one button with the name `Accept` | unit |
| AC-16 | Fixture T | `GET /api/runs/RT/export.csv` | HTTP 200; `Content-Type` starts with `text/csv`; `Content-Disposition` is `attachment; filename=RT.csv`; the first line is exactly the 36-column header in "TNFD export" above | holdout |
| AC-17 | Fixture T | same | 12 data rows, in this order of (`company_id`, `item_type`): (c1, disclosure), (c1, core_metric), (c1, sector_metric), (c1, leap_consideration), (c1, general_requirements), (c2, disclosure), (c3, core_metric), (c4, disclosure), (c5, sector_metric), (c6, disclosure), (c7, none), (c8, leap_consideration) | holdout |
| AC-18 | Fixture T | same | row c1/disclosure has: `ticker` `T1`, `name` `Alpha`, `as_of` `2025-12-31`, `framework_version` `v1.1 (October 2023, incl. Additional Guidance)`, `pillar` `governance`, `recommendation_id` `governance.A`, `leap_stage` `evaluate`, `disclosed` `True`, `summary` `Board oversees nature risks`, `materiality_basis` `double`, `disclosure_scope` `full_value_chain`, `confidence` `0.9`, `grounded` `True`, `verifier_notes` `ok`, `overall_confidence` `0.85`, `needs_review` `False`; every other cell empty | holdout |
| AC-19 | Fixture T | same | row c1/core_metric has: `category` `land_use_change`, `metric_kind` `dependency_impact`, `metric_name` `Land converted`, `value` `12.5`, `unit` `ha`, `baseline_year` `2020`, `confidence` `0.8`, `grounded` `True`; the record columns as in AC-18; every other cell empty | holdout |
| AC-20 | Fixture T | same | row c1/sector_metric has: `sector_name` `oil_and_gas`, `sector_guidance_status` `final`, `sector_guidance_version` `2024-06`, `metric_no` `OG.C2.0`, `is_core_sector_metric` `True`, `metric_name` `Hydrocarbon spills`, `value` `3.0`, `unit` `bbl`, `confidence` `0.7`, `grounded` `False`, `review_flags` `metric_missing_unit_or_baseline; metric_core_flag_mismatch`; the record columns as in AC-18; every other cell empty | holdout |
| AC-21 | Fixture T | same | row c1/leap_consideration has: `sector_name` `oil_and_gas`, `leap_stage` `locate`, `consideration` `Screen upstream sites, then rank`; the record columns as in AC-18; every other cell empty | holdout |
| AC-22 | Fixture T | same | row c1/general_requirements has: `materiality_basis` `double`, `disclosure_scope` `direct_operations`, `location_specificity` `site level`, `cross_framework_links` `TCFD; GRI 101`, `time_horizons` `short=0-3y; long=10y+`, `iplc_engagement_described` `True`; the record columns as in AC-18; every other cell empty | holdout |
| AC-23 | Fixture T | same | row c2/disclosure has `ticker` empty, `name` `Beta`, `pillar` `strategy`, `recommendation_id` `strategy.A`, `overall_confidence` `0.5`, `needs_review` `True`, `review_status` `awaiting review`, and the 15 held-back columns (`disclosed` to `verifier_notes`) all empty | holdout |
| AC-24 | Fixture T | same | row c3/core_metric has `metric_name` `Spills`, `value` `4.0`, `unit` `t`, `baseline_year` `2021`, `confidence` `0.7`, `grounded` `True`, `review_status` `approve` | holdout |
| AC-25 | Fixture T | same | row c4/disclosure has `recommendation_id` `governance.B`, `review_status` `reject`, and the 15 held-back columns all empty | holdout |
| AC-26 | Fixture T | same | row c5/sector_metric has `metric_no` `MM.C23.0`, `value` `7.5`, `unit` `ha`, `review_status` `approve` | holdout |
| AC-27 | Fixture T | same | row c6/disclosure has `recommendation_id` `risk.B`, `review_status` `awaiting review`, and the 15 held-back columns all empty | holdout |
| AC-28 | Fixture T | same | row c7/none has `name` `Eta`, `ticker` `T7`, `needs_review` `False`, `review_status` empty, and the 27 columns from `pillar` to `review_flags` all empty | holdout |
| AC-29 | Fixture T | same | row c8/leap_consideration has `sector_name` `fishing`, `leap_stage` `assess`, `consideration` empty, `review_status` `awaiting review` | holdout |
| AC-30 | Fixture T plus a decision row `{"item_key": "c1", "decision": "correct", "corrected_value": {"value": 1}, "decided_at": ..., "user_id": "x"}` (no `step`) | same | all 5 c1 rows have `review_status` `correct` and the 15 held-back columns empty | holdout |
| AC-30b | Fixture T plus a decision row `{"item_key": "c4", "decision": "edit", "edited_value": {"value": 1}, "decided_at": ..., "user_id": "x"}` (no `step`), written after c4's `reject` | same | row c4/disclosure has `review_status` `edit` and the 15 held-back columns all empty | holdout |
| AC-31 | Must not change. Discovery run `RD` with one record `{"company_id": "d1", "name": "D", "homepage_used": "https://d.example", "documents_found": [{"doc_type": "annual_report", "url": "https://d.example/ar.pdf", "local_path": null}]}` | `GET /api/runs/RD/export.csv` | 2 lines: `company_id,name,homepage_used,doc_type,url,local_path`, then `d1,D,https://d.example,annual_report,https://d.example/ar.pdf,` | holdout |
| AC-32 | Must not change. Extraction run with one record and one field (as Fixture E of `2026-11-23-review-export-correctness.md`, field `plain`) | `GET /api/runs/<id>/export.csv` | the first line is exactly `company_id,ticker,name,field_name,value,confidence,grounded,needs_review,verifier_notes,value_state,unit,canonical_value,canonical_unit,period_start,period_end,basis,review_status` | holdout |

Must not change: AC-4, AC-5, AC-6, AC-10, AC-10b, AC-14b, AC-31, AC-32; and code-mode spec rows AC-48, AC-49 and
AC-50 (whose hidden tests use `done` explorations).

## Wiki

After the merge, check whether `openwiki/` describes the Agent inbox, the accept route or the CSV export
per run type; if it does, the weekly `/context-refresh` regenerates it.
