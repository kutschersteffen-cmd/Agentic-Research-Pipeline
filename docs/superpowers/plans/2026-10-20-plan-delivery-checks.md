# Plan Delivery Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ACT target progress, abatement coverage, phase-out commitment and IEA NZE scenario
carbon-price checks to `GET /api/companies/{ref}/transition` and the company page's Transition section.

**Architecture:** `sch_transition_plan_actions` gains target and phase-out list fields, which the
existing plan extractor fills. The benchmarks file gains a signed `scenario_prices` block. A new pure
module `transition_alignment/delivery.py` computes the four results from counted facts. The router adds
them to `TransitionOut`, and the frontend section adds three parts plus a scenario column.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy/Postgres, pytest (`FakeLLMClient`), React/TS, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-20-plan-delivery-checks-design.md` (owner approved
2026-10-20), on top of `docs/superpowers/specs/2026-10-19-transition-plan-alignment-design.md`
(phase 1–2 fixtures, rulings R1–R14, P1–P9).

## Global Constraints

- The model extracts only. Code computes every ratio, score, band and gap.
- A missing input gives `score`/`percent` null with the spec's exact `reason`, never 0.
- Exact strings are in spec §3–§6a; copy them verbatim. They include:
  - the four reason lists;
  - `Target progress <score>% (ACT GE 1.4)`;
  - `Listed actions cover <percent>% of the <year> target gap (<covered> of <gap> MtCO2e/yr)`;
  - the timeline texts;
  - the sale note;
  - `Band points are ours, not ACT's (ACT GE pp.139–140)`;
  - the scenario text;
  - the three validator lines;
  - the four ACT cite strings.
- Numbers are shown with `fmt_number` (half up, 2 decimals, trailing zeros dropped). A target `score` is rounded half up to 2 decimals before display and before any mean.
- A zero gap is shown as `0 USD/tCO2`; otherwise gaps take a sign (`+` / `-`) as in phase 2.
- Only the latest transition plan (phase 2 P1/P2) counts for targets and phase-outs.
- Must not change: every phase 1–2 row; AC-46, AC-47, AC-48; AC-118 (snapshot S2 of the phase-2 plan-action fields).
- Tests make no network or model calls. DB tests use `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test_impl` (the Stop hook uses `arp_test`).

## Rulings

| # | Ruling | Why |
|---|---|---|
| D1 | List bases `target:<doc>:<page>:<n>` and `phaseout:<doc>:<page>:<n>`; `period_key`'s list prefixes become `action:`, `region:`, `target:`, `phaseout:`. | Each target and phase-out gets its own review item (phase 2 P4). |
| D2 | `E(year)` reads the counted `tp_h_scope1_emissions` / `tp_h_scope2_emissions` facts of the existing preset, keyed by fiscal year as R4. | Reuse; the spec forbids changing that preset. |
| D3 | `delivery.py` is pure, like `actions.py`. The router builds `Fact`s with phase 2's plan mapper. | Same seams as phase 2. |
| D4 | `scenario_prices` is optional in the model and validated only when present. `check_benchmarks()` at startup also requires it for the **bundled** directory. | Spec §6: older signed files stay valid. |

## Review Focus

1. Two running targets with the same target year → coverage uses the earlier page; test in Task 4.
2. A target whose base emissions equal `T` (pct 0) → `E_base − T` is 0; no division error. Gives `reason` `Incomplete target` (treat pct ≤ 0 as incomplete). Test in Task 4.
3. Emissions series with a scope 2 fact but no scope 1 for RY → RY falls back to the latest year with both. Test in Task 4.
4. A phase-out whose year is before the plan year → date points 100 (≤ RY+5); no error. Test in Task 4.
5. A `region:any` carbon-price assumption → one scenario entry per operating region, in region order. Test in Task 4.

---

### Task 1: Preset fields and snapshot S2

**Files:**
- Modify: `backend/arp/presets/transition_plan_actions.py`
- Create: `backend/tests/fixtures/transition_alignment/plan_actions_main.json`
- Test: `backend/tests/test_presets_transition_plan_actions.py`

**Interfaces:**
- Produces: `TARGET_FIELDS = ("ta_target_scope", "ta_target_pct", "ta_target_year", "ta_target_base_year", "ta_target_base_emissions", "ta_target_set_year")`; `PHASEOUT_FIELDS = ("ta_phaseout_activity", "ta_phaseout_share_pct", "ta_phaseout_year", "ta_phaseout_method")`. Both are appended to `FIELD_IDS`. Types, enums and units follow spec §1. Applicability and seed keywords follow the existing fields.

- [ ] **Step 1: Record S2 first.** Before any edit, write the phase-2 fields (`field_id`, `data_type`, `version`, `high_risk`, `extraction_instructions`) to `plan_actions_main.json`, using the same recorder approach as phase 1's `presets_main.json`.
- [ ] **Step 2: Write failing tests:**
  - `test_ac118_phase2_fields_unchanged`: built fields equal S2.
  - `test_target_and_phaseout_fields`: ids, types, enums `S1+2|S1+2+3` and `closure|conversion|sale`, units `tCO2e`/`MtCO2e` named in the base-emissions instructions.
- [ ] **Step 3: Run** `cd backend && python3 -m pytest tests/test_presets_transition_plan_actions.py -v`. Expected: the new-field test fails.
- [ ] **Step 4: Implement** the fields.
- [ ] **Step 5: Run** the file plus `tests/test_presets_transition_capex.py`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(alignment): target and phase-out fields`.

### Task 2: Extract targets and phase-outs

**Files:**
- Modify: `backend/arp/transition_alignment/plan_extraction.py`, `backend/arp/schemas/review.py` (`period_key` prefixes, D1)
- Test: `backend/tests/test_transition_alignment_plan_extraction.py`, `backend/tests/db/test_transition_alignment_api.py`

**Interfaces:**
- Consumes: Task 1 tuples; phase 2's `PlanDraft`, `extract_plan` and row builder (grounding, `unverified_list_item`).
- Produces: `TargetDraft` and `PhaseoutDraft`, where each value has its own `quote` and `page`. `PlanDraft` gains `targets` and `phaseouts`. `extract_plan` emits their rows with D1 bases. The prompt says absolute targets only and gives the enums.

- [ ] **Step 1: Write failing tests:**
  - `test_target_rows_share_basis`: P1 p.22 gives six T1 rows with basis `target:<P1>:22:1`.
  - `test_phaseout_rows`: P1 p.24 gives four O1 rows.
  - `test_list_prefixes_cover_target_phaseout`: `period_key` appends the basis for `target:` and `phaseout:`, and `basis_v1.csv` has no canonical value with these prefixes.
  - DB tests: `test_ac88_target_pending`, `test_ac125_same_basis` and `test_ac115_phaseout_pending` (spec rows; stub-driven run, then `/facts`).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the two files plus `tests/test_review_items.py tests/test_review_context.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): extract targets and phase-outs`.

### Task 3: Benchmarks scenario prices (v2)

**Files:**
- Modify: `backend/arp/transition_alignment/benchmarks.py`, `backend/arp/schemas/transition_alignment.py`, `backend/arp/api/routers/transition_alignment.py` (`/benchmarks`), `backend/arp/transition_alignment/data/benchmarks.json`
- Create: `backend/tests/fixtures/transition_alignment/bm_s/benchmarks.json` (BM v3 plus the two NZE rows, signed v4)
- Test: `backend/tests/test_transition_alignment_benchmarks.py`

**Interfaces:**
- Produces:
  - `ScenarioGroup(group: str, source: Source, prices: dict[int, float])`; `Benchmarks.scenario_prices: list[ScenarioGroup] = []`.
  - `REGION_GROUP = {"European Union": "advanced economies", "United States": "advanced economies", "China": "selected EMDE"}`.
  - Validator lines exactly as in spec §6.
  - `ScenarioGroupOut(group, citation, prices: dict[int, float])` served on `/benchmarks`.
  - The bundled file gains the table (WEO 2024 Table B.2 p.329, URL `https://iea.blob.core.windows.net/assets/140a0470-5b90-4922-a0e9-838b3ac6918c/WorldEnergyOutlook2024.pdf`, licence `CC BY 4.0`). It is re-signed to v2 with `approved_by "<owner, pending approval in this PR>"` (as R3).

- [ ] **Step 1: Write failing tests:**
  - `test_ac87_scenario_no_source` (BM-S edited: exit 1, output contains the line);
  - `test_scenario_missing_in_bundled_refused`;
  - `test_scenario_unknown_group`;
  - `test_bm_without_key_still_valid`, where AC-3 to AC-8 and AC-67 are unchanged;
  - `test_ac113_api`: bundled 140/180/205/250 and 90/125/160/200, each citation containing `p.329`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_transition_alignment_benchmarks.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement**, then sign the bundled file.
- [ ] **Step 4: Run** the file plus `tests/test_transition_barrier_rule_book.py`. Expected: PASS.
- [ ] **Step 5: API contract:** run `python scripts/export_openapi.py`, then `cd frontend && npm run gen:api && npx tsc -b`. Expected: clean.
- [ ] **Step 6: Commit** `feat(alignment): IEA NZE scenario prices in benchmarks v2`.

### Task 4: Pure delivery scoring

**Files:**
- Create: `backend/arp/transition_alignment/delivery.py`
- Modify: `backend/arp/schemas/transition_alignment.py`
- Test: `backend/tests/test_transition_alignment_delivery.py`

**Interfaces:**
- Consumes:
  - phase 1 `Fact` (`basis`, `page`);
  - phase 2 `ActionOut` list and `AssumptionOut` list, whose regions and conversions are already applied;
  - `fmt_number`;
  - `units.convert`;
  - Task 3 `ScenarioGroup`, `REGION_GROUP`.
- Produces:
  - `score_targets(target_groups: list[list[Fact]], emissions: list[Fact], plan_year: int) -> tuple[list[TargetOut], TargetProgressOut | None]`
  - `score_coverage(targets: list[TargetOut], actions: list[ActionOut], saving_facts: dict[str, Fact]) -> CoverageOut`
  - `score_phaseouts(groups: list[list[Fact]], sector: str, plan_year: int) -> list[PhaseoutOut]`
  - `scenario_entries(assumption: AssumptionOut, fact: Fact, regions: list[str], groups: list[ScenarioGroup], conversions: list[dict], doc_year: int) -> list[ScenarioOut]`
  - Models with the field names of spec §7: `TargetOut`, `TargetProgressOut(score, text)`, `CoverageOut`, `CoverageActionOut`, `PhaseoutOut`, `ScenarioOut`. `AssumptionOut.scenario: list[ScenarioOut] = []`. `TransitionOut` gains `targets`, `target_progress`, `coverage`, `phaseouts`.
  - Sector timelines `{"Power & Utilities": 2040, "Shipping": 2040, "Heavy-Duty Road Transport": 2035}`.

- [ ] **Step 1: Write failing tests.** Fixture helpers build C's T0, T1, emissions, O1, P's O2 and A1–A3 from the spec tables. Write one test per spec row, asserting its exact Then:
  - AC-90, AC-91, AC-73, AC-74, AC-122, AC-75, AC-92, AC-123, AC-76, AC-93, AC-94, AC-99, AC-100
  - AC-77, AC-101, AC-78, AC-124, AC-102, AC-79, AC-103
  - AC-80, AC-104, AC-81, AC-105, AC-106, AC-107, AC-108, AC-109, AC-110, AC-82, AC-111
  - AC-84, AC-85, AC-86, AC-95, AC-96, AC-97

  Also one test each for Review Focus 1–5.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_transition_alignment_delivery.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** (Decimal arithmetic; floats only in models).
- [ ] **Step 4: Run** the file plus `tests/test_transition_alignment_actions.py tests/test_transition_alignment_capex.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): target progress, coverage, phase-out, scenario price`.

### Task 5: Endpoint wiring

**Files:**
- Modify: `backend/arp/api/routers/transition_alignment.py`, `backend/tests/transition_alignment_helpers.py` (seed the new fixture facts, P7, BM-S option)
- Test: `backend/tests/db/test_transition_alignment_api.py`

**Interfaces:**
- Consumes:
  - Task 4 functions;
  - phase 2 latest-plan filter and plan `Fact` mapper;
  - `CompanyFactRow.doc_id/page`;
  - `latest_plan` (its `published_at` year is `plan_year`).
- Produces: `TransitionOut` filled for in-scope companies. Out of scope keeps the new keys empty or null.

- [ ] **Step 1: Write failing tests:**
  - `test_ac72_api`
  - `test_ac73_api`
  - `test_ac77_api`
  - `test_ac80_api`
  - `test_ac81_api` (P with P7)
  - `test_ac84_api` (BM-S)
  - `test_ac114`
  - `test_ac116_latest_plan` (P6 stored)
  - `test_ac117_no_model_call`
  - `test_ac83_api`
  - phase 1–2 API tests still pass unchanged
- [ ] **Step 2: Run** the file. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file plus `tests/test_tb_ratings.py`. Expected: PASS.
- [ ] **Step 5: API contract** as in Task 3.
- [ ] **Step 6: Commit** `feat(alignment): delivery checks in /transition`.

### Task 6: Transition section: Targets, Abatement coverage, Phase-out, scenario column

**Files:**
- Modify: `frontend/src/pages/company/TransitionSection.tsx`, `frontend/src/types.ts`, `backend/tests/e2e/test_transition_section.py`
- Test: `frontend/tests/company.test.ts`

**Interfaces:**
- Consumes: Task 5's response.
- Produces:
  - **Targets part:** a table per target, then the progress line and the cite `ACT GE 1.4, GE pp.31–34`.
  - **Abatement coverage part:** the line, the action list and the cite.
  - **Phase-out part:** the table, the band-points note and the cite, or `No phase-out commitment disclosed`.
  - **Assumptions:** a Scenario column group and the cite.
  - Each target and phase-out figure opens its fact (`FactButton`, using `fact_ids`).

- [ ] **Step 1: Write a failing test** for one pure formatting helper you add to `companyQuery.ts`, if one is needed. Otherwise skip to Step 3.
- [ ] **Step 2: Run** `cd frontend && npm test`.
- [ ] **Step 3: Implement.** Use existing classes, as phases 1–2 did.
- [ ] **Step 4: Extend the e2e** with C's response (validated by `TransitionOut.model_validate`). Assert:
  - AC-89 (`Target progress 68.75% (ACT GE 1.4)`);
  - AC-119 (the coverage line);
  - AC-121, AC-126, AC-127, AC-128 (the cites);
  - AC-112 (with a no-phase-out variant).
  Save the screenshot to the session scratchpad, and delete `backend/test-results/` afterwards.
- [ ] **Step 5: Run** `npm run lint && npx tsc -b && npm test`, then the browser flow. Expected: PASS.
- [ ] **Step 6:** Run `/impeccable:impeccable audit` on the screenshot and fix findings within the section.
- [ ] **Step 7: Commit** `feat(alignment): Transition section delivery checks`.

### Task 7: Full checks and PR

- [ ] **Step 1:** Run `ruff`, the full backend suite on `arp_test_impl`, and the frontend checks. Expected: only the known environment failures.
- [ ] **Step 2:** Open a PR against `main` per steward:
  - title `Transition plan alignment: plan delivery checks`;
  - `Spec: plan-delivery-checks-design`;
  - `risk:high` (it touches shared extraction and review keys);
  - per-row coverage, with holdout rows run as unit and listed as owed;
  - every test change;
  - rulings D1–D4;
  - the owner signs benchmarks v2;
  - the evaluator rows: AC-89, AC-112, AC-119 to AC-121, AC-126 to AC-129;
  - `openwiki/` needs an update.
