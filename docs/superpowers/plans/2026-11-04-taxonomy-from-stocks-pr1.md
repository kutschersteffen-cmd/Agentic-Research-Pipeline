# Taxonomy from Stocks, PR 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp taxonomy infer start` and `infer show` take a set of stocks to profiles, topic clusters and ranked
common themes, and the two old derivation methods are retired.

**Architecture:** A new package `arp/research/stock_inference/` holds one module per step (selection, profile,
clusters, themes) and a `run.py` that drives them and stores one `InferRun` snapshot in `RunStore`, like
`authority_taxonomy/run.py`. The CLI is a Typer sub-app `infer` under `taxonomy_app`. It reuses the holdings
loader (fixed here), `_extract_company`, `ground_citations`, `chunk_document` + `select_relevant_chunks`,
`embed_texts`, and `emerging_themes/clustering.py`'s `_run_once` / `_top_terms`.

**Tech Stack:** Python 3.13, Pydantic, Typer, SQLAlchemy (read-only lookups), numpy, umap-learn + hdbscan +
scikit-learn (`emerging_themes` extra), pytest with the `fake_llm` / `pg` fixtures; React (one list change).

**Spec:** `docs/superpowers/specs/2026-11-04-taxonomy-from-stocks-design.md` (approved 2026-11-04). This plan is
**PR 1 of 3**. PR 2 (`pick`, AC-27-39, AC-54-56, scoring script) and PR 3 (layer 1 index rules, AC-42-46) get
their own plans after PR 1 merges.

**AC rows in this PR:** AC-1-26, AC-23a, AC-47-53. AC-27 (needs `pick`) and AC-28/28a/29 move to PR 2.

## Global Constraints

- Every message string is copied verbatim from the spec (`Run <run_id>`, `No stock could be profiled: <n> failed,
  <m> had no document.`, `No common theme is supported by the profiled stocks.`, `--method <m> is replaced by 'arp
  taxonomy infer start --stocks <file>'.`, `Run <run_id> is at stage '<stage>'; '<command>' needs '<needed>'.`).
- Shares, weights and selection are computed in code; any share the model returns is ignored.
- The inference step never writes `companies` or `company_identifiers`; discovery may.
- Run-JSON numbers rounded to 4 decimals; list order as in the spec's run-JSON section.
- Never delete or weaken a test except the old methods' own tests, which the spec retires; list every test change
  in the PR description.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; frontend `cd frontend && npm run lint &&
  npx tsc -b && npm test`.

## Review Focus

1. A holdings CSV with a BOM or `;` separator (European exports): the header row must still be found; a test with
   a UTF-8 BOM goes in Task 1.
2. Duplicate tickers in one holdings file (share classes): selection must count the security once with summed
   weight, not profile it twice; test in Task 2.
3. A stock whose documents are huge (Siemens Energy, 300+ pages): chunk selection must cap at 8 chunks and the
   run must not hold every document in the run JSON; Task 4 asserts profiles store only `citation`, not text.
4. Fewer than 3 described stocks: clustering must return `[]` without calling UMAP (UMAP fails below 3 points);
   test in Task 5.
5. A run re-shown after the process restarts: `infer show` must read the snapshot only, with no model call; test
   in Task 6.

---

### Task 1: Holdings loader fixes

**Files:**
- Modify: `backend/arp/research/taxonomy_sources/etf_holdings.py:22-70`
- Modify: `backend/arp/schemas/taxonomy_sources.py:35` (`HoldingRow`: add `isin`, `sedol`, `lei`, `cik: str | None = None`)
- Create: `backend/tests/fixtures/holdings/hydr_layout.csv` (the 14 lines in the spec's Acceptance conventions, verbatim)
- Test: `backend/tests/test_holdings_loader.py`

**Interfaces:**
- Produces: `load_holdings_with_weights(path: Path) -> list[HoldingRow]` with weights per the column rule;
  `HoldingRow.isin/sedol/lei/cik`. `load_universe_from_holdings` unchanged in signature.

- [ ] **Step 1: Write the failing tests**

```python
FIX = Path(__file__).parent / "fixtures/holdings/hydr_layout.csv"

def test_ac1_rows_and_order():
    assert [r.ticker for r in load_holdings_with_weights(FIX)] == ["BE", "PLUG", "NEL NO", "NANO SP", "288620 KS"]

def test_ac2_weights_scaled_per_column():
    assert [r.weight for r in load_holdings_with_weights(FIX)] == pytest.approx([0.162, 0.079, 0.0512, 0.0065, 0.0039], abs=1e-9)

def test_ac3_universe_from_holdings(tmp_path):  # CliRunner on `universe from-holdings FIX --out u.json`
    ...  # exit 0, 5 companies in u.json

def test_ac4_ticker_rows_kept(tmp_path):  # "Ticker,Name,Weight\n,CASH,1.0\nABC,Cash Holdings Corp,2.0\n"
    rows = ...; assert [(r.ticker, r.weight) for r in rows] == [("ABC", pytest.approx(0.02))]

def test_ac5_fractions_unchanged(tmp_path):  # "Ticker,Name,Weight\nA,Alpha,0.6\nB,Beta,0.4\n"
    assert [r.weight for r in rows] == [0.6, 0.4]

def test_bom_header_found(tmp_path):  # Review Focus 1: "﻿Ticker,Name,Weight\nA,Alpha,60\n" -> weight 0.6
def test_ids_kept(tmp_path):  # ISIN,SEDOL,LEI,CIK columns land on HoldingRow
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_holdings_loader.py -v` — expect failures on AC-1/2/4 (crash at `etf_holdings.py:25`) and the new fields.

- [ ] **Step 3: Implement in `_parse_holdings_rows`**
  - Read with `encoding="utf-8-sig"`; scan `csv.reader` rows for the first row whose lowered, stripped cells contain any `_NAME_COLUMNS` or `_TICKER_COLUMNS` entry; that is the header.
  - Skip rows with fewer cells than the header.
  - Drop rows with empty ticker whose upper-cased name contains any of `CASH CURRENCY POUND EURO DOLLAR YEN FRANC PAYABLE RECEIVABLE FUTURE SWAP`.
  - Weight: collect raw cells first; the column is percent if the header contains `%`, any cell contains `%`, or any parsed value > 1; then divide every value by 100. Replace `_parse_weight`'s per-cell rule.
  - Keep `isin/sedol/lei/cik` from columns named so (case-insensitive).

- [ ] **Step 4: Run** the new tests plus `tests/test_etf_holdings_universe.py tests/test_overlap.py` — all PASS.

- [ ] **Step 5: Commit** `fix(holdings): find the header row, drop cash rows, scale weights per column`

### Task 2: Run record and selection

**Files:**
- Create: `backend/arp/research/stock_inference/__init__.py`, `schemas.py`, `selection.py`
- Test: `backend/tests/test_stock_inference_selection.py`

**Interfaces:**
- Produces in `schemas.py` (Pydantic, field names exactly the spec's run-JSON keys):
  `Selection`, `Citation` reuse from `arp.schemas.common`, `StockProfile`, `Cluster`, `Theme`, `InferRun`
  (`run_id, stage: Literal["started","profiled","themes_ready","drafted","failed"], name, extractor_model,
  verifier_model, selection, profiles, clusters, themes, outliers, index_rules=None, taxonomy_id=None,
  activities=[], mapping=[], coverage=None`), plus `InferStock(company_id, name, ticker, weight, isin, sedol,
  lei, cik, codes)` as selection input.
- Produces in `selection.py`: `load_stocks(path: Path) -> tuple[list[InferStock], float | None]` (holdings CSV →
  weighted, `company_id` = ticker trimmed or name, duplicates merged with summed weight; `.json` or CSV with a
  `company_id` column → `load_company_universe`, unweighted; second value is `total_weight` or `None`) and
  `select(stocks, total_weight) -> tuple[list[InferStock], Selection]`.

- [ ] **Step 1: Write the failing tests** — AC-6 (`cap_30`, the 30 largest), AC-7 (weights `[20,10,10,8,7,6,5,4,4,3,2,1]+[0.5]*28` → 10 largest, `weight_80`), AC-8 (50 unweighted in two orders → same 30 ids, `sample`), AC-9 (`t30a` in, `t30b` out, `cap_30`), duplicate ticker merged (Review Focus 2), 12 unweighted → all 12 with `cutoff_reason == "all"`.
- [ ] **Step 2: Run** — FAIL (module missing).
- [ ] **Step 3: Implement** per spec Step 1: weighted sort key `(-weight, company_id)`; stop at 30 or when the running sum first reaches `0.8 * total_weight` (inclusive); unweighted `random.Random(0).sample(sorted_by_id, 30)` if > 30.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): run record and stock selection`

### Task 3: Read-only database match and stored data

**Files:**
- Create: `backend/arp/research/stock_inference/stored.py`
- Test: `backend/tests/test_stock_inference_stored.py` (uses the `pg` fixture)

**Interfaces:**
- Consumes: `InferStock` (Task 2).
- Produces: `match_company(session, stock: InferStock) -> UUID | None` — `lookup` (`db/companies.py:50`) for ISIN,
  LEI, CIK in that order, else exactly one `companies.name` equal case-insensitively; and
  `stored_data(session, stock, company_id, segments) -> dict` returning `codes`, `exiobase`, `facts`,
  `segments` for the profile. `load_segments(path) -> dict[str, list[CatalogueDataPoint]]` via
  `catalogue.load_catalogue` + `by_company`.

- [ ] **Step 1: Write the failing tests** — AC-19 (company `Nel ASA` with ISIN `NO0010081235`; stock with that ISIN plus an LEI registered nowhere → returns its id; snapshot of `companies` and `company_identifiers` rows, all columns ordered by id, identical before and after), AC-20 (no match → `None`, rows identical), name match with two same-named companies → `None`, facts dedupe keeps the newest `period_end` per `field_id`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with `transaction(dsn)` (`db/session.py:82`) and only `select` statements; `exiobase` from `nace_sectors(code, rev)` for each NACE code; `facts` from `company_view.facts(session, id, ...)` paged until exhausted.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): read-only company match and stored data`

### Task 4: Profile each stock

**Files:**
- Create: `backend/arp/research/stock_inference/profile.py`
- Test: `backend/tests/test_stock_inference_profile.py`

**Interfaces:**
- Consumes: Tasks 2-3.
- Produces:
  - `DESCRIPTION_SCHEMA: DataPointSchema` — one STRING field, description "The company's main business segments,
    products and services, as the company states them.", seed keywords `["segments", "products", "principal
    activities", "business overview", "services"]`.
  - `async profile_stock(stock, *, documents, registry, llm, verifier_llm, settings, field_limit,
    extract=_extract_company) -> tuple[StockProfile, list[DocumentChunk]]` — returns the profile and its 8 chunks.
  - `async profile_all(stocks, *, registry, llm, verifier_llm, settings, discover=discover_missing,
    extract=_extract_company, session_factory, segments) -> tuple[list[StockProfile], dict[str, list[DocumentChunk]]]`.
  - `async discover_missing(stocks: list[InferStock], settings) -> None` — one `run_discovery` call with the
    stocks as `CompanyRef`s.

- [ ] **Step 1: Write the failing tests** (fake `extract`, fake `discover` recording its argument, fixture documents):
  - AC-10/11: `s3`'s extract raises `ValidationError` → other four have `description`; `s3.error.startswith("ValidationError: ")`, no `description`.
  - AC-12: `s3` has no document, fake discover finds none → `s3.error == "no_document"`; discover called with `["s3"]` only.
  - AC-13: fake discover makes doc `D5` available for `s5` → `s5.citation.doc_id == "D5"`.
  - AC-16: returned quote `We make PEM stacks.` present in `D1` → `citation.quote` and `doc_id == "D1"`.
  - AC-17: quote absent → `error == "ungrounded_quote"`, no `description`, no `citation`.
  - AC-18: no value → `error == "not_found"`.
  - Review Focus 3: a 2,000-chunk document → 8 chunks returned; `StockProfile` JSON holds no document text beyond `citation.quote`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**: per stock `registry.fetch_all(CompanyRef)`; stocks with no documents → one `discover(...)` then fetch again; `extract(company, DESCRIPTION_SCHEMA, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings, documents=docs, field_limit=field_limit)`; then `ground_citations(field.citations, {d.doc_id: d for d in docs}, settings.grounding_fuzzy_threshold)` — keep the first grounded one; chunks via `chunk_document` + `select_relevant_chunks(chunks, DESCRIPTION_SCHEMA seed keywords, max_chunks=8, require_hit=False, fallback_to_all=True)`. Run all stocks with `asyncio.gather`, one shared `asyncio.Semaphore(settings.max_concurrent_llm_calls)` as `field_limit`; wrap each in `try/except Exception as e` → `error = f"{type(e).__name__}: {e}"`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): profile stocks with discovery, separate verifier and per-stock errors`

### Task 5: Topic clusters

**Files:**
- Create: `backend/arp/research/stock_inference/clusters.py`
- Modify: `backend/arp/emerging_themes/clustering.py` — none; import `_run_once` and `_top_terms`.
- Test: `backend/tests/test_stock_inference_clusters.py`

**Interfaces:**
- Produces: `cluster_points(embeddings: np.ndarray) -> np.ndarray` (labels; `[-1]*n` when n < 3, else
  `_run_once(embeddings, 3, seed=0)`) and `build_clusters(chunks_by_stock: dict[str, list[DocumentChunk]],
  weights: dict[str, float | None], benchmark_chunks: list[DocumentChunk], *, cluster=cluster_points,
  embed=embed_texts) -> list[Cluster]`.

- [ ] **Step 1: Write the failing tests** — AC-25 (3 stocks × 8 chunks, fixture embeddings A/B + N(0, 0.01) with `np.random.default_rng(0)`, injected `embed`; real `cluster_points` → 2 clusters, 10 terms each, members `["s1","s2"]` and `["s3"]`, sorted by `cluster_id`), AC-26 (fake `cluster` returns all -1 → `[]`), Review Focus 4 (2 points → `[]`, UMAP not imported: patch `_run_once` to raise), benchmark text changes term weights but never appears in `members`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**: embed fund chunks and benchmark chunks together, cluster all points, keep clusters with at least one fund point; terms = `_top_terms(cluster_docs + [benchmark_doc], top_n=10)[:-1]` when a benchmark exists, else `_top_terms(cluster_docs, top_n=10)`; `weight_share` = member weight / described weight, `None` unweighted.
- [ ] **Step 4: Run** — PASS (needs `pip install -e ".[emerging_themes]"`).
- [ ] **Step 5: Commit** `feat(stock-inference): BERTopic-style clusters of business text`

### Task 6: Common themes, `start` and `show`

**Files:**
- Create: `backend/arp/research/stock_inference/themes.py`, `run.py`
- Create: `backend/arp/cli/taxonomy_infer.py`; Modify: `backend/arp/cli/taxonomy.py:30` (`taxonomy_app.add_typer(infer_app, name="infer")`)
- Test: `backend/tests/test_stock_inference_themes.py`, `backend/tests/test_cli_taxonomy_infer.py`

**Interfaces:**
- Consumes: Tasks 2-5.
- Produces:
  - `async propose_themes(profiles, clusters, stated_theme: str | None, methodology_docs, llm) -> tuple[list[Theme], list[str]]` (themes, outliers), with the filtering, share computation and ranking of spec Step 4.
  - `async start(stocks_path, *, methodology, segments_path, benchmark_path, name, run_store, settings, llm,
    verifier_llm, registry, discover, extract) -> InferRun`; `load_run(run_id, run_store) -> InferRun`;
    `class WrongStage(Exception)` carrying `stage`, used by PR 2's `pick`. Snapshot key `"infer"` via
    `run_store.save_snapshot` / `read_snapshot`.
  - CLI: `infer start --stocks --methodology(repeatable) --segments --benchmark --name`, `infer show RUN_ID [--json]`.

- [ ] **Step 1: Write the failing tests**:
  - AC-21: reply supports `x1`, `p1` (0.10), `p2` (0.05) of 0.50 described, claims `weight_share` 0.9 → `supporting == ["p1","p2"]`, `weight_share == 0.3`, `count_share == 0.4`.
  - AC-22: `Beta`, `Alpha` tied at 0.30 → `["Alpha","Beta"]`.
  - AC-23 / AC-23a: `T2` (only `x1`) dropped; only theme dropped → `start` exits 1, stderr `No common theme is supported by the profiled stocks.`, stage `failed`.
  - AC-24: methodology quote absent → `stated_in_methodology is False`, `methodology_quote is None`.
  - AC-14: two raise, one no document → exit 1, stdout line 1 `Run <id>`, stderr `No stock could be profiled: 2 failed, 1 had no document.`, `show --json` stage `failed`.
  - AC-15: `ARP_LLM_MODEL=model-a`, `ARP_LLM_VERIFIER_MODEL=model-b` → `extractor_model`/`verifier_model`.
  - `show --json` prints exactly the spec's key set (assert `set(json.loads(out)) == {...}`).
  - Review Focus 5: `show` after a fresh `RunStore` instance makes no model call (fake client raises on any call).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `start`: create the run via `JobManager(run_store).create_run("stock_inference", params, 0)`, echo `Run <run_id>` first, then select → `profiled` → clusters → themes → `themes_ready`; failures set `failed` and exit 1 with the spec's messages. `--name` defaults to the stocks file's stem. Model ids come from `settings.llm_model` / `settings.llm_verifier_model`.
- [ ] **Step 4: Run** both test files — PASS.
- [ ] **Step 5: Commit** `feat(stock-inference): ranked common themes; taxonomy infer start/show`

### Task 7: Retire `etf_index_holdings` and `empirical`

**Files:**
- Modify: `backend/arp/cli/taxonomy.py:113-142` (both branches → refusal), `backend/arp/api/routers/taxonomies.py:131-180` (refusal before other validation)
- Delete: `build_theme_from_holdings`, `load_holdings_corpus` (`etf_holdings.py`), `backend/arp/research/taxonomy_sources/empirical.py`, `backend/tests/test_etf_holdings_derivation.py`, `backend/tests/test_empirical_derivation.py`
- Modify: `backend/tests/test_walkthrough_pipeline.py:24,231` (call `profile_stock`; assertion lines unchanged)
- Modify: `frontend/src/pages/TaxonomyLibrary.tsx:34-41` (drop both from `CREATABLE_METHODS`, remove their option panels; keep `METHOD_LABELS`)
- Test: `backend/tests/test_taxonomy_retired_methods.py`

**Interfaces:**
- Produces: `RETIRED = {DerivationMethod.EMPIRICAL, DerivationMethod.ETF_INDEX_HOLDINGS}` and
  `retired_message(m) -> str` in `arp/research/stock_inference/__init__.py`, used by CLI and API.

- [ ] **Step 1: Write the failing tests** — AC-47 (CLI, no other options, both methods → exit 1, exact stderr), AC-48 (`POST /api/taxonomies` body `{"name":"X","derivation_method":"empirical"}` and `etf_index_holdings` → 422, `detail` equal), AC-50 (before any change in this task, run `arp taxonomy show` on `main` for one saved `empirical` and one `etf_index_holdings` taxonomy and save the outputs as `tests/fixtures/taxonomy/show_main_{empirical,etf_index_holdings}.json` together with the stored taxonomy files; the test loads the same stored taxonomies and asserts `show`'s JSON equals each fixture; PR 1 adds no new taxonomy keys, so no key removal is needed yet).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the refusal; remove the dead functions and their tests; point the walkthrough test at `profile_stock`; remove the imports the deletions leave unused.
- [ ] **Step 4: Run** `tests/test_taxonomy_retired_methods.py tests/test_walkthrough_pipeline.py` and AC-51/52's files: `tests/test_authority_taxonomy_*.py tests/test_golden_authority_taxonomy.py tests/test_etf_holdings_universe.py tests/test_overlap.py tests/test_activity_generator.py tests/test_authority_derivation.py tests/test_news_mining_derivation.py tests/test_taxonomy_store.py tests/test_taxonomy_compare_merge.py tests/test_cli_taxonomy_author.py` — all PASS; `git diff origin/main -- <AC-51 files>` empty.
- [ ] **Step 5: Frontend:** `cd frontend && npm run lint && npx tsc -b && npm test`; screenshot the taxonomy library with Playwright and run `/impeccable:impeccable audit` (CLAUDE.md frontend rule). AC-49/49a/49b are `evaluator` rows, checked after CI.
- [ ] **Step 6: Commit** `feat(taxonomy): retire etf_index_holdings and empirical in favour of taxonomy infer`

### Task 8: Open PR 1

- [ ] **Step 1:** `cd backend && ruff check . && python3 -m pytest` (full suite) — 0 failures. If request/response models changed, `python scripts/export_openapi.py` then `cd frontend && npm run gen:api`.
- [ ] **Step 2:** Push the branch and open a PR against `main` with `Spec: taxonomy-from-stocks`, the AC rows covered (AC-1-26, AC-23a, AC-47-53), rows owed to PR 2/3, every test change with its reason, and a `risk:` label per the steward skill.
- [ ] **Step 3:** Say whether `openwiki/` needs an update (it does: new `stock_inference` package; the weekly refresh regenerates it).
