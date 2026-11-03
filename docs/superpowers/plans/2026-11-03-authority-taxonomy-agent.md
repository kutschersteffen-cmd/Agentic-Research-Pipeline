# Authority Taxonomy Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pausing run that builds a fully quoted thematic taxonomy from user-chosen authority sources, with three
user checkpoints and an owner-approved source library.

**Architecture:** New package `backend/arp/research/authority_taxonomy/` (checklist, extraction, consolidation,
library, discovery, run). Run state is one snapshot (`run_store.save_snapshot(run_id, "state", …)`) on a run created
by `JobManager.create_run("authority_taxonomy", …)`; each API/CLI call loads the state, runs the next stage, saves it.
No LangGraph checkpointer. Existing `authority_source` derivation stays untouched.

**Tech Stack:** Python 3.12, pydantic, FastAPI, typer, existing `chunk_document`, `select_relevant_chunks`,
`ground_citations`, `map_theme_to_standards`, `load_value_chain(...).links`.

**Status:** approved by the owner, 2026-11-03 (subagent-driven).

**Spec:** `docs/superpowers/specs/2026-11-03-authority-taxonomy-agent-design.md` (approved 2026-11-03).

## Global Constraints

- Every activity, boundary, definition, criterion and threshold kept in the draft has ≥ 1 citation that passed
  `ground_citations` (fuzzy threshold 0.92); ungrounded items are dropped.
- User scope text is in every extraction prompt; scope wins over source text.
- Thresholds go only to `ThemeDefinition.thresholds`; never into activity text or criteria.
- Fetch cap on this path: 400,000 characters. Existing callers keep 60,000.
- Candidate summary ≤ 80 words.
- EXIOBASE widening: top 5 upstream (`side="suppliers"`, `order="total"`, `exclude_own=True`) per core ISIC code.
- Merge key: activity name lower-cased, whitespace and punctuation removed.
- Nothing is written to the Taxonomy Library before `accept`.
- Library files: `backend/arp/data/authority_library/<theme_key>.json`; discovery reads only `approved` entries.
- Tests use `FakeLLMClient` / `FakeSearchClient` from `backend/tests/conftest.py` and fixtures in
  `backend/tests/fixtures/authority_taxonomy/`; rows are `unit`, owed to `holdout`.

## Review Focus

1. A source PDF with no extractable text → candidate `fetchable=false`, run still reaches `awaiting_sources` (Task 5 test).
2. User selects zero sources → 422, run stays `awaiting_sources` (Task 7 test).
3. `PUT /draft` with an activity whose citations were removed → 422 "activity <name> has no citation" (Task 6 test).
4. `value_chain=true` but no IO model loaded → draft built without `exiobase` codes, `notes` says "no IO model" (Task 3 test).
5. Theme key not in the 10 → library lookup yields nothing, web discovery still runs (Task 5 test).

---

### Task 1: Schema fields

**Files:**
- Modify: `backend/arp/schemas/thematic.py` (ActivityDefinition, ThemeDefinition)
- Create: `backend/arp/schemas/authority_taxonomy.py`
- Test: `backend/tests/test_authority_taxonomy_schema.py`

**Interfaces — Produces:**
- `SourceCitation(BaseModel)`: `quote: str`, `source_url: str`, `location: str = ""`
- `SectorCode(BaseModel)`: `system: Literal["ISIC","NACE","NAICS","SIC","GICS"]`, `code: str`, `origin: Literal["source","map_standards","exiobase"]`
- `Criterion` / `Threshold` / `Technology`: `text: str` (Technology: `name: str`), `citations: list[SourceCitation]`
- `Definition`: `term: str`, `text: str`, `citations: list[SourceCitation]`
- `ActivityDefinition` new fields: `value_chain_role: Literal["core","upstream","enabling"]="core"`, `criteria: list[Criterion]=[]`, `citations: list[SourceCitation]=[]`, `out_of_scope_citations: list[SourceCitation]=[]`, `sector_codes: list[SectorCode]=[]`
- `ThemeDefinition` new fields: `scope: str=""`, `technologies: list[Technology]=[]`, `definitions: list[Definition]=[]`, `thresholds: list[Threshold]=[]`, `checklist_report: dict[str, dict[str, Literal["found","not_in_source"]]]={}`
- `merge_key(name: str) -> str` in `schemas/authority_taxonomy.py`

- [ ] **Step 1:** Tests: `test_old_taxonomy_json_loads` (a saved taxonomy JSON fixture without new fields validates; new fields equal defaults — AC-18 data half); `test_merge_key` (`merge_key("Electrolyser stack manufacturing") == merge_key("electrolyser-stack  manufacturing")`).
- [ ] **Step 2:** Run `cd backend && python3 -m pytest tests/test_authority_taxonomy_schema.py -v` → FAIL (import error).
- [ ] **Step 3:** Add the models and fields above (import the helper models into thematic.py from the new module; avoid a cycle by defining them in `schemas/authority_taxonomy.py` without importing thematic).
- [ ] **Step 4:** Run tests → PASS. Also `arp taxonomy show` on an existing saved taxonomy: output identical to `main` (AC-18: add `test_show_unchanged` comparing to a stored expected-output fixture).
- [ ] **Step 5:** Commit `feat(taxonomy): fields for authority taxonomy document`.

### Task 2: Checklist and per-source extraction

**Files:**
- Create: `backend/arp/research/authority_taxonomy/__init__.py`, `checklist.py`, `extract.py`
- Modify: `backend/arp/research/taxonomy_sources/fetch.py` (add `max_chars: int = _MAX_CHARS` to `fetch_source_text` and `fetch_source_text_or_empty`)
- Test: `backend/tests/test_authority_taxonomy_extract.py`, fixtures `long_report.txt`, `eu_310.txt`, `bom_paper.txt`

**Interfaces — Produces:**
- `AUTHORITY_CHECKLIST: list[ChecklistItem]` with `key`, `question`, `keywords: list[str]`, keys exactly: `theme_description, activities, boundaries, technologies, definitions, sector_codes, value_chain, thresholds`
- `async def extract_source(url: str, text: str, *, theme_name: str, scope: str, value_chain: bool, llm: LLMClient) -> SourceExtraction`
- `SourceExtraction`: `url`, `theme_description: str`, `activities: list[ActivityDefinition]`, `technologies`, `definitions`, `thresholds`, `sector_codes: list[SectorCode]`, `report: dict[str, Literal["found","not_in_source"]]`, `usage: LLMUsage`

Approach: `chunk_document` over the whole text; per checklist item `select_relevant_chunks(chunks, item.keywords + [theme_name], max_chunks=6, fallback_to_all=False)`; one `complete_structured` per item (output models named `_<Key>Draft` so `FakeLLMClient` scripts them by class name); every returned element carries `quote`; ground with `ground_citations`; item → `found` if ≥ 1 grounded element else `not_in_source`. Skip `value_chain` entirely when `value_chain=False`. Activities from the `value_chain` item get `value_chain_role` from the draft (`upstream`/`enabling`). Boundary items whose text describes activity outside scope are attached to the matching activity's `out_of_scope_description` and `out_of_scope_citations` (the `_BoundariesDraft` returns `activity_name`, `kind: "include"|"exclude"`, `text`, `quote`).

- [ ] **Step 1:** Tests (fake LLM scripted per item):
  - `test_reads_beyond_100k` — AC-5: quote Q at offset > 100,000 in `long_report.txt` ends up in an activity citation.
  - `test_ungrounded_activity_dropped` — AC-6.
  - `test_ungrounded_definition_and_threshold_dropped` — AC-6b.
  - `test_missing_thresholds_reported` — AC-7: `report["thresholds"] == "not_in_source"`.
  - `test_definition_and_technology` — AC-7b, AC-7c.
  - `test_threshold_found` — AC-7d.
  - `test_scope_excludes_operation` — AC-9, AC-9b.
  - `test_value_chain_off` — AC-11b: `"value_chain" not in report`; no LLM call scripted for it.
  - `test_threshold_not_in_activities` — AC-12, AC-12b.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `checklist.py`, `extract.py`, and the `max_chars` parameter.
- [ ] **Step 4:** Run → PASS; `python3 -m pytest tests/test_authority_extraction.py tests/test_authority_derivation.py` still PASS (old path).
- [ ] **Step 5:** Commit `feat(taxonomy): checklist-driven authority extraction`.

### Task 3: Consolidation, sector codes, EXIOBASE widening

**Files:**
- Create: `backend/arp/research/authority_taxonomy/consolidate.py`
- Test: `backend/tests/test_authority_taxonomy_consolidate.py`, fixture `power_gen.txt`

**Interfaces:**
- Consumes: `SourceExtraction` (Task 2), `merge_key` (Task 1)
- Produces: `async def consolidate(extractions: list[SourceExtraction], *, theme_name: str, scope: str, value_chain: bool, settings: Settings, llm: LLMClient, value_chain_model: ValueChain | None) -> tuple[ThemeDefinition, str]` (theme, notes)

Approach: group activities by `merge_key`; a group keeps the first name/description, the union of `citations`, `out_of_scope_citations`, `criteria`, `seed_keywords`. Deterministic, no LLM. Then `map_theme_to_standards` → append codes with `origin="map_standards"`. If `value_chain` and a model: for each ISIC code of each activity, `model.links(node, "suppliers", "total", limit=5, exclude_own=True)` → `origin="exiobase"` (map node → ISIC via the model's node code). No model → notes contains `no IO model`. `checklist_report` = `{ext.url: ext.report}`.

- [ ] **Step 1:** Tests: `test_merge_keeps_both_citations` (AC-8); `test_value_chain_role_present` (AC-10); `test_exiobase_top5` (AC-10b, sample IO model via `load_value_chain` on the bundled sample, else `resolve_indirect_exposure_model(settings, use_sample=True)`); `test_map_standards_origin` (AC-10c, ISIC D35); `test_value_chain_off_all_core` (AC-11); `test_no_io_model_note` (Review Focus 4).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `consolidate`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(taxonomy): consolidate authority extractions with sector codes`.

### Task 4: Source library

**Files:**
- Create: `backend/arp/research/authority_taxonomy/library.py`, `backend/arp/data/authority_library/.gitkeep`, `backend/arp/cli/authority_library.py`
- Modify: `backend/arp/cli/__init__.py` or the main typer app (register `authority-library`)
- Test: `backend/tests/test_authority_library.py`

**Interfaces — Produces:**
- `THEME_KEYS = ("hydrogen","renewable_power","energy_storage","electric_vehicles","grid_electrification","ai_datacentres","water","ccus","critical_minerals_circular","building_efficiency")`
- `LibraryEntry`: `url, title, source_type: Literal["regulatory_taxonomy","agency_report","index_methodology","standards_body","statistical_classification","engineering_paper"], summary, covers: list[str], fetchable: bool, checked_on: str | None, status: Literal["proposed","approved"]`
- `load_library(theme_key, root: Path | None = None) -> list[LibraryEntry]`, `save_library(...)`, `approve(theme_key, url, today: date)`, `reject(theme_key, url)`
- CLI: `arp authority-library propose --theme`, `approve --theme --url`, `reject --theme --url`

- [ ] **Step 1:** Tests: `test_propose_adds_proposed` (AC-16: 1 existing + 4 new = 5; existing unchanged); `test_approve_sets_date` (AC-17, `today=date(2026,11,10)`); `test_reject_removes` (AC-17b); `test_unknown_theme_rejected` (exit 1, message lists THEME_KEYS).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; `propose` uses Task 5's `discover_candidates` with library lookup off, writes new URLs only.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(taxonomy): authority source library`.

(Task 4 Step 3 depends on Task 5; implement Task 5 first if running in order matters to you, or stub `propose` until Task 5 lands.)

### Task 5: Discovery with candidates

**Files:**
- Create: `backend/arp/research/authority_taxonomy/discovery.py`
- Test: `backend/tests/test_authority_taxonomy_discovery.py`

**Interfaces — Produces:**
- `Candidate`: `url, title, source_type, summary (≤ 80 words), reason, fetchable: bool, covers: list[str], from_library: bool`
- `async def discover_candidates(theme_name: str, theme_key: str | None, guidance: str, *, search_client, llm, user_agent: str, use_library: bool = True) -> list[Candidate]`

Approach: approved library entries first (in file order), then the existing authority queries plus `"{theme} bill of materials"`, `"{theme} engineering cost study"`, `"{theme} technology report"`; dedupe by URL. Guidance: one `_GuidanceDraft` LLM call turns guidance into `allowed_hosts: list[str]` (e.g. "EU Taxonomy only" → `["europa.eu"]`); if non-empty keep only URLs whose host ends with one. Each candidate: `fetch_source_text(max_chars=400_000)`; fetched → one `_CandidateDraft` call (summary, reason, source_type, covers); not fetched → summary = search snippet (truncated to 80 words), reason from a `_CandidateDraft` call on title + snippet, `fetchable=False`.

- [ ] **Step 1:** Tests: `test_unfetchable_candidate` (AC-2); `test_library_first` (AC-3); `test_proposed_not_listed` (AC-3b); `test_guidance_filters_hosts` (AC-4); `test_pdf_without_text_is_unfetchable` (Review Focus 1); `test_unknown_theme_key_web_only` (Review Focus 5).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(taxonomy): authority candidate discovery`.

### Task 6: Run state machine

**Files:**
- Create: `backend/arp/research/authority_taxonomy/run.py`
- Test: `backend/tests/test_authority_taxonomy_run.py`

**Interfaces — Produces:**
- `Stage = Literal["awaiting_sources","awaiting_review","accepted","cancelled"]`
- `RunState`: `run_id, stage, theme_name, theme_key: str | None, scope, guidance, value_chain, candidates: list[Candidate], draft: ThemeDefinition | None, notes: str, taxonomy_id: str | None`
- `async def start_run(...) -> RunState` (creates via `JobManager.create_run("authority_taxonomy", …)`, runs discovery, saves)
- `async def select_sources(run_id, urls: list[str], files: list[Path], **deps) -> RunState` (requires `awaiting_sources`; fetch with 400k cap, `extract_source` each, `consolidate`)
- `def put_draft(run_id, draft: ThemeDefinition, run_store) -> RunState` (requires `awaiting_review`; rejects an activity with empty `citations`)
- `def accept(run_id, run_store, taxonomy_store) -> RunState` (requires `awaiting_review`; `taxonomy_store.create(name, draft, DerivationMethod.AUTHORITY_SOURCE, notes)`; stage `accepted`)
- `def cancel(run_id, run_store) -> RunState` (from either `awaiting_*`)
- `class WrongStage(Exception)` with `.stage`
- `load_state(run_id, run_store) -> RunState`

- [ ] **Step 1:** Tests: `test_put_and_accept` (AC-13, AC-13b, AC-13e); `test_nothing_saved_before_accept` (AC-13c: `len(taxonomy_store.list())` unchanged); `test_local_file_source` (AC-13d); `test_accept_wrong_stage` (AC-14: `WrongStage.stage == "awaiting_sources"`); `test_cancel_both_stages` (AC-15); `test_draft_without_citation_rejected` (Review Focus 3).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(taxonomy): authority taxonomy run stages`.

### Task 7: API router

**Files:**
- Create: `backend/arp/api/routers/authority_taxonomy.py`
- Modify: `backend/arp/api/main.py` (include router with `dependencies=[Depends(authorize)]`, as taxonomies)
- Modify: generated `frontend` OpenAPI types (`python scripts/export_openapi.py`, `npm run gen:api`)
- Test: `backend/tests/test_api_authority_taxonomy.py`

Routes, prefix `/api/authority-taxonomy`:
`POST /runs` → 201 `{id, stage}`; `GET /runs/{id}` → RunState; `POST /runs/{id}/sources` body `{urls, files}` → 200, 422 if both empty; `GET|PUT /runs/{id}/draft` → 200 / 422; `POST /runs/{id}/accept` → 201 `{taxonomy_id}`; `DELETE /runs/{id}` → 204. `WrongStage` → 409 `{"detail": "run is at stage <stage>"}`.

Note: the spec writes `/authority-taxonomy/runs`; the repo prefixes every router with `/api`, so the path is `/api/authority-taxonomy/runs` (my call).

- [ ] **Step 1:** Tests: `test_start_returns_201` (AC-1); `test_get_run_candidates` (AC-1b: exactly 3); `test_put_draft_200` (AC-13); `test_accept_201` (AC-13b); `test_accept_409` (AC-14); `test_delete_204` (AC-15); `test_select_no_sources_422` (Review Focus 2).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS; `cd frontend && npx tsc -b` clean.
- [ ] **Step 5:** Commit `feat(api): authority taxonomy runs` (include both generated files).

### Task 8: CLI `arp taxonomy author`

**Files:**
- Modify: `backend/arp/cli/taxonomy.py` (sub-app `author`: `start`, `select`, `review`, `accept`)
- Test: `backend/tests/test_cli_taxonomy_author.py`

`start NAME --scope TEXT [--theme-key K] [--guidance TEXT] [--value-chain]`; `select RUN_ID [--url U ...] [--file PATH ...]`; `review RUN_ID [--edit draft.json]` (prints draft; with `--edit` does `put_draft`); `accept RUN_ID`. Each prints `stage: <stage>` as its last line.

- [ ] **Step 1:** Test `test_cli_flow` (AC-20: last lines `stage: awaiting_sources`, `stage: awaiting_review`, `stage: awaiting_review`, `stage: accepted`).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(cli): taxonomy author commands`.

### Task 9: Golden command and case

**Files:**
- Modify: `backend/arp/cli/golden_set.py` (command `authority-taxonomy --case ID`)
- Create: `backend/tests/golden/authority_taxonomy/hydrogen_eu_taxonomy/case.json` (`source_url` or `path` to EU Delegated Act Annex I text excerpt for activity 3.2, `scope`, `expected_activities` (3 names), `min_recall: 0.67`)
- Test: `backend/tests/test_golden_authority_taxonomy.py`

Prints `grounded_rate=<x> recall=<y>`, exit 0 iff `grounded_rate == 1.0` and `recall >= min_recall`; nothing saved.

- [ ] **Step 1:** Tests with fake LLM: `test_golden_pass_exit0`, `test_golden_low_recall_exit1`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Real-model run (AC-22) is done once by hand and the output pasted in the PR.
- [ ] **Step 5:** Commit `feat(golden): authority taxonomy golden case`.

### Task 10: Regression rows

**Files:**
- Test: `backend/tests/test_authority_taxonomy_regressions.py`

- [ ] **Step 1:** Tests against stored expected outputs captured from `main` before Task 1: `test_create_authority_source_unchanged` (AC-19), `test_compare_unchanged` (AC-19b), `test_merge_unchanged` (AC-19c), `test_ratify_unchanged` (AC-19d).
- [ ] **Step 2:** Run → PASS (they guard, not drive). Full `ruff check . && python3 -m pytest tests/` (AC-21).
- [ ] **Step 3:** Commit `test(taxonomy): regression guards for existing taxonomy commands`.

**Capture the expected outputs for Task 10 on `main` before starting Task 1.**

## After merge (not code)

Run `arp authority-library propose --theme <key>` for the 10 themes; the owner approves entries with `approve`.
