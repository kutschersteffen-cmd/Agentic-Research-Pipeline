# Value Chain Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp io build-full` turns one EXIOBASE 3 ixi archive into full-resolution Leontief and Ghosh
matrices, a read-only `/api/value-chain` API serves nodes, suppliers, customers, upstream trees and
footprints from them, and a "Value Chain Explorer" screen in the R&D Lab shows the three views.

**Architecture:**
- `arp/research/value_chain/build.py` streams the archive, computes `A`, `L = (I−A)⁻¹`, `G = (I−B)⁻¹`
  in float64 and writes `manifest.json`, `nodes.csv`, `A.npy`, `L.npy`, `G.npy`.
- `arp/research/value_chain/model.py` loads a built directory once per process (cached on directory +
  `built_at`) and answers every query with plain numpy reads. No database, no LLM, no Neo4j.
- `arp/api/routers/value_chain.py` is a thin read-only router; `frontend/src/pages/value-chain/` holds
  the screen, `frontend/src/lib/valueChain.ts` the display formatting.

**Tech Stack:** numpy, FastAPI, Pydantic v2, Typer, pytest; React/TS, `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-24-value-chain-explorer-design.md` (owner approved 2026-10-24).
Its Definitions, Appendix B (API) and Appendix C (screen) are normative; this plan does not repeat them.

## Global Constraints

- All arithmetic, stored matrices and cut-off comparisons are float64. Nothing is rounded before display.
- No LLM call anywhere in this feature; tests make no network calls.
- `arp io import-exiobase` and every existing indirect-exposure test stay unchanged (AC-39 to AC-41).
- Copy verbatim from the spec:
  - caveat: `EXIOBASE <version> · <year> · basic prices, M EUR · now-cast years are estimates · capital goods not included in flows`
  - 503 detail: `value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR`
  - 404 detail: `unknown node '<id>'`
  - picker empty state: `Pick a sector and region.`
  - RoW labels: WA `RoW Asia-Pacific`, WE `RoW Europe`, WF `RoW Africa`, WL `RoW Americas`, WM `RoW Middle East`
  - build stdout: `<n_nodes> nodes (<n_sectors> sectors × <n_regions> regions) -> <out>` then `ARP_VALUE_CHAIN_DIR=<out>`, `<out>` exactly as given
- Display: flows `7.4¢` (one decimal), tree chain `0.80¢` (two), tiles one decimal, value added and home
  share whole percent rounded half up, footprint total one decimal plus unit.
- Limits: build ≤ 20 min and ≤ 8 GB RSS on the real archive; node, tree (depth 4, width 5) and footprint
  requests ≤ 1 s on a warm process.
- Derived files are never committed.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; `cd frontend && npm run lint && npx tsc -b && npm test`.

## Review Focus

1. Malformed or stale node ids in a URL (`#/valueChain/abc`, `DE.999`, `DE.0`) must give 404 `unknown node '<id>'`, shown as the page message, never a crash (Task 3, Task 5).
2. A broken archive (no `Z.txt`, a sector missing from the crosswalk, a non-numeric cell) must exit 1 with one line on stderr and leave `--out` untouched (Task 1).
3. Rebuilding into the same directory while the API runs must be served on the next request without a restart (cache keyed on `built_at`) (Task 2).
4. An empty or whitespace search (`q=`, `q=%20`) must answer 422, and the picker must not request until a non-space character is typed (Task 3, Task 4).
5. `percent(0.845)` must read `85%`: half-up rounding on floats like 84.4999… (Task 4).

---

### Task 1: Build command (`arp io build-full`) and fixture F

**Files:**
- Create: `backend/arp/research/value_chain/__init__.py` (empty), `backend/arp/research/value_chain/build.py`
- Create: `backend/tests/value_chain_fixture.py`, `backend/tests/test_value_chain_build.py`
- Modify: `backend/arp/cli/io_tables.py` (new command next to `import-exiobase`), `backend/arp/config.py` (setting)

**Interfaces:**
- Produces: `build_full(zip_path: Path, out: Path, label: str | None = None) -> list[str]` (stdout lines; raises `ValueError` with a one-line message).
- Produces: `Settings.value_chain_dir: Path | None` (env `ARP_VALUE_CHAIN_DIR`, default `None`).
- Produces: `write_fixture_f(directory: Path) -> Path` in `tests/value_chain_fixture.py`, returning `<directory>/IOT_2022_ixi.zip` built exactly as the spec's Fixture F (same layout as the real archive: three header lines in `Z.txt` and each `F.txt`, `x.txt` with `region, sector, indout`, `metadata.json` with `version` `3.11.2` and `name` `EXIO_IOT_2022_ixi`, satellite folders `air_emissions`, `energy`, `employment`, `factor_inputs`). Mirror `_exiobase_fixture` in `tests/test_io_import.py` for the file shapes.
- Produces on disk: `manifest.json` (Appendix A keys), `nodes.csv` (Appendix A columns, archive order, `goods` as `true`/`false`, intensities empty where `x = 0`), `A.npy`, `L.npy`, `G.npy` (float64, n×n, archive order).

- [ ] **Step 1: Write the failing tests** in `tests/test_value_chain_build.py`

```python
def test_build_fixture_prints_counts_and_setting(tmp_path):        # AC-1
    out = tmp_path / "vc"
    res = runner.invoke(app, ["io", "build-full", str(write_fixture_f(tmp_path)), "--out", str(out)])
    assert res.exit_code == 0
    assert res.stdout.splitlines()[:2] == [f"6 nodes (3 sectors × 2 regions) -> {out}", f"ARP_VALUE_CHAIN_DIR={out}"]

def test_manifest(tmp_path):                                        # AC-1b
    m = json.loads((build(tmp_path) / "manifest.json").read_text())
    assert (m["edition"], m["exiobase_version"], m["year"]) == ("exiobase-IOT_2022_ixi", "3.11.2", 2022)
    assert (m["n_regions"], m["n_sectors"], m["n_nodes"]) == (2, 3, 6)

def test_matrices(tmp_path):
    d = build(tmp_path); L = np.load(d / "L.npy"); G = np.load(d / "G.npy")
    # archive order: DE.1, DE.2, DE.3, CN.1, CN.2, CN.3
    assert round(L[1, 4], 4) == 0.0336 and round(L[5, 4], 4) == 0.1572 and round(G[1, 2], 4) == 0.279
    assert L.dtype == np.float64 and L[0, 0] == 1.0 and not L[0, [1, 2, 4, 5]].any()   # zero-output node isolated

def test_nodes_csv(tmp_path):
    rows = list(csv.DictReader((build(tmp_path) / "nodes.csv").open()))
    de2 = next(r for r in rows if r["node_id"] == "DE.2")
    assert de2["goods"] == "true" and float(de2["ghg_t_per_meur"]) == 5 and float(de2["va_share"]) == 0.3
    de1 = next(r for r in rows if r["node_id"] == "DE.1")
    assert de1["output_meur"] in ("0", "0.0") and de1["ghg_t_per_meur"] == ""

@pytest.mark.parametrize("break_it", ["drop_z", "unknown_sector", "bad_cell"])
def test_broken_archive_exits_1_and_writes_nothing(tmp_path, break_it):   # Review Focus 2
    res = runner.invoke(app, ["io", "build-full", str(broken_fixture(tmp_path, break_it)), "--out", str(tmp_path / "vc")])
    assert res.exit_code == 1 and len(res.stderr.strip().splitlines()) == 1 and not (tmp_path / "vc").exists()

def test_rebuild_replaces_directory(tmp_path):                       # Review Focus 3 (disk side)
    d = build(tmp_path); (d / "stale.txt").write_text("x"); build(tmp_path, label="second")
    assert not (d / "stale.txt").exists() and json.loads((d / "manifest.json").read_text())["edition"] == "second"
```

`build(tmp_path, label=None)` and `broken_fixture(tmp_path, kind)` are small helpers in the test file; `broken_fixture` rewrites fixture F with `Z.txt` removed, a sector renamed to `Not a sector`, or one `Z` cell set to `abc`.

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_value_chain_build.py -q` — expected: FAIL (no `build-full` command).

- [ ] **Step 3: Implement `build_full` in `backend/arp/research/value_chain/build.py`**
  - Reuse `_lines`, `_read_reference` and `REFERENCE_DIR` from `arp.research.indirect_exposure.io_import`; skip the three header lines as `import_exiobase` does.
  - Year: the digits in `metadata.json` `name` (`EXIO_IOT_<year>_ixi`); version: `metadata.json` `version`.
  - Intensities and goods flag exactly per the spec's Definitions; GWP factors from `ghg_gwp100.csv` (unknown stressors count 0); goods = crosswalk `icio_code` starts with `A`–`E`; a sector missing from the crosswalk raises `ValueError(f"EXIOBASE sector not in crosswalk: {sector}")`.
  - `A = Z / x` per column with zero columns where `x = 0`; `B` the row analogue; `L = np.linalg.inv(I − A)`, `G = np.linalg.inv(I − B)`; free `Z` and `B` before the second inversion to stay under 8 GB.
  - Write into a sibling temp dir (`out.parent / f".{out.name}.building"`), then replace `out` (remove old, rename) so a failure leaves `out` untouched and a rebuild leaves no stale files.
  - `--label` default `exiobase-<archive stem>`; `built_at` = UTC now, RFC 3339.

- [ ] **Step 4: Add the setting and the command**
  - `backend/arp/config.py`, next to the EXIOBASE settings: `value_chain_dir: Path | None = Field(default=None, description="Directory written by arp io build-full; unset disables the Value Chain Explorer.")`
  - `backend/arp/cli/io_tables.py`: `@io_app.command("build-full")` with the same `zip_file` / `--out` / `--label` options as `import-exiobase`, calling `_run_import(build_full, zip_file, out, label)`.

- [ ] **Step 5: Run** the Step 2 command — expected: all PASS. Then `ruff check .`.

- [ ] **Step 6: Commit** `feat(io): arp io build-full writes full-resolution EXIOBASE matrices`

### Task 2: Query model

**Files:**
- Create: `backend/arp/research/value_chain/model.py`, `backend/tests/test_value_chain_model.py`

**Interfaces:**
- Consumes: Task 1's output directory and `write_fixture_f`.
- Produces (all in `arp.research.value_chain.model`):

```python
class NotBuilt(Exception): ...                 # message = the spec's 503 detail
class UnknownNode(KeyError): ...               # str(e) == "unknown node '<id>'"

@dataclass(frozen=True)
class Node:
    node_id: str; region: str; region_label: str; sector: str      # sector = name with trailing " (NN)" removed
    output_meur: float; goods: bool
    ghg_t_per_meur: float | None; energy_tj_per_meur: float | None
    jobs_per_meur: float | None; va_share: float | None

@dataclass(frozen=True)
class Link:
    node: Node; direct: float; total: float

@dataclass(frozen=True)
class TreeItem:
    node: Node; coef: float; chain: float; children: list["TreeItem"]

@dataclass(frozen=True)
class Footprint:
    indicator: str; unit: str; total: float; in_home_region: float | None
    by_region: list[tuple[str, float]]; by_sector: list[tuple[str, float]]

class ValueChain:
    manifest: dict
    @property
    def caveat(self) -> str: ...
    def search(self, q: str, limit: int = 20) -> list[Node]: ...
    def node(self, node_id: str) -> Node: ...                     # raises UnknownNode (also for x = 0)
    def links(self, node_id: str, side: Literal["suppliers", "customers"],
              order: Literal["total", "direct"] = "total", limit: int = 10,
              exclude_own: bool = False) -> list[Link]: ...
    def tree(self, node_id: str, depth: int = 2, width: int = 3,
             cutoff: float = 0.01, goods_only: bool = False) -> TreeItem: ...
    def footprint(self, node_id: str, indicator: Literal["ghg", "energy", "jobs"],
                  amount_meur: float = 1.0, top: int = 6) -> Footprint: ...

def load_value_chain(directory: Path | None) -> ValueChain: ...   # raises NotBuilt; cached per (directory, built_at)
```

Rules (from the spec, not to be re-decided): `links` keeps only nodes with output whose `order` value is > 0, sorts descending with ties by node id, then cuts to `limit`; suppliers use `A[:,k]` / `L[:,k] − δ`, customers `B[k,:] = A[k,:]·x / x[k]` / `G[k,:] − δ`. `tree` and `footprint` follow Appendix B; units `t CO₂e`, `TJ`, `people`; footprint intensities treat null as 0; groups summing to 0 are left out. `search` ranks exact region code/label matches first, then the rest, each by node id; zero-output nodes never appear.

- [ ] **Step 1: Write the failing tests** — one test per fixture row, asserting the spec's exact values rounded to 4 decimals:

```python
def test_suppliers_total(vc):            # AC-3
    assert [(l.node.node_id, round(l.direct, 4), round(l.total, 4)) for l in vc.links("CN.2", "suppliers")] == \
        [("CN.2", 0.2, 0.2696), ("CN.3", 0.1, 0.1572), ("DE.3", 0.1, 0.1448), ("DE.2", 0.0, 0.0336)]
def test_suppliers_exclude_own(vc):      # AC-4  -> ["CN.3","DE.3","DE.2"]
def test_customers_total(vc):            # AC-5  -> DE.3 (0.2, 0.279), CN.3 (0.1, 0.1289), DE.2 (0.1, 0.1266), CN.2 (0, 0.0336)
def test_customers_exclude_own(vc):      # AC-6  -> ["DE.3","CN.3","CN.2"]
def test_intensities(vc):                # AC-7, AC-8, AC-8b, incl. vc.node("DE.3").sector == "Other business activities"
def test_tree_full(vc):                  # AC-9 exact nested ids, coefs, chains; leaves have children == []
def test_tree_filters(vc):               # AC-10 to AC-13b: width=1 -> [CN.3]; cutoff=0.1 -> [CN.3, DE.2]; 0.11 -> []; goods_only -> [DE.2]; cutoff=0 -> [CN.3, DE.2]
def test_footprints(vc):                 # AC-15 to AC-19 values, units and top=1
def test_unknown_and_zero_nodes(vc):     # AC-20, Review Focus 1: "DE.1", "DE.999", "DE.0", "abc" raise UnknownNode with "unknown node '<id>'"
def test_search(vc):                     # AC-21, AC-22, AC-22b: paddy -> [], copper -> [CN.2, DE.2], de -> [DE.2, DE.3]
def test_direct_order(vc):               # AC-22c, AC-22d, AC-22f
def test_caveat(vc):                     # == "EXIOBASE 3.11.2 · 2022 · basic prices, M EUR · now-cast years are estimates · capital goods not included in flows"
def test_not_built(tmp_path):            # load_value_chain(None) and load_value_chain(empty dir) raise NotBuilt with the 503 detail
def test_reload_after_rebuild(tmp_path): # Review Focus 3: build, load, rebuild with label "second", load again -> manifest["edition"] == "second"
```

`vc` is a module-scoped fixture: `load_value_chain(build into tmp_path_factory dir)`.

- [ ] **Step 2: Run** `python3 -m pytest tests/test_value_chain_model.py -q` — expected: FAIL (module missing).
- [ ] **Step 3: Implement `model.py`.** Load `A`, `L`, `G` fully into memory with `np.load` (≈1.5 GB on the real table; the API runs one worker) and `nodes.csv` into `Node`s; `functools.lru_cache(maxsize=1)` on `(str(directory), built_at)`.
- [ ] **Step 4: Run** the Step 2 command — expected: all PASS; `ruff check .`.
- [ ] **Step 5: Commit** `feat(value-chain): query model for nodes, links, trees and footprints`

### Task 3: API router and contract

**Files:**
- Create: `backend/arp/schemas/value_chain.py`, `backend/arp/api/routers/value_chain.py`, `backend/tests/test_api_value_chain.py`
- Modify: `backend/arp/api/main.py` (import and `app.include_router(value_chain.router, dependencies=[Depends(authorize)])`)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts`

**Interfaces:**
- Consumes: Task 2's `load_value_chain`, `NotBuilt`, `UnknownNode` and dataclasses.
- Produces response models (names are the OpenAPI schema names the frontend uses): `ValueChainStatus`, `ValueChainNodeRef`, `ValueChainSearch`, `ValueChainLink`, `ValueChainNode`, `ValueChainTreeNode` (recursive), `ValueChainTree`, `ValueChainFootprint`. Fields exactly as Appendix B; every one carrying top-level `edition` and `caveat` except the nested refs.
- Produces endpoints under `/api/value-chain` exactly as Appendix B, with `Query` bounds giving 422: `q` `min_length=1` after strip (whitespace-only → 422), search `limit` 1–100, node `limit` 1–50, `order` `Literal["total","direct"]`, `depth` 1–4, `width` 1–5, `cutoff` 0–1, `indicator` `Literal["ghg","energy","jobs"]`, `amount_meur` `gt=0`, `top` 1–20.
- The router reads `Settings().value_chain_dir` per request (not `get_settings()`), so tests can switch it; `NotBuilt` → 503, `UnknownNode` → 404 with the spec's details.

- [ ] **Step 1: Write the failing tests** in `tests/test_api_value_chain.py` with `TestClient(app)` and `app.dependency_overrides[current_user] = lambda: PRINCIPAL` (as in `test_api_signals.py`; no Postgres needed), `monkeypatch.setenv("ARP_VALUE_CHAIN_DIR", ...)` per test:
  - AC-2 status body; AC-3 `caveat`; AC-22e `edition` and `caveat` on search, tree and footprint.
  - One request per AC-3..AC-22f checking the JSON shape (ids and rounded values), so the router's serialisation is covered, not only the model.
  - AC-14 and AC-22g: every listed out-of-range request answers 422; plus `q=` and `q=%20` → 422 (Review Focus 4).
  - AC-20 and Review Focus 1: `DE.1`, `DE.999`, `abc` → 404 `{"detail": "unknown node '<id>'"}`.
  - AC-23 (unset) and AC-24 (empty dir) → 503 with the exact detail.
  - AC-25/25b: run with `ARP_ANTHROPIC_API_KEY` unset and with `"sk-invalid"`; parametrize the module over both.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_api_value_chain.py -q` — expected: FAIL (404 for the route).
- [ ] **Step 3: Implement** the schemas and router; register it in `main.py` beside the other routers.
- [ ] **Step 4: Run** the Step 2 command — expected: all PASS; `ruff check .`.
- [ ] **Step 5: Regenerate the contract:** `cd backend && python scripts/export_openapi.py && cd ../frontend && npm run gen:api && npx tsc -b` — expected: exit 0.
- [ ] **Step 6: Commit** (include both generated files) `feat(api): read-only /api/value-chain endpoints`

### Task 4: Frontend formatting, types and client

**Files:**
- Create: `frontend/src/lib/valueChain.ts`, `frontend/tests/valueChain.test.ts`
- Modify: `frontend/src/types.ts`, `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: Task 3's schema names.
- Produces types in `types.ts`, each `Served<S["…"]>` (so `contract.ts` needs no line): `VcStatus`, `VcNodeRef`, `VcSearch`, `VcLink`, `VcNode`, `VcTreeNode`, `VcTree`, `VcFootprint`.
- Produces `api` methods: `valueChainStatus()`, `valueChainSearch(q: string, limit?: number)`, `valueChainNode(id: string, opts: { order: "total" | "direct"; excludeOwn: boolean })`, `valueChainTree(id: string, opts: { depth: number; cutoff: number; goodsOnly: boolean })` (always `width=3`), `valueChainFootprint(id: string, opts: { indicator: "ghg" | "energy" | "jobs"; amount: number })` (always `top=6`).
- Produces in `lib/valueChain.ts`: `cents(fraction: number, digits = 1): string`, `linkText(l: { direct: number; total: number }, mode: "total" | "direct"): string`, `tile(v: number | null): string`, `percent(v: number | null): string`, `footprintTotal(total: number, unit: string): string`, `homeShare(share: number | null, regionLabel: string): string`, `searchable(q: string): boolean`, `nodeHash(id: string, view?: "tree" | "footprint"): string`.

- [ ] **Step 1: Write the failing tests** in `tests/valueChain.test.ts`:

```ts
test("flows in cents", () => {
  assert.equal(cents(0.0738), "7.4¢"); assert.equal(cents(0.0079798, 2), "0.80¢");
  assert.equal(linkText({ direct: 0.0433, total: 0.0738 }, "total"), "7.4¢ (direct 4.3¢)");
  assert.equal(linkText({ direct: 0.0433, total: 0.0738 }, "direct"), "4.3¢");
});
test("tiles, percents, totals", () => {
  assert.equal(tile(14.3462), "14.3"); assert.equal(tile(null), "—");
  assert.equal(percent(0.8452), "85%"); assert.equal(percent(0.845), "85%"); assert.equal(percent(null), "—");
  assert.equal(footprintTotal(973.926, "t CO₂e"), "973.9 t CO₂e");
  assert.equal(homeShare(0.8452, "CN"), "85% in CN"); assert.equal(homeShare(null, "CN"), "");
});
test("search only with a non-space character; hashes encode ids", () => {
  assert.equal(searchable(" "), false); assert.equal(searchable("wa"), true);
  assert.equal(nodeHash("CN.95"), "#/valueChain/CN.95"); assert.equal(nodeHash("CN.95", "tree"), "#/valueChain/CN.95/tree");
});
```

- [ ] **Step 2: Run** `cd frontend && npm test` — expected: FAIL (module missing).
- [ ] **Step 3: Implement** `lib/valueChain.ts`, the types and the client methods (query strings via `URLSearchParams`, as `client.ts` already does).
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): value chain types, client and formatting`

### Task 5: Explorer screen and R&D Lab entry

**Files:**
- Create: `frontend/src/pages/value-chain/ValueChainExplorer.tsx` (shell: picker, view switch, message, caveat), `NodeView.tsx`, `TreeView.tsx`, `FootprintView.tsx`
- Modify: `frontend/src/App.tsx` (lazy import; `TABS` entry `{ id: "valueChain", label: "Value Chain Explorer" }`; the all-screens `ids` list; `{active === "valueChain" && <ValueChainExplorer key={route.params.join("/")} params={route.params} />}`), `frontend/src/lib/processes.ts` (rdLab `screens` gains `["#/valueChain", "Value Chain Explorer"]` after Signals workbench), `frontend/tests/processes.test.ts` (assert that pair, AC-38)

**Interfaces:**
- Consumes: Task 4's `api` methods, types and formatting functions.
- Route: `params[0]` = node id (absent → picker and `Pick a sector and region.`), `params[1]` = `tree` | `footprint` | absent (node page).
- Behaviour exactly as Appendix C and the mockups (`https://claude.ai/artifact/CaSz62Xaz1jfzhBANf7TE5`, app look from `DESIGN.md`): Total/Direct switch refetches with `order`; `Hide this node` refetches with `excludeOwn`; tree is a CSS flex layout, suppliers to the left (no new dependency); every row and box navigates with `nodeHash`; a 404 or 503 `detail` is the page message; the API's `caveat` sits at the foot of every view.

- [ ] **Step 1: Write the failing test** in `tests/processes.test.ts`: the rdLab screens contain `["#/valueChain", "Value Chain Explorer"]`.
- [ ] **Step 2: Run** `npm test` — expected: FAIL on that assertion.
- [ ] **Step 3: Implement** the four components and the wiring.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — expected: PASS.
- [ ] **Step 5: Browser check** with fixture F built (`arp io build-full` on `write_fixture_f`'s zip, `ARP_VALUE_CHAIN_DIR` set, then `bash backend/scripts/e2e_stack.sh up`): open `#/valueChain`, `#/valueChain/DE.3`, `/tree`, `/footprint`, `#/valueChain/abc`; screenshot each with Playwright and run `/impeccable:impeccable audit`; fix what it flags. `e2e_stack.sh down` after.
- [ ] **Step 6: Commit** `feat(frontend): Value Chain Explorer screen in the R&D Lab`

### Task 6: Real-data check and setup note

**Files:**
- Modify: `README.md` (one short subsection under the existing input-output import docs: the two commands below and that the output is not committed)

- [ ] **Step 1: Build the real archive** (`IOT_2022_ixi.zip`, Zenodo record 23039074, md5 `4b717f07bc7a8eeda4317aca49e7c2a9`): `/usr/bin/time -v arp io build-full IOT_2022_ixi.zip --out <d>` (or `ru_maxrss` of the child where `/usr/bin/time` is missing). Expected: line 1 `7987 nodes (163 sectors × 49 regions) -> <d>`, elapsed ≤ 20:00, max RSS ≤ 8,388,608 KB (AC-26, AC-27, AC-27b).
- [ ] **Step 2: Check the real figures through the API** with `ARP_VALUE_CHAIN_DIR=<d>`: the CN electrical machinery node gives supplier `Copper production · CN` total 0.0738/direct 0.0433, `ghg_t_per_meur` 14.35; its tree has copper production coef 0.0433 with copper ore CN 0.1843; its footprint `total` 973.9 (one decimal), `in_home_region` 0.845; `q=in&limit=100` gives 100 `IN` items; 10 seeded random nodes answer node, tree (depth 4, width 5, cutoff 0) and footprint in ≤ 1.0 s each after one warm-up (AC-28 to AC-33, AC-35). Record the numbers in the PR description.
- [ ] **Step 3: Must-not-change:** sha256 of `arp io import-exiobase` output equals the merge-base run's; `pytest tests/test_io_import.py tests/test_leontief.py tests/test_icio_loader.py tests/test_exiobase_loader.py tests/test_factory.py tests/test_exposure.py tests/test_criticality.py` exits 0 (AC-39 to AC-41).
- [ ] **Step 4: Add the README note**, then commit `docs: how to build the Value Chain Explorer data`.
- [ ] **Step 5: Open the PR** against `main` with `Spec: value-chain-explorer`, the `risk:` label per `.claude/skills/steward/SKILL.md`, the real-data numbers from Step 2, and a line that `openwiki/` needs a regeneration pass for the new module.
