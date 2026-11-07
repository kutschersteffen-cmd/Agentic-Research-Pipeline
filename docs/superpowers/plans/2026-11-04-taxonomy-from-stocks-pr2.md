# Taxonomy from Stocks, PR 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp taxonomy infer pick <run_id> --theme <rank>` turns a run at `themes_ready` into a saved draft
taxonomy: activities from the stocks merged with the methodology's, tiers, a three-bucket keyword dictionary, a
grounded stock-to-activity mapping, weight coverage and theme KPIs; plus the golden scoring script.

**Architecture:** New module `arp/research/stock_inference/pick.py` holds `pick()` and one function per step
(`synthesize`, `top_down`, `merge`, `keywords`, `map_stocks`, `coverage`, `tiers`, `draft_kpis`), each taking its
fakeable dependency as a keyword argument like `start()` does. `pick` re-reads the described stocks' documents
through the registry (`description_chunks`, no new extraction) and the run's inputs from its JobManager manifest
(`run_store.load_manifest(run_id).params`: `methodology`, `segments`). Schema additions live on the existing
models; `build_taxonomy_schema` appends `theme.kpis`.

**Tech Stack:** Python 3.13, Pydantic, Typer, pytest with `fake_llm` / `pg`; authority agent
(`extract_source`, `consolidate`, `match_activities`), `draft_schema`, `suggest_catalogue_mapping`.

**Spec:** `docs/superpowers/specs/2026-11-04-taxonomy-from-stocks-design.md` (approved 2026-11-04). PR 2 of 3.
PR 1 (#339) is merged: `start`/`show`, profiles, clusters, themes. PR 3 is layer 1 index rules (AC-42-46).

**AC rows in this PR:** AC-27, AC-28, AC-28a, AC-29-41, AC-39a, AC-50 (re-checked with new keys), AC-54, AC-55,
AC-56.

## Global Constraints

- Messages verbatim from the spec: `Run <run_id> is at stage '<stage>'; '<command>' needs '<needed>'.` (already
  `WrongStage` in `run.py:31`), `Run <run_id> has no theme <rank>.`, `Coverage: <a> of profiled weight, <b> of
  fund weight.` (two decimals) / `Coverage: n/a of profiled weight, n/a of fund weight.`
- Shares, weights, coverage and tiers are computed in code; the model never supplies a number that is stored.
- Every activity, keyword and mapping is grounded in a quote; ungrounded ones are dropped (spec Goal 2).
- `infer show --json` prints exactly the spec's run-JSON keys; lists sorted as the spec says (`activities` by
  `activity_id`, `mapping` by `company_id`).
- The inference step never writes `companies` / `company_identifiers`.
- Never delete or weaken a test; list every test change in the PR.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; after model changes
  `python scripts/export_openapi.py` and `cd frontend && npm run gen:api`.

## Review Focus

1. `pick` run twice on the same run: the second call must refuse with the stage message (stage `drafted`), never
   save a second taxonomy (AC-28 covers the message; Task 2 asserts one taxonomy in the store).
2. A methodology URL that no longer answers at `pick` time: top-down is skipped with a warning in
   `source_notes`, bottom-up still saves (Task 3 test with a fake fetch that raises).
3. A picked theme whose supporting stocks all lost their documents since `start` (registry empty): `pick` fails
   with stage `failed` and `No activity could be grounded in the supporting stocks.`, no taxonomy saved (Task 3).
4. Fund weights where every mapped stock has weight `None` in a weighted run (holdings row with an empty weight
   cell): coverage treats `None` as 0, not a crash (Task 5).
5. PR #333 lands first and changes per-activity fields: `build_taxonomy_schema` must append KPIs after whatever
   `activity_fields` returns; Task 1's test compares against `activity_fields`, not a hard-coded count.

---

### Task 1: Schema additions

**Files:**
- Modify: `backend/arp/schemas/thematic.py` (`ActivityDefinition`: `contextual_keywords: list[str] = []`,
  `exclusion_keywords: list[str] = []`, `contextual_window_words: int = 50`; `ThemeDefinition.kpis:
  list[FieldDefinition] = []`)
- Modify: `backend/arp/schemas/taxonomy.py` (`DerivationMethod.STOCK_INFERENCE = "stock_inference"`)
- Modify: `backend/arp/research/taxonomy_schema.py:76-85` (append `taxonomy.theme.kpis` after the per-activity fields)
- Modify: `backend/arp/research/stock_inference/schemas.py` (`ActivityOrigin(activity_id, name, origin:
  Literal["stocks","methodology","both"])`, `Mapping(company_id, activity_id: str | None, reason, quote,
  tier: Literal["core","enabler","adopter","unknown"])`, `Coverage(profiled_weight_share: float | None,
  fund_weight_share: float | None, unmapped: list[str])`; `InferRun.activities: list[ActivityOrigin]`,
  `mapping: list[Mapping]`, `coverage: Coverage | None`)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/test_taxonomy_schema.py` (add), `backend/tests/test_taxonomy_retired_methods.py` (AC-50 update)

- [ ] **Step 1: Failing tests** — AC-40 (3 activities, no KPIs: fields equal `[f for a in acts for f in activity_fields(a, …)]`), AC-41 (same + 2 KPIs: those fields then the 2 KPIs, in order), AC-50 (`show` JSON equals the `main` fixture after removing `kpis`, `contextual_keywords`, `exclusion_keywords`, `contextual_window_words`), a saved taxonomy without the new keys still loads.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the fields and the one-line append; regenerate the two frontend files.
- [ ] **Step 4: Run** the two test files plus `tests/test_stage_evidence_schema.py` if present — PASS.
- [ ] **Step 5: Commit** `feat(taxonomy): keyword buckets, theme KPIs and stock_inference method on the schema`

### Task 2: `pick` skeleton, stage checks and documents

**Files:**
- Create: `backend/arp/research/stock_inference/pick.py`
- Modify: `backend/arp/cli/taxonomy_infer.py` (`infer pick RUN_ID --theme N`)
- Test: `backend/tests/test_stock_inference_pick.py`, `backend/tests/test_cli_taxonomy_infer.py` (add)

**Interfaces:**
- Produces: `async pick(run_id: str, rank: int, *, run_store, taxonomy_store, settings, llm, registry,
  matcher=match_activities, draft=draft_schema, mapper=suggest_catalogue_mapping, fetch=read_methodology) ->
  InferRun`; `async supporting_chunks(run, theme, registry) -> dict[str, list[DocumentChunk]]` (documents via
  `registry.fetch_all(_ref(stock))`, chunks via `description_chunks`, for every described stock).
- Saves the taxonomy with `taxonomy_store.create(run.name, theme_definition, DerivationMethod.STOCK_INFERENCE,
  notes)` and sets stage `drafted`, `taxonomy_id`; any exception after the stage check sets `failed` and finishes
  the manifest with the error (same `fail()` pattern as `start`).

- [ ] **Step 1: Failing tests** — AC-28 (run at `drafted` → exit 1, exact stage message), AC-28a (`--theme 9` → `Run <run_id> has no theme 9.`), AC-29 (exit 0, `stage` `drafted`, `taxonomy_id` set), AC-30 (`taxonomy show` contains `"derivation_method": "stock_inference"` and `"status": "draft"`), Review Focus 1 (second `pick` refused; one taxonomy in the store).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with stub steps that later tasks replace (synthesis returns the theme's name as one activity only in this task's fakes — tests fake every step).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): taxonomy infer pick with stage checks`

### Task 3: Activities — bottom-up, top-down, merge

**Files:**
- Modify: `backend/arp/research/stock_inference/pick.py`
- Test: `backend/tests/test_stock_inference_pick.py`

**Interfaces:**
- Produces: `async synthesize(theme, profiles, chunks, llm, *, fuzzy_threshold) -> list[ActivityDefinition]`
  (one structured call; each activity's `citations` are `SourceCitation`s whose quotes ground in a supporting
  stock's chunk text; activities with none are dropped; out-of-scope boundaries per adjacent role in
  `out_of_scope_description`); `async top_down(sources: list[str], theme_name, llm, settings, fetch) ->
  list[ActivityDefinition]` (`extract_source` per document with today's checklist, then `consolidate(...,
  value_chain=True, value_chain_model=<loaded IO model or None>)`); `async merge(stock_acts, method_acts,
  scope, llm, matcher) -> tuple[list[ActivityDefinition], list[ActivityOrigin]]`.

- [ ] **Step 1: Failing tests** — AC-31 (activity `A` with a grounded chunk quote kept with that quote in `citations`; `B` with an absent quote dropped), AC-35 (fake matcher pairs methodology `Q2` and stock `Q1` activities → one activity, `origin` `both`, citations hold `Q1` and `Q2`), unmatched methodology activity → `origin` `methodology`, Review Focus 2 (methodology fetch raises → bottom-up saved, `source_notes` mentions the skipped source), Review Focus 3 (no grounded activity → `failed`, message `No activity could be grounded in the supporting stocks.`, no taxonomy).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**; matched pair keeps the stock activity's id and name, unions both citation lists.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): grounded activities from stocks merged with the methodology`

### Task 4: Three-bucket keyword dictionary

**Files:** Modify `pick.py`; Test `test_stock_inference_pick.py`

**Interfaces:** `async keywords(activities, chunks_supporting, chunks_other, boundary_quotes, llm) -> list[ActivityDefinition]`
(one call proposes primary / contextual / exclusion per activity; code keeps a primary or contextual keyword only
if it occurs case-insensitively as a whole-word phrase in a supporting stock's chunk, an exclusion keyword only if
it occurs in a non-supporting stock's chunk or a methodology boundary quote; primary goes to `seed_keywords`).

- [ ] **Step 1: Failing tests** — AC-37 (chunk `Our PEM stack plant in Herøya`; primary `PEM stack` kept, `fusion reactor` and `Herøya plants` dropped), AC-38 (`stack efficiency` kept, `warp drive` dropped; exclusion `fuel cell` kept from `We sell fuel cell systems.`; `contextual_window_words` 50).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** with one compiled regex per phrase (`\b` + escaped phrase + `\b`, `re.IGNORECASE`). **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): three-bucket keywords grounded in stock text`

### Task 5: Mapping, coverage, tiers

**Files:** Modify `pick.py`; Test `test_stock_inference_pick.py`

**Interfaces:** `async map_stocks(profiles, activities, chunks, llm) -> tuple[list[Mapping], list[str]]` (one call;
a mapping is kept only when its quote grounds in that stock's own chunks; a grounded `none` gives `activity_id:
None`, `tier` `unknown`; ungrounded → `unmapped`); `coverage(run, mapping, unmapped) -> Coverage` and
`coverage_note(c) -> str`; `async tiers(theme_definition, mapping, segments, llm, mapper) -> list[Mapping]`
(`suggest_catalogue_mapping` links segment labels to activities; share of the company's revenue in labels linked to
its mapped activity: `core` ≥ 0.50, `enabler` ≥ 0.20 and < 0.50, `adopter` < 0.20; no `--segments` or no row →
`unknown`).

- [ ] **Step 1: Failing tests** — AC-32 (`p3` ungrounded → no mapping, in `unmapped`), AC-32a (`p4` grounded `none` → `activity_id` null, `tier` unknown, not in `unmapped`), AC-33 (`Coverage: 0.60 of profiled weight, 0.30 of fund weight.`), AC-34 (unweighted → `n/a` note), AC-36 (60 % core, 50 % core, 25 % enabler, 5 % adopter, no row unknown), AC-39a (no `--segments` → all `unknown`), Review Focus 4 (`None` weight counted as 0).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): grounded stock mapping, weight coverage and tiers`

### Task 6: KPIs, save, determinism

**Files:** Modify `pick.py`; Test `test_stock_inference_pick.py`, `test_cli_taxonomy_infer.py`

**Interfaces:** `async draft_kpis(theme, activities, methodology_text, llm, draft) -> list[FieldDefinition]` (calls
`draft_schema` with criteria text naming the theme, its activities and the methodology excerpts; keeps the first 5
fields).

- [ ] **Step 1: Failing tests** — AC-39 (fake `draft_schema` returns 3 fields → `theme.kpis` holds those 3 in order), AC-27 (10 weighted stocks, same fakes, two row orders → `start` then `pick`; run JSONs identical except `run_id` and `taxonomy_id`).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**; wire every step into `pick` in spec order (activities → keywords → mapping → coverage → tiers → KPIs → save). **Step 4: Run** all stock-inference tests — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): theme KPIs; pick saves the draft taxonomy`

### Task 7: Golden scoring script

**Files:**
- Create: `backend/scripts/score_stock_inference.py`, `backend/scripts/golden_universe.py`
- Test: `backend/tests/test_score_stock_inference.py`

**Interfaces:** `golden_universe.py --cases <cases.json> --split tune|holdout --out <universe.json>` writes a
universe whose `company_id` is each case's `case_id` (unweighted). `score_stock_inference.py --run <run_id> --cases
<cases.json> --split tune|holdout --check theme|mapping [--theme-pattern <regex>] [--min-recall <x>]
[--min-precision <x>]` reads the run JSON through `load_run`, prints one score line per check, exits 0 only when
every given threshold holds. Theme check: top theme's name matches the pattern (case-insensitive) and its
supporting stocks include ≥ min-recall of described core+peripheral cases. Mapping check: ≥ min-precision of
described `not` cases are mapped to `none` or to an activity no described `core` case is mapped to.

- [ ] **Step 1: Failing tests** — fixture run JSONs that pass and fail each check by one stock; exit codes 0 / 1; the printed score line.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): golden scoring script for taxonomy infer`

### Task 8: Golden run, final review, PR

- [ ] **Step 1:** Full backend suite once (`-m "not e2e"`, nothing else running); failures only in known container gaps.
- [ ] **Step 2:** Whole-branch `/code-review` and `/ponytail:ponytail-review`; one fix wave; one re-review.
- [ ] **Step 3:** Golden (AC-54/55, tune split, real model): `golden_universe.py`, `infer start`, `infer pick` on the theme matching `electroly`, both score checks; tune prompts only on tune. Then AC-56 on holdout once; post its score lines in the PR.
- [ ] **Step 4:** PR against `main` with `Spec: taxonomy-from-stocks` and `Rows:` for this PR's rows, `risk:normal`
  (no weight parsing changes) unless the diff says otherwise, test changes listed.
