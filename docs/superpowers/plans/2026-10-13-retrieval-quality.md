# Retrieval quality: eval set, reranker, embedding upgrade

## Status (2026-10-13, after merging main)

- **Phase 0: built** as `arp golden-set retrieval` (`backend/arp/golden_set/retrieval.py`). It replays `field_graph.field_evidence`, the exact path extraction uses, against reviewer-approved citations. It reports recall@5 and recall@`evidence_max_chunks`, plus seconds per field.
- **Phase 1: already on main** (`arp/retrieval/rerank.py`, `rerank_enabled`, off by default). Not rebuilt. Re-measured on BASF 2025 (40 candidates of 3,500 chars, 4 CPUs):

  | Reranker | Full chunks | Truncated to 1,500 chars | Truncated to 800 chars |
  |---|---|---|---|
  | `bge-reranker-v2-m3-int8` (main) | 75 s | 20 s | 10 s |
  | `jina-reranker-v2-base-multilingual` | 51 s | 15 s | 9 s |

  Truncation changes the top 5, so it would need eval before use.
- **Phase 2: candidates changed.** Embedding all 299 BASF chunks takes:

  | Embedder | Time | Notes |
  |---|---|---|
  | MiniLM (today) | 76 s | Truncates at 128 tokens: a chunk cut to 600 chars embeds identically to the full 3,500 |
  | `minishlab/potion-multilingual-128M` | 0.6 s | Reads most of the chunk (cosine 0.89 at 600 chars vs full) |
  | `multilingual-e5-large` | ~8.4 min | Too slow for the in-app wait on CPU |
  | `Qwen3-Embedding-0.6B` | ~43 min | Too slow for the in-app wait on CPU |

  The candidate is now potion vs MiniLM. Decide with `golden-set retrieval` on reviewed runs.

## Context

The user decided to keep Docling as is; parsing is out of scope. What remains from the earlier recommendations is retrieval: which chunks reach the extractor (Claude Sonnet 5.5) and the verifier (Claude Opus 5.5).

Today `select_relevant_chunks` (`backend/arp/retrieval/select_evidence.py:79`) ranks by BM25, fuses that with a MiniLM embedding ranking via reciprocal rank fusion (hybrid is on by default), and hands the top `max_chunks` (default 10) to the LLM. There is no reranker, and the embedding model is the small `paraphrase-multilingual-MiniLM-L12-v2` (384-dim).

Constraints from the conversation:
- **Quality first.**
- **CPU only.**
- **Users wait in the app.** Runs start right after upload, so added CPU time per run must be measured and kept acceptable.
- Reports are annual and sustainability reports, often in German, so the models must be multilingual.

Facts that shape the plan:
- `golden_set_run` uses 5 synthetic text cases (`backend/arp/golden_set/data/extraction_cases.json`). It never runs retrieval, so it cannot measure this work. Phase 0 builds a measure that can.
- The installed fastembed already ships multilingual cross-encoders: `jinaai/jina-reranker-v2-base-multilingual`, `BAAI/bge-reranker-v2-m3`, `BAAI/bge-reranker-v2-m3-int8`. It also ships stronger embedders: `Qwen/Qwen3-Embedding-0.6B`, `intfloat/multilingual-e5-large`. **No new dependency is needed.**
- Embeddings are cached per `(chunk_id, embed_model)` in pgvector with a fixed `EMBED_DIM` (`backend/arp/storage/postgres_models.py:131`). Changing dimension means dropping and recreating `chunk_embeddings`. It's a cache, so no data is lost.
- Correction: the `claude-haiku-4-5-20251001` reference is only a price entry (`backend/arp/orchestration/cost_tracker.py:16`). There is no model pin to update, so that step is dropped.

Order: Phase 0 → Phase 1 → (gate) Phase 2. Each phase can ship on its own.

---

## Phase 0: Retrieval eval (~0.5 day)

**New script `backend/scripts/retrieval_eval.py`** (CLI via typer, matching `arp/cli`).

1. **Gold set.** For each run in the run store (`RunStore.read_results`), take fields whose review state is final and accepted (`item_states()` in `arp/orchestration/review_queue.py:183`, `FINAL_STATES`) and whose citations are `grounded` with `char_start`/`char_end`.
   - Gold = (company documents, field definition, cited span).
   - Fallback if there are fewer than 50 accepted items: use every `grounded=True` citation as a weaker "silver" set, and say so in the output.
2. **Replay retrieval.** For each gold item, rebuild the field's chunks exactly as `field_graph.py:117-140` does (`chunk_document(doc, keywords=field.seed_keywords)`, then `select_relevant_chunks` with the same arguments). Pass the retrieval options as CLI flags so the same script measures every variant.
3. **Metrics.**
   - recall@5 and recall@10: share of gold spans overlapped by a selected chunk.
   - Median and p95 wall-clock time per `select_relevant_chunks` call, plus total time per company.
4. **Output.** A JSON summary written to `docs/evals/retrieval-<date>-<variant>.json`, plus a one-line printout.
5. **Test** (`backend/tests/test_retrieval_eval.py`): the overlap/recall helper on hand-built chunks and spans. Cases: hit, miss, partial overlap counts as a hit, empty gold set.
6. **Baseline:** run it for the current default (hybrid on, no reranker) and commit the JSON. This container has no runs, so the user runs it locally. The command goes in the PR description.

## Phase 1: Reranker (~1 day)

1. **New module `backend/arp/retrieval/rerank.py`.**
   - `rerank(query_text: str, chunks: list[DocumentChunk], model_name: str, top_n: int) -> list[DocumentChunk]`.
   - The fastembed `TextCrossEncoder` is cached per model name (`functools.lru_cache`, same lazy-load style as `arp/retrieval/embeddings.py`).
   - Ties keep their input order, so output stays deterministic.
2. **`select_relevant_chunks`** gets two new keyword arguments: `rerank_model: str | None = None` (None = off, so every existing caller is unchanged) and `rerank_candidates: int = 30`.
   - When set, it takes the top `rerank_candidates` from the final ranking (BM25-only, fused, or fallback order) instead of `max_chunks`, reranks them, and returns the top `max_chunks`.
   - Update the docstring like the existing hybrid/opensearch paragraphs.
3. **Settings** (`backend/arp/config.py`): `rerank_model: str | None = None` and `rerank_candidates: int = 30`, next to `hybrid_retrieval_enabled`. Plumb them exactly where `hybrid_retrieval_enabled` is plumbed today:
   - `arp/extraction/field_graph.py:132-140`
   - `arp/extraction/tnfd_graph.py:50-66`
   - `arp/extraction/financials_graph.py:37-55, 91-106`
   - `arp/research/match_graph.py:169-186`
   - `arp/extraction/steps.py`: setting metadata at line 50, plus the `gather_evidence` lists at lines 80-87
   - `arp/extraction/pipeline.py:109` (run-settings snapshot, so results record which reranker was used)
   - The other `select_relevant_chunks` callers (news mining, engagement, transition plan, replication) stay unchanged.
4. **Tests** (`backend/tests/test_rerank.py`), with the cross-encoder monkeypatched to return fixed scores:
   - `rerank` orders by score, keeps input order on ties, and caps at `top_n`.
   - `select_relevant_chunks(..., rerank_model=None)` returns exactly what it returns today.
   - With a fake reranker it reorders within the top `rerank_candidates` and returns `max_chunks`.
   - A gold chunk ranked 20th by BM25 surfaces in the top 10 after reranking.
5. **Choose the model and the default with Phase 0.** Run the eval for both candidates at `rerank_candidates` ∈ {20, 30, 50}.
   - Make it the default (set `rerank_model` in `config.py`) only if recall@5 improves over baseline AND the added time for a full BASF financials run is acceptable to the user.
   - Report the numbers in the PR and let the user pick. Check the cross-encoder's max input length against chunk size (`DEFAULT_CHUNK_CHARS` in `arp/ingestion/parsing.py`) so chunks aren't silently truncated.

## Phase 2: Embedding upgrade (~0.5 day + one-time re-embed; only if the gate passes)

**Gate:** after Phase 1, Phase 0 still shows misses where the gold chunk isn't in the top `rerank_candidates` at all. Those are first-stage recall misses that a better embedder can fix and a reranker can't.

1. **Model choice.** Evaluate `Qwen/Qwen3-Embedding-0.6B` and `intfloat/multilingual-e5-large` against MiniLM on Phase 0.
   - e5 needs `query: `/`passage: ` prefixes, so add a query-vs-passage flag to `embed_texts` in `arp/retrieval/embeddings.py`.
   - Measure embedding time for the whole BASF report on CPU. That's the in-app cost on a report's first run.
2. **Switch.** Update `EMBED_MODEL_NAME`/`EMBED_DIM` in `arp/retrieval/embeddings.py`. Drop and recreate `chunk_embeddings` through the existing DB init path (check `arp/cli/db.py`). Old vectors are keyed by model name, so nothing goes wrong mid-switch.
3. **Tests:** existing embedding/hybrid tests pass. Add a test that query and passage prefixes are applied for e5 (if e5 is chosen).
4. **Default:** switch only with the measured recall gain and timing in the PR. Otherwise keep MiniLM and record why in `docs/TECHNICAL_REFERENCE.md`.

---

## Verification

- **Per phase:** `cd backend && ruff check . && python3 -m pytest tests/test_retrieval_eval.py tests/test_rerank.py`, plus the existing retrieval tests (`grep -l select_relevant_chunks tests/`), then the full suite. Run `bash .claude/hooks/ensure-deps.sh backend` first.
- **Phase 0:** the script runs on a local run store and prints recall@5/10 and timings. The baseline JSON is committed.
- **Phase 1:** eval JSONs for each reranker and candidate-count variant are committed. A full BASF run in the app with and without the reranker, wall-clock recorded. Extracted values spot-checked against BASF's ESEF tagged facts.
- **Phase 2:** the same, comparing embedders.

## Execution notes

- Branch `claude/optimistic-babbage-1ilm47`. Merge `origin/main` in before the PR. The PR targets `main`.
- First step on approval: save this plan as `docs/superpowers/plans/2026-10-13-retrieval-quality.md` and commit it.
- No new dependencies. Docling, `local_files.py` and parser versioning are untouched.
