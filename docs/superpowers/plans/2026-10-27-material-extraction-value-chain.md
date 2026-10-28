# Material Extraction in the Value Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp io build-full` reads every used-extraction row of EXIOBASE's material accounts; the footprint and upstream tree of the Value Chain Explorer show tonnes extracted per material (metal ores, minerals, fossil fuels, biomass).

**Architecture:** The build parses `material/F.txt` like the other satellites, stores direct (`m`) and total (`M = m · L`) material intensities in new files written only when material rows exist, and leaves `manifest.json` and `nodes.csv` untouched. `ValueChain` loads them when present; the router adds a `material:<key>` footprint indicator and an optional `material` on the tree; the two React views get grouped material selects.

**Tech Stack:** Python 3, numpy, FastAPI, pydantic 2 (≥ 2.7: no `exclude_if`), pytest; React + TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-27-product-recipes-design.md`, sections "Project 1" and "Acceptance (project 1)". Builds on `docs/superpowers/specs/2026-10-24-value-chain-explorer-design.md`.

## Global Constraints

- Material rows: names starting `Domestic Extraction Used - `; the rest splits at its first ` - ` into group and label (no ` - `: group `Other`, label = rest); kt × 1000 → t.
- Key: the rest (group and label) lower-cased, each run of chars outside `a–z0–9` → one `_`, strip leading/trailing `_` (`metal_ores_copper_ores`).
- Unit `t`; note N, exact: `Extraction: tonnes taken from nature (metal ores as gross ore), not content in the product`.
- Build errors, exact: `material/F.txt: no row starts with 'Domestic Extraction Used - '`; `material/F.txt: two rows share the key '<key>'`.
- No `material/F.txt`: build output byte-identical to `main` except `built_at` (AC-18). `manifest.json` and `nodes.csv` never change because of materials (AC-24).
- `/status` `materials`: `[{key, label, group}]` in archive row order; `[]` without material data, also for a build directory made by `main`.
- Display: round to one decimal first; < 1,000 → one decimal; ≥ 1,000 → no decimals with thousands separators (`999.9 t`, `1,000 t`, `1,283 t`).
- No LLM call anywhere (AC-25/25b: API tests run with the key unset and invalid, as `test_api_value_chain.py` already does).
- Checks: `cd backend && ruff check . && python3 -m pytest tests/test_value_chain_build.py tests/test_value_chain_model.py tests/test_api_value_chain.py`; `cd frontend && npm run lint && npx tsc -b && npm test`; API contract: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, commit both generated files.
- PR body says `Spec: 2026-10-27-product-recipes-design` and lists every test change.

## Review Focus

1. A material request on a build without material data (F0, or a `main` build) → 422, never 500 (AC-27). Test in Task 3.
2. `amount_meur` of `nan`, `inf` or ≤ 0 with `material` on the tree → 422, like the footprint's `allow_inf_nan=False`. Test in Task 3.
3. A tree root whose total intensity is 0 → `extracted_t` is `0`, not `null`, and the box shows `0.0 t`. Test in Task 2.
4. A real archive with 100+ materials → the `Indicator` select stays usable: options grouped by material group, keyboard reachable, the page does not widen at phone width. Check by hand in Task 4's screenshot step at 400 px.
5. `/status` failing or slow on the screen → the footprint select still offers CO₂e, Energy, Jobs and works; material groups appear once status loads. Check by hand in Task 4.

---

### Task 1: Build reads material rows

**Files:**
- Modify: `backend/arp/research/value_chain/build.py`
- Modify: `backend/tests/value_chain_fixture.py`
- Test: `backend/tests/test_value_chain_build.py`

**Interfaces:**
- Produces: in the fixture, `MATERIAL: dict[str, list[float]]` (the spec's five rows, in spec order, values for the four live nodes DE.2, DE.3, CN.2, CN.3) and `write_fixture_f(directory: Path, material: dict[str, list[float]] | None = None) -> Path` (writes `material/F.txt` in the satellite layout only when `material` is given).
- Produces: `material_key(rest: str) -> str` and `split_material(rest: str) -> tuple[str, str]` (group, label) in `build.py`.
- Produces: build files, written only when material rows exist: `materials.json` (`[{"key","label","group"}]`, archive row order), `material_m.npy` (float64, shape `(n_materials, n_nodes)`, t per M EUR, 0 where `x = 0`), `material_M.npy` (same shape, `material_m @ L`).

- [ ] **Step 1: Write failing tests** in `test_value_chain_build.py`:
  - `test_material_key_and_split`: `material_key("Metal Ores - Other non-ferrous metal ores (incl. PGM)") == "metal_ores_other_non_ferrous_metal_ores_incl_pgm"`; `split_material("Metal Ores - Copper ores") == ("Metal Ores", "Copper ores")`; `split_material("Peat") == ("Other", "Peat")`.
  - `test_materials_written` (AC-1, AC-32 data): build `write_fixture_f(d, MATERIAL)`; `json.load(materials.json) == MATERIALS` (spec value); `material_M.npy` copper row at DE.2, DE.3, CN.2, CN.3 rounds to `452.4104, 71.6934, 1283.0655, 192.8307`, sand row to `60.2596, 42.3362, 76.6378, 70.7664`; the `Unused Domestic Extraction` row is not present; paddy-rice columns 0. With an extra `Domestic Extraction Used - Peat` row, the last entry is `{"key":"peat","label":"Peat","group":"Other"}`.
  - `test_no_material_no_files` (AC-11, AC-24, AC-33): build F0 and F; F0 dir has none of the three files; `nodes.csv` byte-identical between the two; manifests equal without `built_at` and `source_sha256`; stdout of both builds is exactly the two explorer lines.
  - `test_material_without_rows_fails` (AC-17): material file with only the `Unused Domestic Extraction` row; `CliRunner` exit ≠ 0; last non-empty stderr line equals the exact error; `out` does not exist.
  - `test_key_collision_fails` (AC-31): extra row `Domestic Extraction Used - Metal Ores - Copper-ores` → exit ≠ 0, last stderr line `material/F.txt: two rows share the key 'metal_ores_copper_ores'`.

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_value_chain_build.py -v` — expected: the new tests FAIL (`material_key` missing / `material` unexpected keyword).

- [ ] **Step 3: Implement** in `build.py`:
  - `material_key` and `split_material` per Global Constraints.
  - `_materials(zf, index) -> tuple[list[dict], np.ndarray] | None`: `None` when `"material/F.txt"` is not in the archive; otherwise read it with the same header handling and column check as `_satellite`, keep prefixed rows, kt × 1000; raise the two exact ValueErrors.
  - In `build_full`: call `_materials` inside the `with zipfile` block; keep `L` in memory after inverting long enough to compute `material_M = material_m @ L` (`material_m` = tonnes ÷ `x` where live, 0 elsewhere) before `del`; write the three files into `tmp` only when `_materials` returned a value. Do not touch `nodes.csv`, `manifest.json` or stdout.

- [ ] **Step 4: Run** the Step 2 command — expected: all PASS, including the existing build tests.

- [ ] **Step 5: Commit** `git add backend/arp/research/value_chain/build.py backend/tests/value_chain_fixture.py backend/tests/test_value_chain_build.py && git commit -m "feat(value-chain): build reads material extraction rows"`

### Task 2: Model answers material footprints and trees

**Files:**
- Modify: `backend/arp/research/value_chain/model.py`
- Test: `backend/tests/test_value_chain_model.py`

**Interfaces:**
- Consumes: Task 1's three files.
- Produces: `MATERIAL_UNIT = "t"`, `MATERIAL_NOTE` = N; `class UnknownMaterial(ValueError)` with message `unknown material '<key>'`; `ValueChain.materials -> list[dict]` (`[]` when `materials.json` is absent); `ValueChain.footprint(node_id, indicator: str, amount_meur=1.0, top=6)` accepting `"material:<key>"` (unit `t`, raises `UnknownMaterial`); `ValueChain.tree(node_id, depth=2, width=3, cutoff=0.01, goods_only=False, material: str | None = None, amount_meur: float = 1.0) -> TreeItem`; `TreeItem` gains `extracted_t: float | None` (None when `material` is None).

- [ ] **Step 1: Write failing tests** (module fixture `vc_mat` built from `write_fixture_f(d, MATERIAL)`; existing `vc` stays F0):
  - `test_materials_listed`: `vc_mat.materials == MATERIALS`; `vc.materials == []`.
  - `test_material_footprint` (AC-3): `footprint("DE.3", "material:metal_ores_copper_ores", 2)` → unit `t`, total 143.3869, by_region `[("DE",111.6016),("CN",31.7853)]`, by_sector `[("Mining of copper ores and concentrates",143.3869)]`, in_home 0.7783 (rounded 4).
  - `test_material_footprint_cn2` (AC-4): total 1283.0655.
  - `test_material_footprint_zero` (AC-5): nickel → total 0, in_home None, both lists `[]`.
  - `test_sand_footprint` (AC-6b): total 84.6724; by_region `[("DE",70.3691),("CN",14.3034)]`; by_sector `[("Other business activities",69.133),("Mining of copper ores and concentrates",15.5395)]`; in_home 0.8311.
  - `test_unknown_material` (AC-6, AC-8, AC-27): `material:copper_ores`, `material:metal_ores_gold_ores` on `vc_mat`, and `material:metal_ores_copper_ores` on `vc`, each raise `UnknownMaterial`; same for `tree(..., material="metal_ores_gold_ores")`.
  - `test_material_tree` (AC-7): copper, amount 2 → `extracted_t` root 143.3869; CN.3 38.5661; DE.2 90.4821; CN.3→CN.2 25.6613, CN.3→DE.2 9.0482; DE.2→DE.3 1.4339; shape (ids, coef, chain) equal to `test_tree_full`.
  - `test_sand_tree` (AC-7b): root 84.6724; level-1 CN.3 14.1533; level-1 DE.2 12.0519.
  - `test_material_tree_default_amount` (AC-20): copper root 71.6934.
  - `test_tree_without_material` (AC-10): every item's `extracted_t is None`.
  - `test_material_tree_zero_root` (Review Focus 3): nickel root `extracted_t == 0.0`.

- [ ] **Step 2: Run** `python3 -m pytest tests/test_value_chain_model.py -v` — expected: new tests FAIL.

- [ ] **Step 3: Implement**: load the files in `ValueChain.__init__` only if `materials.json` exists; footprint uses `contribution = material_m[j] * L[:, k] * amount` for a material (same grouping code as today); tree sets `extracted_t = amount_meur * chain * material_M[j, node]` per item. Keep `load_value_chain`'s cache key as is.

- [ ] **Step 4: Run** the Step 2 command — expected: all PASS.

- [ ] **Step 5: Commit** `git commit -am "feat(value-chain): material footprint indicator and embodied tonnes in the tree"`

### Task 3: API exposes materials

**Files:**
- Modify: `backend/arp/schemas/value_chain.py`, `backend/arp/api/routers/value_chain.py`
- Modify (generated): `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/test_api_value_chain.py`

**Interfaces:**
- Consumes: Task 2's `materials`, `footprint`, `tree`, `UnknownMaterial`, `MATERIAL_NOTE`.
- Produces: schemas `ValueChainMaterial {key, label, group}`; `ValueChainStatus.materials: list[ValueChainMaterial]`; `ValueChainMaterialFootprint(ValueChainFootprint)` with `material_note: str`; `ValueChainMaterialTreeNode(ValueChainTreeNode)` with `extracted_t: float` and `children: list[ValueChainMaterialTreeNode]`; `ValueChainMaterialTree(ValueChainMaterialTreeNode)` with `edition`, `caveat`, `material_note`. Footprint returns `ValueChainFootprint | ValueChainMaterialFootprint`, tree returns `ValueChainTree | ValueChainMaterialTree`, so `material_note` / `extracted_t` keys are absent, not null, without a material (pydantic < 2.11 has no `exclude_if`).
- Produces: query params — footprint `indicator: str = "ghg"` (accepted: `ghg`, `energy`, `jobs`, `material:<key>`; anything else 422); tree `material: str | None = None`, `amount_meur: Annotated[float, Query(allow_inf_nan=False)] = 1.0` (≤ 0 with `material` → 422; ignored without `material`, AC-21b).

- [ ] **Step 1: Write failing tests** (a second module fixture `built_mat` for F; existing `built` is F0; both under the existing no-key / invalid-key parametrisation):
  - AC-1, AC-2: `/status` `materials` equals `MATERIALS` / `[]`.
  - AC-3, AC-5, AC-6b full responses including `material_note`; AC-9 ghg values and `"material_note" not in body`.
  - AC-6, AC-8, AC-21, AC-27 (on `built` and on a directory with the three material files deleted, standing in for a `main` build): 422.
  - AC-7, AC-7b, AC-20 `extracted_t` values; AC-10 and AC-21b: no `extracted_t` key anywhere in the tree, no `material_note`; AC-21b body equals AC-10 body.
  - Review Focus 2: `/tree?material=metal_ores_copper_ores&amount_meur=nan` and `=inf` → 422.

- [ ] **Step 2: Run** `python3 -m pytest tests/test_api_value_chain.py -v` — expected: new tests FAIL.

- [ ] **Step 3: Implement** the schemas and router changes; map `UnknownMaterial` and an invalid indicator to `HTTPException(422, str(e))` next to `_unknown_is_404`.

- [ ] **Step 4: Run** the Step 2 command, then `ruff check .` and the three value-chain test files — expected: PASS, clean.

- [ ] **Step 5: Regenerate the contract**: `python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b` — expected: any `tsc` errors are only in `client.ts` and the value-chain views; Task 4 fixes them.

- [ ] **Step 6: Commit** `git add -A backend frontend/src/api && git commit -m "feat(api): materials in value-chain status, footprint and tree"`

### Task 4: Screens show materials

**Files:**
- Modify: `frontend/src/lib/valueChain.ts`, `frontend/src/api/client.ts`, `frontend/src/types.ts` (only for new `Vc*` aliases), `frontend/src/pages/value-chain/FootprintView.tsx`, `frontend/src/pages/value-chain/TreeView.tsx`
- Test: `frontend/tests/valueChain.test.ts`

**Interfaces:**
- Consumes: Task 3's generated types and endpoints.
- Produces: `tonnes(t: number): string` and `MATERIAL_NOTE` in `lib/valueChain.ts`; `api.valueChainFootprint(id, { indicator: string; amount: number })`; `api.valueChainTree(id, { depth, cutoff, goodsOnly, material?: string, amount?: number })` (sends `material` and `amount_meur` only when `material` is set).

- [ ] **Step 1: Write failing tests** in `valueChain.test.ts` (AC-30, My call 4): `tonnes(143.3869) === "143.4 t"`, `tonnes(999.94) === "999.9 t"`, `tonnes(999.96) === "1,000 t"`, `tonnes(1283.0655) === "1,283 t"`, `tonnes(0) === "0.0 t"`.

- [ ] **Step 2: Run** `cd frontend && npm test -- valueChain` — expected: FAIL (`tonnes` not exported).

- [ ] **Step 3: Implement**:
  - `tonnes`: round to one decimal, then `toLocaleString("en-US")` with `minimumFractionDigits: 1` below 1,000 and `maximumFractionDigits: 0` from 1,000.
  - FootprintView: fetch `/status` once; replace the CO₂e / Energy / Jobs buttons with one labelled `Indicator` `<select>`: `<optgroup label="Indicators">` (CO₂e, Energy, Jobs; CO₂e selected), then one `<optgroup>` per material group in `/status` order, options = labels, values `material:<key>`; total uses `tonnes` for material indicators; show `fp.material_note` as a `help-text` line under the caveat when present.
  - TreeView: `Show material` `<select>` (`None`, then the same groups) and an amount input (M EUR, default `1`, same validation as FootprintView); with a material, each box gains a line `tonnes(node.extracted_t)`; `material_note` line under the caveat.

- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — expected: PASS, clean.

- [ ] **Step 5: Look at it**: `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up` with `ARP_VALUE_CHAIN_DIR` set to a build of `write_fixture_f(d, MATERIAL)`; screenshot with Playwright, at 1280 px and 400 px, `#/valueChain/DE.3/footprint` with `Copper ores` at amount 2 and `#/valueChain/DE.3/tree` with `Show material` `Copper ores` at amount 2; check against AC-12, AC-13, AC-14, AC-15, AC-19, AC-22, AC-26, AC-28 and Review Focus 4–5; run `/impeccable:impeccable audit` on both; `e2e_stack.sh down`.

- [ ] **Step 6: Commit** `git add frontend && git commit -m "feat(value-chain): material selects in footprint and tree views"`

---

Out of this plan (spec rows the evaluator checks after CI is green, no task needed): AC-16, AC-16b, AC-16c, AC-16d and AC-29b need the real archive; AC-18 and AC-29 are holdout rows run by CI against `origin/main` and the explorer suite.
