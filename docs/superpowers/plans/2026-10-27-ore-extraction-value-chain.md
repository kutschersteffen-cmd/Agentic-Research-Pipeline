# Ore Extraction in the Value Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp io build-full` reads EXIOBASE's metal-ore rows; the footprint and upstream tree of the Value Chain Explorer show tonnes of gross ore.

**Architecture:** The build parses `material/F.txt` with the existing `_satellite`-style reader, stores direct (`m`) and total (`M = m · L`) ore intensities in new files written only when ore rows exist, and leaves `manifest.json` and `nodes.csv` untouched. `ValueChain` loads them when present; the router adds an `ore:<key>` footprint indicator and an optional `ore` on the tree; the two React views add ore pickers.

**Tech Stack:** Python 3, numpy, FastAPI, pydantic 2 (≥ 2.7: no `exclude_if`), pytest; React + TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-27-product-recipes-design.md`, section "Project 1" and "Acceptance (project 1)". Builds on `docs/superpowers/specs/2026-10-24-value-chain-explorer-design.md`.

## Global Constraints

- Ore rows: names starting `Domestic Extraction Used - Metal Ores - `; label = the rest; kt × 1000 → t.
- Ore key: label lower-cased, each run of chars outside `a–z0–9` → one `_`, strip leading/trailing `_`.
- Unit string `t ore`; note string `Ore: gross ore extracted, not metal content`.
- Build error, exact: `material/F.txt: no row starts with 'Domestic Extraction Used - Metal Ores - '`.
- No `material/F.txt`: build output byte-identical to `main` except `built_at` (AC-18). `manifest.json` and `nodes.csv` never change because of ores (AC-24).
- `/status` `ores`: `[{key, label}]` in archive row order; `[]` without ore data, also for a build directory made by `main`.
- Display: round to one decimal first; < 1,000 → one decimal; ≥ 1,000 → no decimals with thousands separators (`999.9 t ore`, `1,000 t ore`, `1,283 t ore`).
- No LLM call anywhere (AC-25/25b: tests run with the key unset and invalid, as `test_api_value_chain.py` already does).
- Checks: `cd backend && ruff check . && python3 -m pytest tests/test_value_chain_build.py tests/test_value_chain_model.py tests/test_api_value_chain.py`; `cd frontend && npm run lint && npx tsc -b && npm test`; API contract: `cd backend && python scripts/export_openapi.py`, then `cd frontend && npm run gen:api`, commit both generated files.
- PR body says `Spec: 2026-10-27-product-recipes-design` and lists every test change.

## Review Focus

1. Two ore labels that slug to the same key (e.g. `Copper ores` and `Copper-ores`) → the build fails with `material/F.txt: two ore rows share the key '<key>'`, never silently merges. Test in Task 1.
2. A request for an ore on a build without ore data (F0, or a `main` build) → 422, never 500 (AC-27). Test in Task 3.
3. `amount_meur` of `nan`, `inf` or ≤ 0 with `ore` on the tree → 422, like the footprint's `allow_inf_nan=False`. Test in Task 3.
4. A tree root whose total ore intensity is 0 → `ore_t` is `0`, not `null`, and the box shows `0.0 t ore`. Test in Task 2.
5. `/status` failing or slow on the screen → the footprint picker still shows CO₂e, Energy, Jobs and works; ore entries appear once status loads. Covered by Task 4's component behaviour; check by hand in the screenshot step.

---

### Task 1: Build reads ore rows

**Files:**
- Modify: `backend/arp/research/value_chain/build.py`
- Modify: `backend/tests/value_chain_fixture.py`
- Test: `backend/tests/test_value_chain_build.py`

**Interfaces:**
- Produces: in the fixture, `MATERIAL: dict[str, list[float]]` (the spec's four rows, in spec order, values for the four live nodes DE.2, DE.3, CN.2, CN.3 → `[0,0,0,0]`, `[5,5,5,5]`, `[0,0,0,0]`, `[40,0,100,0]`) and `write_fixture_f(directory: Path, material: dict[str, list[float]] | None = None) -> Path` (writes `material/F.txt` in the satellite layout only when `material` is given).
- Produces: `ore_key(label: str) -> str` in `build.py`.
- Produces: build files, written only when ore rows exist: `ores.json` (`[{"key","label"}]`, archive row order), `ore_m.npy` (float64, shape `(n_ores, n_nodes)`, t per M EUR, 0 where `x = 0`), `ore_M.npy` (same shape, `ore_m @ L`).

- [ ] **Step 1: Write failing tests** in `test_value_chain_build.py`:
  - `test_ore_key`: `ore_key("Other non-ferrous metal ores (incl. PGM)") == "other_non_ferrous_metal_ores_incl_pgm"`; `ore_key("Copper ores") == "copper_ores"`.
  - `test_ores_written` (AC-1 data): build `write_fixture_f(d, MATERIAL)`; `json.load(ores.json) == ORES` (spec value); `np.load(ore_M.npy)` row for copper at DE.2, DE.3, CN.2, CN.3 rounds to `452.4104, 71.6934, 1283.0655, 192.8307`; direct row `400, 0, 1000, 0`; paddy-rice columns 0.
  - `test_no_material_no_ore_files` (AC-11, AC-24): build F0 and F; F0 dir has no `ores.json`, `ore_m.npy`, `ore_M.npy`; `nodes.csv` byte-identical between the two; manifests equal without `built_at` and `source_sha256`; F0 stdout lines unchanged.
  - `test_material_without_ore_rows_fails` (AC-17): material `{"Domestic Extraction Used - Non-Metallic Minerals - Sand and gravel": [5,5,5,5]}`; `CliRunner` exit code ≠ 0; last non-empty stderr line equals the exact error; `out` does not exist.
  - `test_ore_key_collision_fails` (Review Focus 1): rows `... - Copper ores` and `... - Copper-ores` → `ValueError` with message `material/F.txt: two ore rows share the key 'copper_ores'`.

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_value_chain_build.py -v` — expected: the new tests FAIL (`ore_key` missing / `material` unexpected keyword).

- [ ] **Step 3: Implement** in `build.py`:
  - `ore_key` per Global Constraints (`re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")`).
  - `_ores(zf, index) -> tuple[list[dict], np.ndarray] | None`: `None` when `"material/F.txt"` is not in the archive; otherwise read it like `_satellite` (same header handling and column check), keep rows with the prefix, kt × 1000; raise the exact ValueErrors above.
  - In `build_full`: call `_ores` inside the `with zipfile` block; after inverting, keep `L` in memory long enough to compute `ore_M = ore_m @ L` (divide by `x` where live, 0 elsewhere) before `del`; write the three files into `tmp` only when `_ores` returned a value. Do not touch `nodes.csv`, `manifest.json` or stdout.
  - Fixture: `MATERIAL` and the `material` parameter; `material/F.txt` uses the same header lines as the other satellites.

- [ ] **Step 4: Run** the Step 2 command — expected: all PASS, including the existing build tests.

- [ ] **Step 5: Commit** `git add backend/arp/research/value_chain/build.py backend/tests/value_chain_fixture.py backend/tests/test_value_chain_build.py && git commit -m "feat(value-chain): build reads metal-ore rows from material/F.txt"`

### Task 2: Model answers ore footprints and ore trees

**Files:**
- Modify: `backend/arp/research/value_chain/model.py`
- Test: `backend/tests/test_value_chain_model.py`

**Interfaces:**
- Consumes: Task 1's `ores.json`, `ore_m.npy`, `ore_M.npy`.
- Produces: `ORE_UNIT = "t ore"`, `ORE_NOTE = "Ore: gross ore extracted, not metal content"`; `class UnknownOre(ValueError)` with message `unknown ore '<key>'`; `ValueChain.ores -> list[dict]` (`[]` when `ores.json` is absent); `ValueChain.footprint(node_id, indicator: str, amount_meur=1.0, top=6)` accepting `"ore:<key>"` (unit `t ore`, raises `UnknownOre`); `ValueChain.tree(node_id, depth=2, width=3, cutoff=0.01, goods_only=False, ore: str | None = None, amount_meur: float = 1.0) -> TreeItem`; `TreeItem` gains `ore_t: float | None` (None when `ore` is None).

- [ ] **Step 1: Write failing tests** (module fixture `vc_ore` built from `write_fixture_f(d, MATERIAL)`; existing `vc` stays F0):
  - `test_ores_listed`: `vc_ore.ores == ORES`; `vc.ores == []`.
  - `test_ore_footprint` (AC-3): `footprint("DE.3", "ore:copper_ores", 2)` → unit `t ore`, total 143.3869, by_region `[("DE",111.6016),("CN",31.7853)]`, by_sector `[("Mining of copper ores and concentrates",143.3869)]`, in_home 0.7783 (rounded 4).
  - `test_ore_footprint_cn2` (AC-4): total 1283.0655.
  - `test_ore_footprint_zero` (AC-5): `ore:nickel_ores` → total 0, in_home None, both lists `[]`.
  - `test_unknown_ore` (AC-6, AC-8, AC-27): `ore:sand_and_gravel`, `ore:gold_ores` on `vc_ore`, and `ore:copper_ores` on `vc`, each raise `UnknownOre`; same for `tree(..., ore="gold_ores")`.
  - `test_ore_tree` (AC-7): `tree("DE.3", ore="copper_ores", amount_meur=2)` → `ore_t` root 143.3869; CN.3 38.5661; DE.2 90.4821; CN.3→CN.2 25.6613, CN.3→DE.2 9.0482; DE.2→DE.3 1.4339; shape (ids, coef, chain) equal to `test_tree_full`.
  - `test_ore_tree_default_amount` (AC-20): root `ore_t` 71.6934.
  - `test_tree_without_ore` (AC-10): every item's `ore_t is None`.
  - `test_ore_tree_zero_root` (Review Focus 4): `tree("DE.3", ore="nickel_ores").ore_t == 0.0`.

- [ ] **Step 2: Run** `python3 -m pytest tests/test_value_chain_model.py -v` — expected: new tests FAIL.

- [ ] **Step 3: Implement**: load the ore files in `ValueChain.__init__` only if `ores.json` exists; footprint uses `contribution = ore_m[j] * L[:, k] * amount` for an ore (same grouping code as today); tree computes `ore_t = amount_meur * chain * ore_M[j, node]` per item. Keep `load_value_chain`'s cache key as is (the manifest changes on every build).

- [ ] **Step 4: Run** the Step 2 command — expected: all PASS.

- [ ] **Step 5: Commit** `git commit -am "feat(value-chain): ore footprint indicator and embodied ore in the tree"`

### Task 3: API exposes ores

**Files:**
- Modify: `backend/arp/schemas/value_chain.py`, `backend/arp/api/routers/value_chain.py`
- Modify (generated): `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`
- Test: `backend/tests/test_api_value_chain.py`

**Interfaces:**
- Consumes: Task 2's `ores`, `footprint`, `tree`, `UnknownOre`, `ORE_NOTE`.
- Produces: schemas `ValueChainOre {key, label}`; `ValueChainStatus.ores: list[ValueChainOre]`; `ValueChainOreFootprint(ValueChainFootprint)` with `ore_note: str`; `ValueChainOreTreeNode(ValueChainTreeNode)` with `ore_t: float` and `children: list[ValueChainOreTreeNode]`; `ValueChainOreTree(ValueChainOreTreeNode)` with `edition`, `caveat`, `ore_note`. Footprint returns `ValueChainFootprint | ValueChainOreFootprint`, tree returns `ValueChainTree | ValueChainOreTree`, so `ore_note`/`ore_t` keys are absent, not null, without an ore (pydantic < 2.11 has no `exclude_if`).
- Produces: query params — footprint `indicator: str = "ghg"` (accepted: `ghg`, `energy`, `jobs`, `ore:<key>`; anything else 422); tree `ore: str | None = None`, `amount_meur: Annotated[float, Query(allow_inf_nan=False)] = 1.0` (≤ 0 with `ore` → 422; ignored without `ore`, AC-21b).

- [ ] **Step 1: Write failing tests** (a second module fixture `built_ore` for F; existing `built` is F0; both run under the existing no-key / invalid-key parametrisation):
  - AC-1, AC-2: `/status` `ores` equals `ORES` / `[]`.
  - AC-3, AC-5 full responses including `ore_note`; AC-9 ghg response values and `"ore_note" not in body`.
  - AC-6, AC-8, AC-21, AC-27 (on `built` and on a directory with the ore files deleted, standing in for a `main` build): status 422.
  - AC-7 and AC-20 `ore_t` values; AC-10 and AC-21b: no `ore_t` key anywhere in the tree, no `ore_note`; AC-21b body equals AC-10 body.
  - Review Focus 3: `/tree?ore=copper_ores&amount_meur=nan` and `=inf` → 422.

- [ ] **Step 2: Run** `python3 -m pytest tests/test_api_value_chain.py -v` — expected: new tests FAIL.

- [ ] **Step 3: Implement** the schemas and router changes; map `UnknownOre` and an invalid indicator to `HTTPException(422, str(e))` next to `_unknown_is_404`.

- [ ] **Step 4: Run** the Step 2 command, then `ruff check .` and the full value-chain test files — expected: PASS, clean.

- [ ] **Step 5: Regenerate the contract**: `python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b` — expected: `tsc` reports only errors in `client.ts`/value-chain views caused by the widened types; leave them for Task 4 if any.

- [ ] **Step 6: Commit** `git add -A backend frontend/src/api && git commit -m "feat(api): ores in value-chain status, footprint and tree"`

### Task 4: Screens show ore

**Files:**
- Modify: `frontend/src/lib/valueChain.ts`, `frontend/src/api/client.ts`, `frontend/src/types.ts` (only if new `Vc*` aliases are needed), `frontend/src/pages/value-chain/FootprintView.tsx`, `frontend/src/pages/value-chain/TreeView.tsx`
- Test: `frontend/tests/valueChain.test.ts`

**Interfaces:**
- Consumes: Task 3's generated types and endpoints.
- Produces: `oreTonnes(t: number): string` in `lib/valueChain.ts`; `ORE_NOTE` constant there; `api.valueChainFootprint(id, { indicator: string; amount: number })`; `api.valueChainTree(id, { depth, cutoff, goodsOnly, ore?: string, amount?: number })` (sends `ore` and `amount_meur` only when `ore` is set).

- [ ] **Step 1: Write failing tests** in `valueChain.test.ts` (AC-30, My call 4): `oreTonnes(143.3869) === "143.4 t ore"`, `oreTonnes(999.94) === "999.9 t ore"`, `oreTonnes(999.96) === "1,000 t ore"`, `oreTonnes(1283.0655) === "1,283 t ore"`, `oreTonnes(0) === "0.0 t ore"`.

- [ ] **Step 2: Run** `cd frontend && npm test -- valueChain` — expected: FAIL (`oreTonnes` not exported).

- [ ] **Step 3: Implement**:
  - `oreTonnes`: round to one decimal, then format with `toLocaleString("en-US")` (`maximumFractionDigits: 0` from 1,000, `minimumFractionDigits: 1` below).
  - FootprintView: fetch `/status` once; picker = the three current buttons, then one per ore labelled `<label> (ore)`, value `ore:<key>`; total uses `oreTonnes` for ore indicators; show `fp.ore_note` as a `help-text` line under the caveat when present.
  - TreeView: `Show ore` `<select>` (`None`, then status labels without suffix) and an amount input (M EUR, default `1`, same validation as FootprintView); with an ore, each box gains a line `oreTonnes(node.ore_t)`; `ore_note` line under the caveat.

- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — expected: PASS, clean.

- [ ] **Step 5: Look at it**: `bash .claude/hooks/ensure-deps.sh postgres && bash backend/scripts/e2e_stack.sh up` with `ARP_VALUE_CHAIN_DIR` set to a build of fixture F (`write_fixture_f(d, MATERIAL)`); screenshot `#/valueChain/DE.3/footprint` with `Copper ores (ore)` at amount 2 and `#/valueChain/DE.3/tree` with `Show ore` `Copper ores` at amount 2 using Playwright; check against AC-12, AC-13, AC-14, AC-15, AC-19, AC-22, AC-26, AC-28; run `/impeccable:impeccable audit` on both; `e2e_stack.sh down`.

- [ ] **Step 6: Commit** `git add frontend && git commit -m "feat(value-chain): ore pickers in footprint and tree views"`

---

Out of this plan (spec rows the evaluator checks after CI is green, no task needed): AC-16, AC-16b, AC-16c, AC-16d and AC-29b need the real archive; AC-18 and AC-29 are holdout rows run by CI against `origin/main` and the explorer suite.
