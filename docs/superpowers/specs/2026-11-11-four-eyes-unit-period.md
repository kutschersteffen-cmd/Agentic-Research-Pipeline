# Four-eyes must compare unit and period; corrections may change the value only

## Intent

A reviewer's correction can carry `unit` and `period_end` next to `value` (`CORRECTED_KEYS`,
`backend/arp/review/decide.py:40-42`). Two things go wrong with them today.

1. **Four-eyes ignores them.** `agrees(first, second)` (`backend/arp/orchestration/review_queue.py:149`)
   compares the decision kind and the value only. A first review corrected to 5 with unit `USD million`
   and a second review corrected to 5 with unit `USD billion` agree, so a scale slip passes the second
   look. The same holds for two different `period_end`.
2. **The two stores disagree.** `merge_correction` (`backend/arp/publish/candidates.py:17`) merges the
   corrected `unit` and `period_end` into the published fact. `apply_decision`
   (`backend/arp/db/observations.py:431-437`) writes only `value` and `canonical_*` to `company_facts`;
   `CompanyFact` has no unit column and `period_end` is part of the fact's identity (`uq_company_facts_current`,
   `db/models.py:535-546`), so a corrected period cannot simply be overwritten. `authoritative/source_values.py:74`
   reads the unit from `fact.canonical_unit or obs.unit`, the original observation's. Same value, two units.

## Evidence (verified on `main` 0e9fa2e)

| Probe | Result on `main` |
|-------|------------------|
| `agrees` of two `edit` rows, `corrected_value` `{value: 5, unit: "USD million"}` and `{value: 5, unit: "USD billion"}` | `True` |
| `agrees` of two `edit` rows, `{value: 5, period_end: "2024-12-31"}` and `{value: 5, period_end: "2023-12-31"}` | `True` |
| Read: `_edited` (`observations.py:369`) returns `edit.get("value")`; the unit of a fact comes from `canonical_unit` or the observation | a corrected `unit` or `period_end` never reaches `company_facts` |

The review UI (`frontend/src/components/ReviewControls.tsx`, `correctedValue`) sends `value` only, so
only API clients can send `unit` or `period_end` today.

## Callers (grep)

- `agrees`: `review_queue.py:163` (`item_state`: first vs second row), `review/decide.py:230`
  (`changes_final`), `review/quality.py:310,312` (reviewer agree and overturn counts).
- `second_review_reasons` (`decide.py:63`) has one caller, `decide.py:226`. It compares the correction with the
  previous published value (`prior.value`), which has no unit; it stays as it is.
- `merge_correction`: `publish/candidates.py:111,130`. Unchanged.
- Tests that touch this: `tests/test_review_decide.py` (line 131 corrects with `{"value": 1234, "unit": "t"}`,
  line 142 `test_corrected_keys_checked`), `tests/test_review_state.py` (agreeing and disagreeing second rows),
  `tests/test_publish_candidates.py`, `tests/db/test_observations.py`.

## Goals

- Two corrections agree only if value, unit and `period_end` all agree.
- A `correct` decision on a `value` or `restatement_candidate` item may change the value only. A decision that
  carries `unit` or `period_end` is refused with 422, so `company_facts` and `published_facts` cannot disagree
  on unit or period again.

## Non-goals

- A unit column on `company_facts`, a migration, or any schema change.
- Changing `merge_correction`, `published_facts`, `source_values.py`, `second_review_reasons` or the frontend.
- Rewriting or re-opening stored review decisions.
- Unit conversion of a corrected value.

## Anti-goals

- A scale or period slip must never count as agreement.
- No stored decision, fact or published row is edited by this change.

## Approaches

1. **Compare all three keys; refuse `unit`/`period_end` at decision time (chosen, owner decision).** No schema
   change; both tables agree because only the value can change. The comparison still matters for stored rows
   and as a guard.
2. Store unit and period on the fact. Needs a migration and changes fact identity for a corrected period.
   Rejected by the owner.
3. Leave both tables as they are and document it. The disagreement stays. Rejected by the owner.
4. For agreement, compare value and unit only. A period slip would still pass. Rejected by the owner.

## Decided (owner answers, 2026-11-11)

1. `agrees` compares value, unit and `period_end`.
2. `unit` and `period_end` corrections are rejected at decision time; no schema change.
3. Stored decisions are left as they are.

Rule the builder implements:

- `agrees(first, second)`: kinds differ → `False`. Kind not `correct` → `True` (unchanged). Kind `correct` →
  `same_value` on the value (unchanged) **and** `unit` equal **and** `period_end` equal. `unit` and
  `period_end` are compared as `str(x).strip()`, case-sensitive; `None`, an empty or whitespace-only string and an
  absent key all count as absent and equal each other; present on one side only is not equal. Read the keys from `corrected_value` or, for legacy rows,
  `edited_value`, as `_value` does.
- `CORRECTED_KEYS["value"]` and `CORRECTED_KEYS["restatement_candidate"]` become `{"value"}`. The existing check
  (`decide.py:125-127`, by key, so `unit: null` is refused too) then answers `corrected_value may only hold ['value']`.

Consequences stated up front, to be accepted with the table:

- **Stored decisions.** Item state is folded from the stored rows on every read, so a stored pair whose two
  corrections agreed on value but differ in `unit` or `period_end` is now `disagreed` instead of `second_done`
  (the owner chose to leave the data alone; the derived state follows the new rule). The implementing PR changes
  no row. Its description must say that this can happen, because the data is not visible to the builder.
- **Agree button.** A first correction that carries `unit` or `period_end` can no longer be re-submitted as is
  (the UI Agree action re-sends the first `corrected_value`): the 422 above applies. The second reviewer enters
  a value-only correction, which then disagrees with it and goes to resolution.
- **Existing test.** `test_grounded_correction_stored_with_server_offsets` (`test_review_decide.py:131`) sends
  `{"value": 1234, "unit": "t"}` and expects 200. Its fixture must change to `{"value": 1234}`; the PR lists that
  change in its description. No assertion is weakened.

## Risk

The implementing PR is `risk:high` (reviewed values, review state of stored items). The owner merges it on
GitHub. The nightly mutation check runs on it.

## Left to the builder

Where the three-key comparison lives (inside `agrees` is expected), test names, wording of the PR note.

## Acceptance

Fixtures: for `agrees` rows, two rows `{"decision": "edit", "corrected_value": {...}}` (the holdout imports
`agrees` from `arp.orchestration.review_queue` directly). For "stored" rows, decision rows are written straight
into the run store, because the API refuses them after this change. For API rows, an item of kind `value` and the
`decide`/`CORRECT` harness of `tests/test_review_decide.py`, a user whose role may decide that item; the item's
observation unit is `USD million`. "Decision rows" means the rows `rows(run_store)` returns for the item.

Comparison rule pinned by the rows: `unit` and `period_end` are compared as `str(x).strip()`, case-sensitive, so
`usd million` differs from `USD million` and `2024-12-31T00:00:00` differs from `2024-12-31`; `None`, an empty or
whitespace-only string and an absent key are all "absent" and equal each other.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | first `{value: 5, unit: "USD million"}`, second `{value: 5, unit: "USD billion"}` | `agrees(first, second)` | `False` | holdout |
| AC-2 | first `{value: 5, period_end: "2024-12-31"}`, second `{value: 5, period_end: "2023-12-31"}` | `agrees(first, second)` | `False` | holdout |
| AC-3 | both `{value: 5, unit: "USD million", period_end: "2024-12-31"}` | `agrees(first, second)` | `True` | holdout |
| AC-4 | first `{value: 5}`, second `{value: 5.0}` | `agrees(first, second)` | `True` | holdout |
| AC-5 | first `{value: 5}`, second `{value: 5, unit: "USD million"}` | `agrees(first, second)` | `False` | holdout |
| AC-6 | first `{value: 5, unit: "USD million"}`, second `{value: 6, unit: "USD million"}` | `agrees(first, second)` | `False` | holdout |
| AC-7 | first `{value: 5, unit: "USD million"}`, second `{value: 5, unit: " USD million "}` | `agrees(first, second)` | `True` | holdout |
| AC-8 | first `{value: 5, unit: "usd million"}`, second `{value: 5, unit: "USD million"}` | `agrees(first, second)` | `False` | holdout |
| AC-9 | first `{value: 5, unit: None}`, second `{value: 5}` | `agrees(first, second)` | `True` | holdout |
| AC-10 | first `{value: 5, unit: ""}`, second `{value: 5}` | `agrees(first, second)` | `True` | holdout |
| AC-11 | first `{value: 5, period_end: " 2024-12-31 "}`, second `{value: 5, period_end: "2024-12-31"}` | `agrees(first, second)` | `True` | holdout |
| AC-12 | first `{"decision": "edit", "edited_value": {"value": 5, "unit": "a"}}`, second the same with `"unit": "b"` (legacy rows) | `agrees(first, second)` | `False` | holdout |
| AC-13 | stored first `correct` row `{value: 5, unit: "USD million"}`, stored second row `{value: 5, unit: "USD billion"}` | the review queue API returns the item | item `state == "disagreed"`; `effective` is `null` | holdout |
| AC-14 | stored first `correct` row `{value: 5, unit: "t"}`, then a second reviewer posts `{value: 5}` | the review queue API returns the item | item `state == "disagreed"`; `effective` is `null` | holdout |
| AC-15 | a `value` item, `corrected_value` `{value: 5, unit: "USD million"}` | `POST` the `correct` decision | status 422 | holdout |
| AC-16 | the AC-15 request | the response body is read | contains `corrected_value may only hold ['value']` | holdout |
| AC-17 | the AC-15 request | decision rows of the item are counted | count unchanged (0 before, 0 after) | holdout |
| AC-18 | a `value` item, `corrected_value` `{value: 5, period_end: "2023-12-31"}` | `POST` the `correct` decision | status 422 and body contains `corrected_value may only hold ['value']` | holdout |
| AC-19 | a `value` item, `corrected_value` `{value: 5, unit: None}` | `POST` the `correct` decision | status 422 (a present key is refused, whatever its value) | holdout |
| AC-20 | a `value` item, `corrected_value` `{value: 5, unit: "x", period_end: "2024-12-31"}` | `POST` the `correct` decision | status 422 and body contains `corrected_value may only hold ['value']` | holdout |
| AC-21 | a `restatement_candidate` item, `corrected_value` `{value: 5, unit: "USD million"}` | `POST` the `correct` decision | status 422 and body contains `corrected_value may only hold ['value']` | holdout |
| AC-22 | a `restatement_candidate` item, `corrected_value` `{value: 5, period_end: "2023-12-31"}` | `POST` the `correct` decision | status 422 and body contains `corrected_value may only hold ['value']` | holdout |
| AC-23 | a `value` item, `corrected_value` `{value: 5, foo: 1}` | `POST` the `correct` decision | status 422 | holdout |
| AC-24 | a `value` item, `corrected_value` `{value: 1234}` with the grounded citation of `test_grounded_correction_stored_with_server_offsets` | `POST` the `correct` decision | status 200 | holdout |
| AC-25 | the AC-24 request | decision rows of the item are read | exactly 1 row; its `corrected_value == {"value": 1234}` (the server's offsets live in `correction_citation`, not in `corrected_value`) | holdout |
| AC-26 | a stored decision row `{value: 5, unit: "USD billion"}` on a `value` item, with a field `{unit: "USD million", value: 1}` | `published_facts` is built for the run (`run_candidates`, `tests/test_publish_candidates.py` harness) | the published fact has `unit == "USD billion"` and value 5 | holdout |
| AC-27 | stored rows from AC-13 in a database with `company_facts` and `published_facts` rows | the code of this change is deployed and the item is read once | row counts and all column values of the decision rows, `company_facts` and `published_facts` are identical before and after | holdout |

Must not change (rows below): the other decision kinds; a decision accepted as is; other item kinds'
`correct` keys; the schema.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-28 | two `approve` rows | `agrees(first, second)` | `True` | holdout |
| AC-29 | an `approve` row and a `reject` row | `agrees(first, second)` | `False` | holdout |
| AC-30 | two `reject` rows; two `escalate` rows | `agrees` on each pair | `True` for both pairs | holdout |
| AC-31 | an `escalate` row and a `reject` row | `agrees(first, second)` | `False` | holdout |
| AC-32 | a `value` item, first reviewer `approve`, second reviewer `approve` | both decisions are posted | the item's `state == "second_done"` | holdout |
| AC-33 | the AC-32 item, applied to `company_facts` | the fact is read | `value` equals the observation's value, `status == "approved"`, and the unit read through `source_values._latest_facts` is `USD million` | holdout |
| AC-34 | a `value` item, first reviewer `correct` `{value: 5}`, second reviewer `correct` `{value: 5}` | both decisions are posted | the item's `state == "second_done"` | holdout |
| AC-35 | the AC-34 item, applied to `company_facts` and published | the fact and the published fact are read | both have value 5 and unit `USD million` (the observation's own) | holdout |
| AC-36 | an item of kind `sector_code`, `corrected_value` `{isic_code: "6201"}` | `POST` the `correct` decision | status 200 (other kinds keep their keys) | holdout |
| AC-37 | the diff of the implementing PR | `git diff --name-only origin/main` is run in CI | lists none of `backend/arp/db/models.py`, `backend/arp/storage/postgres_schema.py` | unit |

Checked by: `holdout` rows are deterministic tests in the private holdout repo (they import `agrees`, use the
decision endpoint and the run store directly; none needs the browser). AC-37 is a one-line diff check the
implementer adds to CI as `unit`: no row is checked in the browser, because the UI sends `value` only and is not
changed.
