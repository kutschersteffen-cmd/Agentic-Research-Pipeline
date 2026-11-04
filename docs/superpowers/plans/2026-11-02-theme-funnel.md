# Theme Funnel (A2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before the Advocate / Opposing / Adjudicator debate, score each company × activity pair with embeddings → cross-encoder → NLI and skip the LLM for pairs the funnel screens out, keeping every score and the best passage.

**Architecture:** A pure scoring module (`arp/research/funnel.py`) takes a pair's chunks and the activity, calls `arp/models/` (`embed`, `rerank`, `classify`) and returns a `FunnelRecord`. `_match_company` calls it per activity when the setting is on and short-circuits screened-out pairs to an `exclude` `CompanyMatch`. Two CLI commands run the funnel alone, or the full run twice, over a golden set.

**Tech Stack:** Python 3.11, pydantic v2, numpy, Typer, pytest; the shared model layer from PR #304.

**Spec:** `docs/superpowers/specs/2026-11-01-theme-funnel-design.md` (approved 2026-11-01).

## Global Constraints

- Setting `ARP_MODELS_UNIVERSE_FUNNEL_ENABLED`, default `false`; when false nothing in this plan runs (`Settings.models_universe_funnel_enabled`).
- `ActivityDefinition.contrast_statements: list[str] = []` (new optional field).
- Positive statement = `in_scope_description`; negatives = `[out_of_scope_description] + contrast_statements`.
- Steps: passages = the pair's chunks (`chunk_document`, no keyword filter) → top `k1` (default 25) by cosine similarity to `in_scope_description` → top `k2` (default 6) by rerank score of `(in_scope_description, passage)` → NLI entailment of positive and each negative on those `k2` passages.
- Pass ⇔ best rerank ≥ `t_rerank` (default 1.5) **and** some passage has positive ≥ `t_entail` (default 0.8) **and** on that passage the positive is **strictly greater** than every negative (a tie fails).
- Thresholds in `backend/arp/research/data/funnel_thresholds.json`: `{"default": {...}, "<theme_id>": {...}}`; a theme entry overrides the default key by key.
- Screened-out pair: `MatchVerdict.EXCLUDE`, `adjudicator_rationale = "screened out by funnel"`, no LLM call.
- `funnel` record keys, exactly: `passed, rerank_max, entail_positive, entail_negatives, best_passage, best_doc_id, passages_scored, thresholds, models`. `best_passage` = the passage that satisfied the pass rule; otherwise the passage with the highest positive entailment. `entail_positive`/`entail_negatives` are the scores on `best_passage`. `models` = the provenance dicts returned by `arp/models/`.
- CLI: `arp theme funnel --theme <theme.json> --cases <cases.json> --documents-dir <dir> [--split tune|holdout|all] [--min-kept-positive x] [--max-kept-negative x] [--out json]`; last lines `<label>: <kept>/<total>` per label; positive = core + peripheral.
- CLI: `arp theme funnel-compare --theme … --cases … --documents-dir … [--split …] [--max-call-ratio x] [--max-precision-drop x]`; precision of `include` verdicts against golden labels (core + peripheral positive).

## Review Focus

1. **Cloud rerank failure** (`models.rerank` returns `None` scores): the funnel must not screen a pair out because a service was down. Keep embedding order, set `rerank_max = None`, and let the pair pass to the debate. → test in Task 2.
2. **A pair with fewer chunks than `k1`/`k2`** (a 2-page document): score what exists; `passages_scored` equals the real count. → test in Task 2.
3. **No chunks at all**: unchanged behaviour (`finalize_no_evidence`), the funnel does not run. → test in Task 3.
4. **Unknown theme id in the thresholds file**: falls back to `default` (AC-14), and a theme entry with only `t_rerank` still inherits `k1`, `k2`, `t_entail`. → test in Task 1.
5. **Golden case whose document file is missing in `--documents-dir`**: the CLI prints the case id, counts it as not kept, and continues. → test in Task 4.

---

### Task 1: Schema fields, setting and thresholds

**Files:**
- Modify: `backend/arp/schemas/thematic.py` (`ActivityDefinition.contrast_statements`; new `FunnelRecord`; `CompanyMatch.funnel: FunnelRecord | None = None`), `backend/arp/config.py` (`models_universe_funnel_enabled: bool = False`)
- Create: `backend/arp/research/data/funnel_thresholds.json` (`{"default": {"k1": 25, "k2": 6, "t_rerank": 1.5, "t_entail": 0.8}}`), `backend/arp/research/funnel_thresholds.py`
- Test: `backend/tests/test_funnel_thresholds.py`

**Interfaces:**
- Produces: `FunnelRecord` (pydantic, fields exactly as in Global Constraints; `rerank_max: float | None`, `entail_negatives: dict[str, float]`, `thresholds: dict[str, float]`, `models: list[dict]`); `thresholds_for(theme_id: str, path: Path | None = None) -> dict[str, float]` (default path = the packaged JSON).

- [ ] **Step 1: Write failing tests**

```python
def test_theme_without_contrast_statements_loads():  # spec AC-16
    a = ActivityDefinition(name="x", in_scope_description="i", out_of_scope_description="o")
    assert a.contrast_statements == []

def test_theme_entry_overrides(tmp_path):  # spec AC-13 (data side)
    p = write(tmp_path, {"default": D, "t1": {"t_rerank": 5.0}})
    assert thresholds_for("t1", p) == {**D, "t_rerank": 5.0}

def test_unknown_theme_uses_default(tmp_path):  # spec AC-14, Review Focus 4
    p = write(tmp_path, {"default": {**D, "t_rerank": 5.0}})
    assert thresholds_for("t2", p)["t_rerank"] == 5.0

def test_funnel_record_keys():  # spec AC-17 (shape)
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
- Consumes: Task 1; `arp.models.embed(texts) -> (ndarray, prov)`, `arp.models.rerank(query, texts) -> (list[float] | None, prov)`, `arp.models.classify(texts, labels, hypothesis) -> (list[dict[str, float]], prov)` (multi-label entailment; call with `hypothesis="{}"` and the statements as labels).
- Produces: `score_pair(chunks: list[DocumentChunk], activity: ActivityDefinition, thresholds: dict[str, float]) -> FunnelRecord`.

- [ ] **Step 1: Write failing tests** (stand-ins monkeypatch `arp.research.funnel.models.embed/rerank/classify` with fixed scores per passage text; one test per spec row):

```python
def test_rerank_below_threshold_screens_out(): ...        # AC-4 data: rerank 0.5, positive 0.99 → passed False
def test_contrast_beats_positive_screens_out(): ...       # AC-7, AC-8: negatives map has contrast → 0.97, passed False
def test_second_passage_passes(): ...                     # AC-9, AC-10: P1 blocked by negative, P2 passes; best_passage == P2
def test_tie_fails(): ...                                 # AC-11: positive 0.90 == negative 0.90 → passed False
def test_screened_best_passage_is_highest_positive(): ... # AC-12: best_passage == P3 (positive 0.70)
def test_k2_from_thresholds(): ...                        # AC-15: k2=1, 10 chunks → passages_scored == 1
def test_rerank_unavailable_passes_on(): ...              # Review Focus 1: rerank returns None → rerank_max None, passed True
def test_fewer_chunks_than_k(): ...                       # Review Focus 2: 2 chunks → passages_scored == 2
def test_models_provenance_recorded(): ...                # models == [embed prov, rerank prov, classify prov]
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_funnel.py -v` → FAIL.
- [ ] **Step 3: Implement** `score_pair` per Global Constraints. With `rerank_max is None` (Review Focus 1), take the top `k2` passages by embedding similarity, skip the rerank threshold and set `passed = True` regardless of NLI, so an outage never drops a pair (the debate decides). Truncation is left to the models.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(theme): funnel scoring`.

### Task 3: Integration into the theme run

**Files:**
- Modify: `backend/arp/research/pipeline.py` (`_match_company`), `backend/arp/research/match_graph.py` only if the screened-out `CompanyMatch` is built there (reuse whatever builds the `finalize_no_evidence` result)
- Test: `backend/tests/test_funnel_integration.py`

**Interfaces:**
- Consumes: `score_pair`, `thresholds_for(theme.theme_id)`, `settings.models_universe_funnel_enabled`.
- Produces: screened-out pairs as `CompanyMatch(verdict=EXCLUDE, adjudicator_rationale="screened out by funnel", confidence=0.0, exposure_estimate=<the same value finalize_no_evidence uses>, funnel=record)`; passing pairs carry `funnel=record` into the normal debate result.

- [ ] **Step 1: Write failing tests** (fixture theme with 1 activity; stand-in LLM counting calls; stand-in models):

```python
def test_setting_off_same_calls_as_all_pass(): ...  # AC-1: calls(off) == calls(on, every pair passes)
def test_passing_pair_reaches_debate(): ...         # AC-2 (≥1 call for A), AC-3 (A.funnel.passed is True)
def test_screened_pair_no_llm(): ...                # AC-4 verdict exclude, AC-5 rationale, AC-6 0 calls for B
def test_second_passage_reaches_debate(): ...       # AC-9: ≥1 call for D
def test_theme_specific_threshold(): ...            # AC-13: theme t1 t_rerank 5.0 → G excluded
def test_default_threshold(): ...                   # AC-14: theme t2 not in file, default 5.0 → G excluded
def test_run_json_funnel_keys(): ...                # AC-17: screened pair's funnel dict has exactly the 9 keys
def test_no_chunks_unchanged(): ...                 # Review Focus 3: no documents → existing no-evidence result, funnel None
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: in `_match_company`, when the setting is on and documents exist, chunk once per document (`chunk_document(doc)`, no keywords), call `score_pair` per activity; screened → build the exclude match and skip `match_company_activity`; passed → call `match_company_activity` and set `match.funnel = record`.
- [ ] **Step 4: Run** the new tests plus `python3 -m pytest tests -q -k "theme or research or match"` → PASS.
- [ ] **Step 5: Commit** `feat(theme): run the funnel before the debate`.

### Task 4: `arp theme funnel` over a golden set

**Files:**
- Modify: `backend/arp/cli/theme.py`
- Create: `backend/tests/golden/exposure/electrolyser_makers/theme.json` (one activity: `in_scope_description` "Manufactures and sells electrolysers or electrolyser stacks for producing hydrogen from water"; `out_of_scope_description` "Buys, operates, finances or supplies components for electrolysers made by others; makes fuel cells"; `contrast_statements` ["The company buys or operates electrolysers made by another company.", "The company supplies components, materials or catalysts for electrolysers that other companies build."]), `backend/scripts/fetch_exposure_documents.py` (downloads each case's first document URL to `<documents-dir>/<case_id>.<ext>`, skips existing files, prints failures)
- Test: `backend/tests/test_funnel_cli.py`

**Interfaces:**
- Consumes: `arp.golden_set.exposure.load_set`, `parse_file_to_text_with_pages`, `chunk_document`, `score_pair`.
- Produces: `funnel_report(theme: ThemeDefinition, cases: ExposureSet, documents_dir: Path, split: str) -> list[dict]` (one row per case: `case_id, label, kept, rerank_max, entail_positive`), used by the CLI and Task 5.

- [ ] **Step 1: Write failing tests** (stand-in models; tiny text documents in `tmp_path`; root-CLI fixture that skips Postgres, as in `tests/test_golden_exposure.py`):

```python
def test_label_lines(): ...                 # AC-18: last three lines "core: 2/2", "peripheral: 1/1", "not: 0/2"
def test_min_kept_positive_fails(): ...     # AC-19: positive kept 0.90 with --min-kept-positive 0.95 → exit 1
def test_max_kept_negative_fails(): ...     # AC-20: not kept 0.40 with --max-kept-negative 0.30 → exit 1
def test_split_filter(): ...                # --split holdout counts only holdout cases
def test_missing_document_counts_not_kept(): ...  # Review Focus 5: case id printed, kept False, exit 0 without limits
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the command and `funnel_report`; document file looked up as the single file `documents_dir.glob(f"{case_id}.*")`.
- [ ] **Step 4: Run** → PASS; `ruff check .`.
- [ ] **Step 5: Commit** `feat(theme): funnel CLI over exposure golden sets`.

### Task 5: `arp theme funnel-compare`

**Files:**
- Modify: `backend/arp/cli/theme.py`
- Test: `backend/tests/test_funnel_cli.py`

**Interfaces:**
- Consumes: `run_thematic_universe(...)` with a `DocumentSourceRegistry` holding one `LocalFileDocumentSource` over `--documents-dir`; the theme JSON; the golden cases as the universe (`CompanyRef(company_id=case_id, name=company)`).
- Produces: printed `llm_calls_off`, `llm_calls_on`, `precision_off`, `precision_on`; exit 1 when `calls_on > max_call_ratio × calls_off` or `precision_off − precision_on > max_precision_drop`.

- [ ] **Step 1: Write failing tests** with a counting stand-in LLM and stand-in models: `test_compare_prints_counts`, `test_compare_call_ratio_exit` (ratio broken → exit 1), `test_compare_precision_drop_exit` (drop broken → exit 1).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: run twice with `settings.model_copy(update={"models_universe_funnel_enabled": False/True})`, count calls from the runs' `LLMUsage` records, compute precision of `include` verdicts with core + peripheral as positive.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(theme): funnel-compare`.

### Task 6: Golden runs and regression

- [ ] **Step 1: Fetch documents** `python3 backend/scripts/fetch_exposure_documents.py --cases backend/tests/golden/exposure/electrolyser_makers/cases.json --out <scratch>/elec_docs` and record how many cases have no document.
- [ ] **Step 2: Golden (real models; GPU or patient CPU)**: `arp theme funnel --split holdout --min-kept-positive 0.95` and `--max-kept-negative 0.30` → exit 0 (AC-21, AC-22). Tune `funnel_thresholds.json` only on `--split tune` before this.
- [ ] **Step 3: Golden (real LLM)**: `arp theme funnel-compare --split holdout --max-call-ratio 0.5` and `--max-precision-drop 0.02` → exit 0 (AC-23, AC-24). If no API key or GPU is available, record AC-21…AC-24 as owed in the PR, not passed.
- [ ] **Step 4: Regression** `python3 -m pytest backend/tests -q` excluding the new files: same pass/fail per test as `main` (AC-25).
- [ ] **Step 5: Commit** any tuned thresholds `chore(theme): funnel thresholds tuned on the electrolyser tune split`.

## Self-review notes

- Spec coverage: AC-1, AC-2/3, AC-4/5/6, AC-9 → Task 3; AC-7/8, AC-10/11/12, AC-15 → Task 2; AC-13/14 → Tasks 1 and 3; AC-16/17 → Tasks 1 and 3; AC-18/19/20 → Task 4; AC-21…24 → Task 6 (golden, likely owed); AC-25 → Task 6.
- Ruling made in this plan (Review Focus 1): a rerank outage skips the rerank threshold instead of screening pairs out. The spec is silent; the alternative would silently drop real matches during an outage.
- The golden set has document URLs only (spec A3), so Task 4 adds a fetch script rather than storing documents in the repo.
