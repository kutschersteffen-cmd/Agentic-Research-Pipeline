# Transition Barrier Rule Book — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the rule book: format, validator, signing, rendering, the `/criteria` change, the export and Word report change, and version 1 content for all 35 criteria, which the owner approves in this PR.

**Architecture:** A new `rule_book.json` sits beside the existing barrier data files, in a directory the setting `ARP_TRANSITION_BARRIER_DATA_DIR` chooses. `arp/transition_barrier/rule_book.py` loads and fingerprints it, `validation.py` checks it against `criteria_schema.json`, and `render.py` turns conditions into sentences. `dataset.load_criteria()` fills each criterion's `rating_rubric` from those sentences, so every existing reader (API, CLI, Decision Studio, Word report) keeps working. No derivation, review or extraction code in this phase.

**Tech Stack:** Python 3.11, Pydantic v2, Typer, FastAPI, pytest; Node (`docx`) for the Word report script.

**Spec:** `docs/superpowers/specs/2026-10-17-transition-barrier-rule-book-design.md` (approved 2026-10-18). Read sections 1 and 7 and the Fixtures part of Acceptance before starting.

## Global Constraints

- Phase 1 acceptance rows: AC-14, AC-17, AC-20, AC-25, AC-74 to AC-95, AC-142, AC-149, AC-153, and the must-not-change rows AC-130/AC-131 (existing fields only), AC-132, AC-133, AC-135, AC-136, AC-155. Message strings in these rows are exact.
- The bundled files under `backend/arp/transition_barrier/data/` are edited only by this PR's content tasks, never at run time.
- Numbers display with at most two decimals, rounded half up on the decimal value, trailing zeros dropped (`72`, `9.37`, `10`).
- Fingerprint: SHA-256 hex of `json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`, where `content` is the rule book without `fingerprint` and `history`.
- Validator prints every error, one per line, in the spec's rule order 1–9; success line `Rule book v<version>: OK, <n> criteria, <m> open thresholds`.
- Version 1 content invents no number: a threshold without a defensible source is an open parameter with its question.
- API model changes: run `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, fix `npx tsc -b`, commit both generated files.
- Checks before each commit: `cd backend && ruff check . && python3 -m pytest tests/<file>`; run `bash .claude/hooks/ensure-deps.sh backend` first.
- The PR body says `Spec: 2026-10-17-transition-barrier-rule-book-design` and lists every test change.

## Review Focus

1. A rule book with a wrong JSON type (a param `value` of `"50"`, a level that is a list) must give a validator error line naming the criterion, not a Pydantic traceback. Test in Task 3.
2. A data directory without `rule_book.json` must fail with `Rule book not found: <path>` (CLI exit 1, app startup refused), not a `FileNotFoundError` trace. Test in Task 5.
3. Reformatting `rule_book.json` (key order, indentation, a non-ASCII `×` in a rationale) must not change the fingerprint. Test in Task 2.
4. `RULE_BOOK.md` must come out byte-identical on every render, in `criteria_schema.json` order, so its diff only shows real changes. Test in Task 4.
5. Existing readers that don't know the rule book (staleness, refresh router, Decision Studio) must see the same 35 criteria and 105 cells as before. Covered by the existing tests, run in Task 7.

---

## File Structure

- Modify `backend/arp/config.py`: `transition_barrier_data_dir` setting.
- Modify `backend/arp/transition_barrier/dataset.py`: read files from the data directory; fill `rating_rubric` from the rule book; `reset_caches()`.
- Modify `backend/arp/schemas/transition_barrier.py`: `Tier`; `PrimarySource.key/tier/cadence`; `BarrierCriterion` gains `rationale`, `actions`, `facts`, `params`, `rule_book_version`.
- Create `backend/arp/transition_barrier/rule_book.py`: models, `load_rule_book`, `compute_fingerprint`, `sign_rule_book`.
- Create `backend/arp/transition_barrier/validation.py`: `validate_rule_book`.
- Create `backend/arp/transition_barrier/render.py`: `fmt_number`, `render_group`, `rubric`, `render_rule_book_md`.
- Modify `backend/arp/cli/transition_barrier.py`: `rules validate|sign|render`, `export`.
- Modify `backend/arp/api/routers/transition_barrier.py`: `/criteria/{code}` new fields.
- Modify `backend/arp/api/main.py`: validate the rule book first in `lifespan`.
- Modify `scripts/build_transition_barrier_report.js`: read an export file.
- Create `backend/tests/fixtures/transition_barrier/` (fixture F) and tests `backend/tests/test_transition_barrier_rule_book.py`, `test_transition_barrier_render.py`.
- Content: `backend/arp/transition_barrier/data/rule_book.json`, `criteria_schema.json`, `source_registry.json`, `docs/transition_barrier/RULE_BOOK.md`, `docs/transition_barrier/RULE_BOOK_V1_IMPACT.md`, `docs/TRANSITION_BARRIER_ASSESSMENT.md`.

---

### Task 1: Data directory setting and fixture F

**Files:**
- Modify: `backend/arp/config.py` (next to `transition_barrier_staleness_days`)
- Modify: `backend/arp/transition_barrier/dataset.py`
- Create: `backend/tests/fixtures/transition_barrier/{criteria_schema.json,assessment_scores.json,source_registry.json}`
- Test: `backend/tests/test_transition_barrier_rule_book.py`

**Interfaces:**
- Produces: `Settings.transition_barrier_data_dir: Path` (env `ARP_TRANSITION_BARRIER_DATA_DIR`, default `REPO_ROOT / "backend/arp/transition_barrier/data"`, i.e. the current `_DATA_DIR`); `dataset.data_dir() -> Path`; `dataset.reset_caches() -> None`; existing loaders read `data_dir()` when `path` is None. Test fixture `fixture_dir` (pytest, in the test file or `tests/conftest.py`): copies `tests/fixtures/transition_barrier/` to `tmp_path`, sets the env var, clears `get_settings` and dataset caches, yields the path.
- Fixture F content exactly as the spec's Fixtures section: one criterion `STL-R1` whose `primary_sources` are, in order, keys `eu_ets_report` (D1, title "EU ETS Market Report 2026", url `https://climate.ec.europa.eu/eu-ets-market-report-2026.pdf`, tier `primary`, cadence `annual`), `cbam_regulation` (D2 "CBAM Regulation 2023/956", `primary`), `steel_policy_tracker` (D3 "Steel Policy Tracker", `secondary`); three scores (EU `H`, US `L`, China `L`, `last_verified` 2026-08-14); a registry derived from the schema. `rule_book.json` comes in Task 2.

- [ ] **Step 1:** Write `test_data_dir_setting_switches_files(fixture_dir)`: `len(load_criteria()) == 1` and `[s.region.value for s in load_scores()] == ["European Union", "United States", "China"]`; and `test_bundled_default_unchanged()`: with the env var unset, `len(load_criteria()) == 35` and `len(load_scores()) == 105`.
- [ ] **Step 2:** Run `cd backend && python3 -m pytest tests/test_transition_barrier_rule_book.py -v`. Expected: FAIL (setting and fixture missing).
- [ ] **Step 3:** Add the setting, `data_dir()`, `reset_caches()` (calls `cache_clear()` on the three loaders), make loaders resolve paths from `data_dir()`. Create the fixture files (the Task 7 schema fields `key`, `tier`, `cadence` are already present in F).
- [ ] **Step 4:** Run the test file plus `tests/test_transition_barrier_dataset.py tests/test_api_transition_barrier.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(barrier): data directory setting and fixture`.

### Task 2: Rule book models, fingerprint and `rules sign`

**Files:**
- Create: `backend/arp/transition_barrier/rule_book.py`
- Modify: `backend/arp/schemas/transition_barrier.py` (`Tier` enum, `PrimarySource.key: str | None`, `tier: Tier | None`, `cadence: Literal["annual","quarterly"] | None`, all defaulting to None until Task 7 fills the bundled file)
- Create: `backend/tests/fixtures/transition_barrier/rule_book.json` (RB, version 7, signed)
- Test: `backend/tests/test_transition_barrier_rule_book.py`

**Interfaces:**
- Produces, in `rule_book.py`, permissive Pydantic models (missing optional text is `""` or None so the validator, not Pydantic, reports it):
  - `FactDef(id: str, label: str, type: Literal["number","boolean","enum","date"] | None = None, unit: str | None = None, allowed_values: list[str] | None = None, definition: str = "", max_age_days: int | None = None, formula: Literal["ratio","ratio_pct","difference"] | None = None, inputs: list[str] = [])` — a computed fact has `formula` and `inputs`, no `type`.
  - `ParamDef(id: str, label: str, value: float | None = None, unit: str | None = None, by_region: dict[str, RegionOverride] = {}, rationale: str = "", source: SourceRef | None = None, status: Literal["set","open"] = "set", question: str = "")`; `RegionOverride(value: float, source: SourceRef | None = None)`; `SourceRef(title: str, url: str | None = None, locator: str | None = None)`.
  - Conditions as plain dicts (`{"fact", "op", "value"|"param"|"other_fact"}` or `{"all"|"any": [...]}`), kept raw so the validator can report bad shapes.
  - `CriterionRules(rationale: str = "", actions: list[str] = [], facts: list[FactDef] = [], params: list[ParamDef] = [], levels: dict[str, dict] = {})`.
  - `RuleBook(version: int, fingerprint: str, history: list[dict], actions: dict[str, list[dict]], conversions: list[dict], domain_tiers: dict[str, str], criteria: dict[str, CriterionRules])`.
  - `load_rule_book(data_dir: Path) -> tuple[RuleBook, dict]` (model, raw JSON); raises `RuleBookNotFound(f"Rule book not found: {path}")` when the file is missing.
  - `compute_fingerprint(raw: dict) -> str` (Global Constraints formula).
  - `sign_rule_book(data_dir: Path, approved_by: str, today: date) -> int`: increments `version`, sets `fingerprint`, appends `{"version", "fingerprint", "approved_by", "approved_at": today.isoformat()}` to `history`, writes the file (2-space indent, `ensure_ascii=False`), returns the new version.

- [ ] **Step 1:** Write the fixture RB exactly as the spec (facts `price`, `applies`, `levy`; params `p_high` 50 and `p_material` 10 USD/tCO2 with source and rationale; levels H/M; actions `steel.h2_dri`, `steel.scrap_eaf`; conversions CNY→USD 0.139 (2024), 0.14 (2025); domain tiers `eur-lex.europa.eu` primary, `reuters.com` news; version 7, fingerprint filled by `compute_fingerprint`).
- [ ] **Step 2:** Write tests: `test_ac91_sign` — after `sign_rule_book(F, "owner", date(2026, 10, 18))` the file has `version` 8 and the last history entry `{"version": 8, "approved_by": "owner", "fingerprint": compute_fingerprint(<content>)}`; `test_fingerprint_ignores_formatting` — re-dumping the raw JSON with `indent=4`, reversed key order, and a rationale containing `×` (signed once before) yields the same fingerprint; `test_missing_rule_book` — `load_rule_book(tmp_path)` raises `RuleBookNotFound` with message starting `Rule book not found: `.
- [ ] **Step 3:** Run them. Expected: FAIL (module missing).
- [ ] **Step 4:** Implement `rule_book.py` and the schema fields.
- [ ] **Step 5:** Run. Expected: PASS. Commit `feat(barrier): rule book model, fingerprint, signing`.

### Task 3: Validator

**Files:**
- Create: `backend/arp/transition_barrier/validation.py`
- Test: `backend/tests/test_transition_barrier_rule_book.py`

**Interfaces:**
- Consumes: `load_rule_book`, `compute_fingerprint` (Task 2); the raw `criteria_schema.json`.
- Produces: `validate_rule_book(raw_rule_book: dict, raw_schema: dict) -> list[str]` — error lines in spec rule order 1–9, criteria in schema order within a rule; `count_open(raw_rule_book) -> int`. Never raises on malformed input: a wrong type becomes `<code>: invalid <field>: <short reason>`.

- [ ] **Step 1:** Write one test per row, each mutating a copy of F and asserting the exact line is in `validate_rule_book(...)`: AC-77 (`STL-R1: condition names unknown fact 'prices'`), AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84 (inline number), AC-85, AC-86 (RB2 with `fos` in `USD/kWh`), AC-87 (`Missing rule book entry: STL-T1`), AC-88, AC-89 (tier removed from `steel_policy_tracker` in `criteria_schema.json`), AC-90 (`Rule book content changed but version is still 7`), AC-142 (depth 3). Also: F itself → `[]`; RB6 (open `p_high`, signed) → `[]` and `count_open == 1`; an open param without `question` → `STL-R1: open parameter 'p_high' has no question`; Review Focus 1: `p_high.value = "50"` → one line starting `STL-R1: invalid`, no exception.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Rules 3 skips conditions reading an open parameter; nesting depth counts the level's own group as 1; booleans, enum values and `YYYY-MM-DD` dates may be inline values, numbers may not; `in` takes a list of allowed values of an enum fact.
- [ ] **Step 4:** Run. Expected: PASS. Commit `feat(barrier): rule book validator`.

### Task 4: Rendering

**Files:**
- Create: `backend/arp/transition_barrier/render.py`
- Test: `backend/tests/test_transition_barrier_render.py`

**Interfaces:**
- Consumes: `CriterionRules` (Task 2).
- Produces: `fmt_number(x: float) -> str`; `render_group(group: dict, rules: CriterionRules, region: str | None = None) -> str` (with `region` None, overrides render in brackets; with a region, its value replaces the default — phase 2 uses this); `rubric(rules: CriterionRules) -> dict[str, str]` with keys `"H"`, `"M"`, `"L"`; `render_rule_book_md(rule_book: RuleBook, raw_schema: dict) -> str`.
- Grammar (spec section 1): `<label> <op> <value> <unit>`; unit `%` attaches without a space (`100%`); unitless values bare; booleans `is Yes` / `is No`; `in` → `in ETS, tax`; dates `YYYY-MM-DD`; fact vs fact `<label> <op> <other label>`; open param `[open: <label>]`; overrides ` (China: 40 USD/tCO2)` after the default value; `all` → ` and `, `any` → ` or `, nested groups in parentheses; L → `Otherwise (neither H nor M holds)`.

- [ ] **Step 1:** Write tests with the spec's exact strings: AC-93 (F's full `rubric`), AC-14 (RB4 M with brackets), AC-17 (RB5 override), AC-20 (RB6 open), AC-25 (RB8 fact vs fact), AC-149 (RB9 `in`), AC-153 (RB10 date); `fmt_number`: `72.0→"72"`, `9.366→"9.37"`, `9.9988→"10"`, `9.2991→"9.3"`, `72.005→"72.01"`; Review Focus 4: rendering F's markdown twice gives equal strings and criteria appear in schema order.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. `fmt_number` uses `Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP)` then strips trailing zeros. `render_rule_book_md` writes, per sector then criterion: `## <code> <criterion>`, rationale, actions (labels), facts with definitions, H/M/L sentences, a parameter table (value, unit, overrides, source, rationale; open ones with their question).
- [ ] **Step 4:** Run. Expected: PASS. Commit `feat(barrier): render rule sentences and the rule book document`.

### Task 5: Rule book CLI

**Files:**
- Modify: `backend/arp/cli/transition_barrier.py`
- Test: `backend/tests/test_transition_barrier_rule_book.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: `arp transition-barrier rules validate [--data-dir DIR]`, `rules sign --approved-by NAME [--data-dir DIR]`, `rules render [--data-dir DIR] [--out FILE]` (default `docs/transition_barrier/RULE_BOOK.md`). `--data-dir` defaults to `dataset.data_dir()`.

- [ ] **Step 1:** Write tests via `typer.testing.CliRunner`: AC-75 and AC-76 (exact output, exit 0); AC-77 (exit 1, line in output); Review Focus 2 — empty dir → exit 1 printing `Rule book not found: <dir>/rule_book.json`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the three commands on a `rules` sub-Typer.
- [ ] **Step 4:** Run. Expected: PASS. Commit `feat(barrier): rules validate, sign, render commands`.

### Task 6: Version 1 content — rules for all 35 criteria

**Files:**
- Create: `backend/arp/transition_barrier/data/rule_book.json`
- Create: `docs/transition_barrier/RULE_BOOK_V1_IMPACT.md`

Split the work into three commits, one per sector group: (a) Power & Utilities, Steel, Cement; (b) Chemicals, Critical Minerals & Mining, Aviation; (c) Shipping, Heavy-Duty Road Transport, Oil & Gas Upstream. Each commit must leave `rules validate` reporting only `Missing rule book entry` lines for the groups not done yet.

For every criterion:
- **Rationale:** 2–4 sentences: which decarbonisation actions it limits and why. Name the action ids.
- **Actions:** per sector, a short list of decarbonisation actions with stable ids (`steel.h2_dri`, `steel.scrap_eaf`, `steel.ccus`, `pwr.renewables`, …).
- **Facts:** what the current `metric` measures, split into typed facts, each with a definition stating period, scope and "net of what". Use computed facts (`ratio`, `ratio_pct`, `difference`) wherever today's rubric compares two quantities (PWR-T1, PWR-T2, CHM-T1, AVI-T1, MIN-D1, STL-T1, HDT-T1 at least).
- **Params:** every number in today's `rating_rubric` becomes a parameter with `source` (title, url, locator) and `rationale`. Every vague word ("material", "meaningful", "significant", "typically cited") becomes a number with a source, or an open parameter whose `question` says what is missing. Never invent a number.
- **Levels:** H and M as conditions on those facts and params, so that L is "neither".

The impact table (`RULE_BOOK_V1_IMPACT.md`): for each of the 105 cells, the current rating, the rating the v1 rules give using only the figures in today's `evidence` text (read by hand), and for every difference one line of reason. Cells whose evidence lacks a needed figure show `not rated: missing <fact>`. STL-R1 China is expected to differ (USD 9–14/t against the "material" threshold).

- [ ] **Step 1:** Draft group (a); run `arp transition-barrier rules validate`; fix until only other groups' `Missing rule book entry` lines remain. Commit `content(barrier): rule book v1, power/steel/cement`.
- [ ] **Step 2:** Same for group (b). Commit.
- [ ] **Step 3:** Same for group (c); then `arp transition-barrier rules sign --approved-by "<owner, pending approval in this PR>"` sets version 1. Expected: `Rule book v1: OK, 35 criteria, <m> open thresholds`. Commit.
- [ ] **Step 4:** Write the impact table. Commit `docs(barrier): v1 impact table`.

### Task 7: Wire it in — loader, `/criteria`, startup, registry, export, Word report

**Files:**
- Modify: `backend/arp/transition_barrier/dataset.py`, `backend/arp/schemas/transition_barrier.py` (`BarrierCriterion`), `backend/arp/api/routers/transition_barrier.py`, `backend/arp/api/main.py`, `backend/arp/cli/transition_barrier.py` (`export`)
- Modify (data): `backend/arp/transition_barrier/data/criteria_schema.json` (each primary source: `key` from the registry, `tier`, `cadence` where periodic; drop `rating_rubric`), `source_registry.json` (same URL fixes and added sources, as a derived view)
- Modify: `scripts/build_transition_barrier_report.js`, `docs/transition_barrier/Transition_Barrier_Assessment_Report.docx` (regenerated), `docs/transition_barrier/RULE_BOOK.md` (rendered), `docs/TRANSITION_BARRIER_ASSESSMENT.md` (a "How a rating is derived" section pointing at the rule book; the copy-pasted-URL note removed once fixed)
- Test: `backend/tests/test_transition_barrier_rule_book.py`, existing barrier tests

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: `load_criteria()` returns `BarrierCriterion`s whose `rating_rubric` is `rubric(...)`, plus `rationale: str`, `actions: list[str]`, `facts: list[dict]`, `params: list[dict]`, `rule_book_version: int | None` (new fields default empty so rows parse). `dataset.check_rule_book() -> None` raises `RuleBookNotFound` or `RuleBookError(<first error line>)`; `lifespan` calls it before `require_postgres`. `get_criterion` returns the new fields inside `criterion`. `arp transition-barrier export --out FILE` writes `{"criteria": [...], "scores": [...], "sources": {<key>: {...}}}` from the dataset functions. `node scripts/build_transition_barrier_report.js <out.docx> <export.json>` reads only the export (second argument required; exit 1 with usage if missing).

Registry clean-up rules (spec section 1, "Content of version 1"): every bundled source points at a fetchable document rather than a landing page, or is marked `"manual": true` with `"manual_reason"` (subscription, dashboard, company disclosure); sources that today's evidence cites but the registry lacks are added (STL-R1 China: ICAP, IEEFA, Transition Asia); the two copy-pasted URLs (`US_SAF_Grand_Challenge_IRA_40B_tax_credit`, `IEA_CCUS_Projects_Database`) are re-sourced. Tiers follow the spec's tier table; list every judgement-call tier in the PR. Before editing, record from `main` the responses AC-132 and AC-155 compare against, as JSON fixtures.

- [ ] **Step 1:** Write tests:
  - AC-92: `check_rule_book()` on AC-77's directory raises with that line, and `lifespan` raises before touching Postgres.
  - AC-93/AC-94 on F: `get_criterion("STL-R1")["criterion"]` has the exact `rating_rubric`, `rule_book_version == 7`, `actions == ["steel.h2_dri", "steel.scrap_eaf"]`, `params` with `p_high` value 50, source and rationale.
  - AC-155: every key of the recorded pre-change `get_criterion("STL-R1")` equals today's, except `criterion.rating_rubric` and the added fields.
  - AC-74: bundled `rules validate` exits 0 with the success line. AC-95: `rules render --out X` equals the committed `RULE_BOOK.md`.
  - AC-135: bundled export, then the report script exits 0 (skip with a reason when `node` or `docx` is missing), and the export's 105 ratings equal `assessment_scores.json`. AC-136: `from_transition_barrier` ratings equal `assessment_scores.json`.
  - AC-130/AC-131 (existing fields): a cell from `list_scores` / `get_matrix` equals its bundled row.
  - AC-132: the recorded pre-change files plus a `tier` per source and a signed 35-entry rule book → `get_refresh_coverage()` equals the recorded `main` response. AC-133: existing test still passes.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the loader, API, startup check and `export`; do the data edits; change the script; render `RULE_BOOK.md`; regenerate the Word report; update `TRANSITION_BARRIER_ASSESSMENT.md`.
- [ ] **Step 4:** Export OpenAPI and regenerate frontend types (Global Constraints); `cd frontend && npm run lint && npx tsc -b && npm test`.
- [ ] **Step 5:** Run `python3 -m pytest tests/test_transition_barrier_*.py tests/test_api_transition_barrier.py tests/test_decision* -q`. Expected: PASS. Commit `feat(barrier): rule book drives the criteria, registry tiers, export and report`.

### Task 8: Open the PR

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest -q -k "barrier or decision"`; `cd frontend && npm run lint && npx tsc -b && npm test`. Expected: all pass.
- [ ] **Step 2:** Merge `origin/main` into the branch if it moved.
- [ ] **Step 3:** Open the PR against `main` with `Spec: 2026-10-17-transition-barrier-rule-book-design`, label `risk:` per `.claude/skills/steward/SKILL.md`, the phase 1 AC list (unit rows owed to holdout listed), every test change, the open thresholds with their questions, and the tier judgement calls. Ask the owner to approve rule book v1 and the impact table in the PR.
