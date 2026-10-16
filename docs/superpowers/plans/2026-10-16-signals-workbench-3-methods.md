# Signals workbench, plan 3: methods

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One method interface with the spec's method families behind it, a `run_recipe` that always evaluates and registers (so the guardrails cannot be skipped), and `arp signals run` to use it.

**Architecture:** A method is a function `(MethodInput, params) -> MethodResult` registered by name. The result is a `CharacteristicPanel` on the price grid plus the model name (for the training-cutoff split) and notes (leakage rate, rerun stability). `run_recipe` runs a recipe's method, evaluates with plan 1's `evaluate_signal`, and registers the experiment. Methods compose by nesting method specs (`transform`, `composite`). Models, search tools and the LLM client are passed in through `MethodInput`, so every method is testable with fakes.

**Tech Stack:** Python 3.11, numpy (ridge solved in closed form), existing `fastembed` (core dependency), pydantic v2, typer. FinBERT needs `transformers` and `torch`: optional, imported lazily. **No change to core dependencies.**

**Spec:** `docs/superpowers/specs/2026-10-14-signals-workbench-design.md` (Goals 2, Guardrails, Components 3). Base: plan 1 (evidence core and registry, merged) and plan 2 (text store and adapters, merged as PR #148).

## Roadmap (plan 3 of 5)

1. Evidence core and registry (done).
2. Text store and adapters (done).
3. **This plan.**
4. Notebook library.
5. App screens and API.

Not in this plan: ChronoBERT vintage wrappers (the embedder is injectable, so a notebook can pass one), Optuna search, size/sector-neutral and value-weighted evidence views, a real search tool for the issuer-first variant (interface and leakage handling only; owner question 3 is parked), the Loughran-McDonald dictionary (licence unanswered), composites that mix different models, any UI.

## Global Constraints

- Python `>=3.11`; every module starts with `from __future__ import annotations`; no new core dependencies. FinBERT's `transformers`/`torch` go in an optional extra named `finbert`, and `bertopic` in an optional extra named `topics`; both are imported inside the function that needs them.
- **Issuer key** is the one identity (`TextRecord.company_id`, panel and price columns). Tickers are never an identity.
- **No look-ahead.** A value at grid index `i` may use only text with event time `<=` `month_end_time(period_ends[i])` and returns at indices `<= i`. Text is bucketed to grid index `i` when its event time is after `month_end_time(period_ends[i-1])` and `<= month_end_time(period_ends[i])`; for `i = 0` the bucket starts at the first second of that calendar month; earlier text is ignored.
- **Walk-forward.** A fitted method scores month `i` using only training months `j < i`, labelled with the return at index `j + 1` (known by the end of month `i`). Fewer than `min_train_months` such months gives `None`.
- **Absent is not zero.** A name with no usable data is `None`, never `0.0`.
- **Model and cutoff.** A method that uses a pretrained model returns its name in `MethodResult.model`. A model with no recorded cutoff is contaminated (plan 1 rule). A method with no pretrained model and only walk-forward fitting returns `None`.
- **Grounding.** An LLM score keeps a verbatim quote or is excluded (existing `build_sentiment_panel` rule).
- **Registration is the enforcement point.** Everything shown, ranked or graduated goes through `run_recipe`; a result computed outside it is "unregistered, not evidence".
- Backend checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`. Postgres tests need `ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test` (restart: `bash .claude/hooks/ensure-deps.sh postgres`).
- Never delete or weaken an existing test. Comments only for the why. Do not touch adjacent code. PRs target `main`.

## Review Focus

1. **Truncation invariance.** For every method, removing all text and prices after month `k` leaves the values at months `<= k` unchanged. (Task 1 supplies the check; Tasks 2 to 6 run it.)
2. **Walk-forward.** A fitted method never trains on a label not yet realised at the formation month; the first `min_train_months` months are `None`; a topic model is refitted only on text already published. (Tasks 4, 5, 6)
3. **No coverage is `None`, not 0**; a composite with a missing component is `None` unless told otherwise. (Tasks 2, 3, 6)
4. **A missing model, tool or client raises a clear `ValueError`** naming what to pass; an unknown model is contaminated, never silently trusted. (Tasks 1, 5 to 9)
5. **Rerun stability cannot be faked by a cache**, and residual leakage is reported beside the score, not hidden. (Tasks 7, 9)

## File structure

| File | Responsibility |
|---|---|
| `backend/arp/signal_lab/methods/__init__.py` | imports every method module so they register |
| `backend/arp/signal_lab/methods/base.py` | `MethodInput`, `MethodResult`, registry, `text_buckets`, `run_method`, `run_recipe`, built-in `panel` and `price_momentum` methods |
| `backend/arp/signal_lab/methods/checks.py` | `lookahead_violations` |
| `backend/arp/signal_lab/methods/transforms.py` | `transform` and `composite` methods |
| `backend/arp/signal_lab/methods/attention.py` | `narrative_attention` |
| `backend/arp/signal_lab/methods/topics.py` | `topic_attention` (BERTopic, refitted walk-forward), `default_topic_model` |
| `backend/arp/signal_lab/methods/lexicon.py` | `learned_lexicon` |
| `backend/arp/signal_lab/methods/embedding.py` | `embedding_ridge`, `default_embedder` |
| `backend/arp/signal_lab/methods/llm_scoring.py` | `grounded_llm`, `estimate_llm_calls`, `rerun_stability` |
| `backend/arp/signal_lab/methods/finbert.py` | `finbert`, `default_finbert` |
| `backend/arp/signal_lab/methods/issuer_first.py` | `SearchTool` interface, `issuer_first` |
| `backend/arp/signal_lab/registry.py` | modify: `ExperimentRecord.notes` |
| `backend/arp/cli/signal_lab.py` | modify: `run` command |
| `backend/pyproject.toml` | modify: optional extras `finbert` and `topics` |
| `backend/tests/test_signal_methods_*.py` | tests |

---

### Task 1: Interface, registry, `run_recipe`, look-ahead check

**Files:**
- Create: `backend/arp/signal_lab/methods/__init__.py`, `base.py`, `checks.py`
- Modify: `backend/arp/signal_lab/registry.py` (`ExperimentRecord.notes: dict = {}`; `Registry.register(..., notes: dict | None = None)` stores it)
- Test: `backend/tests/test_signal_methods_base.py`

**Interfaces:**
- Consumes: `TextRecord`, `month_end_time`, `Recipe`, `Registry`, `ExperimentRecord`, `CutoffTable`, `evaluate_signal`, `sentiment_spec`, `momentum_panel`, `CharacteristicPanel`, `PricePanel`.
- Produces (all in `base.py` unless noted):
  - `@dataclass MethodInput(texts: list[TextRecord], prices: PricePanel, panels: dict[str, CharacteristicPanel] = {}, resources: dict[str, Any] = {})` (`resources` keys used later: `llm`, `embedder`, `finbert`, `search`).
  - `@dataclass MethodResult(panel: CharacteristicPanel, model: str | None = None, notes: dict = {})`.
  - `register_method(name: str)` decorator; `get_method(name: str)` raises `ValueError` listing the known names; `run_method(spec: dict, inp: MethodInput) -> MethodResult` where `spec = {"method": str, "params": dict}`.
  - `text_buckets(texts: list[TextRecord], period_ends: list[str]) -> dict[str, list[list[TextRecord]]]` (issuer to one list per grid index, per the bucketing rule; items with `company_id is None` skipped).
  - `trainable_months(i: int) -> range` (`range(0, i)`; the label for month `j` is the return at index `j + 1`).
  - `run_recipe(recipe: Recipe, inp: MethodInput, *, registry: Registry, cutoffs: CutoffTable, data_version: str) -> ExperimentRecord`: runs `{"method": recipe.method, "params": recipe.params}`; raises `ValueError` if the panel grid differs from the price grid; `n_trials = registry.trial_count(recipe) + (0 if registry.has(experiment_id) else 1)` (same rule as `arp signals evaluate`); baselines are `{"price_momentum": momentum_panel(prices), **inp.panels}`; registers with `notes=result.notes`.
  - Built-in methods: `panel` (`params: {"name": str}`, returns `inp.panels[name]`, `ValueError` naming the missing panel) and `price_momentum` (`params: {"formation_period_months": 12, "skip_month": True}`, wraps `momentum_panel`; `model=None`).
  - `checks.py`: `lookahead_violations(spec: dict, inp: MethodInput, *, at: list[int] | None = None) -> list[tuple[str, int]]`: for each `k` in `at` (default: every index from 2 on), truncate texts with event time after `month_end_time(period_ends[k])`, truncate prices and panels to indices `<= k`, run the method, and return `(issuer, index)` for every value at index `<= k` that differs from the full run (`None` equals `None`; floats compared with `math.isclose`).

- [ ] **Step 1: Write the failing tests**
  - `test_text_buckets_follow_month_ends`: an item at `2020-01-31T23:59:59Z` is in bucket 0 of a `2020-01-31, 2020-02-29` grid, one at `2020-02-01T00:00:00Z` in bucket 1; an item before the grid's first calendar month is ignored; an unlinked item is skipped.
  - `test_unknown_method_lists_known_names`; `test_panel_method_missing_name_raises`.
  - `test_lookahead_violations_catches_a_peeking_method`: a test-registered method that gives month `i` the value of the price return at `i + 1` returns violations; `price_momentum` returns none (Review Focus 1).
  - `test_run_recipe_registers_and_counts_trials` (uses `pg`/the run store as in `tests/test_signal_lab_registry.py`): running the same recipe twice adds one experiment and one trial; a method returning a panel on a different grid raises `ValueError`.
  - `test_register_stores_notes_and_old_rows_still_load`: `notes` round-trips; an experiment row written without `notes` loads with `{}`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_signal_methods_base.py tests/test_signal_lab_registry.py -v`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the modules above.
- [ ] **Step 4: Run** both test files and `ruff check .`. Expected: PASS (existing registry tests unchanged).
- [ ] **Step 5: Commit** `feat(signal-lab): method interface, run_recipe and look-ahead check`.

---

### Task 2: Transforms and composite

**Files:**
- Create: `backend/arp/signal_lab/methods/transforms.py`
- Test: `backend/tests/test_signal_methods_transforms.py`

**Interfaces:**
- Consumes: Task 1 (`register_method`, `run_method`, `MethodInput`, `MethodResult`).
- Produces: `apply_step(panel: CharacteristicPanel, step: dict) -> CharacteristicPanel` with `step["op"]` one of `change` (`lag`, default 1: `x_i - x_{i-lag}`), `decay` (`half_life_months`: weighted mean of the available `x_{i-k}` with weight `0.5 ** (k / half_life)`; `None` if `x_i` is `None`), `zscore` and `rank` (cross-sectional per month; `None` for a month with fewer than 3 names or zero spread; rank is the average-rank percentile in `(0, 1]`), `mean_last` (`months`: mean of the last `months` values, `None` unless all are present). Unknown op raises `ValueError`. Registered methods: `transform` (`params: {"base": spec, "steps": [step, ...]}`; `model` is the base's) and `composite` (`params: {"components": [spec, ...], "weights": [float, ...] | None, "min_components": int | None}`; each component is rank-transformed per month, the value is the weighted mean over the available components; `None` unless at least `min_components` (default: all) are present; if the components have more than one distinct non-`None` model, raise `ValueError("composite of different models is not supported: ...")` because the evidence split applies one cutoff).

- [ ] **Step 1: Write the failing tests**
  - Hand-computed values for each op on a 3-name by 4-month panel: `change` first `lag` months `None`; `decay` with half-life 1 on `[1, 2, 4]` gives `(4 + 2*0.5 + 1*0.25) / 1.75`; `zscore` has mean 0; `rank` of `[10, 20, 30]` is `[1/3, 2/3, 1]`.
  - `test_composite_is_none_when_a_component_is_missing` and `test_composite_min_components_relaxes_it` (Review Focus 3).
  - `test_composite_of_two_models_raises`; `test_transform_keeps_the_base_model`.
  - `test_transforms_and_composite_have_no_lookahead` (Review Focus 1): `lookahead_violations` is empty for a `transform` over `price_momentum` and for a `composite` of two `panel` components.
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): transform and composite methods`.

---

### Task 3: Narrative attention

**Files:**
- Create: `backend/arp/signal_lab/methods/attention.py`
- Test: `backend/tests/test_signal_methods_attention.py`

**Interfaces:**
- Consumes: Task 1 (`text_buckets`).
- Produces: method `narrative_attention`, `params: {"terms": list[str], "mode": "intensity" | "change", "lookback_months": 12}`. Intensity at `i`: number of the issuer's bucket-`i` items whose title or body contains any term (case-insensitive, whole word or phrase). `change`: intensity at `i` minus the mean intensity over the previous `lookback_months` months; `None` with fewer than 3 prior months. An issuer with no items at all in the window `[i - lookback_months, i]` is `None` (no coverage cannot be told from no data); otherwise zero matches is `0.0`. `model=None`. Empty `terms` raises `ValueError`.

- [ ] **Step 1: Write the failing tests:** intensity counts exactly the matching items per month; a phrase term matches as a phrase and `AI` does not match inside "sustain"; `change` equals intensity minus the trailing mean (hand-computed); an issuer with no items in the window is `None` while one with items but no matches is `0.0` (Review Focus 3); `lookahead_violations` is empty (Review Focus 1).
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): narrative attention method`.

---

### Task 4: Learned lexicon (SESTM-style, walk-forward)

**Files:**
- Create: `backend/arp/signal_lab/methods/lexicon.py`
- Test: `backend/tests/test_signal_methods_lexicon.py`

**Interfaces:**
- Consumes: Task 1 (`text_buckets`, `trainable_months`).
- Produces: method `learned_lexicon`, `params: {"min_docs": 20, "kappa": 0.05, "min_train_months": 24}`. A simplified screening version of Ke, Kelly and Xiu, not the full model. At formation `i`: build training documents from months `trainable_months(i)`, each labelled `1` if its issuer's return at `j + 1` is above that month's cross-sectional median, else `0`; tokens are lower-case alphabetic words of at least 3 letters; for each word seen in at least `min_docs` training documents, `tilt = P(label 1 | word in doc) - overall P(label 1)`; keep words with `abs(tilt) > kappa`. A document's score is the mean tilt of its kept words (`None` if it has none); a cell is the mean over the issuer's bucket-`i` documents. `None` before `min_train_months`. `model=None` (fitted only on the past, no pretrained model, no licensed dictionary). Add a comment: `shortcut: word screening only, no mixture model, upgrade if it ranks well`.

- [ ] **Step 1: Write the failing tests** (synthetic corpus where "growth" appears only before positive returns and "recall" before negative):
  - `test_learned_lexicon_scores_known_words_correctly`: after enough months, a new "growth" document scores above a "recall" document.
  - `test_first_min_train_months_are_none` (Review Focus 2).
  - `test_labels_not_yet_realised_are_never_used` (Review Focus 2): replacing every return at indices `> i` with garbage leaves the score at `i` unchanged (`lookahead_violations` is empty).
  - `test_rare_words_are_dropped` (below `min_docs`).
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): walk-forward learned lexicon method`.

---

### Task 5: Embeddings with a ridge head (walk-forward)

**Files:**
- Create: `backend/arp/signal_lab/methods/embedding.py`
- Test: `backend/tests/test_signal_methods_embedding.py`

**Interfaces:**
- Consumes: Task 1; `fastembed` (existing dependency) for the default embedder only.
- Produces: an embedder is any object with `name: str` and `embed(texts: list[str]) -> numpy.ndarray` (rows L2-normalised). `default_embedder(model_name: str = "BAAI/bge-small-en-v1.5")` wraps `fastembed.TextEmbedding` (imported inside). Method `embedding_ridge`, `params: {"alpha": 10.0, "min_train_months": 24}`, `resources["embedder"]` required (`ValueError("pass an embedder in resources['embedder']")`). Per issuer and month the feature is the mean of the bucket's item embeddings; the label for training month `j` is the cross-sectional percentile rank of the return at `j + 1`; the head is ridge regression solved in closed form with numpy on rows from `trainable_months(i)`; the prediction at `i` is the score. `model` is `embedder.name`. Texts are embedded once per call and cached by `item_id`.

- [ ] **Step 1: Write the failing tests** (fake embedder: a deterministic hashing embedder; synthetic returns driven by one embedding direction):
  - `test_ridge_recovers_a_planted_signal`: rank IC of the output over the later months is clearly positive.
  - `test_first_min_train_months_are_none_and_no_lookahead` (Review Focus 1, 2): `lookahead_violations` empty.
  - `test_missing_embedder_raises_value_error` (Review Focus 4); `test_result_model_is_the_embedder_name`; `test_embeds_each_item_once`.
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): embedding ridge method`.

---

### Task 6: Topic attention with BERTopic (walk-forward refits)

**Files:**
- Create: `backend/arp/signal_lab/methods/topics.py`
- Modify: `backend/pyproject.toml` (optional extra `topics = ["bertopic>=0.16,<1.0"]`; its UMAP, HDBSCAN and scikit-learn dependencies are the same ones the `emerging_themes` extra already uses)
- Test: `backend/tests/test_signal_methods_topics.py`

**Interfaces:**
- Consumes: Task 1 (`text_buckets`, `register_method`); Task 5's embedder interface (`name`, `embed`); BERTopic (MIT, adopted in the spec).
- Produces: a topic model factory is any callable `() -> model` where the model has `fit(docs: list[str], embeddings: numpy.ndarray)`, `transform(docs: list[str], embeddings: numpy.ndarray) -> (topics: list[int], probs)` and `find_topics(query: str, top_n: int) -> (topic_ids: list[int], similarities: list[float])` (the BERTopic methods of those names). `default_topic_model(seed: int = 42, min_topic_size: int = 10)` returns a factory building `BERTopic` with a fixed-seed UMAP (imported inside; `ValueError("topic attention needs the topics extra: pip install 'arp[topics]'")` if missing). Method `topic_attention`, `params: {"query": str, "top_n": 1, "min_similarity": 0.3, "refit_months": 12, "min_train_months": 12, "mode": "intensity" | "share" | "change", "lookback_months": 12}`, `resources["embedder"]` and `resources["topic_model"]` required.
  - **Refit schedule (point in time):** refit grid months are `r = min_train_months - 1, + refit_months, ...`. The model for refit `r` is fitted only on items in buckets `<= r` (text already published by `month_end_time(period_ends[r])`). Months before the first refit are `None`.
  - **Assignment:** items in month `m` are assigned with the model of the latest refit `r <= m`. The target topics are `find_topics(query, top_n)` on that model, keeping those with similarity `>= min_similarity`; no topic over the threshold makes that refit's months `None` and is counted in `notes["refits_without_topic"]`.
  - **Values:** `intensity` is the number of the issuer's month-`m` items in a target topic; `share` divides by the issuer's month-`m` item count; `change` is intensity minus the mean over the previous `lookback_months` months (`None` with fewer than 3). An issuer with no items in the window is `None`, not 0.
  - `model` is `embedder.name` (its cutoff decides the contamination split). `notes` carries, per refit, the matched topic ids, their similarities and their top words, so a reader can see what "the topic" meant at each refit.

- [ ] **Step 1: Write the failing tests** (a fake topic model factory that assigns topics by a keyword and records the documents it was fitted on; the fake hashing embedder from Task 5):
  - `test_each_refit_sees_only_published_text` (Review Focus 2): the fake records every fit; no fitted document has an event time after its refit month end.
  - `test_months_use_the_latest_earlier_refit`: an item in month `r + 1` is assigned with the model fitted at `r`, not one fitted later.
  - `test_intensity_share_and_change_values` (hand-computed); `test_issuer_with_no_items_is_none_not_zero` (Review Focus 3).
  - `test_no_topic_over_threshold_gives_none_and_is_counted`.
  - `test_missing_embedder_or_topic_model_raises_value_error` (Review Focus 4); `test_missing_topics_extra_raises_the_documented_error` (monkeypatch the import to fail).
  - `test_topic_attention_has_no_lookahead` (Review Focus 1): `lookahead_violations` is empty with the fake factory.
  - `test_real_bertopic_smoke` marked `pytest.importorskip("bertopic")`: a 200-document synthetic corpus with two vocabularies gives a non-empty `intensity` panel.
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS (the smoke test is skipped where `bertopic` is not installed).
- [ ] **Step 5: Commit** `feat(signal-lab): BERTopic topic attention method`.

---

### Task 7: Grounded LLM scoring, cost estimate, rerun stability

**Files:**
- Create: `backend/arp/signal_lab/methods/llm_scoring.py`
- Test: `backend/tests/test_signal_methods_llm_scoring.py`

**Interfaces:**
- Consumes: Task 1; `build_sentiment_panel` and `SentimentScoreRecord` (`arp/replication/sentiment_scoring.py`); `SourceDocument`; `LLMClient`, `LLMUsage`.
- Produces: method `grounded_llm`, `params: {"stability_runs": 0}`, `resources["llm"]` required. Converts each bucketed `TextRecord` to a `SourceDocument` (`doc_id=item_id`, `published_at=event_time`, `full_text=title + "\n\n" + body`), calls the existing `build_sentiment_panel` unchanged (so the verbatim-quote rule and per-cell averaging hold), runs the coroutine with `asyncio.run` (in a worker thread if a loop is already running, so notebooks work; comment `shortcut: one thread per call, fine for a research session`), and returns `model` from the first `LLMUsage.model`; if the usages name more than one model, raise `ValueError`. `notes` carries `{"calls": n, "ungrounded": m}` plus `rerun_stability` when `stability_runs > 0`. `estimate_llm_calls(inp: MethodInput) -> dict` returns `{"calls": int, "approx_input_tokens": int}` (one call per bucketed item; characters divided by 4; an upper bound because the client cache may serve some). `rerun_stability(score_once: Callable[[], tuple[list[float], list[LLMUsage]]], runs: int) -> float`: mean pairwise Spearman correlation of the score vectors across `runs` runs; raises `ValueError` if any usage has `cached=True` ("cached answers make stability meaningless; pass a client with the cache off").

- [ ] **Step 1: Write the failing tests** (a fake `LLMClient` returning scripted `SentimentScoreDraft`-shaped outputs, as in the existing sentiment tests; read them first):
  - `test_ungrounded_quote_is_excluded_and_counted`.
  - `test_cell_is_the_mean_of_grounded_scores`; `test_missing_llm_raises_value_error` (Review Focus 4).
  - `test_estimate_counts_items_and_tokens`.
  - `test_rerun_stability_is_one_for_identical_runs_and_lower_for_noisy_ones`; `test_rerun_stability_refuses_cached_answers` (Review Focus 5).
  - `test_works_inside_a_running_event_loop` (run the method from an `async def` test).
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): grounded LLM scoring method with cost estimate and rerun stability`.

---

### Task 8: FinBERT scoring

**Files:**
- Create: `backend/arp/signal_lab/methods/finbert.py`
- Modify: `backend/pyproject.toml` (optional extra `finbert = ["transformers>=4.40,<6.0", "torch>=2.2,<3.0"]`)
- Test: `backend/tests/test_signal_methods_finbert.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: a FinBERT scorer is any object with `name: str` and `score(texts: list[str]) -> list[tuple[float, float, float]]` (positive, negative, neutral probabilities). `default_finbert(model_name: str = "ProsusAI/finbert")` loads the Hugging Face pipeline lazily and raises `ValueError("FinBERT needs the finbert extra: pip install 'arp[finbert]'")` if the import fails. Method `finbert`, `resources["finbert"]` required. A document's score is `P(positive) - P(negative)` on `title + "\n\n" + body` truncated by the model's token limit (comment: first 512 tokens only); a cell is the equal-weight mean over the bucket; `model` is the scorer's name; `notes["truncated"]` counts documents cut. Owner decision 2026-10-16 approves FinBERT for internal use (licence CC BY-NC-SA 4.0: no output or model derived from it is sold or distributed). No cutoff entry is added here: the owner owns cutoff dates, so until one is recorded the evaluation treats every period as contaminated and the signal cannot graduate.

- [ ] **Step 1: Write the failing tests** (fake scorer): the score equals the positive minus negative probability, cell mean over two documents; `None` for an issuer with no documents (Review Focus 3); missing scorer raises `ValueError` (Review Focus 4); `default_finbert` without `transformers` raises the `ValueError` above (monkeypatch the import to fail); `lookahead_violations` empty.
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): FinBERT scoring method`.

---

### Task 9: Issuer-first search scoring (interface only)

**Files:**
- Create: `backend/arp/signal_lab/methods/issuer_first.py`
- Test: `backend/tests/test_signal_methods_issuer_first.py`

**Interfaces:**
- Consumes: Task 1; the scoring function from Task 7 (`score_hits`, extracted there if not already a named function; a hit is turned into a `SourceDocument` the same way).
- Produces: `@dataclass SearchHit(url: str, title: str, text: str, published_at: str | None)`; `class SearchTool(Protocol)` with `search(self, query: str, *, before: str) -> list[SearchHit]`. Method `issuer_first`, `params: {"peer_group": str | None}`, `resources["search"]` and `resources["llm"]` required. Quarterly: only grid months that are calendar quarter ends are scored, other months `None`. For each issuer and such month `d`: query `"{issuer} {quarter} results"` with `before=month_end_time(d)`; our own hard filter drops every hit whose `published_at` is missing or after `month_end_time(d)`; if the tool returned any such hit it counts as a leak, the query is repeated once with `before` one day earlier, and a cell that still leaked is counted in the residual rate; surviving hits are scored with Task 7's grounded scorer. `notes`: `{"leak_rate_first_try": float, "leak_rate_after_retry": float, "cells": int}`. No search tool is shipped; with none in `resources` the method raises `ValueError("no search tool configured; the issuer-first variant is interface-only until the owner allows one")`.

- [ ] **Step 1: Write the failing tests** (fake `SearchTool` that sometimes returns a hit dated after `before`; fake LLM):
  - `test_hit_after_the_cutoff_never_reaches_the_scorer` (the hard filter, even when the tool ignores `before`).
  - `test_leak_triggers_one_retry_and_rates_are_reported` (Review Focus 5): first-try rate 1/3, after-retry rate hand-computed.
  - `test_missing_published_at_is_dropped`; `test_non_quarter_months_are_none`; `test_no_search_tool_raises_the_documented_error` (Review Focus 4).
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement.** **Step 4: Run tests and ruff.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(signal-lab): issuer-first search scoring interface`.

---

### Task 10: `arp signals run` and docs

**Files:**
- Modify: `backend/arp/cli/signal_lab.py`, `docs/TECHNICAL_REFERENCE.md` (the `arp signals` entry)
- Test: `backend/tests/test_signal_lab_cli_run.py` (uses `pg`; read `tests/test_signal_lab_cli.py` and `tests/test_signal_lab_cli_text.py` for the setup and synthetic CSV helpers)

**Interfaces:**
- Consumes: Tasks 1 to 9; `TextStore`; the price CSV helpers.
- Produces: `arp signals run --recipe r.json --prices p.csv [--panel NAME=PATH.csv ...] [--known-by ISO] [--confirm-above 200] [--yes] [--out report.json]`. `r.json` holds the `Recipe` fields (`method` is a registered method name; `params` as that method takes). The command loads text from the store (`items(known_by=...)`), builds `MethodInput` (panels from `--panel`, which are plan 2's `build-panel` outputs), builds resources only for the chosen method (`grounded_llm` and `issuer_first`: the repo LLM client from settings; `embedding_ridge`: `default_embedder()`; `topic_attention`: `default_embedder()` and `default_topic_model`; `finbert`: `default_finbert()`; `issuer_first`: no search tool, so it exits 1 with the documented message), computes `data_version` as a hash of the item ids, the price file and the panel files, prints for `grounded_llm` the estimate and exits 1 unless `--yes` when `calls > --confirm-above`, then calls `run_recipe` and prints what `arp signals evaluate` prints plus any `notes`. A recipe window beyond the price file, an unknown method and every library `ValueError` exit 1 with the message on stderr and no traceback; any other exception prints `Run failed: <Type>: <msg>` and exits 1 (it may carry LLM or network detail, never print locals).

- [ ] **Step 1: Write the failing tests:**
  - `test_run_price_momentum_registers_an_experiment_and_prints_windows`.
  - `test_run_twice_registers_once` (trial count does not grow).
  - `test_run_narrative_attention_from_the_store`: ingest a small transcript CSV with `ingest-transcripts`, then `run` a `narrative_attention` recipe; exit 0.
  - `test_run_unknown_method_exits_1_and_lists_names`; `test_run_issuer_first_without_a_tool_exits_1_with_the_documented_message`.
  - `test_run_grounded_llm_over_the_threshold_needs_yes`: monkeypatch the LLM factory to a fake; with `--confirm-above 1` and no `--yes` it exits 1 printing the estimate and makes no LLM call.
  - `test_run_failure_prints_no_traceback` (monkeypatch a method to raise `RuntimeError`).
- [ ] **Step 2: Run** and confirm FAIL. **Step 3: Implement** `run` and add the command with a one-line description (and the registered method names) to the `arp signals` entry in `docs/TECHNICAL_REFERENCE.md`; state there that price CSVs must use calendar month-end dates.
- [ ] **Step 4: Run** the new tests, then `python3 -m pytest tests -q -k "signal_lab or signal_methods or news or replication"`, `ruff check .`, and `python3 -c "import arp.cli"`. Expected: PASS (one known browser-dependent reporting test and one known flaky extraction test may fail; both unrelated).
- [ ] **Step 5: Commit** `feat(signal-lab): arp signals run`.

---

## Self-review

- **Spec coverage:** methods listed in Goals 2: grounded LLM scoring (Task 7), issuer-first search (Task 9, interface only), embeddings with a supervised head (Task 5), topic and attention (Task 3 term-based, Task 6 BERTopic), learned lexicon (Task 4), statistical transforms and composites (Task 2); FinBERT per the 2026-10-16 decision (Task 8). Guardrails: truncation check and walk-forward rule (Tasks 1 to 6), leakage rate and retry (Task 9), rerun stability (Task 7), trial counting and registration (Task 1), contaminated unknown models (Global Constraints, Tasks 5 to 8). Left out on purpose: see the roadmap note.
- **Step scan:** every step names a signature, test or command; no function bodies.
- **Type consistency:** `MethodInput`, `MethodResult`, `run_method`, `text_buckets`, `trainable_months`, `lookahead_violations`, `score_hits`, the embedder interface are defined once (Tasks 1, 5, 7) and reused with the same names.
- **Proportion:** similar in length to plans 1 and 2.
- **Owner flags:** the simplified lexicon is a screening version of SESTM, not the paper's full model; composites refuse mixed models; FinBERT stays contaminated until a cutoff date is recorded; issuer-first needs an allowed search tool; BERTopic topic labels change at each refit, so a recipe names its topic by seed words, not by topic number.
