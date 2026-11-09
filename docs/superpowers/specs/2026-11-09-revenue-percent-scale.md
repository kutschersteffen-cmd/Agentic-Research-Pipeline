# Revenue percent scale: stop reading small percentages as huge ones

## Intent

An extracted revenue share of 1% or 0.8% is read as 100% or 80%. A company with a sliver of revenue in an
activity then looks like a pure play, gets verdict INCLUDE, and `_l1` scores it as full exposure. The
reason is one line, `backend/arp/research/revenue_exposure/resolver.py:95`:
`pct_fraction = pct / 100 if pct > 1 else pct`. It guesses whether a number is a fraction or a
percentage, but the extractor is never ambiguous: `backend/arp/research/taxonomy_schema.py:222` tells it
"Express `value` as a number between 0 and 100 (e.g. 18.5 for 18.5%)". Every extracted value is a
percentage, so the guess is wrong for every value at or below 1.

## Evidence (reproduced on `main` dc33745)

`to_exposure()` run on an extracted value `v` returns `value_pct`:

| v | today | should be |
|---|-------|-----------|
| 0.8 | 0.8 | 0.008 |
| 1 | 1.0 | 0.01 |
| 18.5 | 0.185 | 0.185 |
| 22 | 0.22 | 0.22 |
| 100 | 1.0 | 1.0 |
| 101 | 1.0 (clamped) | unresolved |
| -5 | 0.0 (clamped) | unresolved |

The only test, `backend/tests/test_revenue_resolver.py::test_extract_schema_fields_finds_explicit_percentage`,
uses 22; nothing covers 1 or below.

## Goals

- An extracted value `v` with 0 <= v <= 100 becomes the fraction `v / 100`, with no exception for small values.
- An extracted value below 0 or above 100 (or not a finite number) is not turned into a number: the
  result is `source="unresolved"` with a note. Owner decision, see Decided.
- AC-1 to AC-13 pass; they name 0.8, 1, 18.5, 100, 101, a negative value and 22.

## Non-goals

- Recomputing exposure results already stored. Owner decision: left as they are (see Follow-ups).
- Changing the extractor prompt, the golden set, or the catalogue path (`resolve_from_catalogue`
  already stores fractions via `as_pct_of_total` or `value / denominator`).
- Routing out-of-range values to the review queue.
- The other `/ 100` heuristics found by grep (see Other callers).

## Anti-goals

- A 0-1 extracted value must never again be silently multiplied up to a larger share than the document states.
- No out-of-range value may produce a number that downstream code (`_l1`, verdicts) can use.

## Other callers and places with the same heuristic (grep)

- `to_exposure` has one production caller: `extract_schema_fields` (`resolver.py:131`), used by the
  revenue path and by `rd_exposure/resolver.py:46`. The R&D resolver reads its field through the same
  function, so the fix reaches both. Its own `value_pct` values (`news` score, line 81) do not pass
  through the heuristic.
- `pct > 1` appears nowhere else. Same-family patterns that this spec leaves alone:
  `taxonomy_sources/etf_holdings.py:93` (`weight / 100` once any weight above 1 or a `%` is seen: a
  holdings file with every weight at or below 1 and no `%` is read as fractions) and
  `stock_inference/index_rules.py:40` (`_pct`, always divides by 100, correct). Only the ETF one is a
  possible second bug; mention to the owner, not fixed here.
- `exposure_layers._l1` and verdict logic only consume `value_pct`; they need no change.
- Golden set: this change touches `arp/research/revenue_exposure/resolver.py`, not `arp/extraction`,
  `arp/llm`, `arp/golden_set`, `arp/grounding.py` or `arp/config.py`, so the golden-set CI job does not
  run. A grep of `backend/arp/golden_set` and `backend/tests/golden` finds no case that asserts an
  extracted revenue `value_pct`, so none was produced with the old behaviour.
- Mutation check: runs on `risk:high` PRs, which this will be.

## Approaches

1. **Always divide by 100 and reject out-of-range (chosen).** The extractor contract is 0-100, so the
   code follows it. One line plus a range check.
2. **Keep the heuristic, raise the threshold.** Still guesses; 0.8 and 80 would never be told apart by
   value alone.
3. **Change the extractor to emit fractions.** Touches the prompt and golden-set CI and still leaves the
   resolver guessing for already-extracted data. Out of scope.

## Decided

- Divide by 100 always. No `> 1` test.
- Out-of-range (value < 0, value > 100, NaN, infinite): `MetricExposure(source="unresolved", notes=...)`
  with the exact note `Extracted value <v> is outside 0-100.` where `<v>` is the field's `value` exactly as
  received (`str()` of it, so `101`, `-5`, `100.5`, `nan`). No rounding. Owner chose reject over clamp or
  review-queue.
- Boundaries 0 and 100 are valid.
- Stored results are not recomputed (owner choice).
- The implementing PR is labelled `risk:high` (index maths) and the owner merges it on GitHub. It changes
  nothing under `.claude/`, `.github/`, `backend/arp/extraction`, `backend/arp/llm`,
  `backend/arp/golden_set` or `openwiki/`, and edits or deletes no existing test (new tests only).

## Left to the builder

Where the range check sits in `to_exposure`, the exact test names. Keep the min/max clamp or drop it:
after the check it is redundant. `test_extract_schema_fields_finds_explicit_percentage` stays unchanged.

## Follow-ups (not in this change)

- Stored results: affected rows are extracted revenue or R&D exposures with `source="extracted"` and
  `value_pct` in (0, 1] produced before the fix, where the true share is 100 times smaller. A separate
  piece of work decides recompute versus re-run; it needs the raw extracted value, which `raw_value_text`
  only holds as text.
- ETF weights heuristic (`etf_holdings.py:93`) as above.

## Acceptance

Input form for every row: `to_exposure(field, "s:v1")` where `field.value` is the Python value shown and
`field.citations` is empty. "Result" means the returned `MetricExposure`. `within 1e-9` means `abs(a-b) < 1e-9`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `value` 0.8 | `to_exposure` runs | result `source == "extracted"`, `value_pct` within 1e-9 of 0.008 | holdout |
| AC-2 | `value` 1 | `to_exposure` runs | result `source == "extracted"`, `value_pct` within 1e-9 of 0.01 | holdout |
| AC-3 | `value` 18.5 | `to_exposure` runs | result `source == "extracted"`, `value_pct` within 1e-9 of 0.185 | holdout |
| AC-4 | `value` 100 | `to_exposure` runs | result `source == "extracted"`, `value_pct == 1.0` | holdout |
| AC-5 | `value` is the int 101 | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value 101 is outside 0-100."` | holdout |
| AC-6 | `value` is the int -5 | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value -5 is outside 0-100."` | holdout |
| AC-7 | `value` 22 | `to_exposure` runs | result `source == "extracted"`, `value_pct` within 1e-9 of 0.22 | holdout |
| AC-8 | `value` 0 | `to_exposure` runs | result `source == "extracted"`, `value_pct == 0.0` | holdout |
| AC-9 | `value` 100.5 | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value 100.5 is outside 0-100."` | holdout |
| AC-10 | `value` `float("nan")` | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value nan is outside 0-100."` | holdout |
| AC-11 | `value` `float("inf")` | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value inf is outside 0-100."` | holdout |
| AC-12 | `value` the string `"18.5"` | `to_exposure` runs | result `source == "extracted"`, `value_pct` within 1e-9 of 0.185 (strings are accepted today) | holdout |
| AC-13 | `value` the string `"abc"` | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value was not numeric."` | holdout |
| AC-14 | `field` is `None` | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == ""` | unit |
| AC-15 | a result row for one company whose single match has verdict `include` and `revenue_exposure.revenue` = `to_exposure(field, "s:v1")` with `field.value == 0.8`, passed through `model_dump()`; no other matches | `run_company_l1([company], [row])` runs | the returned tuple's third element (L1) is within 1e-9 of 0.008 | unit |
| AC-16 | a catalogue row with `as_pct_of_total=0.4`, label matched by the mapping | `resolve_from_catalogue` runs (fixture of `test_resolve_from_catalogue_direct_pct`) | result `source == "catalogue"`, `value_pct == 0.4` | unit |
| ~~AC-17~~ | retired: a diff-scope review is not observable behaviour; the protected paths and "no test edited" rule are in Decided and checked by the steward skill | | | |
| ~~AC-18~~ | retired: the `risk:high` label is in Decided | | | |
| AC-19 | `value` the string `"101"` | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value 101 is outside 0-100."` | holdout |
| AC-20 | `value` the string `"nan"` | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == "Extracted value nan is outside 0-100."` (a parseable string is a number, so it is out of range, not "not numeric") | holdout |
| AC-21 | `field` exists and `field.value` is `None` | `to_exposure` runs | result `source == "unresolved"`, `value_pct is None`, `notes == ""` | holdout |
| AC-22 | the AC-15 row, but `field.value == 101` | `run_company_l1` runs | the returned tuple's third element (L1) `is None` | holdout |

Checked by: `to_exposure` is reached in the running app only through an LLM extraction call, so these rows
call the function directly (the test-writer imports `arp`; if the Holdout job cannot, or `HOLDOUT_TOKEN`
is unset, the rows become `unit` and are listed as owed in the PR). The `evaluator` has
nothing to drive for this change, so there is no `evaluator` row. The R&D path shares `to_exposure`, so
AC-1 to AC-14, AC-19 to AC-21 cover it; it has no separate row.

Must not change: a value that already worked (22 gives 0.22, AC-7), 100 gives 1.0 (AC-4), missing and
non-numeric values stay unresolved (AC-13, AC-14), and the catalogue path (AC-16).
