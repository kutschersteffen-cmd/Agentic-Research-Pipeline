# Themes exposure layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a theme run, show Layer 1 (direct), Layer 2 (value chain via Neo4j supply edges), Layer 3 (`not available`) and the score `S`, through `arp theme edges import`, `arp theme layers`, `GET /api/themes/runs/{run_id}/layers` and a Layers table on `#/theme`.

**Architecture:** A pure function computes the layers from the run's companies, results, the edge versions known at `as_of` and five settings, so nearly every acceptance number is unit-tested without a database. A small `arp/company_graph.py` module owns Neo4j: config check, constraint, CSV import, reading edges at `as_of`. The CLI and the endpoint run the same checks in the same order, then call both.

**Tech Stack:** FastAPI, Typer, pydantic-settings, `neo4j` Python driver 5.28 (server: Neo4j 5.26 Community), React + Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-10-18-themes-exposure-layers-design.md`

## Global Constraints

- Settings: `ARP_THEME_LAYER_W1=0.45`, `ARP_THEME_LAYER_W2=0.35`, `ARP_THEME_LAYER_W3=0.20`, `ARP_THEME_LAYER_DECAY=0.85`, `ARP_THEME_LAYER_MAX_HOPS=2`; weights ≥ 0, 0 < decay ≤ 1, max hops ∈ {1, 2}. Pure-play threshold is the existing `revenue_exposure_pure_play_threshold`.
- Bad layer setting: API 503 with `detail` naming the setting; CLI exit 1 with a message naming it. Settings validation must never stop the app from starting (plain fields in `Settings`, checked only by the layers code).
- `ARP_NEO4J_URI` unset or empty → `company graph not configured: set ARP_NEO4J_URI` (503 / exit 1). Unreachable → `company graph unavailable: <error>`.
- Endpoint check order: 401 → 422 `as_of must be a date in YYYY-MM-DD form` → 404 `unknown theme run '<id>'` (missing or not `run_type == "theme"`) → 503 settings → 503 graph.
- API numbers rounded with `round(x, 4)`; CLI prints `f"{x:.4f}"`, missing as `-`; both from unrounded values.
- Edge CSV columns: `supplier_key, supplier_name, customer_key, customer_name, revenue_share, source_doc, source_passage, effective_date, published_at`. Import is all-or-nothing: any bad row → exit 1, nothing written.
- Nothing in existing theme results, CSV/XLSX export, the existing `#/theme` results table, `CompanyMatch` or existing tests changes.
- New CLI commands build `Settings()` fresh (the spec says settings are read when each command starts); the API uses `settings_dep` like the rest of the app.

## Review Focus

1. A CSV with a UTF-8 BOM (Excel export) → the header still parses (`encoding="utf-8-sig"`). Test in Task 2.
2. Two rows in the same file with the same four version keys but different values → refused like a stored conflict, nothing written. Test in Task 2.
3. A run whose companies were never saved (`load_companies` returns `None`, older runs) → 200 with an empty `rows`, not a 500. Test in Task 4.
4. A non-numeric `revenue_share` or a date like `2024/06/30` in the CSV → `row n: …` message, exit 1, no traceback. Test in Task 2.
5. `ARP_NEO4J_URI=` (set but empty, how `e2e_stack.sh` turns it off) → treated as unset. Test in Task 2.

---

### Task 1: Layer computation (pure)

**Files:**
- Create: `backend/arp/research/exposure_layers.py`
- Modify: `backend/arp/config.py` (five settings next to `revenue_exposure_pure_play_threshold`)
- Test: `backend/tests/test_exposure_layers.py`

**Interfaces:**
- Produces:
  - `class LayerSettingsError(ValueError)` — message names the setting, e.g. `ARP_THEME_LAYER_DECAY must be greater than 0 and at most 1`.
  - `@dataclass(frozen=True) class LayerParams: w1: float; w2: float; w3: float; decay: float; max_hops: int; pure_play_threshold: float`
  - `layer_params(settings: Settings) -> LayerParams` (raises `LayerSettingsError`)
  - `@dataclass(frozen=True) class Edge: supplier_key: str; customer_key: str; revenue_share: float` (already the version chosen at `as_of`)
  - `@dataclass class LayerRow: issuer_key: str; name: str; in_run: bool; l1: float | None; l2: float | None; l3: None; score: float | None; pure_play: bool; status: str; rank: int | None; l2_via: list[str] | None` (unrounded)
  - `run_company_l1(companies: list[CompanyRef], result_rows: list[dict]) -> list[tuple[str, str, float | None]]` — `(issuer_key, name, l1)` per run company, first occurrence of a key wins. L1 = max `revenue_exposure.revenue.value_pct` over matches with `verdict == "include"` and `source in {"catalogue", "extracted"}` and a non-null value. Matches join companies by `match["company_id"] == ref.company_id`.
  - `compute_layers(run_companies: list[tuple[str, str, float | None]], edges: list[Edge], node_names: dict[str, str], params: LayerParams) -> list[LayerRow]` — sorted and ranked.

- [ ] **Step 1: Write the failing tests** — one test per spec row computable without Neo4j, each building the inputs directly (`Edge(...)` lists, `LayerParams(0.45, 0.35, 0.2, 0.85, 2, 0.5)` as `DEFAULT`):
  - `test_fixture_f_order_and_values` (AC-8–13): order `[A, B, S1, S2, C]`; A `l1=0.6, score≈0.27, pure_play, rank 1, l2_via None`; B `score≈0.1125, rank 2`; S1 `l2≈0.204, score≈0.0714, via [S1, A]`; S2 `l2≈0.0867, via [S2, S1, A]`; C `status "insufficient data", rank None, score None`. Compare with `pytest.approx` on unrounded values, and `round(x, 4)` equals the spec value.
  - `test_three_hop_path_ignored` (AC-16), `test_max_hops_one` (AC-35), `test_two_anchors_sum` (AC-17, `0.2465`), `test_decay_per_hop` (AC-18, `0.85`/`0.7225`), `test_l2_capped_at_one` (AC-19), `test_no_loop_back_to_self` (AC-36: A `0.085`, B `0.204`), `test_customer_without_l1_gives_no_l2` (AC-40), `test_via_tie_takes_sorted_path` (AC-49: `0.34`, via `[S1, P]`), `test_equal_scores_rank_by_key` (AC-42), `test_weights_from_params` (AC-21: `0.3`), `test_pure_play_threshold` (AC-43).
  - `run_company_l1` tests: `test_l1_max_of_include_matches` (AC-41: `0.5`, score `0.225`), `test_l1_ignores_exclude_and_qualitative` (AC-20 and C).
  - `layer_params` tests: decay `0` and `1.5`, max hops `3`, W1 `-0.1` each raise with the setting name in the message (AC-46/47/48/54); defaults pass.

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_exposure_layers.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Add settings** `theme_layer_w1: float = 0.45`, `theme_layer_w2: float = 0.35`, `theme_layer_w3: float = 0.20`, `theme_layer_decay: float = 0.85`, `theme_layer_max_hops: int = 2` (plain fields, no `ge`/`le`).

- [ ] **Step 4: Implement** `exposure_layers.py`. L2 by depth-first search from every node that has outgoing edges:

```python
def _walk(node, path, product, out, anchors, params):
    for e in out.get(node, ()):
        if e.customer_key in path:          # simple paths only
            continue
        p, nxt = product * e.revenue_share, path + [e.customer_key]
        hops = len(nxt) - 1
        if anchors.get(e.customer_key) is not None:
            yield nxt, p * anchors[e.customer_key] * params.decay ** hops
        if hops < params.max_hops:
            yield from _walk(e.customer_key, nxt, p, out, anchors, params)
```

  L2 = `min(1.0, sum(contribs))`, via = best by `(-contribution, path)`. Listed: every run company, plus nodes outside the run with L2 not None. Score = `w1·(l1 or 0) + w2·(l2 or 0) + w3·0` when l1 or l2 is not None, else None. `pure_play = l1 is not None and l1 >= threshold`. Sort scored rows by `(-score, key)`, rank 1…n, then insufficient rows by key. Names: run name, else `node_names.get(key, key)`.

- [ ] **Step 5: Run** the tests — Expected: PASS. `ruff check arp/research/exposure_layers.py tests/test_exposure_layers.py` clean.

- [ ] **Step 6: Commit** `feat(themes): compute exposure layers`

### Task 2: Company graph (Neo4j) and edge import

**Files:**
- Create: `backend/arp/company_graph.py`
- Modify: `backend/pyproject.toml` (`"neo4j>=5.28,<6"` in `dependencies`), `backend/arp/config.py` (`neo4j_uri: str | None = None`, `neo4j_user: str = "neo4j"`, `neo4j_password: str | None = None`), `backend/tests/conftest.py` (fixture), `.claude/hooks/ensure-deps.sh` (`neo4j` part), `.claude/hooks/check.sh`
- Test: `backend/tests/test_company_graph.py`

**Interfaces:**
- Consumes: `Edge` from Task 1.
- Produces:
  - `class CompanyGraphError(RuntimeError)`
  - `NOT_CONFIGURED = "company graph not configured: set ARP_NEO4J_URI"`
  - `open_graph(settings: Settings) -> neo4j.Driver` — raises `CompanyGraphError(NOT_CONFIGURED)` when `not settings.neo4j_uri`; else builds the driver, `verify_connectivity()`, creates `CREATE CONSTRAINT company_issuer_key IF NOT EXISTS FOR (c:Company) REQUIRE c.issuer_key IS UNIQUE`; any `neo4j.exceptions.Neo4jError`/`DriverError` → `CompanyGraphError(f"company graph unavailable: {exc}")`.
  - `parse_edge_csv(path: Path) -> list[EdgeRow]` — raises `ValueError` with the exact spec messages: `missing column: <name>` (first missing, in column order), `row n: source_passage is required`, `row n: revenue_share must be greater than 0 and at most 1`, `row n: a company cannot supply itself`, plus `row n: <column> is required` for empty keys, `row n: revenue_share must be a number`, `row n: <column> must be a date in YYYY-MM-DD form`. Reads with `encoding="utf-8-sig"`. Two rows in one file with the same version keys and different values → the conflict message on the later row.
  - `EdgeRow` dataclass: the nine columns, dates as `datetime.date`, share as `float`.
  - `import_edges(driver, rows: list[EdgeRow]) -> int` (new count) — one write transaction: read existing versions for the rows' keys; any differing → `ValueError("row n: an edge with this supplier, customer, effective_date and published_at is already stored with different values")`, nothing written; else `MERGE` both nodes and `SET name`, `CREATE` the missing relationships.
  - `edges_at(driver, as_of: date) -> tuple[list[Edge], dict[str, str]]` — relationships with `effective_date <= $as_of AND published_at <= $as_of`, reduced in Python to one per pair by max `(effective_date, published_at)`; returns the names of every node seen. Comment: `shortcut: reads every known edge per request, fine to ~100k edges; move the version pick into Cypher when the graph grows.`
- Test fixture `neo4j_graph` in `conftest.py`: skip unless `ARP_TEST_NEO4J_URI`; sets `ARP_NEO4J_URI/USER/PASSWORD` from `ARP_TEST_NEO4J_*`, clears `get_settings`, runs `MATCH (n) DETACH DELETE n`, yields the driver.

- [ ] **Step 1: Write the failing tests.** Without Neo4j: every `parse_edge_csv` message above (AC-3/4/5/6/34 and Review Focus 1, 2, 4); `open_graph` with `neo4j_uri=None` and `""` raises `NOT_CONFIGURED` (Review Focus 5); a closed port gives `company graph unavailable:`. With `neo4j_graph`: import fixture F → 2 new, again → 0 new (AC-1/2); graph query gives exactly `{(S1, A, 0.4), (S2, S1, 0.5)}` (AC-57); share changed only → conflict, nothing written (AC-50); names-only change counts as identical and updates the node name; `edges_at` picks latest effective then latest published (AC-37, 38, 39, 52) and includes `published_at == as_of` (AC-53).
- [ ] **Step 2: Add the `neo4j` part to `ensure-deps.sh`:** return 0 if port 7687 answers; else download `neo4j-community-5.26.0-unix.tar.gz` from `dist.neo4j.org` into `${XDG_CACHE_HOME:-$HOME/.cache}/neo4j` (needs Java 17+), `neo4j-admin dbms set-initial-password arp_neo4j_test`, `neo4j start`, wait up to 60 s for 7687. Add it to `all` and to the usage line. In `check.sh`, export `ARP_TEST_NEO4J_URI=${ARP_TEST_NEO4J_URI-bolt://localhost:7687}` (+ user `neo4j`, password `arp_neo4j_test`) and run `ensure neo4j` only when a selected test file mentions `neo4j_graph`.
- [ ] **Step 3: Run** `bash .claude/hooks/ensure-deps.sh neo4j && cd backend && pip install -e . -q && python3 -m pytest tests/test_company_graph.py -q` — Expected: FAIL (module missing).
- [ ] **Step 4: Implement `company_graph.py`** per the interface.
- [ ] **Step 5: Run** the tests — Expected: PASS, with and without `ARP_TEST_NEO4J_URI` (graph tests skip without it).
- [ ] **Step 6: Commit** `feat(themes): company graph in Neo4j with supply-edge import`

### Task 3: CLI commands

**Files:**
- Modify: `backend/arp/cli/theme.py`
- Test: `backend/tests/test_cli_theme_layers.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 functions; `RunStore(require_dsn(settings), settings.runs_dir)`.
- Produces:
  - `arp theme edges import --csv FILE` (a Typer sub-app `edges` on `theme_app`): `Settings()`; not configured → stderr message, exit 1 *before* reading the file; parse; `open_graph`; `import_edges`; stdout `{len(rows)} rows, {new} new`. Every `ValueError`/`CompanyGraphError` → stderr, exit 1.
  - `arp theme layers --run R [--as-of YYYY-MM-DD]` (default today UTC): checks in the endpoint's order (run → settings → graph), then prints tab-separated `rank, issuer_key, name, l1, l2, l3, score, status`, numbers as `f"{x:.4f}"`, missing as `-`.
  - `load_run_layers(settings, run_store, run_id, as_of) -> tuple[LayerParams, list[LayerRow]]` in `exposure_layers.py`, shared with Task 4: raises `LookupError(f"unknown theme run '{run_id}'")`, then `LayerSettingsError`, then `CompanyGraphError`.

- [ ] **Step 1: Write failing tests** with `CliRunner` and `pg` (+ `neo4j_graph` where needed): AC-1, AC-2, AC-27 exact lines, AC-46/47/48 (stderr names the setting), AC-56 (`ARP_NEO4J_URI` unset, CSV path that does not exist → still the not-configured message, which proves the check comes first), AC-59.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_cli_theme_layers.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** both commands and `load_run_layers`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(themes): arp theme edges import and arp theme layers`

### Task 4: Layers endpoint

**Files:**
- Modify: `backend/arp/api/routers/themes.py`, `frontend/src/api/openapi.json`, `frontend/src/api/schema.gen.ts` (generated)
- Test: `backend/tests/test_theme_layers_api.py`

**Interfaces:**
- Consumes: `load_run_layers` from Task 3.
- Produces: `GET /api/themes/runs/{run_id}/layers?as_of=` with `response_model=ThemeLayers`:
  - `class LayerWeights(BaseModel): w1: float; w2: float; w3: float`
  - `class ThemeLayerRow(BaseModel)`: the eleven spec keys, `l3: None`
  - `class ThemeLayers(BaseModel): run_id: str; as_of: date; weights: LayerWeights; decay: float; max_hops: int; pure_play_threshold: float; rows: list[ThemeLayerRow]`
  - `as_of: str | None = None` checked against `^\d{4}-\d{2}-\d{2}$` then `date.fromisoformat` → else `HTTPException(422, "as_of must be a date in YYYY-MM-DD form")`; `None` → `datetime.now(UTC).date()`. `LookupError` → 404, `LayerSettingsError`/`CompanyGraphError` → 503 with `str(exc)`. Numbers are rounded here with `round(x, 4)`.

- [ ] **Step 1: Write failing tests** with `TestClient(app)` signed in as a viewer (the existing auth override fixture): AC-7, AC-14, AC-15, AC-22, AC-23, AC-24, AC-25, AC-26 (no override, `ARP_AUTH_MODE=local`), AC-54, AC-55, AC-58 (`/api/runs/R/results` unchanged with the URI unset) and Review Focus 3. Graph-backed cases use `neo4j_graph`.
- [ ] **Step 2: Run** — Expected: FAIL (404 route).
- [ ] **Step 3: Implement** the route and models.
- [ ] **Step 4: Run** the tests, then `python scripts/export_openapi.py && cd ../frontend && npm run gen:api` — Expected: PASS, two generated files changed.
- [ ] **Step 5: Commit** `feat(themes): GET /api/themes/runs/{id}/layers`

### Task 5: Layers table on `#/theme`

**Files:**
- Create: `frontend/src/lib/themeLayers.ts`, `frontend/src/components/ThemeLayersTable.tsx`, `frontend/tests/themeLayers.test.ts`
- Modify: `frontend/src/api/client.ts` (`getThemeLayers`), `frontend/src/types.ts` (`ThemeLayers`, `ThemeLayerRow`), `frontend/src/api/contract.ts` (one `Satisfies` line), `frontend/src/pages/ThemeBuilder.tsx` (render the table under the results when `runId` is set; new prop `initialRunId`), `frontend/src/App.tsx` (pass `route.params[0]`, so `#/theme/<run id>` selects a run; without it the evaluator has no way to select a stored run)

**Interfaces:**
- Consumes: Task 4's response shape.
- Produces:
  - `todayUtc(): string` → `new Date().toISOString().slice(0, 10)`
  - `layersSummary(r: ThemeLayers): string` → `Weights 0.45 / 0.35 / 0.20 · decay 0.85 · as of 2024-06-30` (`toFixed(2)` for weights and decay)
  - `viaLabel(row: ThemeLayerRow, rows: ThemeLayerRow[]): string` → names joined with ` → `, falling back to the key; `""` when `l2_via` is null
  - `errorDetail(e: unknown): string` → the message without its `NNN: ` prefix
  - `api.getThemeLayers(runId: string, asOf: string)`

- [ ] **Step 1: Write failing vitest tests** for the four helpers (summary string from AC-31, `S1 → A`, the 503 prefix stripped).
- [ ] **Step 2: Run** `cd frontend && npm test -- themeLayers` — Expected: FAIL.
- [ ] **Step 3: Implement** the helpers and `ThemeLayersTable({ runId })`: an `As of` date input (default `todayUtc()`), a fetch on every `runId`/`asOf` change, the summary line, then a `data-table` with columns Rank, Company, Layer 1, Layer 2, Layer 3, Score, Via. Numbers `toFixed(4)`, Layer 3 `not available`, Score `insufficient data` and an empty Rank for insufficient rows. On error show `errorDetail(e)` in place of the table. The existing results table stays as it is.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test` — Expected: clean, all pass.
- [ ] **Step 5: Commit** `feat(themes): Layers table on the Thematic Universe page`

### Task 6: Neo4j wherever Postgres is started

**Files:**
- Modify: `.github/workflows/ci.yml` (backend job: `neo4j` service + `ARP_TEST_NEO4J_*`; E2E job: service + `ARP_NEO4J_*`), `.github/workflows/holdout.yml` (service + `ARP_NEO4J_URI/USER/PASSWORD` at job level, as the spec's setup notes promise the test-writer), `backend/scripts/e2e_stack.sh` (`export ARP_NEO4J_URI=${ARP_NEO4J_URI-bolt://localhost:7687}` and user/password defaults; header comment: run with `ARP_NEO4J_URI=` to check the no-graph page), `docker-compose.yml` (optional `neo4j:5.26-community` service on 127.0.0.1:7474/7687, `NEO4J_AUTH`, a volume; backend env `ARP_NEO4J_URI: bolt://neo4j:7687` with no `depends_on`), `backend/.env.example`, `README.md` (one line in the setup block: `docker compose up -d neo4j  # optional: the company graph for theme exposure layers`)
- Service, everywhere: `image: neo4j:5.26-community`, `NEO4J_AUTH: neo4j/arp_neo4j_test`, port 7687, health check `wget -qO- http://localhost:7474 || exit 1`.

- [ ] **Step 1: Edit** the files above.
- [ ] **Step 2: Verify locally:** `bash backend/scripts/e2e_stack.sh up`, import fixture F with the CLI, open `#/theme/<R>` in Playwright, screenshot; then `ARP_NEO4J_URI= bash backend/scripts/e2e_stack.sh up` and screenshot the not-configured text. Run `/impeccable:impeccable audit` on the screenshots.
- [ ] **Step 3: Commit** `ci: run Neo4j next to Postgres`

### Task 7: Finish

- [ ] Full backend suite (`python3 -m pytest -q` with Postgres and Neo4j) — AC-33: no existing theme or revenue-exposure test file edited.
- [ ] `/ponytail:ponytail-review` and `/code-review`; fix what they find.
- [ ] Merge `origin/main`, push, open the PR against `main` with `Spec: themes-exposure-layers-design` on its own line, label `risk:high` (workflows and `.claude/hooks`), the list of test changes (new files only) and the `#/theme/<run id>` deep link named as an addition for the evaluator.
- [ ] Send `themes-exposure-layers-design implement: <PR url>` to session `session_01SVAm62hkDQ8EyfZA8SY8ZX`.
