# Accepted values are never overwritten (slice 7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a value is accepted (`auto_accepted`, `approved` or `edited`), a new run can no longer overwrite it:
- an identical value changes nothing;
- a different value is stored as an observation and raises one `conflict` review item;
- the reviewer either keeps the accepted value or accepts the new one.

**Architecture:**
- The rule lives in the ingestion path only: `record()` → `apply_observation()` → `_write_fact()` → `decide()` in `backend/arp/db/observations.py`. Review decisions keep today's path, so approving a conflict supersedes the old fact as it already does.
- A conflict item uses the same `item_key` as the value item for that company/field/period (`field_item_key`). A new value routed to review therefore makes one item, not two. Its payload carries `kind: "conflict"` and `accepted: {value, fact_id, citation}`. The new observation is linked through the existing `review_item_observations` table.
- The kind is derived from the payload in `review/items.py` `_queue_kind`, so there is no schema migration.
- The decision endpoint accepts the spec's bare `{"decision": "reject" | "approve"}` for conflict items (owner decision 2026-11-11).
- The frontend shows the conflict in step 5 and labels it in the Review Queue.

**Spec:** `docs/superpowers/specs/2026-10-24-argus-simplified-pipeline-design.md` ("The data rules", rule 1; "Calls made by the spec author" on conflicts; pinned interfaces 1 and 2; AC-45 to AC-52, AC-55).

## Owner decision (2026-11-11)
- **Bare decision body for conflicts.** For conflict items only, the decision endpoint fills in a missing `reason_code` (`confirmed` for approve, `wrong_value` for reject) and accepts a missing `context_etag`. Value items keep today's strict rules. The UI still sends the full body.

## Global Constraints

- **Accepted current fact, ingestion path:**

  | New value | Fact | Observation row | Review item |
  |---|---|---|---|
  | identical (`same_value`) | unchanged | none (AC-49) | none |
  | different, any route (auto-accept or review) | unchanged | new observation stored | exactly one `conflict` item (AC-45 to AC-48) |
  | the same different value after an earlier conflict on that fact was decided `reject` | unchanged | — | no new conflict item (AC-51) |
  | another different value | unchanged | — | a new conflict item |

  A pending or held current fact follows today's rules.
- **Trial runs** write no facts and raise no conflicts.
- **Deciding a conflict** goes through the existing endpoint and the second-review rules:
  - **`reject` (keep accepted):** the fact stays; the item closes with `reject`; the observation stays (AC-50).
  - **`approve` (accept new):** the old fact gets `valid_to`; the new value becomes the current fact with status `approved` (AC-52).
- **Correct/edit on a value item** still supersedes an auto-accepted fact. The rule applies to ingestion, not to decisions.
- **Run counts:** the run's review count includes conflict items created during the commit.
- **Importer replay** (`db/importer.py`) must stay consistent: it pairs stored observations by position. Either replay skips the same identical values `record()` skipped, or replay keeps today's semantics with the reason documented. The importer tests must pass, and every change to them is listed.
- **Exact UI copy:**
  - step 5 conflict row: `Accepted: <old>` and `New: <new>`, each with its source, and the buttons `Keep accepted` (reject) and `Accept new` (approve) (AC-55);
  - Review Queue kind label: `Conflict`.
- **Existing tests that pin today's overwrite change, and each change is listed in the PR:**
  - `test_fact_rules.py::test_different_accepted_value_supersedes` and the not-applicable assertion in `test_document_not_applicable_is_a_value`;
  - `db/test_observations.py::test_restated_value_supersedes_and_history_is_queryable`;
  - `db/test_company_api.py::test_trail_lists_every_version`;
  - `db/test_importer.py::test_import_replays_oldest_first`, if replay changes;
  - any other test found that relies on an overwrite.

  Each keeps a test of equal strength for the new rule. Nothing is just deleted.
- **Risk label:** `risk:high`. This changes how stored facts change, so the owner merges on GitHub.

## Review Focus

1. **Concurrency:** two runs committing different values for the same accepted fact at once must give one current fact. Each run gets its own conflict, or the two are merged into one; never an overwrite. The existing `_current()` `FOR UPDATE` lock covers the fact read, and the item insert must stay inside the same transaction.
2. **A conflict must not hide a routed-to-review value:** the new value's citations and review reasons reach the conflict item, so the reviewer sees why it was flagged.
3. **AC-51 lookup:** "same value after reject" is checked on the latest decided conflict for the same company, field, period and basis, using `same_value`. A different value raises a conflict again.
4. **Second review:** approving a conflict replaces an accepted value. Use the existing `published_change` second-review reason when the fact was published, and don't loosen it.
5. **Bare body:** only conflict items get defaults. A bare body on a value item still returns 422.

---

### Task 1: The ingestion rule in `decide()` and `record()`

**Files:** `backend/arp/db/observations.py`; Tests `backend/tests/test_fact_rules.py`, `backend/tests/db/test_observations.py`, `backend/tests/db/test_company_api.py` (changes listed)

- [ ] Test-first:
  - `decide` gains an ingestion-only `conflict` action;
  - AC-45, AC-46 and AC-47 for `approved`, `edited` and `auto_accepted` facts: value 12, then 14 auto-accept, gives fact 12, a new observation 14 and one conflict item;
  - AC-48: 14 routed to review gives exactly one item for that field, of kind conflict;
  - AC-49: 12 again stores no observation row and no item;
  - a trial run creates no conflict;
  - a pending or held current fact behaves as today.
- [ ] Implement, then commit.

### Task 2: Conflict items, the AC-51 memory and run counts

**Files:** `backend/arp/db/observations.py` (queue the conflict inside `record`), `backend/arp/db/runs.py` (`record_company_result` returns or counts the items it created), `backend/arp/orchestration/batch_runner.py` (`review_delta`), `backend/arp/review/items.py` (`_queue_kind` → `CONFLICT`), `backend/arp/schemas/review.py` (`ReviewItemKind.CONFLICT`), `backend/arp/review/context.py` (`_FIELD_KINDS`); Test `backend/tests/db/test_conflicts.py` (new)

- [ ] Test-first:
  - the payload carries `kind`, `accepted.value` and `accepted.fact_id`, and is linked to the new observation;
  - `GET /api/review/items` returns `kind: "conflict"`;
  - the run's review count includes the conflict;
  - AC-51: after a `reject`, another 14 raises nothing, while 15 raises a conflict.
- [ ] Implement, then commit.

### Task 3: Deciding a conflict

**Files:** `backend/arp/review/decide.py` (`ALLOWED`/`CORRECTED_KEYS` for `conflict`; bare-body defaults for conflict items only), the request model or router for the defaults; Test `backend/tests/db/test_conflicts.py`

- [ ] Test-first:
  - AC-50: bare `{"decision": "reject"}` keeps fact 12 `approved`, the item reads `reject`, and observation 14 stays;
  - AC-52: bare `{"decision": "approve"}` makes 14 the current fact `approved`, and the 12 row stays with `valid_to` set;
  - a bare body on a value item still returns 422;
  - a correct on an auto-accepted value item still supersedes the fact (existing test unchanged).
- [ ] Implement, then commit.

### Task 4: Importer replay

**Files:** `backend/arp/db/importer.py`; Test `backend/tests/db/test_importer.py`

- [ ] Make replay consistent with Task 1:
  - replay skips the identical rows `record()` skipped;
  - an accepted fact replayed against a later different value raises a conflict, not an overwrite, or the old behaviour is kept with the reason documented. Document the choice in the PR.
- [ ] Every importer test passes, and every change to them is listed. Then commit.

### Task 5: Conflicts in step 5 and the Review Queue

**Files:** `frontend/src/types.ts` (`ReviewItemKind` gets `"conflict"`), `lib/reviewKeys.ts` (label `Conflict`, `decisionChoices`), `lib/argusFlow.ts` (`resultRows`: conflict rows carry `accepted`), `pages/ArgusResults.tsx` (Accepted/New cells; `CONFLICT_LABELS` = Keep accepted / Accept new); Tests `frontend/tests/argusFlow.test.ts`, `reviewKeys.test.ts`; e2e `backend/tests/e2e/test_argus_steps45.py` (seeded conflict row, AC-55)

- [ ] Test-first:
  - a conflict item gives a row with `Accepted: 12` / `New: 14` and the two buttons, each with its source;
  - the Review Queue shows the kind label `Conflict`.
- [ ] Implement, then commit.

### Task 6: Checks and PR

- [ ] Checks:
  - backend ruff, plus every touched test file and every `db/`, `test_fact_rules`, `test_publish_facts`, `test_snapshots_build`, `test_score_lineage_api_pg`, `test_authoritative_store_pg` and `test_financials_extraction_pipeline` test, run alone;
  - the mutation check on the changed backend code: `python scripts/mutation_check.py --base origin/main`;
  - frontend lint, tsc and test;
  - e2e with and without a key;
  - light and dark screenshots of a conflict row in step 5.
- [ ] Commit, push, PR with `Spec: argus-simplified-pipeline` and `risk:high`, listing every test change. Then run the factory review and evaluator.
