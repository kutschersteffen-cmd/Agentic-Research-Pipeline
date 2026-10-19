# Transition Plan Alignment, Phase 1 (Benchmarks and capex) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the signed benchmarks file with its validator, `sign` and `/benchmarks`, the `sch_transition_capex` preset, ISIC scope with on-demand runs, the D01.a capex score with R&D tests and redlines, `GET /api/companies/{ref}/transition` with `capex`, and the capex part of the Transition section on the company page.

**Architecture:** A new package `backend/arp/transition_alignment/` holds `benchmarks.py` (file models, validator, sign, cached loader) and `capex.py` (pure scoring over fact rows, no DB). Facts are read with the existing `db/company_view.facts`, so the citation label is the Facts table's `source_label`. A new router serves `/api/transition-alignment/*` and `/api/companies/{ref}/transition`; the frontend adds one `TransitionSection` to the existing company page and reuses its trail and PDF viewer.

**Tech Stack:** Python 3.11, Pydantic v2, Typer, FastAPI, SQLAlchemy/Postgres, pytest; React + TypeScript, node:test, Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-10-19-transition-plan-alignment-design.md`. Read sections 1, 2, 3, 6, 7 and the Acceptance Fixtures before starting. Phase 2 (plan actions, barrier match, B02) and phase 3 (golden sets) are out of this plan.

## Global Constraints

- Message strings in the phase 1 rows are exact: the seven validator error forms (spec section 2), `Benchmarks v<version>: OK, <n> sectors, <r> redlines`, the D01.a `rule` texts, the R&D `rule` texts, `No reporting-year low-carbon capex share`, `No reporting-year R&D figures`, `breached` / `not breached` / `no disclosure`, `Not in scope: <reason>` with `ISIC <code> is not in a transition-barrier sector` or `No ISIC code`, headline `Low-carbon capex <share used>% vs benchmark <benchmark>%: <ratio shown>` or `Capex not scored: <reason>`.
- Numbers display with at most two decimals, rounded half up, trailing zeros dropped: reuse `arp.transition_barrier.render.fmt_number`.
- Shares and ratios are computed in `Decimal` and served as floats, so `30/50` gives `60`, not `60.00000000000001`.
- A fact counts only when current (`valid_to` null) and `approved`, `auto_accepted` or `edited`.
- Amounts are never converted between currencies; a share is computed from amounts only when both have the same unit.
- The model never outputs a score, ratio, share used, benchmark or redline status; the transition endpoint makes no model call.
- Taxonomy-eligible-but-not-aligned capex is never low-carbon; nuclear and CCS/CCUS are (spec section 2, "What counts as low-carbon"), written into every low-carbon field's instructions.
- A missing figure is `null` / not scored, never 0; a missing redline fact is `no disclosure`, never `not breached`.
- The barrier rule book, its ratings, bundled barrier data files and the four existing presets do not change.
- Tests make no network or model calls (`FakeLLMClient`, stubs). Postgres tests need `ARP_TEST_POSTGRES_DSN`; run `bash .claude/hooks/ensure-deps.sh backend` (and `postgres`, `frontend`) first.
- Checks per commit: `cd backend && ruff check . && python3 -m pytest tests/<file>`; frontend `cd frontend && npm run lint && npx tsc -b && npm test`.
- API model changes: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, fix `npx tsc -b`, commit both generated files; each new `request<T>()` with a response model gets a line in `frontend/src/api/contract.ts`.
- The PR body says `Spec: 2026-10-19-transition-plan-alignment-design`, lists every test change, and lists the holdout rows run as unit and owed.

## Review Focus

1. A benchmarks file with wrong JSON types (`"value": "80"`, `sectors` as a list, a redline without `fact`) must give validator lines and, at startup, an error naming the first, never a Pydantic traceback. Test in Task 2.
2. Low-carbon capex and total in different currencies (EUR vs USD), or a total of 0, must leave the computed share null (not scored when nothing is disclosed), not divide by zero or mix units. Test in Task 4.
3. A newer `pending_review` version or a `held` fact must not count, and the endpoint must still return the older counted value. Test in Task 5.
4. An in-scope company with no `tc_*` facts at all must return HTTP 200 with `Capex not scored: No reporting-year low-carbon capex share`, R&D tests not scored, redlines `no disclosure`. Test in Task 5.
5. A sector name with spaces and `&` (`Critical Minerals & Mining`) must work in the sector-run endpoint; an unknown sector is a 404 naming it. Test in Task 5.

---

## Rulings (choices the spec leaves open)

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| R1 | `sign_benchmarks` mirrors `sign_rule_book` and reuses its `compute_fingerprint`; `rule_book.py` is not edited. | Touching `rule_book.py` triggers the real-model barrier golden job in CI. | Ten duplicated lines; merge later if wanted. |
| R2 | The preset reads `sector_codes` from the **bundled** `benchmarks.json`, not the setting. | Field definitions must not vary with an env var; a test pins the union. | Narrowing prefixes needs a field version bump. |
| R3 | Bundled v1 is written at version 0 and signed to v1 by the builder with `approved_by` `"<owner, pending approval in this PR>"`; on approval the owner's name replaces it in `history` (history is outside the fingerprint). | CI and app startup need a valid file before approval; spec says the owner signs v1 here. | Owner re-signs to v2 instead; harmless. |
| R4 | Fiscal year = `period_end.year`; one fact per (field, year): basis `""` first, else lowest `fact_id`. | Deterministic, matches the green preset's period key. | A non-December year-end company keyed by end year, same as the rest of the app. |
| R5 | Redlines use the latest counted fact of the field across years. | Booleans may come from any report year. | An old "No" can stand until a newer report is reviewed. |
| R6 | The disclosed `tc_lowcarbon_rnd_share_pct` stands in for any R&D test whose numerator is `tc_lowcarbon_rnd` and denominator `tc_rnd_total` (keyed by the pair, not the test id). | Test ids are file content. | None found. |
| R7 | D01.a and the R&D rule share one helper `combine_years(earlier, later)`: later if higher, earlier/later equal, average if lower; only the labels differ. | The spec's R&D rule is D01.a shifted one year. | None. |
| R8 | `CompanyFactRow` gains `unit: str \| None` (the observation's unit text) so amounts read `300 EUR million`; `view.facts` is called once per preset field. | Canonical values are in base units (`EUR`, 3e8); one additive field beats a second query. | 15 small queries per page load. |
| R9 | Response field names beyond spec section 7: `capex.headline`, `capex.share_used_shown`, `capex.licence_note`, `benchmark.url`, `redlines[].fact_id`, `redlines[].source`, `rnd_tests[].ratio`, `rnd_tests[].fact_ids`. Phase-2 keys are served now as `regions: []`, `actions: []`, `assumptions: []`, `b02a: null`. | Headline tested server-side; AC-22/58 read `actions`. | Phase 2 replaces the untyped lists with models. |
| R10 | A benchmark `citation` is `<title> p.<page>` (or `<title>` when no page), with `url` beside it. | Same shape as a company fact citation (spec section 7). | Link-less owner-defined sources show text only. |
| R11 | Sector runs: `GET /api/transition-alignment/sectors/{sector}/companies` returns the in-scope `CompanyRef`s from the portfolio store; the caller posts them to `POST /api/extraction/start` (profile `custom`, the installed preset schema). No new UI button. | Spec: existing run start path, on demand only. | A person copies the list into the existing run screen. |
| R12 | Bundled `carbon_price` lists `STL-R1.price`, `CEM-R1.price`, `PWR-R1.price`, `CHM-R1.price`; `h2_cost` lists `STL-T1.h2_cost`, `CHM-T1.lc_cost`. | `CHM-R1.price` is the fourth carbon-price fact in the bundled rule book (USD/tCO2). | Phase 2 shows one more chemicals comparison; drop the entry. |
| R13 | F-TA in phase 1 is static files only; the ratification setup (STL-R1/STL-T1 EU) arrives with phase 2. | Phase 1 reads no barrier ratings. | None. |
| R14 | `scripts/mutation_check.py` also sets `ARP_TRANSITION_ALIGNMENT_DATA_DIR`. | API-starting tests now load benchmarks; mutmut's copied tree breaks `REPO_ROOT` paths, as it does for the barrier dir. | Nightly mutation run fails at startup. |

## Decisions for the owner

1. **AC-47 in phase 1.** The row says `PRESETS` holds the four plus `sch_transition_capex` **and** `sch_transition_plan_actions`; the second arrives in phase 2. Default: phase 1's test asserts four plus `sch_transition_capex`, and phase 2 adds the last key. Say so if you want an empty placeholder preset registered now instead.
2. **Sign benchmarks v1** in the PR (replace the pending `approved_by`, R3), after checking the bundled content table and the `act_levers` wording.

---

## File Structure

- Create `backend/arp/presets/transition_capex.py`: the 15 `tc_*` fields; modify `presets/registry.py`.
- Create `backend/arp/transition_alignment/{__init__.py,benchmarks.py,capex.py}` and `data/benchmarks.json`.
- Create `backend/arp/schemas/transition_alignment.py`: API response models.
- Create `backend/arp/cli/transition_alignment.py`; modify `cli/__init__.py`.
- Create `backend/arp/api/routers/transition_alignment.py`; modify `api/main.py` (router, lifespan check).
- Modify `backend/arp/config.py` (setting), `backend/arp/db/company_view.py` (`CompanyFactRow.unit`), `backend/scripts/mutation_check.py`.
- Tests: `backend/tests/test_presets_transition_capex.py`, `test_transition_alignment_benchmarks.py`, `test_transition_alignment_capex.py`, `tests/db/test_transition_alignment_api.py`, `tests/transition_alignment_helpers.py`, `tests/e2e/test_transition_section.py`; fixtures under `backend/tests/fixtures/transition_alignment/` (`presets_main.json`, `f_ta/`, `bm/benchmarks.json`).
- Frontend: `src/types.ts`, `src/api/client.ts`, `src/api/contract.ts`, `src/api/openapi.json`, `src/api/schema.gen.ts`, `src/pages/Company.tsx`, create `src/pages/company/TransitionSection.tsx`, `src/pages/company/companyQuery.ts`, `tests/company.test.ts`.

---

### Task 1: `sch_transition_capex` preset and snapshot S

**Files:**
- Create: `backend/arp/presets/transition_capex.py`, `backend/tests/fixtures/transition_alignment/presets_main.json`
- Modify: `backend/arp/presets/registry.py`
- Test: `backend/tests/test_presets_transition_capex.py`

**Interfaces:**
- Produces: `SCHEMA_ID = "sch_transition_capex"`; `FIELD_IDS: tuple[str, ...]` (the 15 ids of spec section 3, in that table's order); `BOOLEAN_FIELDS = ("tc_new_unabated_coal", "tc_new_blast_furnace", "tc_new_oil_gas_project")`; `build_transition_capex_schema() -> DataPointSchema`; `bundled_prefixes() -> list[str]` (union of `isic_prefixes` in `backend/arp/transition_alignment/data/benchmarks.json`, read as JSON, sorted). `PRESETS[SCHEMA_ID]` registered.
- Field rules: every field `high_risk=True`, `required=False`, `version=1`, `applicability_rules=ApplicabilityRules(sector_codes=bundled_prefixes())`. Amounts `CURRENCY_AMOUNT` with `CheckConfig(non_negative=True)` and the green preset's unit wording (`EUR million`, never convert); percentages `PERCENTAGE`, unit `%`, `min_value=0, max_value=100`; `tc_capex_denominator` `ENUM` `["eu_taxonomy", "cash_flow", "other"]`; booleans `BOOLEAN`. Planned fields: "report under the period_end of the planned fiscal year". Low-carbon fields carry the section 2 definition (ACT; nuclear and CCS/CCUS count; Taxonomy-aligned counts; eligible-but-not-aligned never; own definition only when it says what it includes). `tc_new_blast_furnace` carries "relining or rebuilding an existing furnace at the same capacity is not new build".
- Until Task 3 writes the bundled file, create a minimal `transition_alignment/data/benchmarks.json` holding only the nine sectors' `isic_prefixes` from spec section 1; Task 3 completes it.

- [ ] **Step 1: Record snapshot S from `main`** before editing anything: a one-off Python snippet writes, for each current `PRESETS` key, `[{field_id, data_type, version, high_risk, extraction_instructions}]` to `presets_main.json` (keys sorted, indent 2).
- [ ] **Step 2: Write the failing tests**

```python
def test_ac47_existing_presets_unchanged():
    snap = json.loads(SNAPSHOT.read_text())
    for pid, fields in snap.items():
        assert [_shape(f) for f in PRESETS[pid]().fields] == fields
    assert set(PRESETS) == set(snap) | {"sch_transition_capex"}  # phase 2 adds sch_transition_plan_actions

def test_capex_fields_and_types():
    s = build_transition_capex_schema()
    assert [f.field_id for f in s.fields] == list(FIELD_IDS) and len(FIELD_IDS) == 15
    assert all(f.high_risk and not f.required for f in s.fields)
    assert {f.field_id for f in s.fields if f.data_type == FieldDataType.BOOLEAN} == set(BOOLEAN_FIELDS)

def test_sector_codes_are_bundled_union():
    assert all(f.applicability_rules.sector_codes == bundled_prefixes() for f in build_transition_capex_schema().fields)
    assert {"241", "351", "2394", "1050"} - set(bundled_prefixes()) == {"1050"}

def test_ac48_out_of_scope_company_extracts_nothing():
    to_extract, skipped = plan_fields(build_transition_capex_schema(), CompanyRef(company_id="q", name="Fixture Foods SA", isic_code="1050"))
    assert to_extract == [] and {f.value_state for f in skipped} == {ValueState.NOT_APPLICABLE}

def test_lowcarbon_instructions_exclude_eligible_not_aligned():
    f = {f.field_id: f for f in build_transition_capex_schema().fields}["tc_lowcarbon_capex"]
    assert "eligible" in f.extraction_instructions and "nuclear" in f.extraction_instructions
```

- [ ] **Step 3: Run** `cd backend && python3 -m pytest tests/test_presets_transition_capex.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `transition_capex.py` and the registry line.
- [ ] **Step 5: Run** the test file plus `tests/test_presets_green.py tests/test_presets_eu_taxonomy.py`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(alignment): sch_transition_capex preset`.

### Task 2: Benchmarks file, validator and sign (library) with fixtures F-TA and BM

**Files:**
- Create: `backend/arp/transition_alignment/__init__.py`, `backend/arp/transition_alignment/benchmarks.py`
- Modify: `backend/arp/config.py` (beside `transition_barrier_data_dir`)
- Create: `backend/tests/fixtures/transition_alignment/f_ta/{criteria_schema.json,assessment_scores.json,source_registry.json,rule_book.json}`, `backend/tests/fixtures/transition_alignment/bm/benchmarks.json`, `backend/tests/transition_alignment_helpers.py`
- Test: `backend/tests/test_transition_alignment_benchmarks.py`

**Interfaces:**
- Consumes: `presets.transition_capex.FIELD_IDS`, `BOOLEAN_FIELDS`; `transition_barrier.rule_book.compute_fingerprint`; `transition_barrier.validation.read_and_validate(dir) -> (raw_rule_book, raw_schema, errors)` and `validation._unit(fact, facts)` for barrier fact units; `transition_barrier.dataset.data_dir()`.
- Produces in `benchmarks.py`:
  - `Settings.transition_alignment_data_dir: Path` (env `ARP_TRANSITION_ALIGNMENT_DATA_DIR`, default `REPO_ROOT / "backend/arp/transition_alignment/data"`); `data_dir() -> Path`.
  - `BENCHMARKS_FILE = "benchmarks.json"`; `STALE = "Benchmarks content changed but version is still"`; `MATRIX_SECTORS: tuple[str, ...]` (the nine names, bundled `criteria_schema.json` order); `class BenchmarksError(ValueError)`.
  - Models: `Source(title: str, url: str | None, page: str | None, rationale: str | None)`; `CapexBenchmark(value: float, unit: str = "%", method: str, source: Source, licence: str = "")`; `RndTest(id, label, numerator, denominator, value: float, unit: str = "%", source: Source)`; `Redline(id, label, fact, source: Source)`; `SectorEntry(isic_prefixes: list[str], capex: CapexBenchmark, rnd_tests: list[RndTest] = [], redlines: list[Redline] = [])`; `Assumption(label, unit, barrier_facts: list[str])`; `Benchmarks(version: int (strict), fingerprint, history: list[dict], licence_note: str, sectors: dict[str, SectorEntry], act_levers: dict[str, dict | None], assumptions: dict[str, Assumption])`.
  - `validate_benchmarks(raw: dict, raw_rule_book: dict, raw_schema: dict) -> list[str]`: errors in spec order 1-7; within a rule, file order. Rule 4 reports the shorter prefix of an overlapping pair, once per pair. "No source" = `source` missing or without a non-empty `title`. Raw-dict checks guard every type so bad shapes give a line; when only the stale-fingerprint error (or none) remains, a model backstop (as `_model_errors` in the barrier validator) reports Pydantic errors as `Benchmarks: invalid <path>: <msg>`.
  - `read_and_validate(directory: Path, barrier_dir: Path) -> tuple[dict, list[str]]`: raises `BenchmarksError("Benchmarks not found: <path>")` or `BenchmarksError("benchmarks.json is not valid JSON: ...")`.
  - `count_redlines(raw: dict) -> int`; `sign_benchmarks(directory: Path, approved_by: str, today: date) -> int` (as `sign_rule_book`: version+1, fingerprint, history entry `{version, fingerprint, approved_by, approved_at}`, 2-space indent, `ensure_ascii=False`; R1).
  - `check_benchmarks(directory: Path | None = None) -> None` raises `BenchmarksError(errors[0])`; `load_benchmarks(directory: Path | None = None) -> Benchmarks` (`lru_cache`); `reset_cache() -> None`; `sector_for_isic(b: Benchmarks, isic: str | None) -> str | None`; `citation(s: Source) -> str` (R10).
- Fixtures exactly as spec Acceptance: F-TA (STL-T1 then STL-R1, rule book v7 signed, Steel actions only, EUR→USD 1.08 for 2025; start from a copy of `tests/fixtures/transition_barrier/` and add STL-T1 with fact `h2_cost` USD/kg H2, `H` `h2_cost <= 2`, `M` `h2_cost <= 7`; six hand ratings with the spec's evidence; set `fingerprint` with `compute_fingerprint`, version stays 7). BM version 3 signed, valid against F-TA, contents per spec. `transition_alignment_helpers.py` fixture `ta_dirs(tmp_path, monkeypatch)` copies both to `tmp_path`, sets `ARP_TRANSITION_BARRIER_DATA_DIR` and `ARP_TRANSITION_ALIGNMENT_DATA_DIR`, clears `get_settings`, `dataset.reset_caches()` and `benchmarks.reset_cache()` before and after, yields `(f_ta, bm)`; helper `edit_bm(bm, fn)` loads, applies `fn(raw)`, writes back without re-signing.

- [ ] **Step 1: Write the failing tests** (each calls `read_and_validate(bm, f_ta)` after `edit_bm`):

```python
def test_bm_fixture_is_valid(ta_dirs): assert errors(ta_dirs) == []
def test_ac3_capex_no_source(ta_dirs):      # del Steel capex source, re-sign so only rule 2 fires
    assert "Steel: capex benchmark has no source" in errors_after(lambda r: r["sectors"]["Steel"]["capex"].pop("source"))
def test_ac4_unknown_sector(ta_dirs):       # add "Aluminium" (copy of Cement entry, prefix "242")
    assert "Sector not in the transition-barrier matrix: Aluminium" in ...
def test_missing_sector_entry(ta_dirs):     # drop Steel -> "Missing benchmarks entry: Steel"
def test_ac5_prefix_overlap(ta_dirs):       # Cement prefix "24" -> "ISIC prefix '24' is in two sectors"
def test_ac6_stale_fingerprint(ta_dirs):    # Steel capex 75 -> "Benchmarks content changed but version is still 3"
def test_ac7_missing_lever(ta_dirs):        # pop steel.ccus -> "No ACT lever entry for action: steel.ccus"
def test_ac64_unknown_lever(ta_dirs):       # add pwr.renewables -> "Unknown action in act_levers: pwr.renewables"
def test_ac8_unit_mismatch(ta_dirs):        # h2_cost lists STL-R1.price -> "Assumption 'h2_cost' is in USD/kg H2, 'STL-R1.price' is in USD/tCO2"
def test_unknown_barrier_fact(ta_dirs):     # "STL-R1.nope" -> "Assumption 'carbon_price' names unknown barrier fact 'STL-R1.nope'"
def test_unknown_field(ta_dirs):            # redline fact "tc_nope" -> "Steel: unknown field 'tc_nope'"
def test_ac67_sign(ta_dirs):                # after AC-6 edit: sign_benchmarks(bm, "owner", date(2026, 10, 19)) == 4
    # file version 4, history[-1] has version 4 and approved_by "owner"; errors == []; count_redlines == 2
def test_bad_types_give_lines_not_tracebacks(ta_dirs):  # Review Focus 1
    # capex value "80"; then sectors = []; each returns a non-empty list[str], no exception
def test_matrix_sectors_match_bundled_schema():
    assert list(MATRIX_SECTORS) == list(dict.fromkeys(c["sector"] for c in json.loads(BUNDLED_SCHEMA.read_text())["criteria"]))
def test_missing_file(tmp_path): # BenchmarksError, message starts "Benchmarks not found: "
```

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_transition_alignment_benchmarks.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the setting, `benchmarks.py` and the fixtures.
- [ ] **Step 4: Run** the test file plus `tests/test_transition_barrier_rule_book.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): benchmarks file validator and sign`.

### Task 3: CLI, app startup check, bundled v1 and `GET /api/transition-alignment/benchmarks`

**Files:**
- Create: `backend/arp/cli/transition_alignment.py`, `backend/arp/schemas/transition_alignment.py`, `backend/arp/api/routers/transition_alignment.py`
- Modify: `backend/arp/cli/__init__.py`, `backend/arp/api/main.py`, `backend/scripts/mutation_check.py`, `backend/tests/test_mutation_check.py` (one added assert), `backend/arp/transition_alignment/data/benchmarks.json` (full v1)
- Test: `backend/tests/test_transition_alignment_benchmarks.py`

**Interfaces:**
- Consumes: Task 2's `read_and_validate`, `sign_benchmarks`, `count_redlines`, `check_benchmarks`, `load_benchmarks`, `citation`, `STALE`.
- Produces: `arp transition-alignment benchmarks validate [--data-dir DIR]` (prints every error and exits 1, else the success line with `len(raw["sectors"])` and `count_redlines`); `benchmarks sign --approved-by NAME [--data-dir DIR]` (refuses on any error not starting with `STALE`, prints `Signed benchmarks v<n>`). `--data-dir` defaults to `benchmarks.data_dir()`; the barrier dir is always `dataset.data_dir()`. `lifespan` calls `check_benchmarks()` right after `check_rule_book()`.
- Response models in `schemas/transition_alignment.py`: `BenchmarkOut(value: float, unit: str, method: str, citation: str, url: str | None, licence: str)`; `RndTestDef(id, label, numerator, denominator, value: float, unit: str, citation: str)`; `RedlineDef(id, label, fact, citation: str)`; `SectorBenchmarksOut(sector, isic_prefixes, capex: BenchmarkOut, rnd_tests: list[RndTestDef], redlines: list[RedlineDef])`; `BenchmarksOut(version: int, licence_note: str, sectors: list[SectorBenchmarksOut])` (file order). Router `APIRouter(prefix="/api", tags=["transition-alignment"])`, `GET /transition-alignment/benchmarks -> BenchmarksOut`, included in `main.py` with `Depends(authorize)`.
- Bundled v1 content: spec section 2 table verbatim (values, method strings, page per row, R&D tests for Steel/Cement/Aviation/Shipping, redlines `pwr_coal`, `ogu_new_projects`, `stl_bf` with the owner-defined source and rationale), `licence_note` from the sketch, `act_levers` for all 30 bundled action ids from research 13.4(a) (`steel.h2_dri`, `steel.ccus`, `min.new_supply` null), `assumptions` per R12. Then `benchmarks sign` per R3.

- [ ] **Step 1: Write the failing tests** with `typer.testing.CliRunner`:
  - `test_ac66_bundled_validates`: both data-dir env vars unset (bundled dirs), `benchmarks validate` exit 0, output == `f"Benchmarks v{raw['version']}: OK, 9 sectors, 3 redlines"`.
  - `test_ac3_cli` (and one line each for AC-4, 5, 6, 7, 8, 64): exit 1, output contains the spec string.
  - `test_ac67_cli`: AC-6 edit, `sign --approved-by owner`, then `validate` prints `Benchmarks v4: OK, 3 sectors, 2 redlines`.
  - `test_sign_refuses_other_errors`: AC-3 edit, `sign` exit 1, output contains `Steel: capex benchmark has no source`, version unchanged.
  - `test_ac57_startup_refused`: AC-3 edit, `async with main.lifespan(main.app)` raises `BenchmarksError` matching `Steel: capex benchmark has no source` (as `test_transition_barrier_rule_book.py` does for the rule book).
  - `test_ac2_benchmarks_api`: bundled dirs, `GET /api/transition-alignment/benchmarks`: `capex.value` 95 Power & Utilities, 77 Oil & Gas Upstream and Chemicals, 80 the other six; every `capex.citation` contains `p.`.
- [ ] **Step 2: Run** the test file. Expected: FAIL (commands and route missing).
- [ ] **Step 3: Implement** CLI, models, route, lifespan line, `mutation_check.py` env entry (R14) and the bundled v1 file; sign it.
- [ ] **Step 4: Run** the test file, `tests/test_mutation_check.py`, `tests/test_transition_barrier_rule_book.py`. Expected: PASS.
- [ ] **Step 5: API contract:** `python scripts/export_openapi.py`, `cd frontend && npm run gen:api && npx tsc -b`. Expected: clean.
- [ ] **Step 6: Commit** `feat(alignment): benchmarks CLI, startup check, bundled v1, /benchmarks`.

### Task 4: Capex scoring (pure): D01.a, R&D tests, redlines

**Files:**
- Create: `backend/arp/transition_alignment/capex.py`
- Modify: `backend/arp/schemas/transition_alignment.py`
- Test: `backend/tests/test_transition_alignment_capex.py`

**Interfaces:**
- Consumes: Task 2's `SectorEntry`, `citation`; `fmt_number`.
- Produces in `capex.py`:
  - `@dataclass(frozen=True) class Fact: fact_id: int; field_id: str; year: int | None; value: Any; amount: Decimal | None; unit: str | None; shown: str; citation: str | None`. `amount` = canonical value if set, else the numeric value (bools excluded); `unit` = canonical unit if set, else the observation unit; `shown` = `"<fmt_number(value)> <observation unit>"` for numbers, `Yes`/`No` for booleans.
  - `combine_years(earlier: Decimal | None, later: Decimal | None) -> Decimal | None` (R7).
  - `share_for(facts: dict[tuple[str, int], Fact], year: int, planned: bool) -> ShareOut | None` (disclosed wins; else amount ÷ total × 100 when both counted, same `unit`, total ≠ 0).
  - `score_capex(facts: list[Fact], sector: SectorEntry, licence_note: str) -> CapexOut`; facts are indexed by (field_id, year) per R4.
- Models added to `schemas/transition_alignment.py`: `ShareOut(value: float, source: Literal["disclosed", "computed from amounts"], fact_ids: list[int])`; `AmountOut(field_id, year: int, shown: str, fact_id: int, citation: str | None)`; `RndResultOut(id, label, used: float | None, rule: str | None, benchmark: float, ratio: float | None, ratio_shown: str | None, not_scored: str | None, fact_ids: list[int])`; `RedlineOut(id, label, status: Literal["breached", "not breached", "no disclosure"], text: str, citation: str | None, fact_id: int | None, source: str)`; `CapexOut(reporting_year: int | None, share_ry: ShareOut | None, share_ry1: ShareOut | None, share_used: float | None, share_used_shown: str | None, rule: str | None, benchmark: BenchmarkOut, ratio: float | None, ratio_shown: str | None, not_scored: str | None, headline: str, amounts: list[AmountOut], rnd_tests: list[RndResultOut], redlines: list[RedlineOut], licence_note: str)`.
- Rules: RY = latest year with a counted `tc_capex_total`, `tc_lowcarbon_capex` or `tc_lowcarbon_capex_share_pct`. `rule` texts and the D01.a table exactly as spec section 3; `not_scored` replaces `rule` when RY share is missing. `ratio` = min(share ÷ benchmark, 1). R&D: per test, ratio per year (R6 stand-in), RY required, labels `Only RY known: RY used`, `RY higher: RY used`, `RY equal: RY used`, `RY lower: average of RY-1 and RY`; score min(used ÷ value, 1). `amounts` = every counted currency-amount `tc_*` fact for years RY−1..RY+1, preset field order then year. Redlines per R5.

- [ ] **Step 1: Write the failing tests.** A helper `defaults_c()` builds C's phase-1 `Fact`s from the spec's fixture table (canonical `EUR`, observation unit `EUR million`, citations `Fixture Steel Annual Report 2025 p.<n>` / `Fixture Steel Transition Plan 2025 p.18`); `steel()` and `cement()`/`power()` are BM's entries. Each test drops or replaces facts as the row's Given says.

```python
def test_ac9():
    c = score_capex(defaults_c(), steel(), "x")
    assert (c.reporting_year, c.share_used, c.rule, c.benchmark.value, c.ratio_shown) == (2025, 20, "RY+1 higher: RY+1 used", 80, "0.25")
    assert c.headline == "Low-carbon capex 20% vs benchmark 80%: 0.25"
def test_ac10():  # planned share 8 -> share_used 10, "RY+1 lower: average of RY and RY+1", "0.13"
def test_ac11():  # no planned share -> 12, "Only RY known: RY used", "0.15"
def test_ac12():  # no disclosed 2025 share -> share_ry == ShareOut(value=12, source="computed from amounts", fact_ids=[lowcarbon, total]); share_used 20
def test_ac13():  # no 2025 share/amount/total -> ratio None, not_scored "No reporting-year low-carbon capex share", headline "Capex not scored: No reporting-year low-carbon capex share"
def test_ac14():  # power(), share 97 -> benchmark.value 95, ratio_shown "1"
def test_ac15():  # amounts has ("tc_carbon_intensive_capex", 2025, "300 EUR million", citation "Fixture Steel Annual Report 2025 p.46") and ("tc_capex_total_planned", 2026, "1100 EUR million")
def test_ac70():  # no carbon-intensive fact -> no amounts entry with that field_id
def test_ac16():  # lc_share used 60 "RY higher: RY used" "0.75"; early_stage used 55 "RY lower: average of RY-1 and RY" "0.85"
def test_ac17():  # cement(), tc_lowcarbon_rnd 40 and tc_capex_total 1000 for 2025 -> capex_share used 4 "Only RY known: RY used" "0.8"
def test_ac61():  # no 2025 R&D facts -> reporting_year 2025; lc_share and early_stage not_scored "No reporting-year R&D figures"
def test_ac65():  # redlines == one entry stl_bf "not breached", citation "Fixture Steel Annual Report 2025 p.48"
def test_ac19_ac20():  # power(): Yes -> "breached" with P4 p.9 citation; absent -> "no disclosure", citation None
def test_mixed_currency_and_zero_total():  # Review Focus 2: lowcarbon USD vs total EUR, no disclosed share -> not_scored; total 0 -> not_scored, no exception
def test_share_is_exact():  # 70 / 1000 amounts -> share_ry.value == 7 (not 7.000000000000001)
```

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_transition_alignment_capex.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `capex.py` and the models (Decimal arithmetic throughout; floats only when building the models).
- [ ] **Step 4: Run** the test file. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alignment): D01.a capex score, R&D tests, redlines`.

### Task 5: `GET /api/companies/{ref}/transition`, scope and sector runs

**Files:**
- Modify: `backend/arp/api/routers/transition_alignment.py`, `backend/arp/schemas/transition_alignment.py`, `backend/arp/db/company_view.py` (`CompanyFactRow.unit`, R8)
- Modify: `backend/tests/transition_alignment_helpers.py` (seeding)
- Test: `backend/tests/db/test_transition_alignment_api.py`

**Interfaces:**
- Consumes: `view.facts`, `view.resolve_ref` (404 `Company not found` as `routers/companies.py::_resolve`), `m.Company.isic_code`, Task 2's `load_benchmarks`, `sector_for_isic`; `load_rule_book(dataset.data_dir())[0].version`; Task 4's `Fact`, `score_capex`; `get_portfolio_store().list_companies()`.
- Produces: `TransitionOut(in_scope: bool, reason: str | None, sector: str | None, benchmarks_version: int, rule_book_version: int, capex: CapexOut | None, regions: list[str] = [], actions: list[dict] = [], b02a: dict | None = None, assumptions: list[dict] = [])` (R9); routes `GET /api/companies/{ref}/transition -> TransitionOut` and `GET /api/transition-alignment/sectors/{sector}/companies -> list[CompanyRef]` (404 `Unknown sector: <sector>` when not in the benchmarks file). Facts: one `view.facts(s, cid, field_id=fid, limit=500)` per `FIELD_IDS`, kept when status counted, mapped to `Fact`.
- Helpers: `seed_defaults(pg) -> dict[str, UUID]` creates C, P, K, Q, N (names, ISIC, fiscal year end per spec), registers P2, P4 and P5 as documents with the spec titles, and records the phase-1 default facts (C's capex, R&D, `tc_new_blast_furnace` No, `tc_carbon_intensive_capex`, `green_capex_share_pct` 15 from P2 p.47, the planned facts from P1 p.18; Q's `capex_total` 200 from P5 p.8) as `approved` observations with `CitationIn(page=...)`, following `tests/db/test_company_api.py` (`ObservationIn` + `record` + `record_review_decision`). Install `sch_transition_capex` and `sch_green_lowcarbon` first so the `fields` rows exist.

- [ ] **Step 1: Write the failing tests** (fixtures `pg`, `ta_dirs`, `seed_defaults`; `client = TestClient(app)`):
  - `test_ac9_api`: C → `in_scope` true, `sector` `Steel`, `capex.reporting_year` 2025, `share_used` 20, `rule` `RY+1 higher: RY+1 used`, `benchmark.value` 80, `ratio_shown` `0.25`, `benchmarks_version` 3, `rule_book_version` 7.
  - `test_ac15_ac65_api`: amounts entry for `tc_carbon_intensive_capex` with `citation` `Fixture Steel Annual Report 2025 p.46`; `redlines` == one `stl_bf` `not breached` citing `p.48`.
  - `test_ac19_api`: P with `tc_new_unabated_coal` Yes recorded from P4 p.9 → `breached`, citation `Fixture Power Annual Report 2025 p.9`.
  - `test_ac21_no_model_call`: `monkeypatch` `arp.llm.factory.build_llm_client` and override `deps.get_llm_client` with a client that raises on any call → HTTP 200, `ratio_shown` `0.25`.
  - `test_ac22_ac58_out_of_scope`: Q → `in_scope` false, `reason` `ISIC 1050 is not in a transition-barrier sector`, `capex` null, `actions` `[]`; N → `reason` `No ISIC code`.
  - `test_pending_version_ignored` (Review Focus 3): record a newer `pending_review` 2025 share 50 for C → `share_ry.value` still 12 (the approved fact); a `held` planned share is likewise ignored.
  - `test_no_facts_in_scope` (Review Focus 4): K with no facts → 200, `capex.headline` `Capex not scored: No reporting-year low-carbon capex share`, every R&D test `not_scored`.
  - `test_ac23_run_to_fact`: delete C's 2025 capex facts; record a run result for `sch_transition_capex` whose field `tc_lowcarbon_capex_share_pct` = 12, `period_end` `2025-12-31`, citation P2 p.45 with the spec quote, review item queued (as `test_trail_contains_citation_page_and_decision`); `record_review_decision(..., "approve", ...)`; `GET /api/companies/C/facts?field_id=tc_lowcarbon_capex_share_pct` → one row, value 12, status `approved`, `source_label` `Fixture Steel Annual Report 2025 p.45`.
  - `test_ac45_green_fact_unchanged`: a `sch_transition_capex` run result for C with every field `not_found` recorded → `green_capex_share_pct` facts are exactly one row: 2025-12-31, 15, `approved`, `Fixture Steel Annual Report 2025 p.47`.
  - `test_ac48_api`: Q, record the (not-applicable) result rows for the capex preset → `GET /api/companies/Q/facts` is exactly the one `capex_total` row (200, `approved`, `Fixture Foods Report 2025 p.8`).
  - `test_sector_companies` (Review Focus 5): portfolio store holds C (`2410`) and Q (`1050`); `GET /api/transition-alignment/sectors/Steel/companies` → `[C]`; `.../sectors/Critical%20Minerals%20%26%20Mining/companies` → `[]`; `.../sectors/Aluminium/companies` → 404 `Unknown sector: Aluminium`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/db/test_transition_alignment_api.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the model, routes, `CompanyFactRow.unit = obs.unit`, and the helpers.
- [ ] **Step 4: Run** the test file plus `tests/db/test_company_api.py`. Expected: PASS.
- [ ] **Step 5: API contract** as in Task 3 Step 5.
- [ ] **Step 6: Commit** `feat(alignment): company transition endpoint and sector run list`.

### Task 6: Transition section (capex part) on the company page

**Files:**
- Create: `frontend/src/pages/company/TransitionSection.tsx`, `backend/tests/e2e/test_transition_section.py`
- Modify: `frontend/src/types.ts` (`CompanyTransition` and nested types mirroring Task 4/5 models), `frontend/src/api/client.ts`, `frontend/src/api/contract.ts`, `frontend/src/pages/company/companyQuery.ts`, `frontend/src/pages/Company.tsx`
- Test: `frontend/tests/company.test.ts`

**Interfaces:**
- Consumes: `GET /api/companies/{ref}/transition` (Task 5), `api.getFactTrail`, `Company.tsx`'s `openCitation`, `InspectorModal`.
- Produces: `api.getCompanyTransition(ref: string) => request<CompanyTransition>(\`/api/companies/${encodeRef(ref)}/transition\`)`; contract line `Satisfies<Served<S["TransitionOut"]>, CompanyTransition>`; `primaryCitation(trail: FactTrail): FactCitation | null` in `companyQuery.ts` (the primary citation of the version with `valid_to === null`); `TransitionSection({ data, error, onOpenFact }: { data: CompanyTransition | null; error: string; onOpenFact: (factId: number, el: HTMLElement) => void })`.
- Behaviour: placed after the summary, before Facts, heading `Transition`. Out of scope: only `Not in scope: <reason>`. In scope: `capex.headline`; RY and RY+1 shares (each a button opening `fact_ids[0]`), amounts (buttons), benchmark with method and `citation` (link to `url` when set), R&D tests (`label`, `used`%, `rule` or `not_scored`, `ratio_shown`), redlines (`text`, `status`, citation button when `fact_id`), `licence_note`. `onOpenFact` in `Company.tsx` fetches the trail and opens `primaryCitation` with `openCitation`; with none, it selects the fact so the existing trail drawer opens. Layout per `DESIGN.md`, existing classes only.

- [ ] **Step 1: Write the failing test** in `tests/company.test.ts`: `primaryCitation` returns the current version's primary citation, ignores a superseded version's and a corroborating one, and returns `null` when the current version has no primary.
- [ ] **Step 2: Run** `cd frontend && npm test`. Expected: FAIL (`primaryCitation` not exported).
- [ ] **Step 3: Implement** types, client method, contract line, helper, section, and the `Company.tsx` wiring.
- [ ] **Step 4: Write the e2e test** `test_transition_section.py` in the style of `tests/e2e/test_schema_rules.py`: Playwright routes `/api/companies/C`, `/api/companies/C/facts*` and `/api/companies/C/transition` to fixed JSON (C's AC-9 response) and Q's out-of-scope response; asserts the text `Low-carbon capex 20% vs benchmark 80%: 0.25` on C's page and `Not in scope: ISIC 1050 is not in a transition-barrier sector` on Q's; saves a screenshot of C's page to `test-results/transition-section.png`.
- [ ] **Step 5: Run** `cd frontend && npm run lint && npx tsc -b && npm test`, then the CLAUDE.md browser flow (`ensure-deps.sh postgres`, `e2e_stack.sh up`, `pytest -m e2e tests/e2e/test_transition_section.py`, `e2e_stack.sh down`). Expected: PASS.
- [ ] **Step 6: Run** `/impeccable:impeccable audit` on the screenshot; fix findings within the section only.
- [ ] **Step 7: Commit** `feat(alignment): Transition section capex part`.

### Task 7: Full checks and PR

**Files:** none new.

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest` (with `ARP_TEST_POSTGRES_DSN`); frontend checks. Expected: all pass. Optional: `python scripts/mutation_check.py --base origin/main` if the PR gets `risk:high`.
- [ ] **Step 2:** Open the PR against `main` per `.claude/skills/steward/SKILL.md`: title `Transition plan alignment phase 1: benchmarks and capex`, `Spec: 2026-10-19-transition-plan-alignment-design`, a `risk:` label, the coverage table below, holdout rows run as unit and owed, every test change (including the added assert in `test_mutation_check.py`), the rulings table, the two owner items, and whether `openwiki/` needs an update (yes: new module, endpoints and page section; regenerated by `/context-refresh`, not by hand).

---

## Acceptance coverage (phase 1)

| AC | Task | Test |
|---|---|---|
| AC-66 | 3 | `test_ac66_bundled_validates` |
| AC-2 | 3 | `test_ac2_benchmarks_api` |
| AC-3 | 2, 3 | `test_ac3_capex_no_source`, `test_ac3_cli` |
| AC-4 | 2, 3 | `test_ac4_unknown_sector` + CLI line |
| AC-5 | 2, 3 | `test_ac5_prefix_overlap` + CLI line |
| AC-6 | 2, 3 | `test_ac6_stale_fingerprint` + CLI line |
| AC-7 | 2, 3 | `test_ac7_missing_lever` + CLI line |
| AC-8 | 2, 3 | `test_ac8_unit_mismatch` + CLI line |
| AC-64 | 2, 3 | `test_ac64_unknown_lever` + CLI line |
| AC-67 | 2, 3 | `test_ac67_sign`, `test_ac67_cli` |
| AC-57 | 3 | `test_ac57_startup_refused` |
| AC-9 | 4, 5 | `test_ac9`, `test_ac9_api` |
| AC-10, AC-11, AC-12, AC-13, AC-14 | 4 | `test_ac10` … `test_ac14` |
| AC-15 | 4, 5 | `test_ac15`, `test_ac15_ac65_api` |
| AC-70 | 4 | `test_ac70` |
| AC-16, AC-17, AC-61 | 4 | `test_ac16`, `test_ac17`, `test_ac61` |
| AC-65 | 4, 5 | `test_ac65`, `test_ac15_ac65_api` |
| AC-19 | 4, 5 | `test_ac19_ac20`, `test_ac19_api` |
| AC-20 | 4 | `test_ac19_ac20` |
| AC-21 | 5 | `test_ac21_no_model_call` |
| AC-22, AC-58 | 5 | `test_ac22_ac58_out_of_scope` |
| AC-23 | 5 | `test_ac23_run_to_fact` |
| AC-51, AC-44 | 6 | e2e `test_transition_section.py`; evaluator in the running app |
| AC-52 | 6 | `primaryCitation` unit test; evaluator in the running app |
| AC-45 (must not change) | 5 | `test_ac45_green_fact_unchanged` |
| AC-47 (must not change) | 1 | `test_ac47_existing_presets_unchanged` (owner item 1) |
| AC-48 (must not change) | 1, 5 | `test_ac48_out_of_scope_company_extracts_nothing`, `test_ac48_api` |

AC-46 (barrier files and ratings unchanged) starts in phase 2; phase 1 edits no barrier file.
