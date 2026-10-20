# Transition Plan Alignment Phase 2 (plan actions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract plan actions and assumptions from a company's transition plan, match each action per region
to the barrier criteria that name it, compare assumptions with barrier evidence, score ACT B02.a–d, and show it
all in the company page's Transition section.

**Architecture:** A new preset `sch_transition_plan_actions`. One list extractor turns each transition-plan
document into many company facts that share a `basis` per action. It feeds the existing pipeline's checks,
routing, review queue and publish path. A pure module (`transition_alignment/actions.py`) computes regions,
barrier matches, assumption comparisons and B02 from counted facts plus a read-only barrier lookup. The phase 1
endpoint fills its phase 2 keys from it, and the frontend section gains Actions and Assumptions parts.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy/Postgres, pytest (`FakeLLMClient`), React/TS, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-19-transition-plan-alignment-design.md`: sections 4, 5, 6 (Plan actions,
Assumptions), 7 and 9; acceptance rows AC-24 to AC-35, AC-37, AC-49, AC-50, AC-59, AC-60, AC-62, AC-63, AC-68,
AC-69, AC-71, AC-46, AC-47, AC-48 and evaluator rows AC-53 to AC-55 and AC-43. Phase 1 plan:
`docs/superpowers/plans/2026-10-19-transition-plan-alignment-phase1.md` (rulings R1–R14 still hold).

## Global Constraints

- The model extracts values, quotes and classifications. It never outputs a score, ratio, rating, B02 result,
  gap or benchmark.
- Precision first: "no disclosure" or an empty list beats a wrong figure that counts.
- Tests make no network and no model calls (`FakeLLMClient`, stubbed fetch).
- The match **reads** barrier data only; it never derives, ratifies or writes anything there (AC-46: F-TA files
  stay byte-identical).
- Region order is `European Union`, `United States`, `China`. Barrier entries and comparisons are ordered by
  region, then criterion code.
- Numbers are shown with `fmt_number` (half up to 0.01, trailing zeros dropped).
- Exact strings, verbatim from the spec:
  - `No operating region disclosed`
  - `Unknown action id '<id>'`
  - `No ACT Core lever wording`
  - B02.b: `implemented (<year>)`, `implemented`, `near term (<year>)`, `long term (<year>)`, `No timeframe: ignored`
  - B02.c: `<value> <unit>`, `No quantified GHG saving`
  - B02.d: `<needed> needed, <allocated> allocated`, `Needed and allocated in different currencies`,
    `No split of funds needed and allocated`, `No funding stated`
  - B02.a: `met: <i> implemented, <p> planned with a timeframe`,
    `not met: <i> implemented, <p> planned with a timeframe (needs 3 and 1)`
  - comparisons: `hand-rated, no figure: <cell evidence>`, `no counted value`, `Unit not convertible: <unit>`
- A company-fact citation reads `<document title> p.<page>`. A barrier evidence value reads
  `<value shown> (<document title>, p. <page>)`.

## Rulings (builder's calls the owner checks with this plan)

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| P1 | New `DocType.TRANSITION_PLAN = "transition_plan"`. "Most recent plan" means the company's `transition_plan` document with the latest `published_at` (the as-of date); a tie goes to the later `first_seen_at`. | The code has no plan type, and the spec needs one. `first_seen_at` is the upload time. | The holdout's documents must use `transition_plan`; this is flagged for the test-writer. |
| P2 | Which actions count is decided by the **primary citation's document** of each action's `ta_action_text` fact, not by the `basis` text. Actions are ordered by that citation's page, then `fact_id`. | Hidden tests seed basis values such as `action:3`, so the code must not parse meaning from basis. | None. |
| P3 | The extractor writes basis `action:<doc_id>:<page>:<n>` (n counts actions on that page, in the model's order) and `region:<Region>` / `region:any` for assumptions. | Unique per document, so two plans never supersede each other's actions (the current-fact key is company, field, period, basis). | Re-extraction that reorders actions on one page swaps their facts. They stay reviewable. |
| P4 | Review item keys include basis only for list-item bases (`action:`, `region:`). `period_key` appends `\|<basis>`. Other bases keep today's keys. | Without this, all actions of one field share one review item. Changing keys for every basis would orphan existing review history. | A future basis starting with those prefixes would get the longer key. A test pins that no `basis_v1.csv` canonical value starts with them. |
| P5 | `ta_action_id.allowed_values` = every action id in the **bundled** rule book plus `other` (as R2). The sector check runs in the extractor: an id not in the company's sector list or `other` gets the failed check `action_id` with detail `Unknown action id '<id>'` and is routed to review. | Field definitions cannot vary per company. The reason text is fixed by the spec. | A steel plan citing a power action is refused, which is intended. |
| P6 | Actions and assumptions are extracted only from `transition_plan` documents, one model call per document over its retrieved chunks (keyword retrieval, hybrid off, as phase 3 of the barrier work). `ta_operates_*` go through the normal per-field path over all documents. | Only the latest plan counts for actions. Operating regions are usually stated in annual reports (P2 p.3). | Actions stated only in a sustainability report are not extracted. They would not count anyway. |
| P7 | `CompanyFactRow` gains `doc_id: str \| None` and `page: int \| None` from the primary citation (additive, like R8). | P2 and the assumption's document date need them, and a second query per fact is avoided. | None. |
| P8 | `timeframe` in the response = the B02.b text when met, else null. | The spec lists the field without defining it. | A UI label only. |
| P9 | A criterion cell with no rating returns `rating` null, `basis` null, `evidence` "", `values` []. | The spec is silent. Showing nothing beats inventing a rating. | None. |

## Review Focus

1. An action group with no counted `ta_action_text` (e.g. only `ta_action_id` approved) → not listed. Test in Task 3.
2. A Steel company's action classified `pwr.renewables` (another sector's id) → refused with `Unknown action id 'pwr.renewables'`. Test in Task 2.
3. An assumption whose region has no action of the company → no comparisons (empty list, no error). Test in Task 3.
4. Two plan documents with the same as-of date → the later upload wins (AC-71 shape) even when the earlier one has more actions. Test in Task 4.
5. A barrier cell never rated → the entry is listed with `rating` null (P9), and the request does not fail. Test in Task 3.

---

### Task 1: Preset, document type, fact row fields

**Files:**
- Create: `backend/arp/presets/transition_plan_actions.py`
- Modify: `backend/arp/presets/registry.py`, `backend/arp/schemas/common.py` (`DocType`), `backend/arp/db/company_view.py` (`CompanyFactRow.doc_id`, `.page`)
- Test: `backend/tests/test_presets_transition_plan_actions.py`, `backend/tests/test_presets_transition_capex.py` (AC-47's keys assert)

**Interfaces:**
- Produces: `SCHEMA_ID = "sch_transition_plan_actions"`; `ACTION_FIELDS` (the 8 `ta_action_*` ids, spec order); `ASSUMPTION_FIELDS = ("ta_assumed_carbon_price", "ta_assumed_h2_cost")`; `OPERATES_FIELDS = ("ta_operates_eu", "ta_operates_us", "ta_operates_cn")`; `FIELD_IDS`; `build_transition_plan_actions_schema()`. Every field has `applicability_rules(sector_codes=bundled_prefixes())`, as in the capex preset, plus 3–8 curated seed keywords. Types: as in spec section 4. `ta_action_id` gets `allowed_values` per P5.

- [ ] **Step 1: Write the failing tests:**
  - `test_fields_match_spec` (ids, types, units: `tCO2e/yr`/`MtCO2e/yr`/`%` named in the saving's instructions, enums `implemented|planned` and the four regions);
  - `test_action_id_allowed_values` (= bundled rule-book ids + `other`);
  - `test_registered` (the AC-47 keys assert now expects exactly the four snapshot keys + `sch_transition_capex` + `sch_transition_plan_actions`: this edits the phase 1 assert, so list it in the PR);
  - `test_doc_type_transition_plan`;
  - `test_fact_row_has_doc_and_page` (db test, in `tests/db/test_company_api.py` style: one approved fact cited P2 p.45 → `doc_id` P2's id, `page` 45).
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_presets_transition_plan_actions.py tests/test_presets_transition_capex.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** following `presets/transition_capex.py`.
- [ ] **Step 4: Run** the step 2 files plus `tests/db/test_company_api.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): sch_transition_plan_actions preset, transition_plan doc type`.

### Task 2: List extractor and review keys

**Files:**
- Create: `backend/arp/transition_alignment/plan_extraction.py`
- Modify: `backend/arp/extraction/pipeline.py` (one branch for this schema's list fields), `backend/arp/schemas/review.py` (`period_key`, P4)
- Test: `backend/tests/test_transition_alignment_plan_extraction.py`

**Interfaces:**
- Consumes: Task 1's field tuples; `load_rule_book(dataset.data_dir())` (`RuleBook.actions[sector]`); `sector_for_isic`; the grounding/quote check that `extract_one_field` applies (`arp/extraction/field_graph.py`); `field_evidence` retrieval with `hybrid_retrieval_enabled=False`.
- Produces:
  - Output models `ActionDraft` (text, action_id, status, year, region, ghg_saving + unit, capex_needed + unit, capex_allocated + unit; each value with its own `quote` and `page`), `AssumptionDraft` (kind `carbon_price|h2_cost`, value, unit, region or null, year or null, quote, page) and `PlanDraft(actions, assumptions)`.
  - `async def extract_plan(company, sector: str | None, document, chunks, llm) -> list[ExtractedField]`: one row per stated value, basis per P3. Assumptions: `period_end` 31 Dec of `year`, else none. Each row has its citation and goes through the same quote check as other fields.
  - In `pipeline.py`: when `schema.schema_id == SCHEMA_ID`, the list fields still in `to_extract` (after applicability) are filled by `extract_plan` once per `transition_plan` document in `kept`. The rows land in each field's slot in schema order. Reuse and history are skipped for these fields. The `ta_operates_*` fields take the normal path.
  - `period_key(f)` per P4.

- [ ] **Step 1: Write the failing tests** (`FakeLLMClient` scripts `PlanDraft` and the verifier as other extraction tests do; P1 as a `transition_plan` document whose pages hold the spec quotes):
  - `test_actions_become_rows_with_basis`: P1 pp.12–21 → A1's 6 rows share one basis `action:<P1>:12:1`; A2 `action:<P1>:15:1`; the carbon price row has basis `region:European Union`, `period_end` 2030-12-31, value 90, unit `EUR/tCO2`.
  - `test_ac30_unknown_action_id`: the stub says `steel.foo` → the `ta_action_id` row is routed to review, and its review item's reasons include `Unknown action id 'steel.foo'`. After recording, no counted `ta_action_id` fact has value `steel.foo`.
  - `test_other_sector_id_refused` (Review Focus 2).
  - `test_two_actions_two_review_items`: A1 and A2 `ta_action_status` rows get different item keys; a row with basis `group` (any `basis_v1.csv` canonical) keeps `field_item_key(..., period)` unchanged.
  - `test_basis_table_has_no_list_prefix`: no canonical value in `basis_v1.csv` starts with `action:` or `region:`.
  - `test_ungrounded_quote_goes_to_review`: a quote not in the page text → the same not-grounded reason as other fields.
  - `test_ac48_q_gets_no_rows`: Q (ISIC 1050) → no model call for the list fields; recording the run adds no fact (AC-48 for this preset).
  - `test_only_transition_plans_read`: an annual report in `kept` gets no `PlanDraft` call.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_transition_alignment_plan_extraction.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `plan_extraction.py`, the pipeline branch and `period_key`.
- [ ] **Step 4: Run** the test file plus `tests/test_extraction_pipeline.py tests/test_review_items.py tests/test_tb_extraction.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): plan action list extraction`.

### Task 3: Pure plan scoring: regions, barrier match, assumptions, B02

**Files:**
- Create: `backend/arp/transition_alignment/actions.py`
- Modify: `backend/arp/schemas/transition_alignment.py` (replace the untyped phase 2 keys)
- Test: `backend/tests/test_transition_alignment_actions.py`

**Interfaces:**
- Consumes: phase 1 `Fact` (`capex.py`); `fmt_number`; `units.convert(value, unit, fact_unit, year, conversions)`; `RuleBook` criteria `actions`; Task 2's field ids.
- Produces:
  - `@dataclass(frozen=True) class Cell: rating: str | None; basis: str | None; evidence: str; values: list[dict]` (counted values only, each with `value`, `unit`, `document`, `page`, `document_id`, `url`).
  - `CellLookup = Callable[[str, str], Cell]`.
  - `operating_regions(facts) -> list[str]`.
  - `score_plan(action_groups: list[list[Fact]], assumptions: list[Fact], operates: list[Fact], *, criteria: list[tuple[str, list[str], list[str]]], cell: CellLookup, act_levers: dict, assumption_map: dict, conversions: list[dict], doc_year: Callable[[int], int]) -> PlanOut`. `criteria` holds (code, action ids, regions) in rule-book order. `doc_year(fact_id)` returns the as-of year of the fact's document.
  - Models: `B02Out(met: bool, text: str)`; `BarrierOut(code, region, rating: str | None, basis: str | None, evidence: str, values: list[dict])`; `ActLeverOut(wording, citation)`; `ActionOut(key, action_id: str | None, act_lever: ActLeverOut | None, text, status: str | None, year: int | None, region: str | None, citation: str | None, timeframe: str | None, b02: dict[str, B02Out], barriers: list[BarrierOut], note: str | None, fact_ids: list[int])`; `ComparisonOut(code, region, assumption: str | None, evidence: str, gap: str | None, reason: str | None)`; `AssumptionOut(kind, region: str | None, year: int | None, citation: str | None, fact_id: int, comparisons: list[ComparisonOut])`; `PlanOut(regions, actions, b02a: B02Out | None, assumptions)`. `TransitionOut.regions/actions/b02a/assumptions` use these types.
- Rules: spec sections 4 and 5 verbatim. The gap is shown only when there is exactly one evidence value, as `+25.2 USD/tCO2`/`-3 USD/kg H2`. The converted assumption reads `97.2 USD/tCO2 (90 EUR/tCO2)`, with no brackets when the unit is unchanged. Comparisons run only for criteria that name one of the company's listed actions, in the assumption's region if stated, else every region of those actions. `b02a` is null when there are no actions.

- [ ] **Step 1: Write the failing tests.** A helper `defaults()` builds C's action groups A1–A3 and the assumptions from the spec's fixture table, and `fta_cell()` gives the F-TA cells after setup: STL-R1 EU `H` derived with value 72 USD/tCO2 (EU ETS Market Report 2026, p. 12); STL-T1 EU `M` derived with 6 USD/kg H2 (Hydrogen Cost Review 2026, p. 7); the other four cells `L` hand-rated with the spec's evidence.
  - Unit-level: `test_ac24_regions_and_order`, `test_ac25`, `test_ac26`, `test_ac27`, `test_ac28`, `test_ac69`, `test_ac29`, `test_ac31`, `test_ac32`, `test_ac33`, `test_ac68`, `test_ac34`, `test_ac35`, `test_ac49`, `test_ac50`, `test_ac59`, `test_ac60`, `test_ac37`, `test_ac63`, each asserting its row's exact values. For example AC-31: one comparison `("STL-R1", "European Union", "97.2 USD/tCO2 (90 EUR/tCO2)", "72 USD/tCO2 (EU ETS Market Report 2026, p. 12)", "+25.2 USD/tCO2", None)`.
  - Review Focus 1, 3 and 5: `test_group_without_text_not_listed`, `test_assumption_region_without_actions`, `test_unrated_cell_listed_null`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_transition_alignment_actions.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `actions.py` and the models (no DB, no HTTP).
- [ ] **Step 4: Run** the test file plus `tests/test_transition_alignment_capex.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): plan regions, barrier match, assumptions, B02`.

### Task 4: Endpoint wiring and F-TA ratification setup

**Files:**
- Modify: `backend/arp/api/routers/transition_alignment.py`, `backend/tests/transition_alignment_helpers.py`
- Test: `backend/tests/db/test_transition_alignment_api.py`

**Interfaces:**
- Consumes: Task 3 `score_plan`; Task 1 `CompanyFactRow.doc_id/page`; `Ratings(run_store).cell(code, region)` (`CellView.rating`, `.basis`, `.evidence`, `.result.values` filtered on `counted`); `load_rule_book`; `get_document`; the benchmarks `act_levers` and `assumptions`.
- Produces:
  - `latest_plan(session, company_id) -> Document | None` per P1.
  - The router fills `regions`, `actions`, `b02a` and `assumptions` for in-scope companies. Action groups are counted facts grouped by basis, keeping only groups whose `ta_action_text` primary citation is the latest plan (P2).
  - Helper `ratify_fta(client)`: through the barrier API, enters D1 `price` 72 (p. 12), `applies` Yes and `levy` Yes for STL-R1 EU, and D5 `h2_cost` 6 (p. 7) for STL-T1 EU. It derives both cells, then approves each as analyst and approver, following `tests/test_tb_ratings.py::ratify_change`.
  - `seed_defaults` also registers P1 (and P3, P6 when a test asks) as `transition_plan` documents and seeds A1–A3, `ta_operates_*` and both assumptions as approved facts.

- [ ] **Step 1: Write the failing tests:** `test_ac24_api`, `test_ac25_api`, `test_ac31_api`, `test_ac34_api` (exact values as in Task 3, through the API); `test_ac62_older_plan` (A6 from P3 → actions A1, A2, A3; A6's `ta_action_id` trail returns 200); `test_ac71_revised_plan` (P6 uploaded after P1, A7 seeded → actions exactly A7, citation `Fixture Steel Transition Plan 2025 (revised) p.4`); `test_ac46_barrier_untouched` (scores and the EU STL-R1 cell are equal before and after AC-24…AC-35 requests; every F-TA file is byte-identical); Review Focus 4 `test_same_date_later_upload_wins`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/db/test_transition_alignment_api.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the router changes and helpers.
- [ ] **Step 4: Run** the test file plus `tests/test_tb_ratings.py`. Expected: PASS.
- [ ] **Step 5: API contract:** `python scripts/export_openapi.py`, `cd frontend && npm run gen:api && npx tsc -b`. Expected: clean (fix type errors in `types.ts`).
- [ ] **Step 6: Commit** `feat(alignment): plan actions and assumptions in /transition`.

### Task 5: Transition section, Actions and Assumptions parts

**Files:**
- Modify: `frontend/src/pages/company/TransitionSection.tsx`, `frontend/src/types.ts`
- Modify: `backend/tests/e2e/test_transition_section.py`
- Test: `frontend/tests/company.test.ts`

**Interfaces:**
- Consumes: Task 4's response; `FactButton`/`onOpenFact`; `FileLink` + `api.barrierDocumentUrl(document_id, page)` (or `sourceHref(v)` when there is no document), as in `BarrierCellDetail.tsx`'s `Figure`.
- Produces:
  - An **Actions** part. Per action: text (a button opening `fact_ids[0]`), action id, ACT lever wording or `No ACT Core lever wording`, status, timeframe, region, the B02 b/c/d texts, and per region the matched criteria with rating, basis and evidence. Each barrier figure opens its barrier citation. The `note` when set. Then B02.a for the plan.
  - An **Assumptions** part. Per comparison: code, region, assumption, evidence and gap. The assumption opens its fact.
  - Layout per `DESIGN.md`, using only existing classes, as phase 1 did.

- [ ] **Step 1: Write the failing test** in `company.test.ts`: `barrierEvidence(values)` (or a similarly named pure helper you add to `companyQuery.ts`) formats `72 USD/tCO2 (EU ETS Market Report 2026, p. 12)`.
- [ ] **Step 2: Run** `cd frontend && npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** the helper and the two parts.
- [ ] **Step 4: Extend the e2e test** with C's phase 2 response (validated with `TransitionOut.model_validate`). Assert the texts for AC-53 (EU, `STL-R1` `H`, `STL-T1` `M` on the DRI action), AC-54 (`1500 EUR million needed, 600 EUR million allocated`) and AC-55 (`+25.2 USD/tCO2`). Save the screenshot to the session scratchpad, not the repo.
- [ ] **Step 5: Run** `cd frontend && npm run lint && npx tsc -b && npm test`, then the browser flow from `.claude/CLAUDE.md` for `tests/e2e/test_transition_section.py`. Expected: PASS.
- [ ] **Step 6: Run** `/impeccable:impeccable audit` on the screenshot; fix findings within the section.
- [ ] **Step 7: Commit** `feat(alignment): Transition section actions and assumptions`.

### Task 6: Full checks and PR

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest` (with `ARP_TEST_POSTGRES_DSN`, and no other pytest on the shared DB), and the frontend checks. Expected: only the known environment failures.
- [ ] **Step 2:** Open the PR against `main` per `.claude/skills/steward/SKILL.md`:
  - title `Transition plan alignment phase 2: plan actions`
  - `Spec: transition-plan-alignment-design`
  - `risk:high` (it changes extraction-pipeline and review keys)
  - the acceptance coverage per row, with the holdout rows run as unit and owed
  - every test change (including the AC-47 keys assert)
  - rulings P1–P9
  - the evaluator rows AC-53, AC-54, AC-55 and AC-43
  - that `openwiki/` needs an update
