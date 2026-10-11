# Fact Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The rules that turn a run's observations, review items, decisions and cosigns into item states and facts live in one module, `arp/db/observations.py` (the **Fact ledger**, see `GLOSSARY.md`). `company_view.trail` stops re-deriving them.

**Architecture:** A new link table, `review_item_observations`, is written when an item is queued. A value item links its one observation. A whole-record item links every REVIEW observation of its run and company. `apply_decision` and `trail` both read the links, so the whole-record rule exists once. `RunStore` keeps its public methods: each opens the transaction and lock and calls the ledger. The ledger takes a SQLAlchemy `Session` and has no port, because there is one adapter.

**Tech Stack:** Python 3, SQLAlchemy 2 (Postgres dialect), pytest with the `pg` / `run_store` fixtures (`ARP_TEST_POSTGRES_DSN` required).

**Spec:** candidate 1 in `docs/architecture-reviews/architecture-review-20261011-0405.html`, decisions Q1–Q10 from the grilling session (summarised below), and `docs/adr/0001-importer-keeps-own-rules-until-cutover.md`.

## Global Constraints

- `db/importer.py` is **not edited**. It calls `RunStore.record_company_result(..., apply_facts=False)`, `append_decision_row(..., apply_facts=False)`, `append_cosign(..., apply_facts=False)` and `RunStore._apply_review(s, run_id, item_key, decisions_upto=, cosigns_upto=, at=)`. All of these keep their signatures. It also imports `_DECIDED, _SKIP, _edited, _fits, _same, _status, decide` from `arp.db.observations`, and these keep their names.
- `RunStore._apply_review` becomes a one-line delegate carrying `# ponytail: delete with db/importer.py (ADR-0001)`.
- `observations.py` keeps its file name. Its module docstring opens with "Fact ledger:".
- Out of scope: verify's `_Replay` and the importer's `_unqueued` and `_apply_results` (ADR-0001), API readers that recompute item state through `review_queue.item_states` (candidate 5), and `to_observations` (candidate 2).
- `review_items.observation_id` stays. The link table is added alongside it.
- Deviation from Q7: Q9 makes `observations.py` the ledger, and `tests/db/test_observations.py` already tests it through `RunStore`. So that file **is** the ledger's test file, and new tests go there. No `test_fact_ledger.py`, no test moves.

## Review Focus

1. A re-queued item (`on_conflict_do_update` on `uq_review_items_key`) must not duplicate links or drop its existing link. Test in Task 1.
2. A company-level item that isn't a whole record (`isic:<id>` keys, where `item_key != payload["company_id"]`) gets **no** links and still changes no fact. Test in Task 1.
3. A whole-record item never links observations of another run or another company. Test in Task 1.
4. The importer path (`apply_facts=False`) still writes links, so imported decisions reach facts in the replay. Existing `tests/db/test_importer.py` must stay green (Task 2).
5. The backfill step is idempotent: running `ensure_schema` twice creates no duplicate links. Test in Task 1.

---

### Task 1: Link table, written at queue time, plus backfill

**Files:**
- Modify: `backend/arp/db/models.py`: add `ReviewItemObservation` after `ReviewItem` (~:460)
- Modify: `backend/arp/db/observations.py`: add `queue_item`
- Modify: `backend/arp/db/runs.py:208-232`: `_insert_review_item` delegates to `queue_item`
- Modify: `backend/arp/storage/postgres_schema.py`: new step appended to `SCHEMA_STEPS`
- Test: `backend/tests/db/test_observations.py`, `backend/tests/db/test_schema.py`

**Interfaces:**
- Produces: `ReviewItemObservation` (table `review_item_observations`, columns `review_item_id BIGINT FK review_items.id`, `observation_id BIGINT FK field_observations.id`, composite primary key on both).
- Produces: `observations.queue_item(session: Session, run_id: str, item_key: str, payload: dict, *, company_id, observation_id: int | None, queued_at) -> int`. It upserts the review item exactly as `_insert_review_item` does today (same `on_conflict_do_update` with the `coalesce` on `observation_id`), `RETURNING id`, then writes links with `ON CONFLICT DO NOTHING`. A value item (`observation_id` set after the upsert) gets that one link. A whole-record item (`observation_id IS NULL`, `company_id` not null and `item_key == payload["company_id"]`) gets one link per `FieldObservation` with the same `run_id` and `company_id` and `route == Route.REVIEW`. Any other item gets no links. It returns the item id.
- `RunStore._insert_review_item` keeps its signature. It still resolves `company` (UUID, subquery or universe lookup) and calls `_ensure_run`, then calls `queue_item`.

- [ ] **Step 1: Write the failing tests** in `tests/db/test_observations.py`:
  - `test_value_item_links_its_observation`: after `_financials`-style setup with one value item, `select(ReviewItemObservation)` returns exactly `[(item.id, item.observation_id)]`.
  - `test_whole_record_item_links_review_observations_of_its_run_and_company`: `_financials(run_store, pg, needs_review=True)` plus a second run `f2` for the same company and a second company in `f1`. The `f1`/acme item's links equal the ids of the `f1`/acme REVIEW observations (`capex_total`, `rnd_total`), and nothing from `f2` or the other company.
  - `test_requeue_keeps_links_without_duplicates`: queue the same key twice (the second time without `observation_id`, as `queue_for_review` does). The link count is unchanged.
  - `test_company_level_item_that_is_not_a_record_has_no_links`: an item keyed `isic:acme` gets zero links.
- [ ] **Step 2: Run** `pytest tests/db/test_observations.py -k "links or requeue_keeps_links or not_a_record" -v`. Expected: FAIL (`ReviewItemObservation` not defined).
- [ ] **Step 3: Add the model and `queue_item`, and point `_insert_review_item` at it.** `ensure_schema`'s `create_all` creates the table on existing databases.
- [ ] **Step 4: Run the same tests.** Expected: PASS.
- [ ] **Step 5: Write the failing backfill test** in `tests/db/test_schema.py`, `test_review_item_links_backfill_is_idempotent`. Queue a value item and a whole-record item, `DELETE FROM review_item_observations`, call `_review_item_links(conn)` twice, and assert the links equal what `queue_item` wrote.
- [ ] **Step 6: Add `_review_item_links(conn)`** and append `SchemaStep(name="review_item_links", description="review_item_observations backfilled: value items to their observation, whole-record items to their run and company's REVIEW observations", apply=_review_item_links)`. The step is two `INSERT … SELECT … ON CONFLICT DO NOTHING` statements with the same conditions as `queue_item`.
- [ ] **Step 7: Run** `pytest tests/db/test_schema.py tests/db/test_observations.py -v`. Expected: PASS.
- [ ] **Step 8: Commit** with `feat(db): review_item_observations links written at queue time, backfilled`.

### Task 2: `apply_decision` and `trail` read the links

**Files:**
- Modify: `backend/arp/db/observations.py:327-371` (`apply_decision`)
- Modify: `backend/arp/db/company_view.py:298-360` (`trail`, the `decisions` query)
- Test: `backend/tests/db/test_observations.py`

**Interfaces:**
- Consumes: `ReviewItemObservation` (Task 1).
- `apply_decision` keeps its signature. `whole_record` stays `item.observation_id is None`, because `_edited` needs it. The observation list becomes `FieldObservation` rows joined through `ReviewItemObservation` for `item.id`, ordered by `FieldObservation.id`. The `elif … item_key == payload["company_id"]` branch and the `else: return` are deleted, since no links means an empty list.
- In `trail`, `decisions` selects `ReviewDecision` joined to `ReviewItemObservation` on `review_item_id` where `ReviewItemObservation.observation_id == obs.id`, ordered as today. The `or_(…, and_(…))` whole-record SQL is deleted.

- [ ] **Step 1: Write the failing test** `test_whole_record_decision_follows_links`. After `_financials(..., needs_review=True)`, delete the link for `rnd_total` and approve `f1`/acme. `capex_total` is APPROVED and `rnd_total` stays PENDING_REVIEW. This proves `apply_decision` reads links, not the old rule.
- [ ] **Step 2: Run it.** Expected: FAIL (both approved).
- [ ] **Step 3: Change `apply_decision` and `trail` as described** and remove any import they no longer use.
- [ ] **Step 4: Run** `pytest tests/db -v`. Expected: all PASS, including `test_whole_record_review_resolves_its_facts`, `test_whole_record_edit_sets_only_named_fields`, `test_trail_shows_whole_record_decisions`, `test_trail_contains_citation_page_and_decision` and `test_importer.py`.
- [ ] **Step 5: Commit** with `refactor(db): apply_decision and trail read review_item_observations`.

### Task 3: Move the remaining ledger rules out of RunStore

**Files:**
- Modify: `backend/arp/db/observations.py`: module docstring and three functions
- Modify: `backend/arp/db/runs.py:234-389`
- Test: the existing suite only (this is a pure move)

**Interfaces:**
- Produces, in `observations.py`:
  - `record_result(session: Session, run_id: str, observations: list[ObservationIn], review_items: list[tuple[str, dict]], *, company: CompanyRef | None, apply_facts: bool = True) -> None`. This is today's `record_company_result` body from `observations_db.record(...)` through the review-item loop (`by_target` linking and held documents included), with each item going through `queue_item`. It needs `run_id`, so it receives the resolved entity via `company.entity_id`.
  - `queue_unqueued(session: Session, run_id: str, row: dict) -> None`, today's `RunStore._queue_unqueued`.
  - `apply_review(session: Session, run_id: str, item_key: str | None, *, decisions_upto: int | None = None, cosigns_upto: int | None = None, at: datetime | None = None) -> None`, today's `RunStore._apply_review` body.
- `RunStore` keeps `record_company_result`, `append_decision_row` and `append_cosign` with the same signatures. Each keeps its `_tx`, the run-row writes (`_insert_result`, `RunError`, `ReviewDecision` / `ReviewCosign` inserts) and calls the functions above. `_apply_review` becomes `return observations_db.apply_review(s, run_id, item_key, decisions_upto=decisions_upto, cosigns_upto=cosigns_upto, at=at)` with the ponytail comment from Global Constraints. `_queue_unqueued` is deleted.
- The module docstring becomes "Fact ledger: insert-only field observations with their citations, review items and their observation links, and the rules that turn decisions and cosigns into item states and current facts (spec §2.5, §2.7, §3.2). `decide` is the §2.7 rule table."

- [ ] **Step 1: Run** `pytest tests/db tests/test_review_decide.py tests/test_resume_run.py -q` and record the pass count as the baseline.
- [ ] **Step 2: Move the three bodies.** Keep the deferred imports in `apply_review` (`review_queue`, `review.items`), since they avoid an import cycle. Remove imports from `runs.py` that only the moved code used.
- [ ] **Step 3: Check for a cycle** with `python -c "import arp.db.runs, arp.db.importer"`. Expected: no error. `observations.py` must not import `arp.db.runs`.
- [ ] **Step 4: Run the Step 1 command again.** Expected: the same pass count, zero failures. Then run the whole `pytest -q` suite.
- [ ] **Step 5: Commit** with `refactor(db): fact ledger rules move from RunStore to observations`.
