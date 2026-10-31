# Extraction quick wins: typed answers, two format gaps, a share check, a quieter row-label check

Date: 2026-10-31
Status: draft, awaiting owner approval
Source: the 30–31 October model tests (transition-plan questions and green capex on RWE, Siemens and BASF:
Sonnet + Opus, Haiku + Sonnet, Haiku + Haiku, Gemini) and the owner's choice "quick code wins first".

## Why

The tests turned up wrong values that code could stop or flag for free, with no extra model call:

| Seen in the tests | Example | What happens today |
|---|---|---|
| A yes/no question answered with a number or text | RWE Q60 = `220221`; Q22 = `"Not disclosed"`; BASF Q13 = `"YES"` | `format.data_type` blocks it and the row goes to review. The model was free to send it, and a reviewer has to fix it by hand |
| A text field holding a number | RWE `green_capex_definition` = `11115` | Nothing flags it: `format.data_type` does not check text fields |
| A money field holding a percentage | Siemens `green_capex_circular_economy` = `27.3 %` | Nothing flags it: the unit is never compared with the field's type |
| A share that does not fit its own total | not caught on any run; no rule exists | `green_capex_share_pct` is never compared with `green_capex_total / capex_total` |
| The row-label check firing on yes/no answers | 12–16 of 64 transition-plan answers per company | `numeric.row_label` looks for a table row label on any grounded quote, so prose quotes for yes/no questions fail it. Reviewers learn to ignore it |

## Goals

1. The extractor and the blind verifier can only return a value of the field's type.
2. `format.data_type` also fails a text field holding a bare number, and a money or plain number field whose unit is
   a percent sign (and a percentage field whose unit is a currency).
3. A share field can name its numerator and denominator; a check warns when the share is more than 1 percentage
   point off their ratio. The green preset uses it for revenue, capex and opex shares.
4. `numeric.row_label` is not applicable to yes/no, list (enum), text and date fields.

## Non-goals

- The skip rule, model choice per schema, table-first extraction, a hand-checked answer set: separate specs.
- The `consistency.entity` "ambiguous" warning. It fires on most rows of a report whose cover page names no legal
  entity; that needs its own look at `arp/planning/entity_check.py`.
- Group calls (`extract_group`, used only by non-high-risk fields with `extraction_group_size` above 1), Financials,
  TNFD and transition-plan list fields: they keep today's answer format.
- Changing stored rows of earlier runs.

## Anti-goals

- A run fails, or a company in it fails, because a model's answer did not fit the typed format. Today one such
  answer fails the whole company (the 30 October Signify run lost all 72 fields to one stringified list). After this
  change a bad answer goes through the existing validation retry and, if it still does not fit, only that field ends
  with no value, routed to review.
- A field's version changes beyond the three green share fields named in Design 3, so earlier answers stop being
  reused.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **A** | **Typed answer format built per field from its data type (chosen)** | Stops wrong types at the source; one more helper and the extractor and blind verifier call it |
| B | Keep the loose format; convert `"YES"`/`"Not disclosed"` to yes/no in code afterwards | Hides model mistakes; guesses about strings like `"N/A"` |
| C | Only strengthen the checks | Wrong types still reach reviewers |

## Design

### 1. Typed answers (`arp/extraction/extractor_agent.py`)

A helper builds the draft model for one field. `PeriodValue.value` gets the field's type:

| Field data type | `value` accepts |
|---|---|
| `boolean` | `true`, `false` or null |
| `number`, `currency_amount`, `percentage` | a number or null |
| `enum` | one of the field's `allowed_values`, or null |
| `string`, `date` | text, a number (stored as its text, e.g. `11115` → `"11115"`), or null |

Everything else in `PeriodValue` and `ExtractionDraft` stays as it is. `extract_field` and `blind_verify` (its
blind draft) use the typed model; the result is handled as an `ExtractionDraft` exactly as today. An answer that does
not fit goes through `complete_structured`'s existing validation retry, which tells the model which field failed.
If it still does not fit after the retries, `complete_structured` raises `pydantic.ValidationError` as today; the
field's extract node (`_extract` in `arp/extraction/field_graph.py`) catches it and stores that field as
`not_found` with review reason `extraction_failed` (a new `ReasonCode`), so the company's other fields are kept. The
same applies to the blind verifier: a failed blind draft counts as a disagreement of type `not_disclosed`, so the
row goes to review.

### 2. Format gaps (`arp/checks/runner.py`, `check_format`)

`format.data_type` also fails (severity block, as today) when:

- the field is `string` and its value is a number, or text that, after trimming spaces, matches
  `^[+-]?\d[\d,.' ]*$` (`"11115"`, `"1,234.5"`, `" 11115 "`, `"-5"`, `"2020"`). `"1e3"`, `"€ 5"`, `"5 %"` pass;
- the field is `number` or `currency_amount` and its `unit` or its `canonical_unit` is `%`;
- the field is `percentage` and its unit is an ISO 4217 code or a currency sign (€, $, £).

Detail texts: `string field holds a bare number 11115`, `currency_amount field holds a percentage (unit %)`,
`percentage field holds a currency amount (unit EUR million)`.

### 3. Share check (`arp/schemas/datapoints.py`, `arp/checks/plausibility.py`, `arp/presets/green.py`)

`CheckConfig` gets `ratio_of: list[str]`, two field ids: numerator, then denominator. A new layer-3 check
`plausibility.ratio` (severity warn) takes both from the same company and period. It is not applicable when either is
missing, not numeric, the two have different `canonical_unit`, or the denominator is 0. It fails when
`|share − 100 × numerator / denominator| > 1` (percentage points; exactly 1 passes), detail
`share <v> vs <num>/<den> = <ratio> %`, numbers printed with Python's `:g` (no trailing `.0`), the ratio rounded to
one decimal first. The comparison uses that rounded ratio: fail when `abs(share − ratio) > 1 + 1e-9`.

The green preset sets `ratio_of=[green_<m>_total, <m>_total]` on `green_<m>_share_pct` for revenue, capex and opex.
`check_config` counts as field content (`arp/db/fields.py`: only status, version and effective_from do not), so these
three fields go from version 2 to version 3. Earlier answers for those three fields are not reused; every other field
keeps its version.

### 4. Quieter row-label check (`arp/checks/numeric.py`, `check_row_label`)

Returns not applicable for `boolean`, `enum`, `string` and `date` fields, before reading any text.

## Acceptance

Rows marked `unit` become `holdout` once `HOLDOUT_TOKEN` is set; until then they are listed as owed in the PR.
"Stand-in" is a scripted `LLMClient` returning the given tool inputs in order. "A failed structured call" is the
`pydantic.ValidationError` that `complete_structured` raises after its last attempt (1 + `max_validation_retries`,
default 2, so 3 calls).

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | A boolean field; stand-in answers `value: 220221`, then `value: true` | `extract_field` runs | The returned draft's `values[0].value` is `True` | unit |
| AC-1b | Same | `extract_field` runs | The stand-in received exactly 2 calls | unit |
| AC-2 | A boolean field; stand-in answers `value: "Not disclosed"` on every call | `extract_field` runs | It raises `pydantic.ValidationError` after exactly 3 calls | unit |
| AC-3 | An enum field, `allowed_values=["eu_taxonomy","other"]`; stand-in answers `value: "EU Taxonomy"`, then `value: "eu_taxonomy"` | `extract_field` runs | `values[0].value` is `"eu_taxonomy"` | unit |
| AC-3b | Same field; stand-in answers `value: null`, `state: "not_found"` | `extract_field` runs | `values[0].value` is `None` | unit |
| AC-3c | Same | `extract_field` runs | The stand-in received exactly 1 call | unit |
| AC-4 | A high-risk boolean field, draft `value: false`; stand-in verifier answers `value: "YES"`, then `value: false` | `blind_verify` runs | The returned `VerifierOutput.agrees` is `True` | unit |
| AC-4b | Same | `blind_verify` runs | The stand-in received exactly 2 calls | unit |
| AC-5 | A currency field; stand-in answers `value: 11887` | `extract_field` runs | `values[0].value == 11887.0` | unit |
| AC-5b | Same | `extract_field` runs | The stand-in received exactly 1 call | unit |
| AC-5c | A percentage field; stand-in answers `value: "39.6%"`, then `value: 39.6` | `extract_field` runs | `values[0].value == 39.6` | unit |
| AC-5d | A string field; stand-in answers `value: 11115` | `extract_field` runs | `values[0].value == "11115"` (accepted as text; AC-6 then flags it) | unit |
| AC-5e | A date field; stand-in answers `value: "2025-12-31"` | `extract_field` runs | `values[0].value == "2025-12-31"` | unit |
| AC-6 | A `string` row, value `11115`, state found | checks run | `format.data_type` is `fail`, severity `block`, detail `string field holds a bare number 11115` | unit |
| AC-6b | A `string` row, value `"1,234.5"` | checks run | `format.data_type` is `fail`, detail `string field holds a bare number 1,234.5` | unit |
| AC-6c | A `string` row, value `"2020"` | checks run | `format.data_type` is `fail` | unit |
| AC-6d | A `string` row, value `"1e3"` | checks run | `format.data_type` is `pass` | unit |
| AC-7 | A `string` row, value `"EU Taxonomy definition (Regulation (EU) 2020/852)"` | checks run | `format.data_type` is `pass` | unit |
| AC-8 | A `currency_amount` row, value `27.3`, unit `%` | checks run | `format.data_type` is `fail`, detail `currency_amount field holds a percentage (unit %)` | unit |
| AC-8b | A `number` row, value `5`, unit `%` | checks run | `format.data_type` is `fail`, detail `number field holds a percentage (unit %)` | unit |
| AC-8c | A `currency_amount` row, value `27.3`, unit `percent`, canonical_unit `%` | checks run | `format.data_type` is `fail` | unit |
| AC-9 | A `percentage` row, value `39.6`, unit `EUR million` | checks run | `format.data_type` is `fail`, detail `percentage field holds a currency amount (unit EUR million)` | unit |
| AC-9b | A `percentage` row, value `39.6`, unit `€` | checks run | `format.data_type` is `fail`, detail `percentage field holds a currency amount (unit €)` | unit |
| AC-10 | A `percentage` row, value `39.6`, unit `%` | checks run | `format.data_type` is `pass` | unit |
| AC-11 | One period: `capex_total` 1000, `green_capex_total` 396 (same canonical unit), `green_capex_share_pct` 39.6 | checks run on the share row | `plausibility.ratio` is `pass` | unit |
| AC-12 | Same, share 94 | checks run on the share row | `plausibility.ratio` is `fail`, severity `warn`, detail `share 94 vs 396/1000 = 39.6 %` | unit |
| AC-12b | Same, share 40.6 | checks run on the share row | `plausibility.ratio` is `pass` | unit |
| AC-12c | Same, share 40.7 | checks run on the share row | `plausibility.ratio` is `fail` | unit |
| AC-13 | Same, but `green_capex_total` exists only for a different period | checks run on the share row | `plausibility.ratio` is `not_applicable` | unit |
| AC-13b | Same period, but the two amounts have different `canonical_unit` | checks run on the share row | `plausibility.ratio` is `not_applicable` | unit |
| AC-13c | Same period, `capex_total` 0 | checks run on the share row | `plausibility.ratio` is `not_applicable` | unit |
| AC-13d | Same period, `green_capex_total` value `"n/a"` | checks run on the share row | `plausibility.ratio` is `not_applicable` | unit |
| AC-14 | The green preset | built | `green_capex_share_pct`, `green_revenue_share_pct`, `green_opex_share_pct` each have `check_config.ratio_of == ["green_<m>_total", "<m>_total"]` | unit |
| AC-14b | The green preset | built | Those three fields have `version == 3`; every other green field's `version` equals its value on `main` | unit |
| AC-15 | A `boolean` row grounded on a prose quote containing two numbers | checks run | `numeric.row_label` is `not_applicable` | unit |
| AC-15b | The same for an `enum`, a `string` and a `date` row | checks run | `numeric.row_label` is `not_applicable` for each | unit |
| AC-16 | A `currency_amount` row grounded on a table line whose label does not match the field | checks run | `numeric.row_label` is `fail` | unit |
| AC-17 | A `boolean` row holding `220221` | checks run | `format.data_type` is `fail`, severity `block` (unchanged) | unit |
| AC-18 | A non-high-risk boolean field extracted through `extract_group`; stand-in answers `value: "yes"` for it | the group call runs | The row's value is `"yes"` (group calls keep the loose format) | unit |
| AC-18b | Same | the group call runs | The stand-in received exactly 1 call | unit |
| AC-19 | One company, a 2-field schema (a boolean and a currency field); stand-in answers `"Not disclosed"` on every call for the boolean, `11887` for the currency | `execute_extraction_run` runs | The run status is `completed`, 1 of 1 companies done | unit |
| AC-19c | Same | `execute_extraction_run` runs | The currency row has value `11887.0` | unit |
| AC-19d | Same | `execute_extraction_run` runs | The boolean row has `value_state` `not_found`, route `review`, and `extraction_failed` in `review_reasons` | unit |
| AC-19b | A high-risk boolean field, draft `value: true`; stand-in verifier answers `"YES"` on every call | the field's graph runs | The row has route `review` | unit |
| AC-19e | Same | the field's graph runs | Its verifier result has `disagreement_type` `not_disclosed` | unit |
| AC-22 | `extract_plan` (plan actions preset `sch_transition_plan_actions`, field `ta_action_text`); a recorded stand-in answer fixture that includes at least one value the typed format would reject (`value: "Not disclosed"` for a numeric or yes/no item), with the stored result captured from `main` at spec approval and kept as a snapshot beside the test | the extraction runs on the PR | the plan row stored on the PR equals the snapshot | unit |
| AC-22-calls | Same | Same | The stand-in received the number of calls recorded in the snapshot | unit |
| AC-22b | `extract_financials` (Financials record, `capex` section); a recorded stand-in answer fixture that includes at least one value the typed format would reject (`value: "Not disclosed"` for a numeric or yes/no item), with the stored result captured from `main` at spec approval and kept as a snapshot beside the test | the extraction runs on the PR | the `capex` section stored on the PR equals the snapshot | unit |
| AC-22b-calls | Same | Same | The stand-in received the number of calls recorded in the snapshot | unit |
| AC-22c | `extract_tnfd` (TNFD record, `general_requirements` section); a recorded stand-in answer fixture that includes at least one value the typed format would reject (`value: "Not disclosed"` for a numeric or yes/no item), with the stored result captured from `main` at spec approval and kept as a snapshot beside the test | the extraction runs on the PR | the `general_requirements` section stored on the PR equals the snapshot | unit |
| AC-22c-calls | Same | Same | The stand-in received the number of calls recorded in the snapshot | unit |
| AC-20 | The backend suite | `pytest` runs | It passes. The PR lists every changed test; the only allowed changes are tests expecting `numeric.row_label` to fail on non-numeric fields | evaluator |
| AC-21 | The golden set | `arp golden-set run` in CI | Exits 0 with every case passing. A missing `ARP_ANTHROPIC_API_KEY` (the job warns and passes) counts as fail for this row | golden |

Must not change: AC-16, AC-17, AC-18, AC-18b, AC-20, AC-22, AC-22b, AC-22c and their `-calls` rows (existing behaviour), AC-21 (extraction quality on the golden set).

## Left to the builder

- Where the typed-model helper lives (in `extractor_agent.py` beside `ExtractionDraft` is the obvious place) and
  whether it is cached per field.
