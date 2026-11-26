# EXIOBASE Sectors Replace ICIO — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every activity, link rule, LLM prompt and API names EXIOBASE sectors by full name; the ICIO code layer is gone except inside a one-off migration command.

**Architecture:** `nace.py` and a new `factory.sectors()` become the only sector reference (both read `exiobase_nace.csv`). The Leontief model, links, exposure, relevance and standards mapping key on sector names. Old data is converted once by `arp io migrate-exiobase`, the only reader of the ICIO crosswalk. Loading old-format themes fails with message M8.

**Tech Stack:** Python 3 / pydantic v2 / FastAPI / typer / numpy; React + TypeScript (Vite, vitest).

**Spec:** `docs/superpowers/specs/2026-11-04-exiobase-sectors-replace-icio-design.md` (approved; read it with this plan; AC-n below refer to it).

## Global Constraints

- A sector is its `sector_name()` (`arp/research/value_chain/model.py`): archive name without a trailing ` (NN)`.
- M8, exact: `core_isic_codes (ICIO) is no longer supported; run arp io migrate-exiobase --file <theme.json> to convert it` (`<theme.json>` literal). API: HTTP 422 with M8 in the body. CLI: exit 1, M8 on stderr.
- Link validation messages, exact: `each part needs sectors and a numeric share`, `sectors must not be empty`, `unknown sector '<name>'`, `duplicate sector '<name>'`; existing ones unchanged.
- Migration stdout lines: `taxonomy <id> v<n>`, `link <subject>`, `file <path as passed>`, then `<n> changed`. Error: `unknown ICIO code '<x>' in <taxonomy <id> v<n> | link <subject> | file <path>>`, exit 1, nothing written.
- `links-import` header `company_id,sector,share`; else `header must be company_id,sector,share`, exit 1.
- `build-full` unknown sector: `EXIOBASE sector not in exiobase_nace.csv: <name>`.
- Never delete or weaken an existing test. Tests that used ICIO codes switch to the equivalent sector names with the same assertions; list each changed test in the PR description (CLAUDE.md).
- Checks per task: `cd backend && ruff check . && python3 -m pytest <files>`; frontend `npm run lint && npx tsc -b && npm test`.

## Review Focus

1. A company whose NACE/ISIC code maps to no sector (e.g. NACE `99.00`): exposure returns `None` and relevance is `True`, no crash. Test in Task 3.
2. A split part whose sectors have no live node in the build: reported in `unresolved` with its `sectors` list, not a KeyError. Test in Task 3.
3. A taxonomy dir with a non-taxonomy file or a `latest.json` next to `v*.json`: migration touches only `v*.json` and leaves `latest.json` byte-identical. Test in Task 5.
4. An LLM answering a sector with different case or a ` (31)` suffix: dropped (exact match only), never crashes. Test in Task 2 (AC-36 style, answer `copper production`).
5. `--file` on a run's `theme.json` (bare `ThemeDefinition`, no `theme` wrapper): converted the same as a taxonomy file. Test in Task 4.

---

### Task 0: Record Baseline B (first commit, before any code change)

**Files:**
- Create: `backend/tests/fixtures/icio_baseline.json`
- Create: `backend/tests/fixtures/README_icio_baseline.md` (two lines: what it is, how it was produced, from commit `890c60ea`)

- [ ] **Step 1:** On the unchanged branch, run a throwaway script (scratchpad, not committed) that loads `ValueChain` from `arp/research/indirect_exposure/sample_data` and the sample `LeontiefModel` (`resolve_indirect_exposure_model(settings, use_sample=True)`), then records:
  - `"c1_weights"`: `{node_id: weight}` from `links.resolve_company(vc, CompanyRef(company_id="c1", name="c1"), LinkRule(kind="split", parts=[{"icio_code":"B07","share":0.4},{"icio_code":"D_GEN_REN","share":0.6}], set_by="t", set_at="t"))`, keyed by the node's `node_id`.
  - `"c9"`: `{"upstream_exposure", "downstream_exposure", "critical_input"}` from `compute_indirect_exposure("c9", "", model, {"B07"}, model.edition_label, country="DE", nace=("nace2","24.44","2"))`.
- [ ] **Step 2:** Write them with `json.dumps(..., indent=2, sort_keys=True)` (full float repr). Commit: `test: record ICIO baseline for EXIOBASE migration`.

### Task 1: Sector reference and the migration core (additive)

**Files:**
- Modify: `backend/arp/research/indirect_exposure/factory.py` (add `sectors()`)
- Modify: `backend/arp/research/indirect_exposure/nace.py` (add two lookups)
- Create: `backend/arp/research/indirect_exposure/migrate/__init__.py`
- Move: `reference/exiobase_ixi_to_icio2025.csv` → `migrate/exiobase_ixi_to_icio2025.csv` (`git mv`; update `_read_reference` callers in `factory.py` and `value_chain/build.py` to the new path for now, they are removed in Task 3)
- Test: `backend/tests/test_exiobase_migrate.py`, `backend/tests/test_nace_table.py` (add cases)

**Interfaces — Produces:**
- `factory.sectors() -> list[str]`: 163 names, `sector_name()` of `exiobase_nace.csv`'s `exiobase_sector`, de-duplicated, first-appearance order; `functools.cache`.
- `nace.sector_nace2_codes(sector: str) -> list[str]`: sorted distinct `nace2_code` of rows whose `sector_name(exiobase_sector) == sector`.
- `nace.nace2_to_isic4(code: str) -> list[str]`: sorted distinct `ISIC4code` of `un_nace2_isic4.csv` rows with `NACE2code == code` (partial rows included).
- `migrate.UnknownIcioCode(ValueError)` with attribute `code: str`.
- `migrate.icio_sectors(code: str) -> list[str]`: S(x) per the spec; raises `UnknownIcioCode` when empty.
- `migrate.convert_theme(theme: dict) -> bool`: mutates a `ThemeDefinition`-shaped dict in place (`activities[].core_isic_codes` → `core_sectors` at the same key position; `standards_mapping.unmapped_isic_codes` → `unmapped_sectors`); returns whether anything changed.
- `migrate.convert_document(doc: dict) -> bool`: `convert_theme(doc["theme"])` if `"theme"` in doc (taxonomy), else `convert_theme(doc)`.
- `migrate.convert_parts(kind: str, parts: list[dict]) -> list[dict] | None`: new parts for `split`/`llm` parts with `icio_code`, else `None` (unchanged).

- [ ] **Step 1: Failing tests** in `test_exiobase_migrate.py`:
  - `test_sectors_count_and_first`: `len(sectors()) == 163`, `sectors()[0] == "Cultivation of paddy rice"`, no name ends with `)` digit-suffix (regex `r" \(\d+\)$"`).
  - `test_icio_sectors_b07`: 8 names, includes `"Mining of uranium and thorium ores"` (suffix stripped), sorted.
  - `test_icio_sectors_split_code`: `icio_sectors("D_GEN_REN")` has 7 names, all starting `"Production of electricity by"`.
  - `test_unknown_code`: `icio_sectors("ZZZ")` raises `UnknownIcioCode` with `.code == "ZZZ"`.
  - `test_convert_theme_key_order`: activity `{"activity_id":"a1","name":"n","core_isic_codes":["B07"],"source_citation":None}` → keys in order `activity_id,name,core_sectors,source_citation`; returns `True`; second call returns `False`.
  - `test_convert_unmapped`: `standards_mapping.unmapped_isic_codes ["B07"]` → `unmapped_sectors == icio_sectors("B07")`, old key gone.
  - `test_convert_parts`: split parts of Fixture M → `[{"sectors": S(B07), "share": 0.4}, {"sectors": S(D_GEN_REN), "share": 0.6}]`; `nodes` parts → `None`; already-new parts → `None`.
  - In `test_nace_table.py`: `sector_nace2_codes("Copper production") == ["24.44"]`; `nace2_to_isic4("24.44") == ["2420"]`.
- [ ] **Step 2:** Run `python3 -m pytest tests/test_exiobase_migrate.py tests/test_nace_table.py -q` → FAIL (import errors).
- [ ] **Step 3:** Implement the interfaces above. `migrate` reads its CSV via `Path(__file__).parent / "exiobase_ixi_to_icio2025.csv"`.
- [ ] **Step 4:** Same pytest command → PASS; full `python3 -m pytest -q -x` still green.
- [ ] **Step 5:** Commit `feat: sector list, NACE reverse lookups and ICIO conversion core`.

### Task 2: Activities name sectors (`core_sectors`, M8, prompts, standards, criticality)

> Tasks 2 and 3 are **one review gate and one commit**: once the model keys on sector names, the ICIO company paths break until Task 3 lands. Do Task 2's steps, then Task 3's, then run the full suite and commit once.

**Files:**
- Modify: `backend/arp/schemas/thematic.py` (`core_isic_codes` → `core_sectors`, M8 validator; drop `icio` wording), `backend/arp/schemas/standards.py` (`unmapped_isic_codes` → `unmapped_sectors`), `schemas/revenue_exposure.py`, `schemas/rd_exposure.py` (field descriptions only)
- Modify: `research/indirect_exposure/leontief.py`, `factory.py` (`_load`), `core_sectors.py`, `criticality.py`, `research/activity_generator.py`, `research/standards_mapping/mapper.py` + `crosswalk.py` docstring, `research/taxonomy_sources/activity_merge.py` (comment), `cli/theme.py`, `cli/taxonomy.py`, `api/routers/taxonomies.py`
- Test: `tests/test_core_sectors.py`, `test_criticality.py`, `test_activity_generator.py`, `test_standards_mapper.py`, new `tests/test_old_theme_rejected.py`

**Interfaces:**
- Consumes: `sectors()`, `sector_nace2_codes`, `nace2_to_isic4` (Task 1).
- Produces:
  - `ActivityDefinition.core_sectors: list[str]`; a `model_validator(mode="before")` raising `ValueError(M8)` when the input dict has `core_isic_codes`. `M8` is a module constant `OLD_FORMAT_MESSAGE` in `schemas/thematic.py`.
  - `LeontiefModel`: `codes` = `sectors()`, `code_nodes: dict[str, np.ndarray]` keyed by sector name (via `sector_name(node sector)`); fields `labels`, `isic_divisions`, `nace_classes`, `prompt_codes` removed. `industry_reference_list() -> list[str]` (names); `industry_prompt_list() -> str` (one name per line). `generate_activities_industry_anchored(theme_name, theme_description, anchor_industries: list[str], llm)`; `_format_anchor_industries` joins names by newline.
  - `criticality.critical_sectors() -> set[str]`: union of `division_sectors(d)` (as `sector_name`) over `critical_isic_codes()`; `apply_criticality_overlay` flags on `core_sectors ∩ critical_sectors()`.
  - `mapper.map_activity_standards`: ISIC codes = sorted union of `nace2_to_isic4(n)` over `sector_nace2_codes(s)` for `s in core_sectors`; the three tables look those up; `unmapped_sectors` = sectors whose ISIC codes got zero matches in every loaded table.
  - `compute_indirect_exposure` core set = `code_nodes` of `core_sectors` (rename param `core_codes` → `core_sectors: set[str]`). Company side stays as is until Task 3.

- [ ] **Step 1: Failing tests:**
  - `test_old_theme_rejected.py::test_model_rejects` — `ActivityDefinition.model_validate({"name":"n","in_scope_description":"i","out_of_scope_description":"o","core_isic_codes":["B07"]})` raises `ValidationError` whose `str()` contains M8 (AC-16/62 base).
  - `::test_post_taxonomies_422` — `TestClient` `POST /api/taxonomies` with that activity in the theme → 422, `M8 in response.text` (AC-14); same for `POST /api/taxonomies/t1/versions` (AC-15).
  - `::test_get_unmigrated_422` — write a raw old-format `v1.json` + `latest.json` into the taxonomies dir; `GET /api/taxonomies/t1` → 422, M8 in body (AC-17). Implement by catching `pydantic.ValidationError` in the router's GET and raising `HTTPException(422, str(exc))`.
  - `::test_cli_classify_sectors_rejects` — `CliRunner` `theme classify-sectors --theme <old> --out x.json --use-sample-io` → exit 1, M8 in stderr (AC-16). Implement by wrapping the `model_validate_json` in the existing `except ValueError` pattern.
  - `::test_resume_rejects` — run dir whose `theme.json` is old format; `theme resume <run_id>` → exit 1, M8 in stderr (AC-62; the existing `except ValueError` should already cover it).
  - `test_core_sectors.py::test_llm_picks_only_listed` — fake LLM returns `["Copper production","Made-up sector","copper production"]` → activity `core_sectors == ["Copper production"]` via `classify_theme_core_sectors` (AC-36, Review Focus 4).
  - `test_activity_generator.py::test_anchored_drops_unlisted` — fake LLM drafts `core_sectors ["Copper production","Made-up sector"]` → `["Copper production"]` (AC-37).
  - `test_io_tier.py::test_prompt_list` — sample model `industry_prompt_list().splitlines()` has 163 lines, first `Cultivation of paddy rice` (AC-38).
  - `test_standards_mapper.py` — AC-39 (`nace` codes `["24"]`, naics `["331"]`, sic `["33"]`), AC-40, AC-41 with the bundled sample tables and an empty GICS reference.
  - `test_criticality.py` — AC-42 (`Copper production` → `True`), AC-43 (`Cultivation of wheat` → `False`).
  - Existing tests in these files: replace ICIO codes with sector names (for example `["B07"]` → `icio_sectors("B07")`, or the literal names), keeping the assertions.
- [ ] **Step 2:** Run the files above → FAIL.
- [ ] **Step 3:** Implement the interfaces. Prompts say "EXIOBASE sectors" where they said "ISIC Rev.4 industries"; `_CoreSectorSelection.isic_codes` → `sectors`; `_AnchoredActivityDraft.core_isic_codes` → `core_sectors`. `cli/theme.py` / `cli/taxonomy.py` / router texts say `core_sectors`; router's anchored notes use `len(model.industry_reference_list())`.
- [ ] **Step 4:** Run the files above → PASS (other suites may be red until Task 3).
- [ ] **Step 5:** No commit yet; continue with Task 3.

### Task 3: Companies and link rules name sectors; ICIO code list removed

**Files:**
- Modify: `research/indirect_exposure/company_mapper.py`, `exposure.py`, `factory.py` (delete `CodeList`, `code_list`), `io_import.py` (delete `SPLIT_INDUSTRIES`), `value_chain/build.py` (validate against `exiobase_nace.csv`), `value_chain/links.py`, `research/match_graph.py`, `research/pipeline.py`, `research/revenue_exposure/resolver.py`, `research/rd_exposure/resolver.py`, `schemas/value_chain.py`, `api/routers/value_chain.py`, `cli/io_tables.py`, `storage/postgres_models.py` (docstring)
- Delete: `reference/icio2025_industries.csv`
- Test: `tests/test_value_chain_links.py`, `test_value_chain_links_nace.py`, `test_indirect_exposure_nace.py`, `test_io_tier.py`, `test_company_mapper.py`, `test_rd_exposure_resolver.py`, revenue resolver tests, `test_research_pipeline.py`, `tests/e2e/test_value_chain_portfolio.py`, new `tests/test_exiobase_baseline.py`

**Interfaces:**
- Consumes: Task 1, Task 2 (`LeontiefModel.code_nodes` by sector).
- Produces:
  - `links.company_nace(company)`: also returns `("isic4", "<2 digits>", "2")` for a 2-digit ISIC code (AC-32); an `isic_code` like `"C26"` returns `None` (AC-33).
  - `links.company_nace_sectors(company) -> set[str]`: sector names of the company's NACE set (`isic4` 4-digit → `isic_to_nace2`; 2-digit → `[code]` as NACE division), empty when `company_nace` is `None`. Used by `nace_weights`, `exposure.compute_indirect_exposure` (NACE path) and the pipeline.
  - `links.company_source(company, rule) -> Literal["nodes","split","nace","llm","none"]` (no `code`).
  - Split/llm parts `{sectors: list[str], share: float}`; `validate_rule` order: part shape → non-empty → known sector → duplicate (within and across parts) → existing share checks. `Resolution.unresolved` carries the part as stored.
  - `company_mapper.resolve_company_sector(company, model, llm) -> tuple[str | None, LLMUsage]` (replaces `resolve_company_isic`; `lookup_isic` deleted).
  - `compute_indirect_exposure(company_id, sector: str, model, core_sectors: set[str], io_edition: str, *, critical_sectors=None, country=None, nace=None)`: non-NACE path uses `code_nodes[sector]`, `code_scheme="exiobase"`, `isic_code = isic_label = sector`; `critical_input = bool(company sectors ∩ critical_sectors())`.
  - `revenue_exposure.resolver.is_sector_relevant(company_sectors: set[str], core_sectors: list[str]) -> bool` (`True` if either is empty, else overlap). Resolvers and `match_graph` take `company_sectors: set[str]` instead of `company_isic`.
  - Pipeline: `company_sector, usage = await resolve_company_sector(...)` once per company; `company_sectors = company_nace_sectors(company) or ({company_sector} if company_sector else set())`; `CompanyMatchesResult.isic_code = company_sector`.
  - `schemas.value_chain.Sector(BaseModel): name: str`; `GET /api/value-chain/codes -> list[Sector]` from `sectors()`.
  - `links-import`: header `company_id,sector,share`, rows grouped per company into one-sector parts in CSV order.

- [ ] **Step 1: Failing tests:**
  - `test_exiobase_baseline.py::test_c1_weights_match_baseline` — migrate Fixture M's c1 parts with `convert_parts`, `resolve_company` on the sample build; each node weight equals `icio_baseline.json` to `1e-12` (AC-18).
  - `::test_c9_exposure_match_baseline` — `compute_indirect_exposure("c9", "", model, set(icio_sectors("B07")), …, country="DE", nace=("nace2","24.44","2"))`: up/downstream equal the baseline to `1e-12` (AC-19); `code_scheme == "nace2"`, `isic_code == "24.44"` (AC-20); `critical_input is True` (AC-44).
  - `test_io_tier.py::test_sector_path` — non-NACE path with `"Copper production"` → `code_scheme "exiobase"`, `isic_code == isic_label == "Copper production"` (AC-21).
  - `test_value_chain_links.py`: AC-22 (`GET /api/value-chain/codes` 163 items, item 0 `{"name": "Cultivation of paddy rice"}`), AC-23..27, AC-63..66 via `PUT /api/value-chain/links/company/c1` with the exact `detail`; AC-32, AC-33 on `company_source(company, None)`; Review Focus 2: a part whose sectors have no live node → appears in `unresolved` unchanged.
  - `test_indirect_exposure_nace.py`: Review Focus 1 — `nace=("nace2","99.00","2")` → `None`; relevance with that company's empty sectors → `True`.
  - `test_company_mapper.py`: AC-34 (NACE company → `None`, fake LLM call count 0), AC-35 (`Made-up sector` → `None`), LLM answering `Copper production` → `"Copper production"`.
  - revenue/rd resolver tests: AC-28..31 on `is_sector_relevant` with `company_nace_sectors(CompanyRef(..., nace_code="24.44", nace_rev="2"))`.
  - `tests/test_io_cli.py` (or the existing links-import test file): AC-45, AC-67, AC-46 via `CliRunner`; AC-47 with a minimal archive fixture containing sector `Foo` (reuse the build-full test's archive helper).
  - Existing tests: ICIO codes → sector names; `{icio_code}` parts → `{sectors}`; source `code` expectations → `nace` (2-digit ISIC) or `none`.
- [ ] **Step 2:** Run those files → FAIL.
- [ ] **Step 3:** Implement the interfaces; delete `CodeList`, `code_list`, `lookup_isic`, `SPLIT_INDUSTRIES`, `IcioCode`, `icio2025_industries.csv`. `build.py` checks the raw archive name against the raw `exiobase_sector` set from `nace._sector_rows()`.
- [ ] **Step 4:** `python3 -m pytest -q` (whole backend) → PASS; `ruff check .` clean.
- [ ] **Step 5:** Commit Tasks 2+3 together: `feat: EXIOBASE sectors replace ICIO codes in activities, companies and links`.

### Task 4: Past run results keep loading (`io_edition`)

**Files:**
- Modify: `backend/arp/schemas/exposure.py`, `research/indirect_exposure/exposure.py`, `research/match_graph.py`, every reader of `icio_edition` (`grep -rn icio_edition backend/arp`)
- Test: `tests/test_runs_export.py` or a new `tests/test_io_edition_compat.py`

**Interfaces — Produces:** `IndirectExposureResult.io_edition: str = Field(validation_alias=AliasChoices("io_edition", "icio_edition"), …)`, serialized as `io_edition`; `code_scheme: Literal["exiobase","nace2","nace21","isic4","icio"] = "exiobase"`.

- [ ] **Step 1: Failing tests:** a stored run (fixture run dir) whose result JSON has `"code_scheme": "icio", "icio_edition": "X"`; `GET /api/themes/runs/<run_id>/results` → 200 (AC-48), the result has `io_edition == "X"`, `code_scheme == "icio"` (AC-49). Review Focus 5: `migrate.convert_document` on a bare run `theme.json` dict converts like a taxonomy (add to `test_exiobase_migrate.py`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the field change.
- [ ] **Step 4:** Run + full backend suite → PASS.
- [ ] **Step 5:** Commit `feat: io_edition replaces icio_edition, old runs still load`.

### Task 5: `arp io migrate-exiobase`

**Files:**
- Modify: `backend/arp/research/indirect_exposure/migrate/__init__.py` (add the runners), `backend/arp/cli/io_tables.py` (command)
- Test: `backend/tests/test_exiobase_migrate.py` (CLI cases), Postgres case in the same file marked like other `ARP_TEST_POSTGRES_DSN` tests

**Interfaces:**
- Consumes: Task 1 converters; `TaxonomyStore.taxonomies_dir`; portfolio store `list_link_rules()` / `save_link_rule()`; `atomic_write_text`.
- Produces:
  - `migrate.plan_all(taxonomies_dir: Path, store) -> list[tuple[str, Callable[[], None]]]`: `(line, write)` per changed item in the order taxonomies (sorted id, then version number), then link rules (sorted subject); raises `UnknownIcioCode` re-raised as `ValueError(f"unknown ICIO code '{code}' in {where}")` before returning, so nothing is written on error.
  - `migrate.plan_file(path: Path, shown: str) -> list[tuple[str, Callable[[], None]]]`.
  - JSON written as `json.dumps(doc, indent=2, ensure_ascii=False)` (no trailing newline, matching `model_dump_json(indent=2)`); only `v*.json` files are read.
  - CLI `arp io migrate-exiobase [--file PATH] [--dry-run]`: prints each line, runs the writes unless `--dry-run`, prints `<n> changed`; on `ValueError` prints it to stderr, exit 1.

- [ ] **Step 1: Failing tests** (Fixture M built in a `tmp_path` fixture; taxonomies via raw JSON files, store = the file portfolio store):
  - AC-1, AC-2, AC-3 (`status`, `ratified_by`, `ratified_at` equal), AC-55, AC-56, AC-57, AC-4, AC-5, AC-6 (stdout lines exact, exit 0), AC-7, AC-59, AC-8, AC-9 (stderr exact), AC-10, AC-11, AC-60, AC-61, AC-12, AC-13.
  - AC-58: same as AC-4 on the Postgres store, skipped without `ARP_TEST_POSTGRES_DSN`.
  - Review Focus 3: `latest.json` and a stray `notes.txt` in `t1/` are byte-identical after migrate.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run + full backend suite → PASS.
- [ ] **Step 5:** Commit `feat: arp io migrate-exiobase`.

### Task 6: Frontend and API contract

**Files:**
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts` (`cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`)
- Modify: `frontend/src/types.ts` (`VcIcioCode` → `VcSector = Served<S["Sector"]>`; `core_isic_codes` → `core_sectors`; `icio_edition` → `io_edition`), `frontend/src/api/client.ts` (`valueChainCodes` returns `VcSector[]`), `frontend/src/lib/valueChain.ts`, `frontend/src/pages/value-chain/PortfolioView.tsx`, `frontend/src/pages/ThemeBuilder.tsx`, `frontend/src/api/contract.ts` if it lists `/api/value-chain/codes`
- Test: `frontend/tests/valueChain.test.ts`, the PortfolioView test file if present (else add `frontend/tests/linkEditor.test.tsx`)

**Interfaces — Produces:**
- `unresolvedText(part: { sectors?: string[]; region?: string; sector?: string; share: number })` → `` `Not in this edition: ${sectors.join(", ")} ${pct1(share)}` `` for split parts (AC-53: `A, B 40.0%`).
- `PortfolioView` `Part = { sectors?: string[]; region?: string; sector?: string; share: number }`; `Row` gets `sectors: string[]` in place of `code`; split rows render a labelled `<select multiple>` of the 163 names plus the share input; save sends `{ sectors: r.sectors, share }`.

- [ ] **Step 1: Failing tests:** `unresolvedText({sectors:["A","B"], share:0.4}) === "Not in this edition: A, B 40.0%"`; LinkEditor loaded with migrated c1 and saved unchanged sends a PUT body deep-equal to the loaded rule (AC-51).
- [ ] **Step 2:** `cd frontend && npm test` → FAIL.
- [ ] **Step 3:** Implement; `npx tsc -b` clean.
- [ ] **Step 4:** `npm run lint && npx tsc -b && npm test` → PASS. Screenshot the portfolio link editor with Playwright and run `/impeccable:impeccable audit` (CLAUDE.md).
- [ ] **Step 5:** Commit `feat(frontend): EXIOBASE sectors in the link editor and exposure view`.

### Task 7: ICIO leftovers sweep

**Files:**
- Modify: any remaining docstrings/comments naming ICIO outside the allowed set (`schemas/revenue_exposure.py`, `portfolio/entity_resolution.py`, `research/indirect_exposure/leontief.py`, `criticality.py`, `io_import.py`, `research/revenue_exposure/sample_data/README.md`, `research/standards_mapping/sample_data/README.md`)
- Test: `backend/tests/test_no_icio_left.py`

- [ ] **Step 1: Failing test** `test_no_icio_left.py`: runs the AC-50 command (Python `pathlib` walk equivalent: case-insensitive `icio` in file text, excluding `sanity_check.py` and `StrategyReplication.tsx`) and asserts the set equals the AC-50 list exactly; and the AC-68 filename check.
- [ ] **Step 2:** Run → FAIL (lists the leftovers).
- [ ] **Step 3:** Reword the leftovers (e.g. "OECD ICIO" → "OECD input-output tables" where it names the external dataset generally). `cli/io_tables.py` keeps `RETIRED_SETTINGS` and the migrate command; `pipeline.py` keeps `use_sample_icio`; `schemas/exposure.py` keeps the `"icio"` literal and alias; `schemas/thematic.py` keeps M8.
- [ ] **Step 4:** Run → PASS; full backend + frontend checks green.
- [ ] **Step 5:** Commit `chore: remove ICIO leftovers`. Then say in the PR whether `openwiki/` needs an update (it does: value-chain links and indirect exposure pages).
