# Shared Model Layer (A1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One package, `backend/arp/models/`, through which every ARP function calls non-LLM models (`embed`, `rerank`, `classify`, `spans`, `tag`), cloud-first with local fallback, cached, from a pinned registry, returning provenance.

**Architecture:** A registry file pins every model; a small cache keys results by model, revision, text hash and labels; each capability tries the existing `arp-models` Cloud Run service through `arp/compute/client.py` and falls back to a lazily loaded local model. `embed`/`rerank` keep today's behaviour exactly: their loaders move from `arp/retrieval/` into `arp/models/`, and `retrieval/*` calls the layer.

**Tech Stack:** Python 3.11, fastembed (embed, rerank, existing), transformers + torch (NLI, `tag`), gliner (spans), FastAPI (`compute/server.py`), httpx MockTransport and FastAPI TestClient in tests.

**Spec:** `docs/superpowers/specs/2026-11-01-model-stack-design.md` (approved 2026-11-01).

## Global Constraints

- Every public capability returns a tuple `(results, provenance)`, provenance = `{"model": key, "revision": ..., "where": "cloud"|"local"}`.
- Registry: `backend/arp/models/registry.json`, entries `{key, capability, hf_id, revision, labels?}`. Allow-list: `backend/arp/models/allowed.txt`.
- A registry `hf_id` not in `allowed.txt` raises `ValueError` (message contains the `hf_id`) at load, for every capability.
- An unknown registry key raises `KeyError` (message contains the key).
- Cloud: `/classify`, `/spans`, `/tag` on `arp-models` take header `x-arp-model: <hf_id>@<revision>` and answer HTTP 409 on mismatch.
- Cloud failure → local, with the existing `COOLDOWN_S` (600 s) cooldown in `compute/client.py`.
- Cache key `(registry key, revision, sha256(text), labels)`, stored under `settings.cache_dir / "models"`.
- Defaults: `nli` = `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`; `gliner` = `urchade/gliner_multi-v2.1`; `classify` hypothesis default `"This text is about {}."`; `spans` threshold default 0.5.
- New dependencies: `transformers`, `torch` (already in the `finbert` extra) and `gliner` in a new `models` extra in `backend/pyproject.toml`; the same packages in the `arp-models` image.
- `embed` and `rerank` results must be numerically unchanged (`allclose`, atol 1e-6).
- After this change, `grep -rnE "from_pretrained|TextEmbedding\(|GLiNER\(|transformers\.pipeline\(|pipeline\(\"" backend/arp --include=*.py` hits only `backend/arp/models/` and `backend/arp/compute/server.py`.

## Review Focus

1. **Empty input** (`classify([], …)`, `spans([], …)`, `embed([])`): expect an empty results list and valid provenance, no model load. → test in Task 3, Task 4.
2. **Duplicate texts in one call**: expect one result per input position (cache must not collapse positions). → test in Task 2.
3. **`labels` order changes the cache key**: `classify(t, ["a","b"])` and `classify(t, ["b","a"])` must both return scores keyed by label name, correct per label. → test in Task 3.
4. **Text longer than the model limit**: truncated, no exception. → test in Task 3 (stand-in records `truncation=True`).
5. **`signal_lab` embedding model** (`arp/signal_lab/methods/embedding.py` calls `TextEmbedding` with any model name): would break the grep rule. Route it through `arp.models.local.text_embedding(model_name)` with no behaviour change. → test in Task 5.

---

### Task 1: Registry, allow-list and provenance

**Files:**
- Create: `backend/arp/models/__init__.py`, `backend/arp/models/registry.py`, `backend/arp/models/registry.json`, `backend/arp/models/allowed.txt`
- Test: `backend/tests/models/test_registry.py` (+ `backend/tests/models/__init__.py`)

**Interfaces:**
- Produces: `RegistryEntry` (pydantic: `key: str, capability: Literal["embed","rerank","classify","spans","tag"], hf_id: str, revision: str, labels: list[str] | None = None`); `entry(key: str) -> RegistryEntry` (raises `KeyError`, `ValueError` per constraints); `provenance(e: RegistryEntry, where: Literal["cloud","local"]) -> dict`; `model_header(e) -> str` returning `f"{e.hf_id}@{e.revision}"`.
- `registry.json` initial keys: `embed` (current `EMBED_MODEL_NAME`), `rerank` (current `RERANK_MODEL_NAME`), `nli`, `gliner`, `climate_detector`, `climate_commitment`, `climate_specificity`, `finbert_fls`, `esg_topics`; revisions pinned to the Hugging Face commit hashes at implementation time.

- [ ] **Step 1: Write failing tests**

```python
def test_unknown_key_raises_keyerror():  # spec AC-7
    with pytest.raises(KeyError, match="not_in_registry"):
        registry.entry("not_in_registry")

def test_hf_id_not_allowed_raises(tmp_registry):  # spec AC-8
    tmp_registry.write({"key": "nli", "capability": "classify", "hf_id": "evil/model", "revision": "abc"})
    with pytest.raises(ValueError, match="evil/model"):
        registry.entry("nli")

def test_provenance_shape():
    e = registry.entry("nli")
    assert registry.provenance(e, "local") == {"model": "nli", "revision": e.revision, "where": "local"}
```
(`tmp_registry` fixture: monkeypatch `registry.REGISTRY_PATH` and `registry.ALLOWED_PATH` to tmp files.)

- [ ] **Step 2: Run** `cd backend && python3 -m pytest tests/models/test_registry.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `registry.py` (load JSON once per process via `functools.cache` on the path; check allow-list on every `entry()` call).
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `feat(models): registry, allow-list and provenance`.

### Task 2: Result cache

**Files:**
- Create: `backend/arp/models/cache.py`
- Test: `backend/tests/models/test_cache.py`

**Interfaces:**
- Consumes: `RegistryEntry` (Task 1).
- Produces: `cached(e: RegistryEntry, texts: list[str], labels: tuple[str, ...] | None, compute: Callable[[list[str]], list[Any]]) -> list[Any]` — calls `compute` only for texts without a cache hit, in input order, writes JSON files under `get_settings().cache_dir / "models" / e.key / e.revision / <sha256>.json`; result list aligned with `texts`.

- [ ] **Step 1: Write failing tests**

```python
def test_second_call_hits_cache(tmp_settings):  # spec AC-12, AC-13
    calls = []
    f = lambda ts: (calls.append(list(ts)), [len(t) for t in ts])[1]
    a = cache.cached(entry_nli, ["x", "yy"], ("l",), f)
    b = cache.cached(entry_nli, ["x", "yy"], ("l",), f)
    assert calls == [["x", "yy"]] and a == b == [1, 2]

def test_duplicates_keep_positions(tmp_settings):  # Review Focus 2
    assert cache.cached(entry_nli, ["x", "x", "z"], None, lambda ts: [t.upper() for t in ts]) == ["X", "X", "Z"]

def test_labels_are_part_of_key(tmp_settings):
    n = []
    f = lambda ts: (n.append(1), [0] * len(ts))[1]
    cache.cached(entry_nli, ["x"], ("a",), f); cache.cached(entry_nli, ["x"], ("b",), f)
    assert len(n) == 2
```

- [ ] **Step 2: Run** `python3 -m pytest tests/models/test_cache.py -v` → FAIL.
- [ ] **Step 3: Implement** `cached` (key = sha256 of `json.dumps([e.key, e.revision, text, list(labels or [])])`; write files atomically with `arp.storage.atomic_io.atomic_write_text`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(models): result cache`.

### Task 3: `classify` and `tag` (NLI and fine-tuned classifiers)

**Files:**
- Create: `backend/arp/models/local.py` (all local loaders), `backend/arp/models/capabilities.py`
- Modify: `backend/arp/compute/client.py` (add `classify_scores`, `spans_result`, `tag_result`), `backend/arp/compute/server.py` (add `/classify`, `/tag`), `backend/pyproject.toml` (new `models` extra)
- Test: `backend/tests/models/test_classify.py`, `backend/tests/test_compute_server.py` (new tests only)

**Interfaces:**
- Consumes: Tasks 1–2; `compute.client._models_call(path, payload, model, read)`.
- Produces:
  - `classify(texts: list[str], labels: list[str], hypothesis: str = "This text is about {}.") -> tuple[list[dict[str, float]], dict]` in `arp/models/__init__.py` (re-exported from `capabilities.py`).
  - `tag(model_key: str, texts: list[str]) -> tuple[list[dict], dict]`, each result `{"label": str, "score": float}`.
  - `local.nli_scores(e, texts, labels, hypothesis) -> list[dict[str, float]]` (transformers zero-shot pipeline, `truncation=True`), `local.tag_scores(e, texts) -> list[dict]`.
  - `compute.client.classify_scores(texts, labels, hypothesis, model_header) -> list[dict] | None`, `compute.client.tag_result(key, texts, model_header) -> list[dict] | None`.
  - Server: `POST /classify {texts, labels, hypothesis}` → `{"scores": [{label: score}]}`; `POST /tag {key, texts}` → `{"results": [{label, score}]}`; both `_check_model(x_arp_model, model_header(entry))`.

- [ ] **Step 1: Write failing tests**

```python
def test_classify_local_keys_and_where(no_cloud, stand_in_nli):  # spec AC-1
    res, prov = models.classify(["a"], ["x", "y"])
    assert set(res[0]) == {"x", "y"} and prov["where"] == "local"

def test_classify_cloud(cloud_returns({"scores": [{"x": 0.9, "y": 0.1}]})):  # spec AC-2
    res, prov = models.classify(["a"], ["x", "y"])
    assert res == [{"x": 0.9, "y": 0.1}] and prov["where"] == "cloud"

def test_cloud_500_falls_back_and_cools(cloud_500, stand_in_nli):  # spec AC-3, AC-4
    models.classify(["a"], ["x"]); _, prov = models.classify(["b"], ["x"])
    assert cloud_500.requests == 1 and prov["where"] == "local"

def test_empty_input(no_cloud, stand_in_nli):  # Review Focus 1
    assert models.classify([], ["x"])[0] == [] and stand_in_nli.loads == 0

def test_label_order_irrelevant(no_cloud, stand_in_nli):  # Review Focus 3
    assert models.classify(["a"], ["x", "y"])[0][0]["x"] == models.classify(["a"], ["y", "x"])[0][0]["x"]

def test_truncation_requested(no_cloud, stand_in_nli):  # Review Focus 4
    models.classify(["w " * 5000], ["x"]); assert stand_in_nli.kwargs["truncation"] is True

def test_tag_unknown_key():  # spec AC-7
    with pytest.raises(KeyError): models.tag("not_in_registry", ["a"])

def test_provenance_revision(no_cloud, stand_in_nli):  # spec AC-14
    _, prov = models.classify(["a"], ["x"])
    assert set(prov) == {"model", "revision", "where"} and prov["revision"] == registry.entry("nli").revision
```
Server (in `tests/test_compute_server.py`): `test_classify_model_mismatch_409` and `test_tag_model_mismatch_409` — POST with `x-arp-model: wrong` → `status_code == 409` (spec AC-9, AC-11).

- [ ] **Step 2: Run** `python3 -m pytest tests/models/test_classify.py tests/test_compute_server.py -v` → new tests FAIL.
- [ ] **Step 3: Implement** loaders in `local.py` (lazy, one instance per registry key, guarded by a lock), the client functions via `_models_call`, the server endpoints (load with `cuda=True`/`device=0`, `_require_cuda` equivalent for torch: 503 if `not torch.cuda.is_available()`), and `classify`/`tag` = cache → cloud if `models_configured()` and not cooling → local.
- [ ] **Step 4: Run** → PASS; also `ruff check .`.
- [ ] **Step 5: Commit** `feat(models): classify and tag, cloud and local`.

### Task 4: `spans` (GLiNER)

**Files:**
- Modify: `backend/arp/models/local.py`, `backend/arp/models/capabilities.py`, `backend/arp/compute/client.py`, `backend/arp/compute/server.py`
- Test: `backend/tests/models/test_spans.py`, `backend/tests/test_compute_server.py` (new test only)

**Interfaces:**
- Produces: `spans(texts: list[str], labels: list[str], threshold: float = 0.5) -> tuple[list[list[dict]], dict]`, each span `{"label", "text", "start", "end", "score"}`; server `POST /spans {texts, labels, threshold}` → `{"spans": [[...]]}`.

- [ ] **Step 1: Write failing tests**

```python
def test_span_returned(cloud_returns({"spans": [[{"label": "risk", "text": "credit risk", "start": 14, "end": 25, "score": 0.9}]]})):  # spec AC-5
    res, _ = models.spans(["We reduce the credit risk"], ["risk"])
    assert res == [[{"label": "risk", "text": "credit risk", "start": 14, "end": 25, "score": 0.9}]]

def test_span_with_wrong_offsets_dropped(cloud_returns({"spans": [[{"label": "risk", "text": "credit risk", "start": 15, "end": 26, "score": 0.9}]]})):  # spec AC-6
    assert models.spans(["We reduce the credit risk"], ["risk"])[0] == [[]]

def test_spans_empty_input(no_cloud):  # Review Focus 1
    assert models.spans([], ["risk"])[0] == []
```
Server: `test_spans_model_mismatch_409` (spec AC-10).

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: after cloud or local, keep a span only if `text[start:end] == span["text"]` (applies to both paths).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(models): spans`.

### Task 5: Move `embed` and `rerank` behind the layer

**Files:**
- Modify: `backend/arp/models/local.py` (add `text_embedding(model_name)`, `cross_encoder(model_name)`), `backend/arp/models/capabilities.py` (`embed`, `rerank`), `backend/arp/retrieval/embeddings.py`, `backend/arp/retrieval/rerank.py`, `backend/arp/signal_lab/methods/embedding.py`
- Create: `backend/tests/models/fixtures/main_vectors.npz` (generated on `main` before any change, with the stand-in models used in the test)
- Test: `backend/tests/models/test_embed_rerank.py`

**Interfaces:**
- Produces: `embed(texts: list[str]) -> tuple[np.ndarray, dict]`, `rerank(query: str, texts: list[str]) -> tuple[list[float], dict]`; `local.text_embedding(model_name: str)` returns a fastembed `TextEmbedding`, cached per name.
- `retrieval.embeddings.embed_texts` and `retrieval.rerank.rerank` keep their signatures and return values; they now call `models.embed` / `models.rerank` and drop the provenance.

- [ ] **Step 1: Generate the fixture on `main`**: write `backend/tests/models/make_main_fixture.py` (stand-in `TextEmbedding` and cross-encoder returning deterministic values; saves `texts`, `query`, `vectors`, `scores`), run it on a checkout of `origin/main` (`git worktree add /tmp/main origin/main`), copy the `.npz` into this branch and commit it before changing any loader.
- [ ] **Step 2: Write failing tests**

```python
def test_embed_matches_main(stand_in_models):  # spec AC-15
    f = np.load(FIXTURE)
    vec, _ = models.embed(list(f["texts"]))
    assert np.allclose(vec, f["vectors"], atol=1e-6)

def test_rerank_matches_main(stand_in_models):  # spec AC-15
    f = np.load(FIXTURE)
    scores, _ = models.rerank(str(f["query"]), list(f["texts"]))
    assert np.allclose(scores, f["scores"], atol=1e-6)

def test_no_loaders_outside_models():  # spec AC-16, Review Focus 5
    out = subprocess.run(["grep", "-rnE", r'from_pretrained|TextEmbedding\(|GLiNER\(|transformers\.pipeline\(|pipeline\("', "arp", "--include=*.py"], capture_output=True, text=True, cwd=BACKEND).stdout
    assert all(l.startswith(("arp/models/", "arp/compute/server.py")) for l in out.splitlines())
```

- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement** the move. Keep `EMBED_MODEL_NAME`, `EMBED_DIM`, `RERANK_MODEL_NAME` importable from their current modules (other code imports them). Keep rerank's "warn once, keep order" fallback in `retrieval/rerank.py`.
- [ ] **Step 5: Run** `python3 -m pytest tests/models tests/test_compute_client.py tests/test_compute_server.py tests/test_compute_models.py -v` and the retrieval tests (`python3 -m pytest tests -k "retriev or rerank or embed or signal" -q`) → PASS.
- [ ] **Step 6: Commit** `refactor(models): embed and rerank through the shared layer`.

### Task 6: Regression gates and image

**Files:**
- Modify: `backend/Dockerfile.compute` (install the `models` extra), `.github/workflows/deploy-compute.yml` only if its path filter must include `backend/arp/models/**`
- Test: none new; runs existing suites.

- [ ] **Step 1: Run the full backend suite** on this branch and on `main` (`python3 -m pytest backend/tests -q --ignore=backend/tests/models -p no:randomly > /tmp/<branch>.txt`), compare pass/fail per test → identical (spec AC-17).
- [ ] **Step 2: Check** `git diff --name-only origin/main -- backend/tests ':!backend/tests/models' ':!backend/tests/test_compute_server.py'` prints nothing (spec AC-18; `test_compute_server.py` only gains new tests, list them in the PR).
- [ ] **Step 3: Record** `arp golden-set retrieval --out main.json` on `main`, put `recall_at_12` in the PR description, run the same on the branch → `recall_at_12` ≥ main − 0.01 (spec AC-19, golden; needs the real model).
- [ ] **Step 4: Commit** `build(compute): models extra in the arp-models image`.

## Self-review notes

- Spec coverage: AC-1…AC-19 map to Tasks 1–6 (AC-1/2 → T3, AC-3/4 → T3, AC-5/6 → T4, AC-7 → T1/T3, AC-8 → T1, AC-9/10/11 → T3/T4, AC-12/13 → T2, AC-14 → T1/T3, AC-15/16 → T5, AC-17/18/19 → T6).
- The signal-lab embedder change (Review Focus 5) is the one change outside the spec's listed files; it is required by AC-16 and keeps behaviour.
