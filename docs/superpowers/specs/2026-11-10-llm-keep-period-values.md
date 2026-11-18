# LLM keep period values: one bad citation must not delete a whole period

## Intent

When a model's structured answer fails validation, both LLM clients try to save it by dropping the bad
list item instead of asking the model again. The helper that does this, `_drop_invalid_list_items`
(`backend/arp/llm/langchain_client.py:57`, via `_droppable_list_indices` at line 44), keeps only
`loc[0]` and `loc[1]` of each pydantic error. An error at `('values', 0, 'citations', 1, 'quote')` therefore
removes `values[0]`, the whole most recent period, although only one citation is malformed. The only
guard is for `values.<i>.value`. The caller sees a normal-looking draft with the older period first, and
the only trace is one `logger.info`. The latest-year number becomes "not disclosed", or the older year
becomes `values[0]` and the verifier judges that year instead.

## Evidence (reproduced on `main` 674d099, no model call; `ExtractionDraft` plus the helper)

| Draft | Error locs | Helper returns |
|-------|-----------|----------------|
| `values[0]` (100) has citations [good, bad]; `values[1]` (90) has [good] | `values.0.citations.1.doc_type`, `values.0.citations.1.quote` | dropped 1; values = [90] |
| `values[0]` (100) has its only citation bad; `values[1]` (90) good | `values.0.citations.0.doc_type`, `...quote` | dropped 1; values = [90] |
| as the first row, inside a `GroupDraft` (`fields[0].draft.values[0]...`) | `fields.0.draft.values.0.citations.1.quote` | dropped 1; the whole field `a` (both periods) gone, only field `b` left |
| `values[1].value` is a list | `values.1.value.str` (and `.float`, `.bool`) | `(None, 0)`: retried (guard works) |

## Callers and affected models (grep)

- The helper has two production callers: `LangChainAnthropicClient.complete_structured`
  (`langchain_client.py:265`) and `GeminiClient.complete_structured` (`gemini_client.py:98`, which imports
  it from `langchain_client`). `batching_client.py` does not use it. One direct test call exists:
  `tests/test_langchain_client_retry.py:390` (`test_tnfd_metric_with_bad_value_is_still_dropped`).
- Output models with a list of items that themselves hold `list[Citation]`: `ExtractionDraft.values[]`
  (`extractor_agent.py:58-72`, also reached through `GroupDraft.fields[].draft`), the TNFD drafts
  (`tnfd_extractor_agent.py:152-202`: `core_global_metrics`, sector metrics, LEAP considerations, general
  requirements, disclosures), `SpendSectionDraft`/`FinancialsExtractionDraft`, the spend and segment
  extractors. A top-level `citations` list (`VerifierOutput`, `AdjudicatorOutput`) is a list of citations
  at depth 1: dropping the bad one is already the right behaviour and does not change.
- Downstream of a period value with no citations: `aggregator.py:157` sets `all_grounded = False` when
  there is a value and no final citation, which adds `ReasonCode.NOT_GROUNDED` (review) and the note "No
  grounded citation supports this value." So an uncited kept period is flagged for review today, without
  any change in `arp/extraction`.
- `LLMUsage` (`arp/llm/base.py:10`) is not part of an API response model or the frontend types
  (grep of `arp/api` and `frontend/src`: no hits), so a new field does not touch the API contract.
  It is stored in the disk cache next to the result, so the count survives a cache hit.

## Goals

- A validation error inside a citation of a list item removes that one citation, not the item.
- If every citation of an item is bad, the item keeps its value with `citations == []`.
- The number of dropped list elements is visible on the returned `LLMUsage` and in a warning log.
- The same behaviour in both clients.

## Non-goals

- Refactoring the retry loop that is duplicated between `langchain_client.py` and `gemini_client.py`.
  Follow-up only: both loops, the helper and the fix should eventually live in one place.
- New review reasons or any change in `arp/extraction`, `arp/api`, `frontend/`, `.claude/`, `.github/`.
- Changing what happens to an error at the top level of a list item (item dropped, as today) or to a bad
  `values.<i>.value` (retried, as today). The one deliberate exception is a non-citation, non-`value`
  sub-field error under a `values` item, which is now retried (AC-10).
- Repairing a malformed citation (for example guessing a missing `doc_type`).

## Anti-goals

- A period value that has a good `value` must never disappear because of a malformed citation.
- Nothing may be dropped without being counted on `LLMUsage` and logged at warning level, top-level
  items included (AC-4, AC-12).

## Approaches

1. **Drop the bad nested citation, keep the item (chosen, owner decision).** No extra model call; the
   existing `NOT_GROUNDED` path flags an item left with no citations.
2. **Retry the whole call on any nested error.** Safest for data but costs a call each time and can fail
   again on the same citation. Rejected by the owner.
3. **Drop the item and record "not disclosed" with a review flag.** Still loses the number and needs a
   review reason in `arp/extraction`. Rejected by the owner.

## Decided (owner answers, 2026-11-10)

1. A nested error inside a citation: drop only that citation element, keep the item.
2. Every citation of an item bad: keep the item with `citations == []`.
3. Visibility: one `logger.warning` (was `info`) per `complete_structured` call that dropped anything,
   whose message names the output model and lists every dropped path (for example `values.0.citations.1`),
   plus a new `LLMUsage` field `dropped_items: int = 0`: the number of list elements removed by the
   recovery of the answer that is finally accepted (a discarded attempt counts nothing). Only the removed element counts: a top-level item that is dropped counts 1 whatever its
   citations held, and a citation inside a kept item counts 1. No new review reason; the flag is the
   existing `NOT_GROUNDED`.

Rule the builder implements, from the error `loc` (a tuple of names and list indexes):

- Error path contains `'values', <int>, 'value'` at any depth: retried (unchanged, extended to nested
  drafts such as `GroupDraft`).
- Error path passes through a list whose field name ends in `citations`, then an index: drop that one
  citation. Several errors in the same citation count once.
- Error at a list item itself or at one of its other sub-fields, outside any citations list: dropped as the
  top-level item, as today, **except** under a `values` item (`values.<i>.<field>`, field not `citations`
  and not `value`), which is retried: that is the same silent loss of a period, for example a wrongly typed
  `period_text`. This is the one deliberate behaviour change beyond citations (AC-10, AC-17).
- An error on a `citations` list itself, with no index (for example citations given as a string): retried.
- An error at a `values` item itself (`values.<i>`, no sub-field, for example the item is a number): the
  item is dropped, as today.
- Any error that cannot be placed in these rules, or a draft that still fails after the drops: retried,
  as today.

Risk and CI: the implementing PR is `risk:normal`. It touches `arp/llm`, so the **golden-set check runs
in CI**; it needs the `ARP_ANTHROPIC_API_KEY` repo secret and without it the check warns and passes. No
real model is called by the new tests: they use the existing fake clients
(`tests/test_langchain_client_retry.py` fakes, `tests/test_gemini_and_modes.py` fake). The implementing
PR edits no existing test; the new tests are added beside them.

## Left to the builder

Where the walk over `loc` lives (one helper used by both clients is expected, it exists already), the rest
of the log wording beyond what AC-10 fixes, test names. `dropped_items` is stored in the disk cache as part of `usage` (it is not excluded
the way `cached` is).

## Follow-ups (not in this change)

- One shared retry loop for both clients.
- TNFD, spend and segment items with a bad non-citation sub-field are still dropped whole (as today);
  decide separately whether those should retry too.

## Acceptance

Fixtures: `ExtractionDraft` for the revenue field type (`draft_model_for`); a good citation
`{"doc_id":"d","doc_type":"10-K","quote":"q"}`, a bad citation `{"doc_id":"d"}` (no `doc_type`, no
`quote`), the same `Citation` shape in the TNFD and `VerifierOutput` rows; period A `value` 100 and period B
`value` 90, `confidence` 0.5. Unless a row says "second answer", the model answers once. "Valid answer" in a
retry row means A (100) and B (90) with one good citation each. Every row calls `complete_structured` on the
fake Anthropic client (`LangChainAnthropicClient`) unless it says Gemini (the fake Gemini client, JSON text).
"Calls" and "model requests" mean requests the fake received. "WARNING record" means a record at level
WARNING on logger `arp.llm.langchain_client`, which both clients log to (`gemini_client.py` imports that
logger); INFO records are ignored.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | draft: A has citations [good, bad], B has [good] | the answer is validated | 1 call; `usage.attempts == 1`; `usage.dropped_items == 1`; values `[100, 90]` in that order; A has 1 citation (the good one); B has 1 | unit |
| AC-2 | draft: A has citations [bad], B has [good] | the answer is validated | 1 call; `usage.dropped_items == 1`; values `[100, 90]`; A has `citations == []`; B has 1 | unit |
| AC-3 | draft: A has [bad, bad], B has [good] | the answer is validated | 1 call; `usage.dropped_items == 2`; values `[100, 90]`; A has `citations == []`; B has 1 | unit |
| AC-4 | draft: `values` is [A with [good], the number `5`] (error at `values.1`) | the answer is validated | 1 call; `usage.attempts == 1`; `usage.dropped_items == 1`; values `[100]` with 1 citation; exactly one WARNING record whose message contains `values.1` | unit |
| AC-5 | first answer: B's `value` is the list `[1]`; second answer: valid answer | the answer is validated | 2 calls; `usage.attempts == 2`; `usage.dropped_items == 0`; values `[100, 90]` | unit |
| AC-6 | the AC-1 draft wrapped in a `GroupDraft`: field `a` = A and B as in AC-1, field `b` = one period (value 1) with [good] | the answer is validated | 1 call; `usage.dropped_items == 1`; field `a` values `[100, 90]` and A has 1 citation | unit |
| AC-7 | the AC-6 draft (same `GroupDraft`) | the answer is validated | field `b` values `[1]` with 1 citation (field `b` is untouched) | unit |
| AC-8 | the AC-1 draft answered by the fake Gemini client | the answer is validated | 1 model request; `usage.attempts == 1`; `usage.dropped_items == 1`; values `[100, 90]`; A has 1 citation | unit |
| AC-9 | the AC-2 draft answered by the fake Gemini client | the answer is validated | 1 model request; `usage.dropped_items == 1`; values `[100, 90]`; A has `citations == []` | unit |
| AC-10 | first answer: A's `period_text` is the list `["x"]` (error at `values.0.period_text`); second answer: valid answer | the answer is validated | 2 calls; `usage.attempts == 2`; `usage.dropped_items == 0`; values `[100, 90]` | unit |
| AC-11 | the AC-1 draft | the answer is validated | exactly one WARNING record; its message contains `ExtractionDraft` and `values.0.citations.1` | unit |
| AC-12 | `_TargetWithItems` answer `{"value":1,"items":[{"kind":"a"},{"not_kind":"b"}]}` (fixture of the existing test) | the answer is validated | 1 call; items `["a"]`; `usage.dropped_items == 1`; exactly one WARNING record whose message contains `items.1` | unit |
| AC-13 | `TNFDExtractionDraft` answer `{"core_global_metrics":[{"value":"Not disclosed"}],"confidence":0.5}` (error at `core_global_metrics.0.<field>`) | the answer is validated | 1 call; `core_global_metrics == []`; `usage.dropped_items == 1` | unit |
| AC-14 | a fully valid draft (A and B with [good]) | the answer is validated | 1 call; `usage.dropped_items == 0`; no WARNING record | unit |
| AC-15 | the AC-1 draft, `cache_enabled=True`, called twice | the second call runs | 1 call in total; the second result has `usage.cached is True` and `usage.dropped_items == 1` | unit |
| AC-16 | the same, called twice | the second call runs | no WARNING record is logged by the second call | unit |
| AC-17 | first answer: A's `citations` is the string `"x"` (error at `values.0.citations`); second answer: valid answer | the answer is validated | 2 calls; `usage.attempts == 2`; `usage.dropped_items == 0`; values `[100, 90]` | unit |
| AC-18 | first answer: A has [good, bad] and B's `value` is the list `[1]`; second answer: A has [good, good], B has [good] | the answer is validated | 2 calls; `usage.attempts == 2`; `usage.dropped_items == 0`; A has 2 citations (the second answer's); no WARNING record | unit |
| AC-19 | `TNFDExtractionDraft` answer: `core_global_metrics` [{category "c", metric_kind "k", metric_name "n", value 5.0, citations [good, bad]}], `confidence` 0.5 | the answer is validated | 1 call; `usage.dropped_items == 1`; 1 metric with value 5.0 and 1 citation | unit |
| AC-20 | `VerifierOutput` answer: `agrees` true, `confidence` 0.5, `notes` "n", `citations` [good, bad] | the answer is validated | 1 call; `usage.dropped_items == 1`; 1 citation left (the good one) | unit |
| AC-21 | `AdjudicatorOutput` answer with `citations` [good, bad] and its other required fields valid | the answer is validated | 1 call; `usage.dropped_items == 1`; 1 citation left (the good one) | unit |
| AC-22 | the AC-5 first answer (B's `value` a list) then a valid answer, answered by the fake Gemini client | the answer is validated | 2 model requests; `usage.attempts == 2`; `usage.dropped_items == 0`; values `[100, 90]` | unit |
| AC-23 | the AC-10 answers, by the fake Gemini client | the answer is validated | 2 model requests; `usage.attempts == 2`; `usage.dropped_items == 0` | unit |

Checked by: every row is `unit`. No row is `holdout` or `evaluator`: the app stack started by
`e2e_stack.sh up` never calls a model, so it cannot reach these clients, and the tests use the fake clients.
The golden-set CI check covers real-model behaviour only as a regression guard and has no row.

Must not change: a bad item at the top level of a list is dropped and counted (AC-4, AC-12, AC-13); a bad
citation in a top-level `citations` list is dropped (AC-20, AC-21); a wrongly typed `value` is retried,
never turned into "not disclosed" (AC-5, AC-22); a valid draft passes through untouched (AC-14).

Changes deliberately, beyond the nested-citation fix: a bad non-citation sub-field of a `values` item
(for example `period_text`) used to drop the period silently and is now retried (AC-10, AC-23), as is a
bad `citations` list that is not a list (AC-17). Existing tests are not edited: AC-12 and AC-13 reuse the
fixtures of existing tests, which stay as they are, and new tests assert the count and the warning.
