# Transition Barrier Rule Book — Phase 2 (Engine and Ratification) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive H/M/L ratings from the rule book and analyst-entered facts, send every result through the existing review screens (a rating change needs two people), and make every reader of barrier ratings see the ratified ones.

**Architecture:** A pure evaluator (`transition_barrier/engine.py`) turns a criterion's rules and the counted values for one cell into a result with three-valued outcomes and the spec's detail sentences. Analyst facts, uploaded documents and choices are stored append-only in three new Postgres tables (`transition_barrier/store.py`). A `transition_barrier_derivation` run stores one result per cell (`run_results`) and queues one review item (`review_items`) of a new item kind, `barrier_cell`, decided through the existing `review/decide.py`, which gains the barrier rules. Current ratings are computed at read time: the bundled hand rating, overlaid by each cell's latest ratified result read from Postgres. Nothing is cached, so a new approval is visible without a restart.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy (Postgres), pypdf, Typer, pytest; React/TS (hash routes, `request<T>()`), Node test runner; Playwright for the screenshot.

**Spec:** `docs/superpowers/specs/2026-10-17-transition-barrier-rule-book-design.md` (approved 2026-10-18). Read sections 3 (analyst facts, several values, choices, dates, confidence), 4, 5, 6 and 7, and the Fixtures part of Acceptance, before starting. Acceptance strings are quoted from there; each test asserts the exact string in its AC row.

## Global Constraints

- **Phase 2 acceptance rows:**
  - AC-1 to AC-8, AC-10 to AC-13, AC-15, AC-16, AC-18, AC-19, AC-21 to AC-24, AC-35, AC-143, AC-146, AC-147, AC-150 to AC-152, AC-154 (engine);
  - AC-36 to AC-53, AC-139, AC-145 (several values, confidence, analyst facts, choices);
  - AC-54 to AC-73, AC-140, AC-141 (review and ratification);
  - AC-96, AC-97, AC-115;
  - the `basis`, `ratified_by` and `flags` parts of AC-130 and AC-131, plus AC-130 to AC-136 and AC-155 still passing;
  - evaluator rows AC-124 to AC-129.
- **Exact strings, copied from the spec:**
  - HTTP 403 `a rating change is confirmed by an approver`
  - HTTP 409 `you entered a fact this result uses`
  - bulk-accept reasons `a rating change is not bulk-accepted` and `you entered a fact this result uses`
  - HTTP 422 `News cannot ground a fact.`, `Quote not found in the uploaded document.`, `Number not in quote.`, `An uploaded document needs a title, publisher, as-of date and tier.` and `A reason is required.`
  - flags `Not re-derived: missing <labels>`, `Not re-derived: open threshold <labels>` (labels joined with `, `) and `Rules changed since this rating (v<n>)`
  - note `Sources not fetched: refresh is disabled`
  - the marker `not machine-checked`
- **Numbers display** through `render.fmt_number` (at most two decimals, half up, trailing zeros dropped). Booleans show as `Yes` / `No`.
- **One clock:** every run date, age and interval comes from `transition_barrier.clock.today()`. Tests freeze it at 2026-10-20; the CLI's `--now` sets it.
- **The model:** the engine never calls it. Phase 2 makes no model, fetch or search call anywhere.
- **The bundled files** under `backend/arp/transition_barrier/data/` and fixture F are never written at run time (AC-71).
- **Test users** are `Principal(user_id=<name>, name=<name>, role=...)` for `a.analyst` and `b.analyst` (analyst) and `a.approver` and `b.approver` (approver). Tests act as one by overriding `current_user`, as `tests/test_review_decide.py:70` does. `ratified_by`, `by` and "entered by" show `user_id`.
- **API contract:** after a request or response model change, run `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`. Fix `npx tsc -b`, commit both generated files, and add a `frontend/src/api/contract.ts` line for each new `request<T>()` against an endpoint with a response model.
- **Checks before each commit:**
  - run `bash .claude/hooks/ensure-deps.sh backend` (and `postgres`) first;
  - backend: `cd backend && ruff check . && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python3 -m pytest tests/<file>`;
  - frontend: `cd frontend && npm run lint && npx tsc -b && npm test`.
- **PR:** the body says `Spec: transition-barrier-rule-book-design`, carries `risk:normal`, and lists every test change. Never delete or weaken an existing test.

## Rulings (where the spec leaves a choice or two rows meet)

1. **Item kind.** Barrier results are queued with a new `ReviewItemKind.barrier_cell`. Today `_queue_kind` maps unknown run types to `other`, and `decide()` refuses `other` outside extraction. The payload's `kind` (`changed`, `unchanged`, `not_rated`, `conflict`) is the spec's item kind.
2. **Bulk accept.**
   - For `transition_barrier_derivation` runs, bulk accept refuses per item and accepts the rest (spec section 5, AC-66). Extraction stays all-or-nothing (AC-134).
   - The response gains `refused: [{item_key, reason}]`, which is empty for extraction.
   - Barrier items skip the `failed_checks` and etag checks that only mean something for value items.
3. **`POST /derive` runs the derivation before it responds.** Phase 2 derivation is pure code and database work, so a test or the evaluator sees a finished run. Phase 3, which adds extraction, moves it to the job launcher.
4. **`GET /cells/{code}/{region}`** returns the current cell's `BarrierScore` fields (`rating`, `confidence`, `evidence`, `source`, `last_verified`), plus `basis`, `ratified_by`, `flags`, `latest_result` and `history`. AC-73 reads the current rating's detail from `evidence`.
5. **Units.** An analyst fact's unit must be the fact's unit; otherwise HTTP 422 `Unit not convertible: <unit>`, the wording phase 3 uses. Conversions arrive with extraction in phase 3.
6. **Division by zero.** A computed fact whose denominator is 0 is not counted, with reason `Division by zero`, so its conditions are `unknown`.
7. **Combination cap.** More than 1,000 value combinations gives `conflict`, with note `Too many value combinations (<n>)`.
8. **Uploads are PDF only.** Anything else gets HTTP 422 `Upload a PDF document.`, and a file above `max_upload_bytes` gets HTTP 413. The quote check runs `ground_citations` (exact, normalised, fuzzy at `grounding_fuzzy_threshold`) on the pypdf text of every page. The stored page is the page where the quote was found (spec section 3).
9. **Current ratings are read per request** from Postgres. With no `ARP_POSTGRES_DSN` they fall back to the bundled ratings. `load_scores()` keeps returning the bundled file. A new `current_scores()` is what readers use.
10. **Value ids.** Each `values[]` entry also carries `id`, the stored fact id, so `POST .../choices` can name the value chosen.
11. **Stale items.** Older pending items for a cell stay open. If one is approved later, its result becomes current only if its final decision is the latest one, because the current rating is the latest ratified result by decision time.

## Review Focus

1. A scanned PDF with no text layer must give HTTP 422 `Quote not found in the uploaded document.`, not a 500. Test in Task 3.
2. An unknown code, or a region that isn't European Union, United States or China, in `/cells/...`, `/facts`, `/choices` or `/derive` must give HTTP 404 `Unknown cell <code> / <region>`, not a KeyError. The URL-encoded `European%20Union` path must work. Test in Task 5.
3. Re-entering the same fact from the same source (same upload title and publisher) must replace the earlier value, never count both and turn into a conflict with itself. Test in Task 3.
4. With no Postgres configured (CLI export, scripts), `current_scores()` must return the 105 bundled ratings, not raise. Test in Task 7.
5. An older pending item approved after a newer result was ratified must not roll the cell back (Ruling 11). Test in Task 6.

---

## File Structure

**Create:**
- `backend/arp/transition_barrier/clock.py`: `today()`.
- `backend/arp/transition_barrier/engine.py`: `Value`, `Result`, `derive`, `fact_confidence`, and the detail sentences.
- `backend/arp/transition_barrier/store.py`: documents, analyst facts, choices, and `cell_values`.
- `backend/arp/transition_barrier/facts.py`: the analyst-fact checks and PDF page text.
- `backend/arp/transition_barrier/derivation.py`: the run type, create and execute.
- `backend/arp/transition_barrier/ratings.py`: current cells, flags and history.
- `frontend/src/pages/BarrierCellDetail.tsx`: cell detail, analyst fact form and conflict choice.
- `backend/tests/transition_barrier_helpers.py`: fixture F copy, users, `client_as`, `fixture_pdf`, `enter_fact`, `derive`.
- `backend/tests/fixtures/transition_barrier/D1.pdf`, `D2.pdf`, `D3.pdf`.
- Tests: `backend/tests/test_tb_engine.py`, `test_tb_facts.py`, `test_tb_review.py`, `test_tb_derivation.py`, `test_tb_ratings.py`, `test_tb_consumers.py`.

**Modify:**
- `backend/arp/db/models.py`: the three tables.
- `backend/arp/schemas/review.py`: `ReviewItemKind.barrier_cell`.
- `backend/arp/review/items.py`: `REVIEWABLE_RUN_TYPES` and `_queue_kind`.
- `backend/arp/review/decide.py`: the barrier rules and per-item bulk refusals.
- `backend/arp/schemas/transition_barrier.py`: `BarrierScore.basis`, `ratified_by` and `flags`.
- `backend/arp/transition_barrier/dataset.py`: `current_scores()`; `filter_scores` and `build_matrix` read it.
- `backend/arp/api/routers/transition_barrier.py`: the new routes.
- `backend/arp/cli/transition_barrier.py`: `derive`; `export` reads current scores.
- `backend/arp/decision/sources.py:412`: reads `current_scores`.
- Frontend:
  - `frontend/src/types.ts`: the reviewable kind and the barrier types;
  - the five reviewable lists named in Task 8;
  - `frontend/src/components/RunReviewList.tsx`: payload fields and the bulk accept button;
  - `frontend/src/pages/TransitionBarrierAssessment.tsx`: the criterion page fields, and a cell click opens the cell detail;
  - `frontend/src/api/client.ts` and `frontend/src/api/contract.ts`.

---

### Task 1: Engine — three-valued evaluation and ratings

**Files:** Create `backend/arp/transition_barrier/clock.py` and `backend/arp/transition_barrier/engine.py`. Test: `backend/tests/test_tb_engine.py`.

**Interfaces:**
- Consumes: `CriterionRules`, `FactDef` and `ParamDef` from `rule_book.py`. The condition shape is `{"all"|"any": [...]}`, with leaves `{"fact", "op", "value"|"param"|"other_fact"}`.
- Produces:
  - `clock.today() -> date` (tests monkeypatch it).
  - `@dataclass(frozen=True) Value(id: str, fact: str, value: float|bool|str|date, unit: str|None, document: str|None, page: int|None, locator: str|None, confidence: Literal["high","medium","low"], machine_checked: bool, entered_by: str|None = None, counted: bool = True, reason: str|None = None)`. `document` is the cited title: the uploaded document's title, or the registered source's `source_name`.
  - `fact_confidence(tier: str|None, as_of: date|None, max_age_days: int|None, today: date, has_document: bool) -> str`. It is `low` without a document; `high` for a `primary` tier with `today - as_of <= max_age_days` (or no limit); `medium` otherwise.
  - `derive(rules: CriterionRules, region: str, values: list[Value], *, rule_book_version: int, run_id: str, snapshot: dict, notes: list[str] = []) -> Result`.
  - `Result` (pydantic): `run_id`, `rating` (`H`, `M`, `L`, `not_rated` or `conflict`), `confidence`, `missing_facts: list[str]` (labels), `open_params: list[str]` (labels), `notes`, `rule_book_version`, `snapshot`, `levels: dict[str, LevelResult]`, `values: list[dict]`. Task 2 fills `detail`, `text`, `clause` and the `values` entries.

- [ ] **Step 1: Write failing tests.** Load RB from fixture F and build its variants RB2–RB10 in a helper `rb_variant(n) -> CriterionRules`, by editing the loaded dict exactly as the Fixtures section says. Build `Value`s with the default citations. One test per row, asserting the rating, the level outcomes, `missing_facts` and `confidence` exactly as written:
  - `test_ac1` to `test_ac6`, `test_ac12`, `test_ac13`, `test_ac15`, `test_ac16`;
  - `test_ac18_result` (rating `not_rated`, `open_params == ["High price level"]`) and `test_ac19_result`;
  - `test_ac22`, `test_ac23` (the `ratio` value 0.75 has confidence `medium`), `test_ac150`, `test_ac151`, `test_ac152`, `test_ac154`;
  - `test_ac36_conflict`, `test_ac38_rating`, `test_ac39`, `test_ac40_rating`, `test_ac41`, `test_ac42`, `test_ac45_result`;
  - `test_ac43_ac44_fact_confidence`: 2025-09-01 gives `medium`, 2025-10-20 gives `high`, with `max_age_days` 365 and today 2026-10-20;
  - `test_division_by_zero`: RB2 with `fos` = 0 gives `not_rated`, and the `ratio` value has `counted` False and reason `Division by zero`;
  - `test_combination_cap`: 11 values each for `price`, `applies` and `levy` (1,331 combinations) give `conflict` with note `Too many value combinations (1331)`.
- [ ] **Step 2:** Run `pytest tests/test_tb_engine.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement the engine** following the spec's section 4 table.
  - A leaf is `unknown` when its fact (or other fact) has no counted value, or its param is open. A param's value uses `by_region[region]` when present, the same lookup `render._param_text` uses.
  - Computed facts (`ratio`, `ratio_pct`, `difference`) are evaluated first from their inputs. Their confidence is the lowest of the inputs'.
  - With several counted values, use `itertools.product` over the facts that have values. Then:
    - every combination gives the same rating: that rating stands;
    - otherwise, any `not_rated` combination: `not_rated`, with the union of missing labels;
    - otherwise: `conflict`.
  - `missing_facts` and `open_params` come from the unknown leaves of the level that made the rating unknown (H when H is unknown; M when H fails and M is unknown), in rule-book fact order, without duplicates.
  - Result `confidence` is the lowest over every counted value of every fact.
  - `levels[L].outcome` is the outcome every combination shares, else `mixed`.
- [ ] **Step 4:** Run `pytest tests/test_tb_engine.py -q`. Expected: all pass.
- [ ] **Step 5:** Commit `feat(barrier): rules engine with three-valued logic`.

### Task 2: Engine — rendered conditions, clauses and details

**Files:** Modify `engine.py`. Test: `test_tb_engine.py`.

**Interfaces:**
- Produces:
  - each `levels[L]` = `{outcome, detail, conditions: [{text, outcome, clause}]}`;
  - each `values[]` entry = `{id, fact, value, unit, shown, extracted, document, page, locator, confidence, machine_checked, counted, reason}`. A computed fact gets one entry with `document` and `page` null. `extracted` equals `shown` in phase 2.
  - `engine.cell_evidence(result) -> str`: the `H` detail, then a space and the `M` detail when `H` failed.
  - `engine.cell_source(result, rules) -> str`: distinct cited titles in fact order, joined with `; `.
- [ ] **Step 1: Write failing tests** that assert the exact strings of AC-7, AC-8, AC-21, AC-24, AC-35 (`72.01 USD/tCO2`), AC-38's clause, AC-40's `mixed` clause, AC-143's prefix, AC-146's prefix `LCOE ratio = 75% from`, and AC-147's prefix `LCOE ratio = -15 USD/MWh from`.
  - `test_ac10`: `rule_book_version` 7, `run_id` as passed, and `snapshot` equal to `raw["criteria"]["STL-R1"]`.
  - `test_ac45_clause`: the `applies` clause cites `(EU ETS Market Report 2026, entered by a.analyst)`, and the value has `machine_checked` False.
  - `test_ac59_evidence`: `cell_evidence` gives AC-59's exact string.
  - `test_ac58_source`: `cell_source` gives `EU ETS Market Report 2026; CBAM Regulation 2023/956`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `text` is `render.render_group(leaf_as_group, rules, region)`.
  - The level sentence is `render_group(levels[L], rules, region)`.
  - Clause formats are the spec's section 4 "Detail sentences", word for word.
  - Nested groups contribute their leaves' clauses in order.
  - A `%` unit attaches without a space (`75%`); other units follow a space.
- [ ] **Step 4:** Run. Expected: all pass.
- [ ] **Step 5:** Commit `feat(barrier): detail sentences for derived results`.

### Task 3: Storage, analyst facts, documents and choices

**Files:** Modify `backend/arp/db/models.py`. Create `store.py`, `facts.py`, `backend/tests/transition_barrier_helpers.py` and D1–D3 PDFs in F. Modify `routers/transition_barrier.py`. Test: `test_tb_facts.py`.

**Interfaces:**
- Consumes: `Value` and `fact_confidence` (Task 1); `ground_citations` (`arp/grounding.py:260`); the number-in-quote check `review/decide.py` uses for `corrected number not in the cited text` (`decide.py:95-102`). Move it into `arp/grounding.py` as `number_in_quote(number: float, quote: str) -> bool` and call it from both places.
- Produces:
  - **Tables** (append-only, created by `Base.metadata.create_all`):
    - `barrier_documents(id, title, publisher, as_of date, tier, filename, content_key, page_texts JSONB, uploaded_by, uploaded_at)`;
    - `barrier_facts(id, code, region, fact, value JSONB, unit, quote, page, locator, source_key NULL, document_id NULL, entered_by, entered_at, machine_checked)`;
    - `barrier_choices(id, code, region, fact, fact_id, reason, value_ids JSONB, chosen_by, chosen_at)`.
  - `facts.pdf_pages(data: bytes) -> list[str]`: pypdf text per page.
  - `facts.FactRefused(status: int, message: str)`.
  - `facts.check_fact(fact_def, *, value, unit, quote, page, upload: UploadMeta|None, pdf: bytes|None) -> CheckedFact` with `page`, `machine_checked` and the parsed `value`. The checks run in the spec's order: required upload fields, then tier, then unit (Ruling 5), then number in quote, then quote in the document.
  - `store.add_document(...) -> int`, `store.add_fact(...) -> int`, `store.add_choice(...) -> int`, `store.cell_facts(code, region) -> list[row]`, `store.cell_choices(code, region) -> list[row]`, and `store.document(id) -> (row, bytes)`.
  - `store.cell_values(code, region, rules, registry, today) -> list[Value]`:
    - A later fact for the same fact and same source replaces the earlier one. Uploads are the same source when title and publisher match; a registered source is the same source as itself.
    - A choice keeps only its chosen value while that fact's value ids are a subset of `value_ids`.
    - Order: registered-source values in registry order then page, then uploaded-document values in entry order then page.
  - **Routes:**
    - `POST /api/transition-barrier/cells/{code}/{region}/facts` (multipart: `fact`, `value`, `unit`, `quote`, `page`, `locator`, `source_key`, `file`, `title`, `publisher`, `as_of`, `tier`) returns 201 `{id, page, machine_checked}`.
    - `POST /cells/{code}/{region}/choices` (JSON `{fact, value_id, reason}`) returns 201 `{id}`.
    - `GET /documents/{id}` returns the PDF inline.
  - **Helpers:**
    - `fixture_pdf(doc: str) -> bytes`: builds D1, D2 or D3 with reportlab, one quote per stated page from the quotes table, other pages blank.
    - `enter_fact(client, fact, value, doc, page, *, as_user=B_APPROVER, ...)` uploads `fixture_pdf(doc)` with the documents-table title, as-of and tier, and publisher `Fixture`.
- [ ] **Step 1: Write failing tests.**
  - `test_ac46`, `test_ac47`, `test_ac48`, `test_ac145`, each the exact 422 from its row.
  - `test_ac49`: the stored fact gives a `Value` with confidence `high`.
  - `test_ac50_empty_reason`.
  - `test_unit_refused` (Ruling 5); `test_pdf_only` and `test_too_large` (Ruling 8).
  - `test_scanned_pdf_gives_quote_not_found` (Review Focus 1, a PDF with an image-only page).
  - `test_same_source_replaces` (Review Focus 3): two `price` facts from D1 give one `Value`, the later one.
  - `test_choice_holds_until_new_value` (the store half of AC-53 and AC-139).
  - `test_value_order`: D1 values before D3 values.
  - `test_committed_pdfs_have_their_quotes`: `pdf_pages` of each committed D1–D3 has every quote on its stated page.
- [ ] **Step 2:** Run `pytest tests/test_tb_facts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Write D1–D3 into F once from `fixture_pdf`.
  - Store uploads in the blob store (`blob_store_dep`, content key = sha256), plus their page texts.
  - The router's existing `authorize` dependency already requires analyst or higher for POST.
- [ ] **Step 4:** Run. Expected: all pass.
- [ ] **Step 5:** Commit `feat(barrier): analyst facts, uploaded documents and choices`.

### Task 4: Review integration — item kind, decision rules, bulk accept

**Files:** Modify `schemas/review.py`, `review/items.py` and `review/decide.py`. Test: `test_tb_review.py`.

**Interfaces:**
- Produces:
  - `RUN_TYPE = "transition_barrier_derivation"`, in `REVIEWABLE_RUN_TYPES`. `_queue_kind` maps it to `barrier_cell`, and `ALLOWED["barrier_cell"]` is approve, reject and escalate.
  - Barrier payload: `{kind, code, region, current, proposed, values, result_key, entered_by: [user_id], rule_book_version}`.
  - Decision rules for `barrier_cell`:
    1. A user listed in `entered_by` gets 409 `you entered a fact this result uses`, before anything else.
    2. A first-step approve of `kind == "changed"` adds `published_change` to the second-review reasons; a reject is final at once.
    3. At the second step, after the existing different-person check, a non-approver gets 403 `a rating change is confirmed by an approver`.
    4. `unchanged` uses the normal sampling at `second_review_sample_rate`.
  - `bulk_accept` for a barrier run:
    - per-item refusals (`kind == "changed"` gives `a rating change is not bulk-accepted`; the accepting user in `entered_by` gives `you entered a fact this result uses`); the rest are accepted;
    - response `{accepted, second_review, refused: [{item_key, reason}]}`;
    - extraction keeps its all-or-nothing 409 and returns `refused: []`.
- [ ] **Step 1: Write failing tests** with items queued directly through `queue_for_review` on a `transition_barrier_derivation` run made with `JobManager.create_run`:
  - `test_ac60`, `test_ac61`, `test_ac62`, `test_ac64`, `test_ac66_refusals`, `test_ac67_refusals`;
  - `test_changed_reject_is_final`;
  - `test_ac134_extraction_second_review_unchanged`;
  - `test_extraction_bulk_accept_still_all_or_nothing`.
- [ ] **Step 2:** Run `pytest tests/test_tb_review.py tests/test_review_decide.py tests/test_bulk_accept.py -q`. Expected: the new tests FAIL and the existing ones pass.
- [ ] **Step 3: Implement** in `decide.py`: the rules in `_decide_locked` and `_step`, and the barrier branch of `_bulk_refusal`/`bulk_accept`. `build_context` must not fail for `barrier_cell`; its documents come back empty.
- [ ] **Step 4:** Run the same three files. Expected: all pass.
- [ ] **Step 5:** Commit `feat(review): barrier rating items with two-person rating changes`.

### Task 5: Derivation runs, `POST /derive`, `GET /cells` and CLI `derive`

**Files:** Create `derivation.py` and `ratings.py` (only `current_cell`, read in this task from the bundled data plus ratified results; flags and history come in Task 6). Modify the router and the CLI. Test: `test_tb_derivation.py`.

**Interfaces:**
- Consumes: `store.cell_values` (Task 3), `engine.derive` (Tasks 1–2), the payload shape (Task 4).
- Produces:
  - `create_derivation_run(run_store, cells: list[tuple[str, str]]) -> str` raises `UnknownCell(code, region)` (the route maps it to 404 `Unknown cell <code> / <region>`).
  - `execute_derivation_run(run_store, run_id, settings) -> None`, per cell:
    - notes `Sources not fetched: refresh is disabled` when `transition_barrier_refresh_enabled` is false;
    - `derive(...)` with the current rule book;
    - `append_result({"_key": f"{code}:{region}", **result})`;
    - `queue_for_review`, with kind `changed` when the proposed rating differs from `current_cell(...).rating`, `unchanged` when equal, else the result's `not_rated` or `conflict`. A `conflict` payload's `values` are `<value shown>, <document title>` in order.
    - then `finish_run`.
  - `ratings.current_cell(code, region) -> CellView`. It carries the `BarrierScore` fields plus `basis`, `ratified_by`, `result` (the ratified `Result` or None) and `ratified_at`. A rating is ratified when its item is in `FINAL_STATES` with an effective `approve`; `ratified_by` is the `user_id` of the decision that made it final, and `last_verified` is that decision's date.
  - `POST /derive {"cells": [{"code", "region"}]}` returns `{"run_id"}` after the run finishes (Ruling 3).
  - `GET /cells/{code}/{region}` returns Ruling 4's fields. `latest_result` is the latest finished derivation's result for the cell, or null.
  - CLI `arp transition-barrier derive --code --region [--now]` prints the run id.
- [ ] **Step 1: Write failing tests** through the API, as `a.analyst` unless the row says otherwise, with values entered by `enter_fact`:
  - `test_ac11` (the LLM client factory monkeypatched to raise; rating `H`);
  - `test_ac18`, `test_ac19`, `test_ac37`;
  - `test_ac51`, `test_ac53`, `test_ac139`;
  - `test_ac54`, `test_ac55`, `test_ac115`;
  - `test_unknown_cell_404` (Review Focus 2);
  - `test_cli_derive_prints_run_id`.
- [ ] **Step 2:** Run `pytest tests/test_tb_derivation.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The run uses `JobManager.create_run(RUN_TYPE, {"cells": [...]}, company_count=len(cells))`.
- [ ] **Step 4:** Run. Expected: all pass.
- [ ] **Step 5:** Commit `feat(barrier): derivation runs and the cell endpoint`.

### Task 6: Current ratings, flags and history on every reader

**Files:** Modify `ratings.py`, `dataset.py`, `schemas/transition_barrier.py` and the router. Test: `test_tb_ratings.py`.

**Interfaces:**
- Produces:
  - `BarrierScore` gains `basis: Literal["hand_rated","derived"] = "hand_rated"`, `ratified_by: str | None = None` and `flags: list[str] = []`.
  - `dataset.current_scores() -> list[BarrierScore]`: bundled scores overlaid by `ratings.current_cell` for every cell with a ratified result. Without `ARP_POSTGRES_DSN` it returns the bundled scores. No caching. `filter_scores` and `build_matrix` read it.
  - Flags (`ratings.flags(code, region) -> list[str]`):
    - `Not re-derived: missing ...` and/or `Not re-derived: open threshold ...` when the latest finished derivation is `not_rated`;
    - `Rules changed since this rating (v<n>)` when the current rating is derived and its `rule_book_version` is below the loaded rule book's, until a result derived under the current version is ratified.
  - History (`ratings.history(code, region) -> list[dict]`), oldest first:
    - the hand rating (`at` the bundled `last_verified`, `by` null, kind `rating`, `basis` `hand_rated`);
    - each fact (kind `fact`);
    - each choice (kind `choice`, `value` = `<value shown>, <document title>`, `reason`);
    - each decision (kind `decision`);
    - each ratified rating (kind `rating`, `basis` `derived`).
- [ ] **Step 1: Write failing tests:**
  - AC-52, AC-56, AC-57, AC-58, AC-59 (through `GET /scores`), AC-63, AC-65 and AC-68 to AC-70;
  - AC-140, AC-72, AC-73 (`evidence` starts `H: Effective carbon price >= 50 USD/tCO2`) and AC-141;
  - AC-130 and AC-131: bundled data, no derivation, so `basis` `hand_rated`, `ratified_by` null and `flags` `[]`;
  - `test_stale_item_does_not_roll_back` (Review Focus 5).
- [ ] **Step 2:** Run `pytest tests/test_tb_ratings.py tests/test_transition_barrier_rule_book.py tests/test_api_transition_barrier.py -q`. Expected: the new tests FAIL and the old ones pass.
- [ ] **Step 3: Implement.** For AC-72, sign RB `p_high` = 60 as version 8 in the temp copy of F, then `dataset.reset_caches()` (the restart).
- [ ] **Step 4:** Run the same files. Expected: all pass.
- [ ] **Step 5:** Run the API contract steps (Global Constraints), then commit `feat(barrier): ratified ratings, flags and history on every reader`.

### Task 7: Consumers and must-not-change

**Files:** Modify `decision/sources.py:412` and the CLI `export`. Test: `test_tb_consumers.py`.

- [ ] **Step 1: Write failing tests:**
  - `test_ac96`: after AC-57, `export --out X` puts STL-R1 European Union `M` in X. The Word script half skips with the same reason as AC-135 when node's `docx` or `adm-zip` is missing.
  - `test_ac97`: Decision Studio loads before AC-57's approval, then again after it, in one process, and the row's rating is `M`.
  - `test_ac71`: for each of AC-49, AC-51, AC-57, AC-63 and AC-65, run from a fresh copy of F, the sha256 of every file in the copy is unchanged.
  - `test_current_scores_without_postgres` (Review Focus 4): the env has no DSN; 105 bundled ratings.
- [ ] **Step 2:** Run. Expected: FAIL for AC-96 and AC-97.
- [ ] **Step 3: Implement.** `from_transition_barrier` and `export` read `current_scores()`.
- [ ] **Step 4:** Run `pytest tests/test_tb_consumers.py tests/test_transition_barrier_rule_book.py -q`, plus the Decision Studio tests that import `from_transition_barrier`. Expected: all pass.
- [ ] **Step 5:** Commit `feat(barrier): Decision Studio and export read ratified ratings`.

### Task 8: Frontend — review kind, bulk accept, cell detail, criterion page

**Files:**
- `frontend/src/types.ts`: `ReviewableRunKind` gains `"transition_barrier_derivation"`. The barrier types gain the criterion fields, `basis`, `ratified_by`, `flags`, and `BarrierCell` / `BarrierResult`.
- The five reviewable lists: `RunHistory.tsx:8`, `lib/runs.ts:7`, `App.tsx:134`, `lib/processes.ts:37`, and `REVIEW_KIND_LABEL` in `RunReviewList.tsx:15` (label "Transition barrier ratings").
- `lib/reviewKeys.ts`: `decisionChoices("barrier_cell")` is approve and reject.
- `RunReviewList.tsx` / `ReviewItemFields`: show `kind`, `current → proposed`, and the conflict `values`. A "Bulk accept" button for barrier runs posts the pending items to `/api/extraction/items/bulk-accept` and lists every `refused` reason.
- `TransitionBarrierAssessment.tsx`:
  - the criterion page shows the rationale, the actions, each fact with its definition, the H, M and L sentences, each threshold with its value, source and rationale (or its open question), and "rule book v<n>";
  - a matrix cell opens `#/transitionBarrier/cell/<code>/<region>`.
- New `BarrierCellDetail.tsx` shows:
  - rating and confidence;
  - "ratified by <user> <date>", or "hand-rated <date>";
  - each level and condition with pass, fail or unknown;
  - for every figure, its quote, title and page, with a link to `GET /documents/{id}#page=<page>`;
  - flags and history;
  - an analyst fact form (multipart, copied from `HoldingsIntake.tsx:130`);
  - a choice control when the latest result is a conflict.
- `client.ts`: `getBarrierCell`, `deriveBarrierCells`, `addBarrierFact`, `chooseBarrierValue`. `contract.ts`: a line for each of these with a response model.
- Test: `frontend/tests/barrierCell.test.ts` for the pure helpers (the "ratified by"/"hand-rated" line, and the clause outcome classes).

- [ ] **Step 1: Write the failing helper tests:** `ratifiedLine({basis:"hand_rated", last_verified:"2026-08-14"}) === "hand-rated 2026-08-14"` and `ratifiedLine({basis:"derived", ratified_by:"a.approver", last_verified:"2026-10-20"}) === "ratified by a.approver 2026-10-20"`.
- [ ] **Step 2:** Run `cd frontend && npm test`. Expected: FAIL.
- [ ] **Step 3: Implement**, following `DESIGN.md`:
  - status colours only for H/M/L, mono only for data, flat square cards, spacing tokens, compact outlined in-table buttons;
  - the "Proposed" tag is the only signal colour on a review item.
- [ ] **Step 4:** Run `npm run lint && npx tsc -b && npm test`. Expected: clean.
- [ ] **Step 5: Screenshot and audit.**
  - Start the stack: `bash .claude/hooks/ensure-deps.sh postgres && ARP_TRANSITION_BARRIER_DATA_DIR=$PWD/backend/tests/fixtures/transition_barrier bash backend/scripts/e2e_stack.sh up`.
  - Walk AC-124 to AC-129 by hand with Playwright, uploading D1–D3 from F. Screenshot the criterion page, the cell detail and the review screen into the scratchpad.
  - Run `/impeccable:impeccable audit` and fix its blocking findings.
  - `e2e_stack.sh down`.
- [ ] **Step 6:** Commit `feat(frontend): barrier cell detail, analyst facts and review`.

### Task 9: Open the PR

- [ ] Run the full backend barrier, review and decision suites and the frontend checks. Push. Open a PR against `main`:
  - title `Transition barriers: rules engine and ratification (phase 2)`;
  - label `risk:normal`;
  - body with `Spec: transition-barrier-rule-book-design`, the rulings above, the phase 2 AC list, the evaluator rows left for the `evaluator` skill, and every test change.
