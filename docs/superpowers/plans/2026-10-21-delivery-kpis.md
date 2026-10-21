# Sector Delivery KPIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nine sector delivery KPIs in `GET /api/companies/{ref}/transition` and a "Delivery KPIs" table in the
company page's Transition section, each showing the actual figure, a sourced range and the matching plan actions.

**Architecture:**
- A new extraction preset holds the nine percentage fields.
- The benchmarks file (v3) holds each KPI's range, levers and cite.
- A pure `transition_alignment/delivery_kpis.py` picks the latest counted fact and builds the range text,
  the marker position and the action links.
- The router adds the result to `TransitionOut`, and `TransitionSection.tsx` renders one table.

**Tech Stack:** FastAPI, Pydantic v2, Typer, pytest, React/TS, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-21-delivery-kpis-design.md` (owner approved 2026-10-21). It builds on the
phase 1–2, delivery-checks and consistency-flags specs, which define fixtures C, K, Q, P8 and A1–A3.

## Global Constraints

- Code builds every range, position and match. The model only extracts. Tests make no network or model calls.
- Copy verbatim from the spec:
  - the KPI table (§1: ids, labels, fields, points, levers, cites);
  - the range text format and the `position_pct` rule (§3);
  - the note text `No delivery KPI for this sector.`
- Must not change: every earlier result (AC-2 to AC-166).
- DB tests use `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test_impl`. The Stop hook uses
  `arp_test`.

## Rulings

| # | Ruling | Why |
|---|---|---|
| D1 | `bm` and `bm_s` gain the `delivery_kpis` blocks. Their `fingerprint` is recomputed (`compute_fingerprint`), and `version` and `history` stay as they are (3 and 4). | AC-6 pins BM's message `… version is still 3`. Signing would bump it. |
| D2 | A KPI's `cite` is a plain string, plus an optional `url`. The other blocks' `source` objects are left untouched. | The spec's response and rows use `cite` strings. |
| D3 | For AC-200, the KPI e2e test points `ARP_TRANSITION_BARRIER_DATA_DIR` at a copy of `f_ta`. In the copy, `cement.alt_fuels` is added to the `actions` of one criterion that has a European Union score. `f_ta` itself is not changed. The copy must pass the barrier validator. | It gives K1 a barrier row without changing any earlier result or `rule_book_version`. |
| D4 | The new companies H, X and F and document P9–P10 are seeded only by helpers that a test calls, like `ON_REQUEST`. | `COMPANIES` drives `seed_defaults`, and sector listings must not change. |

## Review Focus

1. A fact whose `value` is stored as a string (e.g. `"14"`) must still give a number, or `value` null. It must never
   raise. Test in Task 3.
2. A value above 100 or below 0 slipping past review: the position is clamped to 0–100. A negative value gives
   `position_pct` 0.0. Test in Task 3.
3. A company with ISIC 4923 must get only `fleet_lc_share`, never `zev_sales_share`, through the KPI-level prefixes.
   This is AC-174; add the negative assert there.
4. The validator must not crash when `delivery_kpis` is not a list, or when `points` holds a non-number. It reports
   one error line instead. Test in Task 2.
5. On a 390 px screen, the long range text (`0% → 37% (2030) → …`) wraps inside its cell. This is evaluator
   row AC-191; check it in the Task 4 screenshot.

---

### Task 1: Delivery-KPI preset

**Files:**
- Create: `backend/arp/presets/transition_delivery_kpis.py`
- Modify: `backend/arp/presets/registry.py`, and `backend/tests/transition_alignment_helpers.py`
  (`seed_defaults` installs the preset)
- Test: `backend/tests/test_presets_transition_delivery_kpis.py`

**Interfaces:**
- Produces:
  - `SCHEMA_ID = "sch_transition_delivery_kpis"`;
  - `FIELD_PREFIXES: dict[str, tuple[str, ...]]`, field id → ISIC prefixes, in spec §1 order;
  - `build_transition_delivery_kpis_schema() -> DataPointSchema`.
- Follows `presets/transition_capex.py`'s `_field` pattern for percentages: unit `%`, `CheckConfig(min_value=0,
  max_value=100)`, `high_risk=True`, `required=False`, `version=1`, and
  `ApplicabilityRules(sector_codes=list(prefixes))`.
- Each field's extraction instructions are its spec §2 sentence, followed by capex's `_COMMON` per-year wording
  without the currency part.

- [ ] **Step 1: Write the failing test** `test_ac186_delivery_kpi_preset`:
  - nine fields, in the order `tc_alt_fuel_share_pct`, `tc_nh3_electrolytic_pct`, `tc_meoh_electrolytic_pct`,
    `tc_electrolysis_lc_power_pct`, `tc_ccs_capex_share_pct`, `tc_zev_sales_share_pct`, `tc_fleet_lc_share_pct`,
    `tc_saf_share_pct`, `tc_ship_lc_fuel_share_pct`;
  - each field `high_risk`, unit `%`, min 0, max 100;
  - sector codes: `tc_alt_fuel_share_pct` `["2394"]`, the three chemicals fields `["201"]`, CCS `["061","062"]`,
    ZEV `["2910"]`, fleet `["4923"]`, SAF `["511"]`, ship `["501","502"]`;
  - the schema is installable through the registry.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_presets_transition_delivery_kpis.py -v`.
  Expected: FAIL.
- [ ] **Step 3: Implement** the preset and register it.
- [ ] **Step 4: Run** the file, plus `tests/test_presets_*.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): delivery KPI preset`.

### Task 2: Benchmarks v3 with delivery KPIs

**Files:**
- Modify:
  - `backend/arp/transition_alignment/benchmarks.py`;
  - `backend/arp/transition_alignment/data/benchmarks.json`;
  - `backend/arp/schemas/transition_alignment.py`;
  - `backend/arp/api/routers/transition_alignment.py` (`get_benchmarks`);
  - `backend/tests/fixtures/transition_alignment/{bm,bm_s}/benchmarks.json` (ruling D1).
- Test: `backend/tests/test_transition_alignment_benchmarks.py` (extend), and the CLI tests in its existing file.

**Interfaces:**
- Consumes: Task 1 `FIELD_PREFIXES`.
- Produces:
  - `KpiPoint(value: float, year: int | None = None)`;
  - `DeliveryKpi(id, label, field, isic_prefixes: list[str] = [], levers: list[str] = [], points: list[KpiPoint],
    cite: str, url: str | None = None, note: str | None = None)`;
  - `SectorEntry.delivery_kpis: list[DeliveryKpi] = []`;
  - `range_text(points: list[KpiPoint]) -> str` (spec §3);
  - `kpi_prefixes(sector: SectorEntry, kpi: DeliveryKpi) -> list[str]`: the KPI's prefixes, or the sector's
    when the KPI has none;
  - `SectorBenchmarksOut.delivery_kpis: list[KpiDefOut]`, where `KpiDefOut(id, label, field_id, isic_prefixes,
    range_text, levers, cite)` and `isic_prefixes` is always the resolved list.
- Validator: one new rule function, run after `_rule6`, giving one line per error. It covers the four §1 checks:
  - the field is in `FIELD_PREFIXES`, and its prefixes cover every resolved KPI prefix;
  - the KPI prefixes are a subset of the sector's;
  - the points are non-empty, numeric, in (0, 100], with values strictly rising and years strictly rising;
  - `cite` matches `\bpp?\.\s?\d`.

  Every line starts with `<sector>: delivery KPI '<id>'` and names the field when the field is the problem.
  Non-list or non-object input gives one line, never an exception (Review Focus 4).

- [ ] **Step 1: Write failing tests:**
  - AC-178 to AC-182 against the API on the bundled file. `ta_dirs` sets the data dir, so point it at the bundled
    dir the way the existing bundled-file tests do.
  - AC-183: the CLI on the bundled dir prints exactly `Benchmarks v3: OK, 9 sectors, 3 redlines`.
  - AC-184, AC-185, AC-192 to AC-195, AC-204, AC-205: `validate --data-dir` on an edited BM copy (`edit_bm`).
  - AC-199: compare each sector's `isic_prefixes`, `capex`, `rnd_tests` and `redlines` with a frozen copy of v2's
    `sectors`, saved before editing as `tests/fixtures/transition_alignment/bm_v2_sectors.json`.
  - Review Focus 4: `delivery_kpis: "x"` and `points: [{"value": "a"}]` each give exit ≠ 0 with one line.
  - `range_text` unit cases for the three point shapes in spec §1.
- [ ] **Step 2: Run** the test files. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the models, rule, `range_text`, `kpi_prefixes` and the `BenchmarksOut` mapping. Add
  the §1 table to the bundled `benchmarks.json`:
  - each KPI gets its `cite` and `url`;
  - aviation and shipping get `note` `Sum of the fuel rows on p.94 (ours); the IEA prints no total.`;
  - fleet gets the MPP url from `docs/TRANSPORT_KPI_BENCHMARKS_RESEARCH.md` §2.

  Then run `arp transition-alignment benchmarks sign --approved-by kutschersteffen-cmd`. Expected:
  `Signed benchmarks v3`. Update `bm` and `bm_s` per ruling D1.
- [ ] **Step 4: Run** the files, plus `tests/test_transition_alignment_*.py` and `tests/db/test_transition_alignment_api.py`.
  Expected: PASS, with every earlier test unchanged.
- [ ] **Step 5: API contract.** Run `python scripts/export_openapi.py`, then `cd frontend && npm run gen:api && npx tsc -b`.
  Commit the generated files.
- [ ] **Step 6: Commit** `feat(alignment): delivery KPI ranges in benchmarks v3`.

### Task 3: Delivery KPIs in `/transition`

**Files:**
- Create: `backend/arp/transition_alignment/delivery_kpis.py`
- Modify:
  - `backend/arp/schemas/transition_alignment.py` (`KpiOut`, and `TransitionOut.delivery_kpis` and
    `delivery_kpis_note`);
  - `backend/arp/api/routers/transition_alignment.py`;
  - `backend/tests/transition_alignment_helpers.py` (fixtures, ruling D4).
- Test: `backend/tests/test_transition_alignment_delivery_kpis.py` (pure), and
  `backend/tests/db/test_transition_alignment_api.py` (API rows).

**Interfaces:**
- Consumes:
  - Task 2's `DeliveryKpi`, `range_text` and `kpi_prefixes`;
  - the router's counted facts for the nine Task 1 fields, read with the existing `_company_facts` (counted
    statuses `_COUNTED`; same tie rule as capex);
  - `scored.actions`.
- Produces:
  - `score_delivery_kpis(sector: SectorEntry, isic: str, facts: list[Fact], actions: list[ActionOut])
    -> tuple[list[KpiOut], str | None]`;
  - `KpiOut(id, label, field_id, cite, value: float | None, year: int | None, fact_ids: list[int], range_text,
    position_pct: float | None, action_keys: list[str])`, with exactly these keys (AC-198);
  - `TransitionOut.delivery_kpis: list[KpiOut] = []` and `delivery_kpis_note: str | None = None`.
- Rules:
  - the latest `period_end` wins, and ties go to the lowest fact id;
  - `position_pct = round(min(max(value, 0) / points[-1].value, 1) * 100, 1)`;
  - an empty list for an in-scope sector gives the note.
- Fixture helpers:
  - `publish_kpi(pg, run_store, ids, name)` for K's alt-fuel fact (P8 p.12, FY2025, quote per spec);
  - `seed_kpi_companies(pg) -> dict` for H, X and F with P9 and P10;
  - an `ACTIONS["K1"]` entry per spec;
  - K's FY2024 fact (10, P8 p.13) only for AC-196.

- [ ] **Step 1: Write failing tests:**
  - pure: Review Focus 1 and 2; the tie rule; the three point shapes;
  - API: AC-167 to AC-177, AC-196, AC-197, AC-198, AC-206;
  - AC-174 also asserts that no `zev_sales_share` entry appears (Review Focus 3);
  - AC-197 publishes K's fact to review without approving it.
- [ ] **Step 2: Run** both files. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Add the nine field ids to the router's fact read for in-scope companies only.
- [ ] **Step 4: Run** both files, plus every `tests/*transition_alignment*` file. Expected: PASS.
- [ ] **Step 5: API contract.** Run the Task 2 step 5 commands again, and add `delivery_kpis` to
  `frontend/src/types.ts` if the section reads types from there.
- [ ] **Step 6: Commit** `feat(alignment): delivery KPIs in /transition`.

### Task 4: Delivery KPIs table

**Files:**
- Modify:
  - `frontend/src/pages/company/TransitionSection.tsx`;
  - `frontend/src/types.ts` if not generated;
  - `backend/tests/e2e/test_transition_section.py`.

**Interfaces:**
- Consumes: Task 3's response.
- Produces: the part per spec §4. It goes right before the Plan actions heading, with:
  - the heading `Delivery KPIs`;
  - a table with the caption `Delivery KPIs; choose a figure to open its source` (visually hidden, as the other
    tables do);
  - columns `KPI | Actual | Year | Range | Action · barrier`.

  The Actual cell uses `FactButton` with the label `<KPI label>: <n>%`, or a muted `not disclosed`.
  The bar is a `div` with `aria-hidden="true"` and an inner marker styled `left: <position_pct>%`.
  The action cell shows `action_id`, then each barrier's region and the rating chip used in Plan actions; with
  no action, `—`.
  It uses existing classes and tokens only, and the range text wraps inside its cell.

- [ ] **Step 1: Implement** the part.
- [ ] **Step 2: Extend the e2e:**
  - a K variant with K's fact and K1, using the `f_ta` copy from ruling D3: assert AC-187, AC-188, AC-200,
    AC-201 and AC-203 (read the marker's `style.left`);
  - an X variant: AC-189 and AC-202;
  - C: AC-190;
  - H at a 390 px viewport: AC-191 (`document.documentElement.scrollWidth <= 390`);
  - save screenshots of each variant to the scratchpad, then delete `backend/test-results/`.
- [ ] **Step 3: Run** `cd frontend && npm run lint && npx tsc -b && npm test`, then the browser flow. Expected: PASS.
- [ ] **Step 4: Run** `/impeccable:impeccable audit` on the screenshots, and fix any findings inside the part.
- [ ] **Step 5: Commit** `feat(alignment): Delivery KPIs table`.

### Task 5: Full checks and PR

- [ ] Run:
  - `ruff check .`;
  - the full backend suite on `arp_test_impl` (known environment-only failures as before);
  - the frontend checks;
  - the final whole-branch review.
- [ ] Open the PR against `main`:
  - Title: `Transition plan alignment: sector delivery KPIs`.
  - Body line: `Spec: delivery-kpis-design`.
  - Label: `risk:normal`. It adds a preset and touches no shared extraction or review code.
  - Body contents:
    - per-row coverage;
    - test changes, including the fixture edits (D1, D3, D4);
    - rulings D1–D4;
    - evaluator rows AC-187 to AC-191 and AC-200 to AC-203;
    - a note that the benchmarks v3 values were approved with the spec.
