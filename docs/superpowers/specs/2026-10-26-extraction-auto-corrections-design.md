# Extraction auto-corrections

Status: draft for owner approval, 2026-10-26.

## Why

The 2026-10-26 extraction test (`docs/EXTRACTION_TEST_LESSONS_2026-10-26.md`, lessons 3.1, 3.2, 3.3 and 3.6) found
four slips that a rule can settle without a model: an enum label spelled differently from the allowed value, a
per-year number with no year, a unit whose scale contradicts the grounded quote, and a planned figure stored as an
actual. Cheap models make these often. Today each one sends the value to review with no hint of the fix, or is
stored wrong and caught only by another signal: Claude stored Caterpillar's "$2.794 billion" with the unit
"Millions of dollars", and it reached review only because the verifier happened to disagree.

## Owner decisions (2026-10-26)

1. **Correct automatically and keep the original.** The rule fixes the value; the model's original stays on the
   record with the rule and the reason.
2. **Every corrected value goes to review**, at least until the rules have proven themselves. A correction saves
   the reviewer the fix, never the look.
3. **Approach C: a separate correction step** between "combine into one record" and the record checks.

## Goals

- The four rules below, applied in code with no model call, to custom-schema extraction runs (scope below).
- Each correction stored on the field with its original value, so nothing changes without a trace.
- Reviewers see each correction where they review the value.

## Non-goals

- The financials, TNFD, transition-plan and replication pipelines. They keep their behaviour.
- Changing grounding, models, prompts, evidence retrieval or the existing checks.
- Learning or configuring rules per user.

## Anti-goals (a failure even if it runs)

- A value changed with no record of the original.
- A corrected value auto-accepted.
- A correction made when the evidence is ambiguous (two candidate labels, two years, two scale words).

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| A | Inside value normalisation (`arp/normalise/value.py`) | Earliest point, but mixes fixing into a core function every pipeline shares, and the trace of which rule changed what is harder to keep |
| B | Inside the checks (`arp/checks/`) | One place for all rules, but checks are read-only today; rewriting values there creates ordering problems with checks that already ran |
| **C** | **A separate correction step before the checks** | **Chosen.** One isolated, testable module whose output maps directly onto a "Corrections" stage in the planned walkthrough screen. Costs one extra step and a re-run of unit conversion when a unit changes |

## Design

### Where it runs

New module `backend/arp/extraction/corrections.py` with

```python
def apply_corrections(schema, fields, *, documents_by_id, fiscal_year_end) -> list[ExtractedField]
```

`_extract_company` in `backend/arp/extraction/pipeline.py` calls it once per company, after every field's rows are
gathered (extracted and reused rows alike) and before `check_record`. The record checks therefore run on corrected
values. Rules run in this order: R1, R2, R3, R4 (R4 needs the period that R2 may fill).

**Scope (builder's question, settled as my call):** `_extract_company` gains a keyword `corrections: bool = False`.
Only `execute_extraction_run` passes `True`, and only when the schema is neither `transition_plan_indicators` nor
`sch_transition_plan_actions` (their year-valued and forward-looking fields don't fit these rules). The other callers,
`research/revenue_exposure/resolver.py` and `research/taxonomy_sources/empirical.py`, keep the default and are
unchanged.

### What the record gains

- `ExtractedField.corrections: list[Correction]`, default empty, so stored rows from earlier runs load unchanged.
- `Correction` (in `backend/arp/schemas/datapoints.py`):

  | Field | Type | Meaning |
  |---|---|---|
  | `rule` | `"label_map" \| "period_fill" \| "unit_scale" \| "planned_move"` | Which rule fired |
  | `attribute` | `"value" \| "period_end" \| "unit" \| "field_id"` | What it changed |
  | `original` | `str \| float \| bool \| None` | The value before the rule |
  | `corrected` | `str \| float \| bool \| None` | The value after the rule |
  | `reason` | `str` | One sentence a reviewer can read, naming the evidence |

- Two new `ReasonCode` values in `backend/arp/schemas/review.py`:
  - `auto_corrected`: added to `review_reasons` whenever the row has at least one correction. Routing already sends
    any row with a review reason to `review`, so no routing change is needed.
  - `period_missing`: a numeric row that still has no `period_end` after R2. It also routes to review.
- `FieldDefinition.planned_field_id: str | None`, default `None`: on an actual-figure field, the `field_id` of its
  planned sibling. The `sch_transition_capex` preset sets it on `tc_capex_total` → `tc_capex_total_planned`,
  `tc_lowcarbon_capex` → `tc_lowcarbon_capex_planned` and `tc_lowcarbon_capex_share_pct` →
  `tc_lowcarbon_capex_share_pct_planned`.

A request or response model changes, so the PR runs `python scripts/export_openapi.py` and `npm run gen:api` as the
repo's checks require.

### Shared definitions

- **Grounded quotes**: the `quote` of every citation on the row with `grounded == true`.
- **Report period end** of a row: `period_plan.current` of the first cited document (in citation order) that has
  one. A row whose cited documents have none has no report period end.
- **Numeric field**: `data_type` in `number`, `currency_amount`, `percentage`.
- **Planned field**: a field that another field's `planned_field_id` points at (in the preset,
  `tc_capex_total_planned`, `tc_lowcarbon_capex_planned`, `tc_lowcarbon_capex_share_pct_planned`).

### R1 label_map (enum fields)

Applies when the field's `data_type` is `enum`, `value_state` is `found` and `value` is not in `allowed_values`.

`norm(s)`: lowercase, replace every run of characters other than `a-z` and `0-9` with `_`, strip leading and
trailing `_`. Tokens of a string are `norm(s).split("_")`.

1. If `norm(value)` equals `norm(a)` for exactly one allowed value `a`, the value becomes `a`.
2. Otherwise, if exactly one allowed value `a` has every one of its tokens among the value's tokens, the value
   becomes `a`.
3. Otherwise there is no correction, and the existing `format.allowed_values` check fails the row as today.

| Model value | Allowed values | Result |
|---|---|---|
| `Cash flow` | `eu_taxonomy, cash_flow, other` | `cash_flow` (step 1) |
| `cash-flow capex` | same | `cash_flow` (step 2) |
| `other $ (millions)` | same | `other` (step 2) |
| `cash flow or EU taxonomy` | same | no correction (two allowed values match) |
| `operating cash` | same | no correction (none match) |

Reason text: `"<original>" maps to the allowed value "<corrected>".`

### R2 period_fill (numeric fields)

Applies when the field is numeric, `value_state` is `found` or `zero`, and `period_end` is null.

Years named in the grounded quotes are the distinct matches of `\b(19|20)\d{2}\b`.

1. Exactly one year Y named: `period_end` becomes the fiscal year end in Y. The fiscal year end is the company's
   `fiscal_year_end` (MM-DD), or `12-31` when unset. `period_start` is set one year earlier plus a day, the way
   `resolve_period` does.
2. No year named, the field is **not** a planned field, and the row has a report period end: `period_end` becomes
   that date. (A planned figure is about a future year, so the report's own period end would be wrong for it.)
3. Otherwise (two or more years named, no year on a planned field, or no year and no report period end): no
   correction; add `period_missing`.

If the filled period would give the field a second row for the same `period_end` (another row already has it, or
two period-less rows resolve to the same year), the row is not filled and gets `period_missing` instead, so the
record never holds two rows for one field and period.

Reason text: `The quote names only <Y>.` for step 1, and `No year in the quote; taken from the report's period end <date>.`
for step 2.

### R3 unit_scale (numeric fields except percentage)

Applies when the field is `number` or `currency_amount`, `value_state` is `found`, and the row has at least one
grounded quote.

- **Scale words**: `thousand`, `thousands`, `k` = 1e3; `million`, `millions`, `mn`, `m` = 1e6; `billion`,
  `billions`, `bn`, `b` = 1e9. Matched case-insensitively as whole words.
- **Effective scale**: the row's `scale_applied` when normalisation computed one. When it didn't (normalisation
  failed with "scale stated twice and differs" because the unit and the raw text disagree), the scale that the
  existing parser `split_unit` (`backend/arp/normalise/units.py`) reads from `unit`. Comparing against the effective
  scale means a unit with no scale word whose raw text already says "billion", and which normalisation already
  converted correctly, is left alone.
- **Quote scale**: in each grounded quote, find the printed value (the digits of `raw_value_text` when set, otherwise
  `value` formatted with its decimals, thousands separators optional) followed by optional spaces and a scale word
  within 3 characters. Collect the distinct scales found.

If exactly one quote scale is found and it differs from the effective scale, `unit` is rewritten: the unit's scale
word is replaced by the quote's word in the same letter case (`Millions of dollars` → `Billions of dollars`), or the
quote's word is appended when the unit has none (`USD` → `USD billion`). The canonical value, canonical unit and
`scale_applied` are then recomputed with the same conversion `typed_value` uses. If normalisation had added
`check_failed` with the note "scale stated twice and differs", that reason and note are removed once the
recomputation succeeds. In every other case there is no correction.

Example: value 2.794, unit `Millions of dollars`, grounded quote "Capital expenditures were $2.794 billion during
2025" → unit `Billions of dollars`.

Reason text: `The quote says "<quote scale word>" next to <value as printed in the quote>.`

Known gap, not fixed here: units such as `$ million` or `of dollars` produce no canonical value today because the
currency isn't recognised. R3 still rewrites the unit; the canonical value stays empty, as it does now.

### R4 planned_move (numeric fields with a period)

Applies only to fields that have a `planned_field_id` (an opt-in, so forward-looking fields in other schemas, such
as targets, are never touched), when `value_state` is `found` or `zero`, `period_end` is set, the row has a report
period end, and `period_end` is later than it. A figure for a year after the report's period end cannot be an
actual.

- **The planned field has no `found` or `zero` row for that `period_end`:** the row moves. Its `field_id` and
  `field_name` become the planned field's, it takes the planned field's `input_hash` and field version (so the next
  run can reuse it under the planned field), and the correction (attribute `field_id`) is recorded on the moved row.
- **The planned field already has a `found` or `zero` row for that `period_end`:** the actual row's value is cleared
  (`value` null, `value_state` `not_found`), with the original kept in the correction. If the two values differ by
  more than 1%, the cleared value is also added to the planned row's `alternatives` with `source` `"planned_move"`.

Reason text: `Period 2026-12-31 is after the report's period end 2025-12-31, so it is a planned figure.`

### Idempotence

Running `apply_corrections` on rows it already corrected changes nothing and adds no second correction. Rows reused
from an earlier run (`reused_from_run` set) keep the corrections they were stored with.

### Reviewer view

Wherever a field's detail is shown in the extraction results (`frontend/src/components/ExtractionResults.tsx`) and
in the review queue item, each correction appears as one line:
`Auto-corrected (<rule label>): <original> → <corrected>. <reason>`, with the rule labels "Label", "Year", "Unit
scale" and "Planned figure". An empty original or corrected value shows as `—`. For `planned_move` the line shows the
two fields' names (`Total capex → Total capex, planned`), not their IDs. Styling is left to the builder.

## Left to the builder

The internal structure of `corrections.py`, helper names, how the canonical conversion is reused, and the styling of
the correction line.

## Acceptance

All rows use the test stand-ins for model calls (`ARP_STANDINS_DIR`), on schema `sch_transition_capex` unless the row
says otherwise. "The run" is a trial `arp extract run`; "the row" is the result row for the named field and period.
Unless a row says otherwise, the company has no `fiscal_year_end`, the cited document's `period_plan.current` is
`2025-12-31`, and every quote named in a row is grounded.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The stand-in extractor returns `Cash flow` for `tc_capex_denominator` | the run completes | The row's `value` is `cash_flow`; `corrections` has exactly one entry: `rule` `label_map`, `attribute` `value`, `original` `Cash flow`, `corrected` `cash_flow` | holdout |
| AC-2 | The stand-in returns `cash-flow capex` for `tc_capex_denominator` | the run completes | `value` is `cash_flow`; exactly one correction: `rule` `label_map`, `original` `cash-flow capex`, `corrected` `cash_flow` | holdout |
| AC-3 | The stand-in returns `cash flow or EU taxonomy` for `tc_capex_denominator` | the run completes | `value` is `cash flow or EU taxonomy`; `corrections` is empty; the `format.allowed_values` check has outcome `fail` | holdout |
| AC-4 | The stand-in returns 2479 with unit `USD millions` and no period for `tc_capex_total`, quote "capital expenditures were $2,479 million in 2025" | the run completes | `period_end` is `2025-12-31`; `period_start` is `2025-01-01`; exactly one correction: `rule` `period_fill`, `attribute` `period_end`, `original` null, `corrected` `2025-12-31` | holdout |
| AC-5 | As AC-4, but the quote is "capital expenditures were $2,479 million" (no year) | the run completes | `period_end` is `2025-12-31`; exactly one correction with `rule` `period_fill` and `corrected` `2025-12-31` | holdout |
| AC-6 | As AC-4, but the quote is "capital expenditures were $2,479 million in 2025 and $2,940 million in 2024" | the run completes | `period_end` is null; `corrections` is empty; `review_reasons` contains `period_missing`; `route` is `review` | holdout |
| AC-7 | The stand-in returns 2.794 with unit `USD millions` for `tc_capex_total` with period 2025, quote "Capital expenditures were $2.794 billion during 2025" | the run completes | `unit` is `USD billions`; exactly one correction: `rule` `unit_scale`, `attribute` `unit`, `original` `USD millions`, `corrected` `USD billions`; `canonical_value` is 2794000000.0; `canonical_unit` is `USD`; `scale_applied` is 1000000000.0 | holdout |
| AC-8 | As AC-7, but the quote is "Capital expenditures were 2.794 during 2025" (the value printed, no scale word) | the run completes | `unit` is `USD millions`; `corrections` is empty | holdout |
| AC-9 | The stand-in returns 2.5 with unit `USD billions` for `tc_capex_total` with period 2026, quote "Capital expenditures for 2026 are estimated to be approximately $2.5 billion", and nothing for `tc_capex_total_planned` | the run completes | No `tc_capex_total` row for `2026-12-31` holds a value; exactly one `tc_capex_total_planned` row for `2026-12-31`, with value 2.5 and exactly one correction: `rule` `planned_move`, `attribute` `field_id`, `original` `tc_capex_total`, `corrected` `tc_capex_total_planned` | holdout |
| AC-10 | A custom schema whose numeric field has no `planned_field_id`; the stand-in returns 100 with unit `USD millions` for period 2026 | the run completes | The row's `value` is 100; `period_end` is `2026-12-31`; `corrections` is empty | holdout |
| AC-11 | The rows produced in AC-1, AC-2, AC-4, AC-5, AC-7 and AC-9 | each run completes | Each of those rows has `auto_corrected` in `review_reasons` and `route` `review` | holdout |
| AC-12 | The stand-in returns `cash_flow` for `tc_capex_denominator` (period 2025), and 2479 with unit `USD millions`, period 2025, quote "capital expenditures were $2,479 million in 2025" for `tc_capex_total` | the run completes | `tc_capex_denominator` 2025: `value` `cash_flow`, `corrections` empty. `tc_capex_total` 2025: `value` 2479, `unit` `USD millions`, `period_end` `2025-12-31`, `corrections` empty. Both rows have `route` `review` with `unreleased_version` in `route_reasons` (the trial-run route, the same as today); neither row has `auto_corrected` or `period_missing` in `review_reasons` | holdout |
| AC-13 | A completed run that produced the AC-2 row, then a second run with unchanged inputs | the second run completes | The `tc_capex_denominator` row has `reused_from_run` set and exactly one `label_map` correction | holdout |
| AC-14 | A result row stored before this feature (no `corrections` key) | the run's results are read through the API | The row is returned with `corrections` equal to `[]` and HTTP status 200 | unit |
| AC-15 | The AC-7 run, AC-2 run, AC-4 run and AC-9 run, for a company named "Caterpillar", in the running app | a reviewer opens each corrected field in the extraction results and in the review queue | Each place shows, for its row: `Auto-corrected (Unit scale): USD millions → USD billions. The quote says "billion" next to 2.794.` · `Auto-corrected (Label): cash-flow capex → cash_flow. "cash-flow capex" maps to the allowed value "cash_flow".` · `Auto-corrected (Year): — → 2025-12-31. The quote names only 2025.` · `Auto-corrected (Planned figure): Total capex → Total capex, planned. Period 2026-12-31 is after the report's period end 2025-12-31, so it is a planned figure.` | evaluator |
| AC-16 | A PR touching `backend/arp/extraction` | CI runs the golden set | `arp golden-set run` exits 0 | golden |
| AC-17 | A completed run that produced the AC-9 moved row, then a second run with unchanged inputs | the second run completes | Exactly one `tc_capex_total_planned` row for `2026-12-31`; it has `reused_from_run` set and exactly one `planned_move` correction | holdout |
| AC-18 | The stand-in returns 2.5 with unit `USD billions` for `tc_capex_total_planned` with no period, quote "capital expenditures are expected to be about $2.5 billion" | the run completes | `period_end` is null; `corrections` is empty; `review_reasons` contains `period_missing` | holdout |
| AC-19 | The stand-in returns two `tc_capex_total` values: 2479 for period 2025, and 2480 with no period and quote "capex of $2,480 million in 2025" (both unit `USD millions`) | the run completes | Exactly one `tc_capex_total` row has `period_end` `2025-12-31` (value 2479); the period-less row keeps `period_end` null, has `period_missing` and no correction | holdout |
| AC-20 | The stand-in returns 2.794 with unit `USD`, raw text "$2.794 billion", period 2025, for `tc_capex_total`, quote "Capital expenditures were $2.794 billion during 2025" | the run completes | `corrections` is empty; `canonical_value` is 2794000000.0; `canonical_unit` is `USD` | holdout |
| AC-21 | A `transition_plan_indicators` run where the stand-in returns one answer per rule: `Cash flow` for an enum field (R1); a numeric value with no period and a quote naming only 2025 (R2); and 2.794 with unit `USD millions` and the quote "$2.794 billion" (R3) | the run completes | No row has a `corrections` entry, `auto_corrected` or `period_missing` | holdout |
| AC-22 | As AC-21 (the same three answers), for a `sch_transition_plan_actions` run | the run completes | No row has a `corrections` entry, `auto_corrected` or `period_missing` | holdout |
| AC-23 | A revenue-exposure resolver call (`research/revenue_exposure/resolver.py`) where the stand-in returns one answer per rule: `Cash flow` for an enum field (R1); a numeric value with no period and a quote naming only 2025 (R2); and 2.794 with unit `USD millions` and the quote "$2.794 billion" (R3) | it completes | No returned row has a `corrections` entry, `auto_corrected` or `period_missing` | unit |
| AC-24 | A taxonomy empirical-derivation call (`research/taxonomy_sources/empirical.py`) where the stand-in returns one answer per rule: `Cash flow` for an enum field (R1); a numeric value with no period and a quote naming only 2025 (R2); and 2.794 with unit `USD millions` and the quote "$2.794 billion" (R3) | it completes | No returned row has a `corrections` entry, `auto_corrected` or `period_missing` | unit |
| AC-25 | In the same run, the stand-in returns 2.5 (`USD billions`) for `tc_capex_total_planned` with period 2026, and 3.0 (`USD billions`) for `tc_capex_total` with period 2026 | the run completes | The `tc_capex_total` 2026 row has `value` null, `value_state` `not_found` and exactly one `planned_move` correction with `original` 3.0; the planned row's `alternatives` include one with value 3.0 and `source` `planned_move` | holdout |
| AC-26 | As AC-25 (both answers in the same run), but the actual value is 2.51 (`USD billions`, under 1% apart) | the run completes | The `tc_capex_total` 2026 row has `value` null and one `planned_move` correction; the planned row has no alternative with `source` `planned_move` | holdout |
| AC-27 | As AC-7, but the quote is "capex was $2.794 billion, of which $2.794 million was leased" (two scale words next to the value) | the run completes | `unit` is `USD millions`; `corrections` is empty | holdout |
| AC-28 | The stand-in returns 2.794 with unit `USD millions` and raw text "$2.794 billion" for `tc_capex_total` 2025, quote "Capital expenditures were $2.794 billion during 2025" | the run completes | `unit` is `USD billions`; `canonical_value` is 2794000000.0; `review_reasons` contains `auto_corrected` and does not contain `check_failed`; no note on the row contains `scale stated twice and differs` | holdout |
| AC-29 | As AC-4, but the company's `fiscal_year_end` is `03-31` | the run completes | `period_end` is `2025-03-31`; `period_start` is `2024-04-01` | holdout |
| AC-30 | This change merged | the existing test files for the financials, TNFD, transition-plan and replication pipelines run | They pass with no test changed | unit |
| AC-31 | As AC-5 (no year in the quote), but the cited document has no `period_plan.current` | the run completes | `period_end` is null; `corrections` is empty; `review_reasons` contains `period_missing` | holdout |

Must not change: rows that need no correction keep their values, units, periods and routes (AC-12); stored rows from earlier
runs still load (AC-14); the transition-plan schemas and the research callers get no corrections (AC-21 to AC-24);
the other pipelines' tests pass unchanged (AC-30).
