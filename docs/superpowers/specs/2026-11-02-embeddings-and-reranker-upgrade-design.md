# Better embedding model and a fast reranker

Spec slug: `embeddings-and-reranker-upgrade`. Items #4 and #5 of the RAG improvement plan
(https://claude.ai/artifact/RnMhVmhQNmJPwY8UCaY38t). Earlier measurements: `docs/superpowers/plans/2026-10-13-retrieval-quality.md`.

## Why

1. **The top 5 is weak.** On the committed gold set (`backend/tests/golden/retrieval/cases.json`: 60 cases,
   33 on a German report, 27 on an English one) main has recall@5 **45.6%** and recall@12 **64.7%** (hybrid on,
   context headers on, rerank off). The embedder is `paraphrase-multilingual-MiniLM-L12-v2` (384-dim), which
   reads only the first 128 tokens of a ~3,500-character chunk.
2. **The reranker is never used.** `bge-reranker-v2-m3` exists (`arp/retrieval/rerank.py`) but is off: ~47 s
   per field on a CPU. The `arp-models` GPU service (`compute_models_url`, one L4) already serves it and has
   never been measured on the gold set.
3. **Stronger models are too slow on a CPU** (multilingual-e5-large: ~8 min for 300 chunks), so they only make
   sense on the GPU service.

## Goal

Make three embedders and three reranker modes selectable, serve the new ones from `arp-models`, and let
`arp golden-set retrieval` compare any combination in one command. Defaults stay exactly as today. Each new
option becomes a default later, by a one-line PR, only when the comparison shows **recall@12 ≥ 64.7% and
recall@5 ≥ 45.6%** on the gold set (switch-on rule, below).

Non-goals: changing chunking, BM25, RRF, `evidence_max_chunks` or `rerank_candidates`; a local CPU path for the
new models; a new CI workflow; Qwen3 or other embedders. Anti-goal: a run where one field's ranking mixes
vectors of two models, or where an outage of `arp-models` stops a run.

## Decisions (owner, 2026-11-02)

- New models run **only on the `arp-models` GPU service.** Without `compute_models_url` (or when it fails),
  retrieval behaves as on main.
- **All options are selectable**, by setting and on the CLI; which one becomes the default is decided later
  from the gold set.
- **No new CI job.** The comparison is a feature of `arp golden-set retrieval`; whoever has
  `compute_models_url` runs it and pastes the table into the switch-on PR.

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| A. One fixed pick (e5-large + existing GPU cross-encoder) | Smallest diff; no way to compare alternatives | Rejected by owner: wants all options |
| B. All candidates selectable on the GPU service, compared by the gold-set tool | More server code; decision is data-driven | **Chosen** |
| C. Local CPU support for the new models | Minutes per document on first embed, ~47 s/field rerank | Rejected: owner chose GPU only |

Excluded models: `jinaai/jina-colbert-v2`, `jina-reranker-v2`, `jina-embeddings-v3` are CC-BY-NC-4.0 (non-commercial).
The multilingual ColBERT used instead is `lightonai/mLateOn` (Apache-2.0, in the installed fastembed).

## What changes

### 1. Settings (`arp/config.py`)

| Setting | Values | Default |
|---|---|---|
| `embed_model` (`ARP_EMBED_MODEL`) | `minilm`, `e5-large`, `bge-m3` | `minilm` |
| `rerank_model` (`ARP_RERANK_MODEL`) | `cross-encoder`, `colbert` | `cross-encoder` |

`rerank_enabled` (default `False`) and `rerank_candidates` (40) stay as they are; `rerank_model` only says which
reranker runs when `rerank_enabled` is true. Any other value fails settings validation.

### 2. Models (`arp/models/registry.json`, `allowed.txt`)

| Key | Hugging Face id | Revision | Licence | Dim | Served by |
|---|---|---|---|---|---|
| `embed` (unchanged) | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `e8f8c21…` (as today) | Apache-2.0 | 384 | fastembed, local or GPU |
| `embed_e5_large` | `intfloat/multilingual-e5-large` | `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3` | MIT | 1024 | fastembed-gpu |
| `embed_bge_m3` | `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` | MIT | 1024 | `transformers` (dense: CLS token, L2-normalised); already a `[models]` dependency |
| `rerank` (unchanged) | `BAAI/bge-reranker-v2-m3` | as today | Apache-2.0 | – | fastembed-gpu cross-encoder |
| `rerank_colbert` | `lightonai/mLateOn` | `bbd883ae1fadb563056ff73b1061ae8172a3fcda` | Apache-2.0 | – | fastembed-gpu `LateInteractionTextEmbedding`, MaxSim score |

e5-large gets `query: ` before the query and `passage: ` before each chunk's index text (its model card's
format). bge-m3 and mLateOn get no prefix. Prefixes are applied where the text is sent, so the stored
index text and its hash key are unchanged.

### 3. `arp-models` service (`arp/compute/server.py`, `client.py`)

- `/embed` and `/rerank` accept any registry entry of the matching capability in `X-ARP-Model`
  (`hf_id@revision`), load it lazily on the GPU, and answer `409` for anything else (as today for a mismatch).
  All five models fit the L4's 24 GB together.
- `/embed` returns vectors of that model's dimension; the client checks the dimension against the registry.
- No new dependency in `Dockerfile.compute`.

### 4. Retrieval (`arp/retrieval/embeddings.py`, `rerank.py`, `select_evidence.py`)

- **Embedding fallback:** if `embed_model` is not `minilm` and `arp-models` is not configured, or any embed call
  for the field fails (no answer, an error status, or a vector whose length is not the registry dimension),
  that field's whole vector ranking (query and every chunk) uses MiniLM exactly as on main. Vectors of the
  requested model that did come back are still stored. A warning is logged once per process:
  `arp-models unavailable; embedding with MiniLM`.
- `chunk_embeddings.embed_model` holds the model's `hf_id` (as today for MiniLM), and `chunk_id` is the same
  key MiniLM uses for that chunk's index text (the prefix is not part of it).
- **Rerank fallback:** `rerank_model=colbert` with `arp-models` not configured or failing keeps retrieval order
  (no local model is loaded). `cross-encoder` keeps today's behaviour, including its local CPU path.
- The retrieval trace (`explain`, shown in the Walkthrough) gains `embed_model` and `rerank_model`: the registry
  key that actually ranked the field, or `null` when none ran.

### 5. Cached vectors (`chunk_embeddings`)

The column is `vector(384)`, so 1024-dim rows cannot be stored. `arp db init-postgres` alters it to untyped
`vector` (`ALTER TABLE chunk_embeddings ALTER COLUMN embedding TYPE vector`), idempotent, in
`arp/storage/postgres_schema.py`. Rows are already keyed by `(chunk_id, embed_model)`, so MiniLM rows stay valid
and each model gets its own rows; nothing is deleted. No ANN index exists on the column, so none is lost.

### 6. Retrieval recall CI cache key

The key hashes `backend/arp/retrieval/embeddings.py`, so editing that file (this change will) forces a cold
MiniLM re-embed of both reports on the CPU runner. The key instead hashes `backend/.retrieval-embed-model.txt`,
written by the install step as the MiniLM registry entry's `hf_id@revision`: the only model CI can compute.
The CI job keeps running the default settings and its `--min-recall 0.627` floor; it never needs a GPU.

### 7. `arp golden-set retrieval` comparison

New options `--embed-model` and `--rerank-model`, each a comma-separated list. `--rerank-model` takes `off`,
`cross-encoder`, `colbert` (`off` = `rerank_enabled=false`; any other value sets `rerank_enabled=true` and
`rerank_model`). The command runs every combination over the same parsed documents and prints one line each:

```
embed=e5-large rerank=colbert: 60 gold span(s) over 60 field(s): recall@5 51.7%, recall@12 66.7%; 1.90s median, 3.10s max per field; fallback 0 field(s).
```

That is main's summary line with an `embed=… rerank=…: ` prefix and a `; fallback N field(s).` suffix.
`fallback` counts fields where the requested embedder or the requested reranker did not run (section 4); a
local MiniLM or local cross-encoder run is not a fallback, since that is the requested model.
`--out` writes a JSON list, one report per combination in the printed order, each with `settings.embed_model`,
`settings.rerank_model` (`null` for `off`) and `fallback_fields`. `--min-recall` applies to every combination:
exit 1 if any is below, with main's stderr message prefixed by that combination's `embed=… rerank=…: `.
An unknown value exits 2 with `--embed-model must be one of minilm, e5-large, bge-m3` (or
`--rerank-model must be one of off, cross-encoder, colbert`). Without the new options the output is main's.

## Latency and cost

- **Latency per field** is the report's `median_seconds_per_field` and `max_seconds_per_field`, with chunk
  vectors already cached (the first run per document also pays its embedding once; report that separately as
  the first run's total seconds). Last measured on CPU: rerank ~47 s/field; embedding with e5-large ~8 min per
  300 chunks. The GPU numbers are measured, not guessed.
- **Cost** = GPU-instance seconds × the Cloud Run price for 1 L4 + 4 vCPU + 16 GiB in `europe-west1`
  (instance-based billing, scales to zero; roughly USD 1 per instance-hour, the builder confirms the current
  rate and states it). Per field: `median_seconds_per_field × rate`. One-off per document: its embedding
  seconds × rate. Cold start (model load) is stated separately.

## Switch-on rule (later PRs, not this one)

For each option, a later PR changes one default in `arp/config.py` and pastes the comparison output for
`--embed-model minilm,e5-large,bge-m3 --rerank-model off,cross-encoder,colbert` (with `compute_models_url`
set). It may merge only if that option's line shows recall@12 ≥ 64.7% and recall@5 ≥ 45.6%, and its PR states
latency per field and cost per the section above. Order: embedder first, then reranker on the chosen embedder.

## Left to the builder

Batch sizes for `/embed` and `/rerank`; how bge-m3 truncates (its 8,192-token limit covers a chunk); whether
the comparison reuses one `RunStore`; test stand-in shapes, as long as no other seam is added.

## Acceptance

Conventions: "stand-in" = functions in `arp.compute.client`, `arp.retrieval.embeddings._get_model` and
`arp.retrieval.rerank._score` replaced by recording fakes (monkeypatch), so no GPU, network or model download
is used; no other seam is added. "Configured" = the stand-in plays a configured `arp-models`. Ranks count from
0; `evidence_max_chunks` is 12. `<s>` in an expected line matches `\d+\.\d\d`. Model names in "received"
are `hf_id@revision` from section 2. `--no-hybrid` means BM25 only, as on main (no embeddings).
`--min-recall` gates recall@12, and its stderr wording is main's: `recall@12 <x>% is below the minimum <y>%.`

| ID     | Given | When | Then (observable, exact) | Checked by |
|--------|-------|------|--------------------------|------------|
| AC-1   | No `ARP_EMBED_MODEL` / `ARP_RERANK_MODEL` set | `Settings()` is built | `embed_model == "minilm"`, `rerank_model == "cross-encoder"`, `rerank_enabled is False` | holdout |
| AC-2   | `ARP_EMBED_MODEL=e5-small` | `Settings()` is built | Validation error whose message contains `minilm`, `e5-large` and `bge-m3` | holdout |
| AC-2b  | `ARP_RERANK_MODEL=foo` | `Settings()` is built | Validation error whose message contains `cross-encoder` and `colbert` | holdout |
| AC-3   | The PR build, default settings, the gold-set documents, no GPU | `arp golden-set retrieval --cases tests/golden/retrieval/cases.json --min-recall 0.647` | Exit 0, and the printed recall@5 is ≥ 45.6% | golden |
| AC-4   | `embed_model=e5-large`, configured, stand-in returns 1024-dim vectors | one field is ranked with hybrid on | The stand-in received model `intfloat/multilingual-e5-large@3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`; the query text starts `query: `; every chunk text starts `passage: `; the trace has `embed_model: "embed_e5_large"` | holdout |
| AC-5   | `embed_model=bge-m3`, configured, stand-in returns 1024-dim vectors | one field is ranked | The stand-in received model `BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181`; no text sent starts with `query: ` or `passage: `; trace `embed_model: "embed_bge_m3"` | holdout |
| AC-6   | `embed_model=e5-large`, `compute_models_url` unset, local MiniLM stand-in; reference = same input with `embed_model=minilm` | two fields are ranked in one process | Each field's evidence order equals the reference's; each trace has `embed_model: "embed"`; the log contains `arp-models unavailable; embedding with MiniLM` exactly once | holdout |
| AC-7   | `embed_model=e5-large`, configured; stand-in returns vectors for the chunks, `None` for the query | one field is ranked | Trace `embed_model: "embed"`; evidence order equals the AC-6 reference for that field | holdout |
| AC-7b  | As AC-7, with Postgres | one field is ranked | `chunk_embeddings` has one row per chunk with `embed_model = 'intfloat/multilingual-e5-large'` and 1024 values | holdout, deferred to PR #353 |
| AC-7c  | `embed_model=e5-large`, configured; stand-in returns 384-dim vectors (case 1) or raises `httpx.HTTPError` (case 2) | one field is ranked | Both cases: no exception escapes; trace `embed_model: "embed"` | holdout |
| AC-8   | Postgres with `chunk_embeddings` created as `embedding vector(384)` holding one MiniLM row for chunk `c1` | `arp db init-postgres` runs twice, then a 1024-dim row for `c1` with `embed_model='intfloat/multilingual-e5-large'` is stored | Both runs exit 0; `SELECT embedding FROM chunk_embeddings WHERE chunk_id='c1' AND embed_model=…` returns the original 384 values for MiniLM and 1024 values for e5-large | holdout |
| AC-8b  | AC-6 reference run and an AC-4 run over the same document, with Postgres | both have stored vectors | The set of `chunk_id`s stored for `intfloat/multilingual-e5-large` equals the set stored for `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | holdout |
| AC-9   | `rerank_enabled=true`, `rerank_model=colbert`, configured, stand-in returns scores `[0.1, 0.9, 0.5]` for 3 candidates | rerank runs | The stand-in received model `lightonai/mLateOn@bbd883ae1fadb563056ff73b1061ae8172a3fcda`; order is candidates 1, 2, 0; trace `reranked: true`, `rerank_model: "rerank_colbert"` | holdout |
| AC-10  | `rerank_enabled=true`, `rerank_model=colbert`, `compute_models_url` unset, `HF_HUB_OFFLINE=1`, empty `FASTEMBED_CACHE_PATH` | rerank runs on 3 candidates | Returns the 3 candidates in input order; no exception; trace `reranked: false`, `rerank_model: null` | holdout |
| AC-10b | `rerank_enabled=true`, `rerank_model=colbert`, configured; stand-in raises `httpx.HTTPError` | rerank runs on 3 candidates | Returns the 3 candidates in input order; no exception; trace `reranked: false`, `rerank_model: null` | holdout |
| AC-11  | `rerank_enabled=true`, `rerank_model=cross-encoder`, `compute_models_url` unset, local scorer stand-in returns `[0.2, 0.8, 0.5]` | rerank runs on 3 candidates | Order 1, 2, 0; trace `reranked: true`, `rerank_model: "rerank"` | holdout |
| AC-12  | The compute server app, models replaced by fakes returning 1024-dim vectors | `POST /embed` with `X-ARP-Model` = the e5-large name | 200; each vector has 1024 numbers | holdout |
| AC-12b | As AC-12 | `POST /embed` with `jinaai/jina-colbert-v2@x`; `POST /rerank` with the e5-large name | Both 409 | holdout |
| AC-12c | As AC-12 | `POST /embed` with the bge-m3 name; `POST /rerank` with the mLateOn name, a query and 3 texts | First: 200, each vector has 1024 numbers. Second: 200 with exactly 3 scores | holdout |
| AC-13  | The model registry | `registry.entry(k)` for `embed_e5_large`, `embed_bge_m3`, `rerank_colbert` | Each returns the hf_id and revision in section 2; `jinaai/jina-colbert-v2` is not in `allowed.txt` | holdout |
| AC-14  | A cases file of 2 cases, configured; the stand-in returns any valid vectors and scores for every model | `arp golden-set retrieval --cases <file> --embed-model minilm,e5-large --rerank-model off,colbert` | Exit 0; stdout is exactly 4 lines, in this order, starting `embed=minilm rerank=off: 2 gold span(s)`, `embed=minilm rerank=colbert: 2 gold span(s)`, `embed=e5-large rerank=off: 2 gold span(s)`, `embed=e5-large rerank=colbert: 2 gold span(s)`; each ends `; fallback 0 field(s).` | holdout |
| AC-15  | As AC-14 with `--out <json>`, `compute_models_url` unset, local MiniLM stand-in | the command runs | The JSON is a list of 4 objects with `fallback_fields` 0, 2, 2, 2 in AC-14's order; stdout lines end `fallback 0 field(s).`, `fallback 2 field(s).`, `fallback 2 field(s).`, `fallback 2 field(s).` | holdout |
| AC-15b | As AC-14 with `--embed-model foo` | the command runs | Exit 2; stderr contains `--embed-model must be one of minilm, e5-large, bge-m3` | holdout |
| AC-15d | As AC-14 with `--rerank-model foo` | the command runs | Exit 2; stderr contains `--rerank-model must be one of off, cross-encoder, colbert` | holdout |
| AC-15c | As AC-14, with documents and stand-in vectors built so `minilm` reaches recall@12 100.0% and `e5-large` reaches 0.0% | `... --embed-model minilm,e5-large --rerank-model off --min-recall 0.9` | Exit 1; stderr contains `embed=e5-large rerank=off: recall@12 ` and `is below the minimum 90.0%` | holdout, deferred to PR #353 |
| AC-16  | A cases file of 3 cases built so BM25 ranks each gold chunk at 0 | `arp golden-set retrieval --cases <file> --no-hybrid` (no new options) | stdout is exactly `3 gold span(s) over 3 field(s): recall@5 100.0%, recall@12 100.0%; <s>s median, <s>s max per field.` | holdout |
| AC-17  | `.github/workflows/ci.yml` on the PR | the Retrieval recall job is read | The cache key hashes `backend/.retrieval-embed-model.txt` and not `backend/arp/retrieval/embeddings.py`; the install step writes that file; the run step still passes `--min-recall 0.627` | unit |

Must not change: default retrieval results (AC-3, AC-16), the cross-encoder's local path (AC-11), existing
MiniLM cached vectors and their keys (AC-8, AC-8b), the CI job's floor `--min-recall 0.627` (AC-17).
