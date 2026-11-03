# Theme Funnel (A2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inside the per-pair LangGraph, after the revenue paths and after `gather_evidence`, score each company × activity pair with embeddings → cross-encoder → NLI and skip the Advocate / Opposing / Adjudicator debate for pairs the funnel screens out, keeping every score and the best passage.

**Architecture:** A pure scoring module (`arp/research/funnel.py`) turns a pair's documents and its `ActivityDefinition` into a `FunnelRecord` via `arp/models/` (`embed`, `rerank`, `classify`). A new `funnel` node in `match_company_activity`'s graph (`arp/research/match_graph.py`) sits between `gather_evidence` and `run_advocate`; screened pairs go to a new `finalize_screened_out` node. Contrast statements live on the activities of a taxonomy version, so both CLI commands take `--taxonomy <id> [--taxonomy-version N]`, never a loose theme JSON.

**Tech Stack:** Python 3.11, pydantic v2, LangGraph, numpy, Typer, pytest; the shared model layer `arp/models/` (on `main`).

**Status:** approved by the owner, 2026-11-03. Answers: Q1 = A (AC-23 on `not` cases only), Q2 = companies without codes are kept, Q3 = ISIC division width.

**Spec:** `docs/superpowers/specs/2026-11-01-theme-funnel-design.md` (approved 2026-11-01). This plan changes two things in it at the owner's request; see **Spec amendments**.

## Changes from the first draft (owner corrections)

1. **Hook position.** The funnel runs inside the graph, after `resolve_revenue` / `resolve_rd` / `finalize_from_revenue` routing and after `gather_evidence`, not in `_match_company` before the whole graph. A pair resolved from the revenue catalogue or an extracted figure never reaches the funnel; a pair with no keyword evidence still ends in `finalize_no_evidence` unchanged. The funnel only ever replaces a debate.
2. **Contrast statements come from a taxonomy version.** `contrast_statements` is a field on `ActivityDefinition`, saved in a `TaxonomyStore` version (`taxonomies/<id>/v<N>.json`). `arp theme funnel` and `arp theme funnel-compare` take `--taxonomy`/`--taxonomy-version` (same options as `arp theme run`) and refuse `--theme` with the existing `THEME_NOT_ALLOWED` message. The golden set ships its taxonomy as a store directory, selected with `--taxonomies-dir`.
3. **Sector-code narrowing at universe building (owner addition, then owner correction).** Not in the theme run or the funnel. A new command `arp universe narrow --universe <in> --taxonomy <id> [--taxonomy-version N] --out <universe.json>` (in `backend/arp/cli/universe.py`, next to `from-holdings`) writes a universe already reduced to companies whose known codes (`CompanyRef.isic_code`, `CompanyRef.nace_code`) match any activity's codes (`core_isic_codes`, plus `sector_codes` entries with system ISIC or NACE once PR #325 lands). Every dropped company goes to `<out stem>.dropped.json` with its codes and the reason; `--keep <company_id>` (repeatable) overrides a drop. Identity resolution, discovery, `documents warm` and the theme run then only see the narrowed list; the theme run and the funnel are unchanged by this. Task 8.
4. **Precomputed chunk embeddings (owner addition).** Found (file:line below): the store exists, but nothing fills it ahead of a run. The funnel reads and writes the same store, and `arp documents warm --embed` fills it for every chunk. Task 7.

### What exists for chunk embeddings

- `backend/arp/storage/postgres_models.py:145-158`: table `chunk_embeddings` (pgvector, key `chunk_id` + `embed_model`, `EMBED_DIM` 384).
- `backend/arp/storage/postgres_embeddings.py:12-43`: `PgVectorEmbeddingsStore.lookup_embeddings` / `store_embeddings`; exposed as `DocumentContentStore.lookup_embeddings` / `store_embeddings` at `backend/arp/storage/document_store.py:141-148`.
- Only writer: `backend/arp/retrieval/select_evidence.py:65-87` (`_vector_ranking`), lazily, during hybrid retrieval, and only for the keyword-candidate chunks of the field/activity being matched. Model `EMBED_MODEL_NAME` (`backend/arp/retrieval/embeddings.py:17`), the same `paraphrase-multilingual-MiniLM-L12-v2` as `arp/models` `embed` (`backend/arp/models/registry.json:5`), so the vectors are shareable.
- `arp documents warm` (`backend/arp/cli/documents.py:16-52`) only fetches and parses (`registry.fetch_all`); it computes no embeddings.
- Chunk ids are deterministic (`chk_<doc_id>_<start>_<end>`, `backend/arp/ingestion/parsing.py:174`), so a vector stored by warm is found again by the run.
- Gap: the funnel embeds every chunk of every document (no keyword filter), which is the expensive part. Without warm, the first run pays it; with warm, the run only embeds the activity's `in_scope_description`.

## Spec amendments (applied in Task 3, docs only)

- *Integration*: replace "In `_match_company`, after documents are fetched and before `match_company_activity`" with "In `match_company_activity`'s graph, as a node between `gather_evidence` and `run_advocate`; revenue-resolved and no-evidence pairs never reach it".
- *CLI*: replace `--theme <theme.json>` with `--taxonomy <id> [--taxonomy-version N] [--taxonomies-dir <dir>]` in both commands.
- *Acceptance*: AC-23 per the owner's answer to Q1 below.
- *Design*: new section "Narrowing the universe" (`arp universe narrow`, change 3) and a *Precompute* paragraph for `documents warm --embed` (change 4). The Non-goal "new document sources" stands; neither adds one.
- *Acceptance*, new rows (unit unless noted):
  - AC-26: taxonomy with one activity, codes `["2790"]`; universe with company X `isic_code "2610"` → X is not in `--out`; `<out stem>.dropped.json` has X with reason `no sector match (company 26, taxonomy 27)`.
  - AC-27: company with no known codes → kept in `--out` (or dropped with reason `no known codes`, per the owner's answer to Q2).
  - AC-28: activity `"2790"`, company `"2711"` → kept at division width, dropped at class width (per the owner's answer to Q3).
  - AC-29: taxonomy whose activities have no codes → `--out` equals the input universe, and the command prints `Taxonomy has no sector codes; nothing narrowed.`
  - AC-30: after `arp documents warm --embed` over a universe, a theme run with the funnel on makes 1 `embed` call per activity (the in-scope statement) and none for passages.
  - AC-31: `--keep X` with X dropped by AC-26's rule → X is in `--out` and not in the dropped file.
  - AC-32 (golden): `arp universe narrow --universe <universe from electrolyser_makers holdout> --taxonomy tax_electrolyser_makers --cases <cases.json>` prints `core dropped: <n>/9`; the PR states n.

## Q1 for the owner: AC-23 cannot pass together with AC-21 on this golden set

The electrolyser holdout split has 19 positive cases (9 core, 10 peripheral) and 14 `not`. AC-21 needs ≥ 95 % of positives kept, which means all 19 (18/19 = 0.947). AC-22 lets up to 4 `not` through. Calls with the setting on ∝ kept pairs ≥ 19, calls off ∝ 33 pairs with evidence, so the ratio is about 19/33 = 0.58 > 0.5 (if every case has keyword evidence). The spec's 0.5 assumes a universe of mostly non-matches (4,000 companies); this set is 58 % positive. Options:

- **A (recommended):** AC-23 counts LLM calls on `not` cases only (setting on ≤ 0.5 × off). That is the saving the funnel is for; with AC-22 met it is ≤ 4/14 ≈ 0.29.
- **B:** Keep all cases, raise the limit to `--max-call-ratio 0.75`.
- **C:** Keep AC-23 as written and record it as failing / owed in the PR.

The plan below is written for **A** (`--negatives-only` flag on `funnel-compare`); B or C change only Task 5 Step 1 and Task 6 Step 3.

## Q2 and Q3 for the owner: universe narrowing

**Q2. A company with no known codes:** **kept (recommended)**, so a universe without code columns is not emptied; or dropped with reason `no known codes`. A company with only a `gics_code` counts as having no known codes: GICS does not map onto ISIC/NACE without a table this plan does not add.

**Q3. Match width:** **ISIC division, first 2 digits (recommended)**; or ISIC class, all 4 digits. NACE and ISIC share divisions, so division width also lets a NACE-only company match an ISIC activity code without a mapping table. Class width needs NACE→ISIC class mapping and drops diversified makers whose registered class is another one.

**Can the wrong drops be measured on the golden set now? No.** `electrolyser_makers/cases.json` has `case_id, company, isin, label, role, rationale, label_sources, documents, split`, no industry code. Task 8 adds a sourced `nace_code` per case (from the company's registry entry or annual report) and then measures. Expected risk before measuring: the 18 core cases are pure-play makers, but several are young companies (Hysata, H2Pro, Stargate Hydrogen, Electric Hydrogen, Ohmium) whose registered code can be R&D (NACE 72.1) rather than manufacturing (27.90 / 28.29); each of those is a wrongly dropped core case at either width unless the activity lists 72 as well.

## Global Constraints

- Setting `ARP_MODELS_UNIVERSE_FUNNEL_ENABLED`, default `false` (`Settings.models_universe_funnel_enabled`); when false the graph is exactly today's graph path (the `funnel` node is never entered).
- `ActivityDefinition.contrast_statements: list[str] = []` (new optional field; existing taxonomy versions load unchanged).
- Positive statement = `in_scope_description`; negatives = `[out_of_scope_description] + contrast_statements`.
- Steps: passages = the pair's documents chunked with `chunk_document(doc)` (no keyword filter) → top `k1` (default 25) by cosine similarity to `in_scope_description` → top `k2` (default 6) by rerank score of `(in_scope_description, passage)` → NLI entailment of the positive and each negative on those `k2` passages.
- Pass ⇔ best rerank ≥ `t_rerank` (default 1.5) **and** some passage has positive ≥ `t_entail` (default 0.8) **and** on that passage the positive is **strictly greater** than every negative (a tie fails).
- Thresholds in `backend/arp/research/data/funnel_thresholds.json`: `{"default": {...}, "<theme_id>": {...}}`; a theme entry overrides the default key by key. The key is the taxonomy version's `theme.theme_id`.
- Screened-out pair: `MatchVerdict.EXCLUDE`, `adjudicator_rationale = "screened out by funnel"`, no LLM call.
- `funnel` record keys, exactly: `passed, rerank_max, entail_positive, entail_negatives, best_passage, best_doc_id, passages_scored, thresholds, models`. `best_passage` = the passage that satisfied the pass rule; otherwise the passage with the highest positive entailment. `entail_positive`/`entail_negatives` are the scores on `best_passage`. `models` = the provenance dicts returned by `arp/models/`.
- CLI: `arp theme funnel --taxonomy <id> [--taxonomy-version N] [--taxonomies-dir <dir>] --cases <cases.json> --documents-dir <dir> [--split tune|holdout|all] [--min-kept-positive x] [--max-kept-negative x] [--out json]`; last lines `<label>: <kept>/<total>` per label; positive = core + peripheral.
- CLI: `arp theme funnel-compare --taxonomy … [--taxonomy-version …] [--taxonomies-dir …] --cases … --documents-dir … [--split …] [--negatives-only] [--max-call-ratio x] [--max-precision-drop x]`; precision of `include` verdicts against golden labels (core + peripheral positive).
- Both funnel commands read the taxonomy with `TaxonomyStore(dir).get(id, version)`; a draft version is accepted (evaluation only, nothing is published). `arp theme run` keeps its ratified + released-schema gate.
- Universe narrowing: only in `arp universe narrow`; reads the taxonomy with `TaxonomyStore(dir).get(id, version)` (`--taxonomies-dir` as in the funnel commands); activity codes empty → nothing narrowed; company codes unknown → kept (Q2); match at ISIC division (Q3); no model or LLM call; the theme run and the funnel do not narrow.
- Passage embeddings: read from and written to `DocumentContentStore.lookup_embeddings` / `store_embeddings`, key = `chunk_id`, model = `EMBED_MODEL_NAME`; no in-process cache.
- Branch off `main`; merge `origin/main` once PR #325 lands (it adds `value_chain_role`, `criteria`, `citations`, `out_of_scope_citations`, `sector_codes` to `ActivityDefinition` next to `contrast_statements`; keep both sides).

## Review Focus

1. **Revenue-resolved pair** (catalogue hit): never enters the funnel; `funnel` is `None`, no model call. → test in Task 3.
2. **Cloud rerank failure** (`models.rerank` returns `None` scores): the pair is not screened out because a service was down. Keep embedding order, set `rerank_max = None`, pass to the debate. → test in Task 2.
3. **A pair with fewer chunks than `k1`/`k2`** (a 2-page document): score what exists; `passages_scored` equals the real count. → test in Task 2.
4. **Unknown taxonomy id / version** in the funnel commands: message `Taxonomy not found: <id>` and exit 1, before any model loads. → test in Task 4.
5. **Golden case whose document file is missing in `--documents-dir`**: the CLI prints the case id, counts it as not kept, and continues. → test in Task 4.

---

### Task 1: Schema fields, setting and thresholds

**Files:**
- Modify: `backend/arp/schemas/thematic.py` (`ActivityDefinition.contrast_statements`; new `FunnelRecord`; `CompanyMatch.funnel: FunnelRecord | None = None`), `backend/arp/config.py` (`models_universe_funnel_enabled: bool = False`)
- Create: `backend/arp/research/data/funnel_thresholds.json` (`{"default": {"k1": 25, "k2": 6, "t_rerank": 1.5, "t_entail": 0.8}}`), `backend/arp/research/funnel_thresholds.py`
- Test: `backend/tests/test_funnel_thresholds.py`

**Interfaces:**
- Produces: `FunnelRecord` (pydantic; `passed: bool`, `rerank_max: float | None`, `entail_positive: float`, `entail_negatives: dict[str, float]`, `best_passage: str`, `best_doc_id: str`, `passages_scored: int`, `thresholds: dict[str, float]`, `models: list[dict]`); `thresholds_for(theme_id: str, path: Path | None = None) -> dict[str, float]` (default path = the packaged JSON).

- [ ] **Step 1: Write failing tests**

```python
def test_activity_without_contrast_statements_loads():  # AC-16
    a = ActivityDefinition(name="x", in_scope_description="i", out_of_scope_description="o")
    assert a.contrast_statements == []

def test_saved_taxonomy_version_keeps_contrast_statements(tmp_path):  # correction (b)
    store = TaxonomyStore(tmp_path)
    t = store.create("t", ThemeDefinition(name="t", description="", activities=[act(contrast_statements=["c1"])]),
                     DerivationMethod.MANUAL)
    assert store.get(t.taxonomy_id, 1).theme.activities[0].contrast_statements == ["c1"]

def test_theme_entry_overrides(tmp_path):  # AC-13 (data side)
    p = write(tmp_path, {"default": D, "t1": {"t_rerank": 5.0}})
    assert thresholds_for("t1", p) == {**D, "t_rerank": 5.0}

def test_unknown_theme_uses_default(tmp_path):  # AC-14
    p = write(tmp_path, {"default": {**D, "t_rerank": 5.0}})
    assert thresholds_for("t2", p)["t_rerank"] == 5.0

def test_funnel_record_keys():  # AC-17 (shape)
    assert set(FunnelRecord.model_fields) == {"passed", "rerank_max", "entail_positive", "entail_negatives",
                                              "best_passage", "best_doc_id", "passages_scored", "thresholds", "models"}

def test_setting_defaults_off():
    assert Settings().models_universe_funnel_enabled is False
```
(`D = {"k1": 25, "k2": 6, "t_rerank": 1.5, "t_entail": 0.8}`.)

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_funnel_thresholds.py -v` → FAIL.
- [ ] **Step 3: Implement** the fields, the setting and `thresholds_for` (`{**data["default"], **data.get(theme_id, {})}`).
- [ ] **Step 4: Run** → PASS; `ruff check .`.
- [ ] **Step 5: Commit** `feat(theme): funnel schema fields, setting and thresholds`.

### Task 2: Funnel scoring

**Files:**
- Create: `backend/arp/research/funnel.py`
- Test: `backend/tests/test_funnel.py`

**Interfaces:**
- Consumes: Task 1; `arp.models.embed(texts) -> (ndarray, prov)`, `arp.models.rerank(query, texts) -> (list[float] | None, prov)`, `arp.models.classify(texts, labels, hypothesis) -> (list[dict[str, float]], prov)` (call with `hypothesis="{}"` and the statements as labels).
- Produces: `score_pair(documents: list[SourceDocument], activity: ActivityDefinition, thresholds: dict[str, float], content_store: DocumentContentStore | None = None) -> FunnelRecord`; `passage_vectors(chunks: list[DocumentChunk], content_store: DocumentContentStore | None) -> dict[str, np.ndarray]` (used by Task 7).

- [ ] **Step 1: Write failing tests** (stand-ins monkeypatch `arp.research.funnel.models.embed/rerank/classify` with fixed scores per passage text):

```python
def test_rerank_below_threshold_screens_out(): ...        # AC-4 data: rerank 0.5, positive 0.99 → passed False
def test_contrast_beats_positive_screens_out(): ...       # AC-7, AC-8: contrast → 0.97 in entail_negatives, passed False
def test_second_passage_passes(): ...                     # AC-9, AC-10: P1 blocked by negative, P2 passes; best_passage == P2
def test_tie_fails(): ...                                 # AC-11: positive 0.90 == negative 0.90 → passed False
def test_screened_best_passage_is_highest_positive(): ... # AC-12: best_passage == P3 (positive 0.70)
def test_k2_from_thresholds(): ...                        # AC-15: k2=1, 10 chunks → passages_scored == 1
def test_rerank_unavailable_passes_on(): ...              # Review Focus 2: rerank None → rerank_max None, passed True
def test_fewer_chunks_than_k(): ...                       # Review Focus 3: 2 chunks → passages_scored == 2
def test_models_provenance_recorded(): ...                # models == [embed prov, rerank prov, classify prov]
def test_passages_embedded_once_per_document_set(): ...   # two activities, same documents → passages embedded once (fake content store)
def test_cached_vectors_used(): ...                       # all chunk vectors in the store → embed called only for in_scope_description
def test_no_content_store_still_scores(): ...             # content_store None → embeds passages in the call, same record
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_funnel.py -v` → FAIL.
- [ ] **Step 3: Implement** `score_pair` per Global Constraints. Passage vectors come from `passage_vectors(chunks, content_store) -> dict[str, ndarray]`: look up by `chunk_id`, embed only the missing ones with `models.embed`, store them back (same pattern and lock as `select_evidence._vector_ranking`). `content_store` is built once per run with `build_hybrid_content_store(settings)` (as `_gather_evidence` does) and is `None` when Postgres is not configured. With `rerank_max is None`, take the top `k2` by embedding similarity, skip the thresholds and set `passed = True`. Truncation is left to the models.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(theme): funnel scoring`.

### Task 3: Funnel node in the match graph

**Files:**
- Modify: `backend/arp/research/match_graph.py` (`MatchState.funnel_thresholds: dict[str, float] | None`, `MatchState.funnel: FunnelRecord | None`; nodes `funnel`, `finalize_screened_out`; routing; `match_company_activity(..., funnel_thresholds: dict[str, float] | None = None)`), `backend/arp/research/pipeline.py` (`_match_company` passes `funnel_thresholds=thresholds_for(theme.theme_id) if settings.models_universe_funnel_enabled else None`), `docs/superpowers/specs/2026-11-01-theme-funnel-design.md` (the amendments above)
- Test: `backend/tests/test_funnel_integration.py`

**Interfaces:**
- Consumes: `score_pair`, `thresholds_for`.
- Produces: graph routing
  - `_route_after_evidence`: no evidence → `finalize_no_evidence`; evidence and `funnel_thresholds is None` → `run_advocate`; otherwise → `funnel`.
  - `funnel` node: `{"funnel": score_pair(state["documents"], state["activity"], state["funnel_thresholds"], content_store)}` with `content_store` built the way `_gather_evidence` builds it; route passed → `run_advocate`, screened → `finalize_screened_out`.
  - `finalize_screened_out`: builds the match from `_finalize_no_evidence(state)` with `adjudicator_rationale="screened out by funnel"`, `advocate=None`, `opposing=None`, `funnel=state["funnel"]` (keeps its arbitration, structural review flag and `exposure_estimate=NONE`).
  - `_run_adjudicator_node` sets `funnel=state["funnel"]` on the match (None when the funnel did not run).

- [ ] **Step 1: Write failing tests** (fixture theme with 1 activity; stand-in LLM counting calls per company; stand-in models; run through `run_thematic_universe` or `_match_company`):

```python
def test_setting_off_same_calls_as_all_pass(): ...  # AC-1: calls(off) == calls(on, every pair passes)
def test_passing_pair_reaches_debate(): ...         # AC-2 (≥1 call for A), AC-3 (A.funnel.passed is True)
def test_screened_pair_no_llm(): ...                # AC-4 exclude, AC-5 rationale, AC-6 0 calls for B
def test_contrast_screens_out(): ...                # AC-7 C exclude
def test_second_passage_reaches_debate(): ...       # AC-9: ≥1 call for D
def test_tie_screens_out(): ...                     # AC-11: E exclude
def test_theme_specific_threshold(): ...            # AC-13: theme t1 t_rerank 5.0 → G exclude
def test_default_threshold(): ...                   # AC-14: theme t2 not in file, default 5.0 → G exclude
def test_run_json_funnel_keys(): ...                # AC-17: screened pair's funnel dict has exactly the 9 keys
def test_revenue_resolved_pair_skips_funnel(): ...  # Review Focus 1: catalogue hit → funnel None, models stand-ins not called
def test_no_keyword_evidence_unchanged(): ...       # no evidence → finalize_no_evidence rationale, funnel None, models not called
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the state keys, nodes, routing and the `_match_company` argument; apply the spec amendments.
- [ ] **Step 4: Run** the new tests plus `python3 -m pytest tests -q -k "theme or research or match"` → PASS.
- [ ] **Step 5: Commit** `feat(theme): funnel node between evidence and debate`.

### Task 4: `arp theme funnel` from a taxonomy version

**Files:**
- Modify: `backend/arp/cli/theme.py`
- Create: `backend/tests/golden/exposure/electrolyser_makers/taxonomies/tax_electrolyser_makers/v1.json` and `latest.json` (written with `TaxonomyStore`, `derivation_method=manual`, status draft; one activity: `in_scope_description` "Manufactures and sells electrolysers or electrolyser stacks for producing hydrogen from water"; `out_of_scope_description` "Buys, operates, finances or supplies components for electrolysers made by others; makes fuel cells"; `contrast_statements` ["The company buys or operates electrolysers made by another company.", "The company supplies components, materials or catalysts for electrolysers that other companies build."]), `backend/scripts/fetch_exposure_documents.py` (downloads each case's first document URL to `<documents-dir>/<case_id>.<ext>`, skips existing files, prints failures)
- Test: `backend/tests/test_funnel_cli.py`

**Interfaces:**
- Consumes: `TaxonomyStore.get`, `THEME_NOT_ALLOWED`, `arp.golden_set.exposure.load_set`, `parse_file_to_text_with_pages`, `score_pair`, `thresholds_for`.
- Produces: `_funnel_taxonomy(taxonomy_id: str, version: int | None, taxonomies_dir: Path | None) -> Taxonomy` (exit 1 with `Taxonomy not found: <id>` when missing; default dir `settings.taxonomies_dir`); `funnel_report(theme: ThemeDefinition, cases: ExposureSet, documents_dir: Path, split: str) -> list[dict]` (one row per case: `case_id, label, kept, rerank_max, entail_positive`; one activity per golden theme — the set's `subject`), used by the CLI and Task 5.

- [ ] **Step 1: Write failing tests** (stand-in models; tiny text documents in `tmp_path`; a `TaxonomyStore` in `tmp_path`; root-CLI fixture that skips Postgres, as in `tests/test_golden_exposure.py`):

```python
def test_label_lines(): ...                       # AC-18: last three lines "core: 2/2", "peripheral: 1/1", "not: 0/2"
def test_min_kept_positive_fails(): ...           # AC-19: kept 0.90 with --min-kept-positive 0.95 → exit 1
def test_max_kept_negative_fails(): ...           # AC-20: not kept 0.40 with --max-kept-negative 0.30 → exit 1
def test_split_filter(): ...                      # --split holdout counts only holdout cases
def test_contrast_from_taxonomy_version(): ...    # v1 without contrast keeps C, v2 with it screens C; --taxonomy-version picks
def test_theme_option_refused(): ...              # --theme x.json → THEME_NOT_ALLOWED, exit 1
def test_unknown_taxonomy(): ...                  # Review Focus 4: "Taxonomy not found: tax_nope", exit 1, models not called
def test_missing_document_counts_not_kept(): ...  # Review Focus 5: case id printed, kept False, exit 0 without limits
def test_golden_taxonomy_loads(): ...             # the committed store dir loads; contrast_statements has 2 entries
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the command, `_funnel_taxonomy` and `funnel_report`; document file looked up as the single file `documents_dir.glob(f"{case_id}.*")`.
- [ ] **Step 4: Run** → PASS; `ruff check .`.
- [ ] **Step 5: Commit** `feat(theme): funnel CLI over exposure golden sets, taxonomy-version input`.

### Task 5: `arp theme funnel-compare`

**Files:**
- Modify: `backend/arp/cli/theme.py`
- Test: `backend/tests/test_funnel_cli.py`

**Interfaces:**
- Consumes: `_funnel_taxonomy`; `run_thematic_universe(taxonomy.theme, companies, ..., taxonomy_id=taxonomy.taxonomy_id, taxonomy_version=taxonomy.version)` with a `DocumentSourceRegistry` holding one `LocalFileDocumentSource` over `--documents-dir`; the golden cases as the universe (`CompanyRef(company_id=case_id, name=company)`).
- Produces: printed `llm_calls_off`, `llm_calls_on`, `precision_off`, `precision_on`; with `--negatives-only` the call counts cover `not` cases only; exit 1 when `calls_on > max_call_ratio × calls_off` or `precision_off − precision_on > max_precision_drop`.

- [ ] **Step 1: Write failing tests** with a counting stand-in LLM and stand-in models: `test_compare_prints_counts`, `test_compare_call_ratio_exit` (ratio broken → exit 1), `test_compare_negatives_only_counts` (positive-case calls excluded from both counts), `test_compare_precision_drop_exit` (drop broken → exit 1), `test_compare_uses_taxonomy_version` (the run manifest records `taxonomy_id` and `taxonomy_version`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: run twice with `settings.model_copy(update={"models_universe_funnel_enabled": False/True})`, count calls per company from the runs' `LLMUsage` records, compute precision of `include` verdicts with core + peripheral as positive.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(theme): funnel-compare from a taxonomy version`.

### Task 6: Golden runs, merge of #325, regression

- [ ] **Step 1: Fetch documents** `python3 backend/scripts/fetch_exposure_documents.py --cases backend/tests/golden/exposure/electrolyser_makers/cases.json --out <scratch>/elec_docs`; record how many cases have no document.
- [ ] **Step 2: Tune** on `--split tune` only: `arp theme funnel --taxonomy tax_electrolyser_makers --taxonomies-dir backend/tests/golden/exposure/electrolyser_makers/taxonomies --split tune`; change `funnel_thresholds.json` (key `tax_electrolyser_makers`' `theme_id`) or the taxonomy's contrast statements (as a new version `v2`), never from holdout output.
- [ ] **Step 3: Gate on holdout (real models)**: `--split holdout --min-kept-positive 0.95` and `--max-kept-negative 0.30` → exit 0 (AC-21, AC-22). Then `funnel-compare --split holdout --negatives-only --max-call-ratio 0.5` and `--max-precision-drop 0.02` → exit 0 (AC-23, AC-24). Without an API key or GPU, record AC-21…AC-24 as owed in the PR, not passed.
- [ ] **Step 4: Merge main** once PR #325 is merged: `git fetch origin main && git merge origin/main`; resolve `ActivityDefinition` by keeping #325's fields and `contrast_statements`; rerun Tasks 1–5 tests.
- [ ] **Step 5: Regression** `python3 -m pytest backend/tests -q` excluding the new files: same pass/fail per test as `main` (AC-25). Commit any tuned values `chore(theme): funnel thresholds tuned on the electrolyser tune split`.

### Task 7: `arp documents warm --embed`

**Files:**
- Modify: `backend/arp/cli/documents.py` (`documents_warm`: option `--embed/--no-embed`, default off)
- Test: `backend/tests/test_documents_warm_embed.py`

**Interfaces:**
- Consumes: `passage_vectors` (Task 2), `chunk_document(doc)`, `build_hybrid_content_store(settings)`.
- Produces: after each company's `fetch_all`, `passage_vectors(chunks_of_all_docs, content_store)`; prints `Embedded <n> new chunks (<m> already stored).`; exit 1 with `--embed needs ARP_POSTGRES_DSN` when no content store can be built.

- [ ] **Step 1: Write failing tests** (fake registry with 2 documents, fake content store, counting `embed` stand-in): `test_warm_embed_stores_every_chunk` (store holds one vector per `chunk_document(doc)` chunk), `test_warm_embed_rerun_embeds_nothing` (second run: 0 new), `test_warm_without_embed_unchanged` (no embed calls, same output lines as today), `test_warm_embed_without_dsn_exits_1`, and AC-30 in `test_funnel_integration.py` (warm, then theme run with the funnel on: `embed` called once per activity).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the option; embed after the semaphore-bounded fetch, one company at a time (the model is not thread-safe; `_EMBED_LOCK` already serialises it).
- [ ] **Step 4: Run** → PASS; `ruff check .`.
- [ ] **Step 5: Commit** `feat(documents): warm --embed precomputes chunk embeddings`.

### Task 8: `arp universe narrow` (after PR #325 is merged into this branch)

**Files:**
- Create: `backend/arp/universe_narrow.py`
- Modify: `backend/arp/cli/universe.py` (command `narrow`), `backend/arp/golden_set/exposure.py` (`ExposureCase.nace_code: str | None = None`, `nace_source: str | None = None`), `backend/tests/golden/exposure/electrolyser_makers/cases.json` (both fields per case), the golden taxonomy (new version `v2` with `sector_codes` for the activity: NACE 27.90 and 28.29, plus whatever Step 4 shows is needed)
- Test: `backend/tests/test_universe_narrow.py`

**Interfaces:**
- Consumes: `load_company_universe`, `TaxonomyStore.get`, `_funnel_taxonomy` (Task 4, for the taxonomy lookup and its `Taxonomy not found` exit).
- Produces: `narrow_universe(companies: list[CompanyRef], theme: ThemeDefinition, keep: set[str] = frozenset()) -> tuple[list[CompanyRef], list[dict]]`. Taxonomy codes = every activity's `core_isic_codes` + `sector_codes` with system ISIC or NACE; company codes = `isic_code`, `nace_code`; each normalised to its first 2 digits (dots removed). Kept when the taxonomy has no codes, the company has none (Q2), any division matches, or `company_id in keep`. Each dropped row: `{"company_id", "name", "isic_code", "nace_code", "reason"}`, reason `no sector match (company <divs>, taxonomy <divs>)`.
- CLI: `arp universe narrow --universe <in> --taxonomy <id> [--taxonomy-version N] [--taxonomies-dir <dir>] --out <universe.json> [--keep <company_id> ...] [--cases <golden cases.json>]`; writes `--out` and `<out stem>.dropped.json`; prints `Kept <k> of <n> companies; <d> dropped (see <path>).`; with `--cases`, then one line per label `<label> dropped: <n>/<total>` (company_id = case_id).
- Golden universe: `arp golden-set exposure universe --set <dir> [--split …] --out <universe.json>` writes `CompanyRef(company_id=case_id, name=company, isin, nace_code)` per case.

- [ ] **Step 1: Write failing tests**: `test_narrow_drops_out_of_sector` (AC-26, reason text exact), `test_narrow_keeps_company_without_codes` (AC-27), `test_narrow_division_width` (AC-28), `test_narrow_taxonomy_without_codes_is_noop` (AC-29, message exact), `test_narrow_keep_overrides` (AC-31), `test_narrow_nace_matches_isic_division` (`nace_code "27.90"` vs activity ISIC `"2790"` → kept), `test_narrow_gics_only_counts_as_unknown`, `test_narrow_cases_prints_label_lines` (fixture: `core dropped: 1/3`), `test_golden_universe_from_cases`.
- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/test_universe_narrow.py -v` → FAIL.
- [ ] **Step 3: Implement** `narrow_universe`, the two commands.
- [ ] **Step 4: Measure** (golden data work, about 1 hour): fill `nace_code` + `nace_source` for all 66 cases from a public registry entry or the annual report. Build the tune universe, run `narrow --cases`, widen the activity's codes in `v2` only from that tune output; then run the holdout universe once and put `core dropped: n/9` and `not dropped: m/14` in the PR (AC-32).
- [ ] **Step 5: Run** → PASS; `ruff check .`; **Commit** `feat(universe): narrow a universe to a taxonomy's sector codes`.

## Self-review notes

- Spec coverage: AC-1…AC-7, AC-9, AC-11, AC-13, AC-14, AC-17 → Task 3; AC-7/8, AC-10…12, AC-15 → Task 2; AC-13/14/16/17 data side → Task 1; AC-18…20 → Task 4; AC-21…24 → Task 6 (golden, likely owed); AC-25 → Task 6.
- AC-26…AC-32 (owner additions) → Tasks 7 and 8.
- Rulings made in this plan: a rerank outage skips the rerank threshold instead of screening pairs out (spec silent); funnel commands accept a draft taxonomy version (evaluation only); thresholds stay keyed by `theme_id` as the spec says.
- The funnel only runs where a debate would have run, so revenue-path LLM calls (extraction fallback) are not reduced by it. The golden runs use no revenue resolver, so AC-23 measures debate calls only.
