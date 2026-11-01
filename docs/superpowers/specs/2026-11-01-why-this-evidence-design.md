# Why this evidence? (retrieval scores in the Argus Walkthrough)

Status: draft, awaiting owner approval.

## Goal

When a value is missing or wrong, a reviewer can tell in one look whether retrieval missed the passage, ranked it
too low, or the model misread it. Today the Argus Walkthrough's "Find evidence" step lists the passages a field
saw (`walkthrough/trace.py` → `walkthrough/view.py` → `ArgusWalkthrough.tsx`), but not why they were picked:
`select_relevant_chunks` computes BM25, vector-rank, RRF and reranker scores and throws them away.

Idea taken from RAGFlow's retrieval-testing page (`web/src/pages/dataset/testing/testing-result.tsx`), which shows
hybrid, term and vector similarity per passage.

## Design

1. **Record.** `select_relevant_chunks` takes an optional `explain: dict | None = None`. When given, it fills:
   - `method`: `"bm25"`, `"hybrid"` (BM25 + vectors, RRF), `"opensearch"` or `"opensearch_hybrid"`;
     `"unranked"` when `fallback_to_all` returned candidates nothing ranked; `"none"` when there are no query terms.
   - `reranked`: true when the cross-encoder ran on the list (even if it kept the order), false otherwise.
   - `candidates`: how many chunks were eligible after the doc-type filter.
   - `scores`: per chunk id: `bm25` (score, or null when it had no keyword hit), `vector_rank` (1-based, hybrid only),
     `rrf` (hybrid only), `rerank` (cross-encoder score, only when reranked). Missing keys mean "not computed".
   - `near_misses`: the chunk ids ranked directly after the cut, at most 3.
   Return value and ranking are unchanged; every other caller passes nothing and behaves exactly as today.
2. **Trace.** `field_evidence` passes `explain`; `trace.passage` adds the chunk's `scores`; `trace.field_entry`
   adds `retrieval: {method, reranked, candidates}` and `near_misses` (same shape as passages, with scores).
   Grouped fields keep each passage's scores from the field ranking it came from and record no near-misses.
3. **API.** `build_walkthrough` passes `retrieval`, per-passage `scores` and `near_misses` (with text, like passages)
   through; each near-miss item gets `rank` = passage count + i (1-based, so ranks continue after the passages),
   `doc_title` and `text`, like passages. Old traces without them return `retrieval: null`, `near_misses: []`, and passages without `scores`.
4. **UI.** In the "Find evidence" step:
   - one mono line above the list: `{method label}{", re-ranked" if reranked} · {candidates} candidates`, with labels
     `bm25` → `BM25`, `hybrid` → `BM25 + vectors (RRF)`, `opensearch` → `BM25 (OpenSearch)`,
     `opensearch_hybrid` → `BM25 (OpenSearch) + vectors (RRF)`, `unranked` → `No keyword hit: first passages in document order`,
     `none` → `No query terms: first passages in document order`;
   - on each passage line, after the character range: ` · ` then its scores in this order, only the keys present:
     `BM25 {bm25, 2 dp}` · `vector #{vector_rank}` · `RRF {rrf, 3 dp}` · `rerank {rerank, 2 dp}`;
   - under the passages a "Just missed (n)" disclosure, collapsed on load, hidden when n = 0; open, it lists the
     near-misses with ranks continuing after the last passage (passages 1–12 → near-misses 13, 14, 15), in the same
     line layout as passages (rank · document · section · characters · scores) and their text;
   - old traces: one muted line `Scores were not recorded for this run.` above the passages.
5. **Seed.** Seeded known-answer items (`arp golden-set seed-known-answers`, `review/quality.py`) build their trace with
   the same `field_evidence(..., explain)` call, so they carry scores. The e2e stack does not seed them (it would put
   items in the review queue that `tests/e2e/test_argus_start.py` expects to be empty), so the evaluator runs
   `arp golden-set seed-known-answers --count 2 --seed 1` against the running stack first; the first seeded item is
   `seeded-scored` below. The stack runs with default settings: hybrid retrieval on, re-ranking off. (Amended during
   implementation; owner to confirm.)

Signal Room rules: scores are ink mono text at 13px, no status or signal colour; numbers use tabular figures.

## Out of scope

Retrieval test sandbox, per-step timings, the sufficiency gate, any change to how evidence is chosen, other pipelines
(TNFD, financials, research) which call `select_relevant_chunks` without `explain`.

## Acceptance

Fixtures: **F1** = 20 chunks where at least 8 contain a query term, BM25 only, `max_chunks=5`. **VS** = the stub content
store the existing hybrid tests in `tests/` use. **OS** = the stub OpenSearch client the existing OpenSearch tests use.
**RR** = a stub reranker. **DOCS** = the fixture documents and stub LLM of the existing `tests/test_walkthrough_field_graph.py`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | F1, `explain={}` | `select_relevant_chunks` runs | Returns the same 5 chunks in the same order as the same call without `explain` | unit |
| AC-2 | F1 | Call returns | `explain["method"] == "bm25"` | unit |
| AC-3 | F1 | Call returns | `explain["reranked"] is False` | unit |
| AC-4 | F1 | Call returns | Each returned chunk has `scores[id]["bm25"] > 0`, and the values are non-increasing in return order | unit |
| AC-5 | F1 | Call returns | `explain["near_misses"]` equals the ids at ranks 6, 7, 8, in that order | unit |
| AC-6 | F1 + VS (hybrid) | Call returns | `explain["method"] == "hybrid"` | unit |
| AC-7 | F1 + VS | Call returns | Every returned chunk has a float `rrf` and an int `vector_rank` ≥ 1 | unit |
| AC-8 | F1 + RR, `rerank_candidates=10` | Call returns | `explain["reranked"] is True` | unit |
| AC-9 | F1 + an RR that keeps the input order | Call returns | `explain["reranked"] is True` | unit |
| AC-10 | F1 + OS | Call returns | `explain["method"] == "opensearch"` | unit |
| AC-11 | F1 + OS + VS | Call returns | `explain["method"] == "opensearch_hybrid"` | unit |
| AC-12 | Chunks with no keyword hit, `fallback_to_all=True`, BM25 only | Call returns | `explain["method"] == "unranked"` | unit |
| AC-13 | F1 with `query_terms=[]` | Call returns | `explain["method"] == "none"` | unit |
| AC-14 | DOCS, one ungrouped field | Trace entry is written | `retrieval` has exactly the keys `method`, `reranked`, `candidates` | unit |
| AC-15 | As AC-14 | Trace entry is written | Every passage has a `scores` object | unit |
| AC-16 | As AC-14, fixture with ≥ 3 near-misses | Trace entry is written | `near_misses` has exactly 3 items, each with `doc_id`, `char_start`, `char_end`, `section`, `scores` | unit |
| AC-17 | DOCS, a grouped field | Trace entry is written | Each passage's `scores` equal the scores its source field's ranking recorded for that chunk id | unit |
| AC-18 | As AC-17 | Trace entry is written | `near_misses == []` | unit |
| AC-19 | Trace written by new code | `GET` walkthrough for that field | Response `retrieval` equals the trace's `retrieval` | unit |
| AC-20 | As AC-19 | Same | Each response passage carries the trace passage's `scores` | unit |
| AC-21 | As AC-19 | Same | `near_misses` items have `rank` == len(passages)+1 … +3, each with `doc_title` and non-null `text` | unit |
| AC-22 | Trace written before this change (no `scores`, no `retrieval`) | `GET` walkthrough | `retrieval` is null and `near_misses == []` | unit |
| AC-23 | As AC-22 | Same | Passages are byte-equal to the response `main` returns for the same trace | unit |
| AC-24 | `seeded-scored` in the e2e stack | Reviewer opens its Walkthrough, "Find evidence" step | The line above the passages reads `BM25 + vectors (RRF) · {n} candidates` (`1 candidate` when n = 1) with n = the trace's `candidates` (no `, re-ranked`: re-ranking is off in the stack) | evaluator |
| AC-25 | As AC-24 | Same view | Each passage line ends with ` · BM25 x.xx · vector #n · RRF x.xxx`, numbers matching the trace (BM25 part absent where the trace has no `bm25`) | evaluator |
| AC-26 | As AC-24, if its trace has near-misses (n ≤ 3) | Page loads | `Just missed (n)` is shown and collapsed (no near-miss text visible) | evaluator |
| AC-27 | As AC-24 | Reviewer clicks `Just missed (n)` | n rows appear with ranks last-passage+1 … +3, each with document, section, characters, scores and text | evaluator |
| AC-28 | Walkthrough of a trace without scores (frontend test fixture) | Step renders | Shows `Scores were not recorded for this run.` | unit |
| AC-29 | As AC-28 | Step renders | Passage lines render the same as on `main` (snapshot of the existing test) | unit |
| AC-30 | As AC-24, Graphite and Night | Same view | Score text computed `font-size` ≥ 13px | evaluator |
| AC-31 | As AC-30 | Same view | Score text contrast ≥ 4.5:1 against its background | evaluator |
| AC-32 | As AC-30 | Same view | Score text colour is not the signal colour (`--hi`) | evaluator |
| AC-33 | As AC-30 | Same view | Score text has `font-variant-numeric: tabular-nums` | evaluator |
| AC-34 | DOCS, full field extraction | Run on this branch vs. the same run with `select_relevant_chunks` monkeypatched to be called with `explain=None` | Extracted values and grounding results are equal | unit |
| AC-35 | TNFD, financials and research `select_relevant_chunks` callers' existing fixtures | Their existing tests run | Same chunks as on `main` (existing assertions pass unchanged) | unit |
| AC-36 | Golden set | CI golden-set job (`arp golden-set run`) | Exits 0 with 0 failing cases | golden |
| AC-37 | Existing backend and frontend suites | CI | All existing tests pass unchanged | unit |
| AC-38 | F1 | Call returns | `explain["candidates"] == 20` | unit |
| AC-39 | F1 + RR, `rerank_candidates=10` | Call returns | Every returned chunk has a float `rerank` | unit |
| AC-40 | As AC-12 | Call returns | No returned chunk has a `bm25` key | unit |
| AC-41 | As AC-13 | Call returns | `explain["scores"] == {}` | unit |
| AC-42 | Walkthrough field with `near_misses == []` (frontend fixture) | Step renders | No `Just missed` element is rendered | unit |

Must not change: which evidence is chosen and its order (AC-1, AC-34, AC-36), callers without `explain` (AC-35,
AC-37), old traces (AC-22, AC-23, AC-28, AC-29).
