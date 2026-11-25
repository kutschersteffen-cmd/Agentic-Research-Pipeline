# Extraction retrieval quality: field query, reranking small pieces, overlap removal

Status: Draft, for owner approval
Slug: `extraction-retrieval-bundle`
Risk: `risk:normal` (backend retrieval only: `arp/retrieval/select_evidence.py`, `arp/retrieval/rerank.py`,
`arp/extraction/field_graph.py`, `arp/config.py`; no auth, schema, money, workflow or UI file)
Size: `S`, one PR, no slices

## Decisions for the owner

None needed a question: every change ships behind its own setting, all three default off, so no default flips
in this item. Every other choice is listed under "Defaults taken"; approving the spec approves them. Whether a
default flips is decided later on the numbers in the PR body.

## Why

The extraction review of 25 Nov 2026 (`/mnt/project-files/extraction-precision/review-and-ideas.md`, ideas 1, 2
and 4) found three retrieval gaps on `main` at `7e2e955`. Steffen's goal: the fastest and most robust pipeline
on CPU only.

1. **The meaning ranking and the reranker get a keyword bag.** `field_evidence` passes
   `with_german(field.seed_keywords)` to `select_relevant_chunks`, which joins it with spaces into one
   `query_text` and uses that one string for BM25, for the embedder's query vector and for the reranker. The
   field's own description and extraction instructions, written in plain language, never reach the two
   meaning-based rankers.
2. **The reranker reads whole parents.** With `small_to_big_enabled` (default on) the ranking units are pieces of
   at most `small_chunk_chars` (800), but the reranker scores each pool entry's full text, which is the parent:
   a section of up to 3,500 characters, or a whole table passage of any length. ARP's own note
   (`rerank.py` docstring): 40 chunks took about 47 s per field on a 4-core CPU, which is why
   `rerank_enabled` is off.
3. **Overlapping passages fill the 12 slots.** Table passages and text chunks cover the same characters by
   construction, and sections overlap plain chunks. The cap at `evidence_max_chunks` (12) removes duplicates
   by `chunk_id` only, so two passages with mostly the same text can both be sent.

## What the user can do afterwards that they cannot do today

- Turn on `ARP_RETRIEVAL_FIELD_QUERY_ENABLED=true` to rank meaning (embeddings, reranker) against the field's
  name, description and instructions, while BM25 keeps the keywords.
- Turn on `ARP_RERANK_SMALL_PIECES_ENABLED=true` so the reranker reads at most `small_chunk_chars` characters per
  passage, which should make `rerank_enabled` affordable on CPU.
- Turn on `ARP_EVIDENCE_OVERLAP_REMOVAL_ENABLED=true` so the 12 passages sent to the extractor do not repeat
  each other.
- Compare each switch with `arp golden-set retrieval` (no LLM calls), since every setting is read from the
  environment like the others.

## What exists today (main `7e2e955`)

- `select_relevant_chunks(chunks, query_terms, *, doc_type_filter, max_chunks, require_hit, fallback_to_all,
  hybrid_retrieval_enabled, content_store, retrieval_backend, opensearch_client, rerank_candidates,
  on_unranked_fallback, index_texts, explain, parents, embed_model, rerank_model)` in
  `backend/arp/retrieval/select_evidence.py`. `query_text = " ".join(query_terms)` is used for BM25 (in-memory
  or OpenSearch), for `_vector_ranking` / `_model_vector_ranking` and for `rerank(query_text, pool, ...)`.
  Research Desk wave 1 also calls this function.
- `finish()` takes `pool = ranked[:rerank_candidates]` and calls `rerank(query_text, pool, max_chunks, ...)`,
  which scores `[c.text for c in pool]`. With `parents` given, every ranking is mapped to parents before fusion,
  so the pool holds parents.
- `rerank()` in `backend/arp/retrieval/rerank.py` fails open: when the model can't load or score it returns
  `chunks[:top_n]` in the given order (and sets `_unavailable` for the cross-encoder). Tests patch
  `rerank._score(query, texts)`.
- `field_evidence(field, documents, settings, on_unranked_fallback=None, explain=None)` in
  `backend/arp/extraction/field_graph.py` builds `keywords = with_german(field.seed_keywords)`, the pieces
  (`small_pieces`) and their `parents` (`piece_parents`), and calls `select_relevant_chunks`. A high-risk field
  whose small-to-big call returns nothing falls back to a call with `parents=None` over the plain chunks.
- `FieldDefinition` (`backend/arp/schemas/datapoints.py`) has `name`, `description` and
  `extraction_instructions` (all `str`) and `seed_keywords`.
- Spec `extraction-trace-parse-report` (written in parallel, builder goes first) adds full rank lists, the
  winning piece per parent and step times to `explain`. This item adds no `explain` key and changes none of
  that spec's keys.

## Goals

1. G1, field query: with `retrieval_field_query_enabled`, the embedder's query and the reranker's query are the
   field query (defined in Design); BM25's query stays the keyword string.
2. G2, rerank small pieces: with `rerank_small_pieces_enabled`, small-to-big and the reranker on, every text the
   reranker scores is at most `small_chunk_chars` characters; the chunks returned are still the parents.
   The high-risk fallback call over plain chunks (`parents=None`) is unchanged and may still score longer texts.
3. G3, overlap removal: with `evidence_overlap_removal_enabled`, a passage is not returned when a better-ranked
   returned passage of the same document already covers at least 80 % of its characters.
4. G4, nothing else moves: with all three settings off (their defaults), picked chunks, their order and the
   reranker's inputs are identical to `main`.

## Non-goals

- Flipping any default. Steffen decides in the PR, on the measured numbers.
- Caching reranker scores per (query, piece), weighted fusion, a richer query for keyword-less fields, the
  matcher's retrieval path (`research/match_graph.py`, separate item `matcher-shared-retrieval`), long-table
  row groups, embedder changes.
- Any `explain` key, trace field or UI change.
- The grouped-field path `merge_evidence` (it keeps deduping by id).

## Anti-goals (must stay true)

- `select_relevant_chunks` keeps every existing parameter, its default and its return type (a list of
  `DocumentChunk`). New parameters are keyword-only with defaults that give today's behaviour, so a caller that
  passes none of them (Research Desk, the matcher, the funnel) gets exactly today's result whatever the
  settings say.
- Grounding (`arp/grounding.py`), routing (`arp/extraction/routing.py` and `route_documents`) and every prompt
  are untouched. The PR diff touches no file under them; stage-4 code review checks this (not a test row).
- The reranker still fails open: when it can't score, retrieval order is kept and the run goes on.

## Design

Three settings in `backend/arp/config.py` `Settings`, next to the retrieval settings, each `bool`, default
`False`, read from `ARP_<NAME>` like the rest:

| Setting | Env var | Turns on |
|---|---|---|
| `retrieval_field_query_enabled` | `ARP_RETRIEVAL_FIELD_QUERY_ENABLED` | G1 |
| `rerank_small_pieces_enabled` | `ARP_RERANK_SMALL_PIECES_ENABLED` | G2 |
| `evidence_overlap_removal_enabled` | `ARP_EVIDENCE_OVERLAP_REMOVAL_ENABLED` | G3 |

Only `field_evidence` reads them and passes them on as three new keyword-only parameters of
`select_relevant_chunks`:

- `dense_query: str | None = None`. When it is a non-empty string, the embedder's query (MiniLM through
  `_vector_ranking`, or the arp-models embedder through `_model_vector_ranking`, prefix rules unchanged) and the
  reranker's query are `dense_query`. BM25 (in-memory and OpenSearch) still uses `" ".join(query_terms)`.
  When `query_terms` is empty the function still returns the first `max_chunks` candidates unranked, as today,
  whatever `dense_query` is.
- `rerank_pieces: int | None = None`. When set and `parents` is given and a reranker runs, each pool parent is scored
  on one text instead of its own full text (rule below). The chunks returned, their `chunk_id`s and the
  reranker scores in `explain` stay keyed by parent. When `parents` is `None` this parameter does nothing; when it is `None`, nothing changes.
- `drop_overlaps: bool = False`. When true, the overlap rule below runs on the final ordering before the cut at
  `max_chunks`.

**Field query.** `field_evidence` builds it as

```python
"\n".join(s.strip() for s in (field.name, field.description, field.extraction_instructions) if s.strip())
```

and passes it as `dense_query` when `retrieval_field_query_enabled` is true and the result is not empty; else
it passes `None`. It passes the same `dense_query` to both of its `select_relevant_chunks` calls (the
small-to-big call and the high-risk fallback over plain chunks). The keywords passed as `query_terms` do not change.

**Rerank piece of a parent.** A parent's pieces are the candidates whose `parents[...]` is that parent. Each
piece gets a piece score: with hybrid off, its BM25 score (pieces with no BM25 score after `require_hit` are not
eligible); with hybrid on, its reciprocal-rank-fusion score (`_rrf_fuse`, k = 60) over BM25's list of pieces
(after `require_hit`) and the vector ranking of pieces, i.e. the rankings before they are mapped to parents. A
parent's rerank piece is its eligible piece with the highest piece score; pieces with equal piece scores count as
tied, and a tie goes to the piece with the lowest `char_start`. The text scored is that piece's `text` (not its
index text). A table passage is its own parent and its own only piece; when its `text` is longer than the limit
the reranker gets `text[:limit]`. `select_relevant_chunks` reads no settings, so `field_evidence` passes the limit
in the same parameter: `rerank_pieces=settings.small_chunk_chars` when `rerank_small_pieces_enabled` is on, else
`None`.

**Overlap rule.** Walk the final ordering (the reranked pool when a reranker scored it, else the fused, BM25 or
unranked order) from best to worst and keep a passage unless an already-kept passage of the same `doc_id`
covers at least 80 % of its characters:

```
covered = max(0, min(A.char_end, B.char_end) - max(A.char_start, B.char_start))
drop B  if  covered >= 0.8 * (B.char_end - B.char_start)        # A kept and ranked above B
```

The share is always taken of the lower-ranked passage B. Passages of different documents never drop each
other. Then cut the kept list at `max_chunks`; `near_misses` are the next up to 3 of the kept list. With a
reranker on, the whole pool is reranked (not only the best `max_chunks`), then the rule runs, then the cut. A
list with fewer than `max_chunks` passages after the rule is returned as it is, without refilling from dropped
ones. With `query_terms` empty, `drop_overlaps` does nothing (the early return of the first `max_chunks`
candidates is unchanged). `field_evidence` passes `drop_overlaps` to both of its calls.

**Fail open.** When the reranker returns no scores (model missing, error, wrong count) the order is the
retrieval order, exactly as today, and the overlap rule (if on) runs on that order.

## Defaults taken

- All three switches default `False` (brief: defaults stay as today; Steffen flips on the numbers).
- Field query = name, description, instructions joined by newlines, each stripped, blanks skipped. The name is
  included because it is the shortest exact statement of the field; long instructions are cut by the embedder's
  own token limit, so name and description come first.
- Overlap threshold fixed at 80 % of the lower-ranked passage's characters, a constant in code, not a setting
  (one setting per change, brief rule).
- Rerank piece chosen by piece-level RRF with a lowest-`char_start` tie-break; table passages truncated from the
  start, where the caption and header row are.
- The reranker scores raw piece text, as it scores raw chunk text today (no context header).
- No new `explain` keys: the trace spec owns `explain`; the rows below observe this item through the returned
  chunks and the texts given to the patched scorer and embedder.
- One PR. The three changes are small and share `select_relevant_chunks`; slicing would make three PRs edit the
  same function in a row.

## PR body report (not an acceptance row)

The PR body reports, old (all three off) vs each switch on alone vs all three on, from
`cd backend && arp golden-set retrieval --cases tests/golden/retrieval/cases.json` (cases mode downloads the two
PDFs listed in `tests/golden/retrieval/documents.json` and checks their hashes; it needs Postgres, as the CI job
"Retrieval gold set" does): recall at 12,
passages sent per field (mean), median seconds per field with `rerank_enabled` on, and the CPU core count. If the
gold-set PDFs or Postgres are not available in the build environment, it says so plainly and reports nothing
measured.

## Slices

None: one PR (`Spec: extraction-retrieval-bundle`, no `Rows:` line). The builder starts only after
`extraction-trace-parse-report` has merged, and merges `origin/main` in first.

## Acceptance

All rows are `holdout`: backend tests with fixture documents or chunks, no LLM, no network. Test setup:

- Stub scorer: `monkeypatch.setattr(arp.retrieval.rerank, "_score", stub)` and
  `monkeypatch.setattr(arp.retrieval.rerank, "_unavailable", False)` (restored after each test);
  `ARP_COMPUTE_MODELS_URL` unset in the environment and the `get_settings` cache cleared, so the local path that
  calls `_score` runs.
- Stub embedder: `arp.retrieval.embeddings.embed_texts` patched to return fixed vectors and record its calls;
  content store = a dict-backed object with `lookup_embeddings(ids, model)` (returns only stored keys) and
  `store_embeddings(vectors, model)`, starting empty. For `field_evidence`, patch
  `arp.retrieval.content_store_factory.build_hybrid_content_store` to return it.
- Every fixture uses `chunk_id`s and `doc_id`s unique to its test, or the test clears
  `arp.retrieval.index_cache.INDEX_CACHE` (the BM25 index is cached by chunk ids).
- "The AC-3 fixture": one field with `seed_keywords=["capex"]`, one `SourceDocument` with `#` headings, a table
  passage longer than 800 characters and text chunks overlapping it, every ranked part containing `capex`.
- "Ranked A, B, C, ..." for `select_relevant_chunks` rows: called as
  `select_relevant_chunks(chunks, ["capex"], require_hit=False, ...)` where each better-ranked chunk's text has
  more occurrences of `capex` than the next (same length otherwise), so BM25 scores strictly decrease; the test
  first checks that order with the new parameters absent.

"Settings" means a `Settings` passed to `field_evidence`; unless a row says otherwise:
`retrieval_backend="bm25"`, `hybrid_retrieval_enabled=False`, `rerank_enabled=False`,
`small_to_big_enabled=True`, `small_chunk_chars=800`, `evidence_max_chunks=12`, `rerank_candidates=40`, and the
three new switches `False`. "Main" is `main` at the commit the test is written on.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | A fresh `Settings()` with no `ARP_*` variables for the new names | read the three fields | `retrieval_field_query_enabled`, `rerank_small_pieces_enabled` and `evidence_overlap_removal_enabled` are each `False` | holdout |
| AC-2 | Env `ARP_RETRIEVAL_FIELD_QUERY_ENABLED=true`, `ARP_RERANK_SMALL_PIECES_ENABLED=true`, `ARP_EVIDENCE_OVERLAP_REMOVAL_ENABLED=true` | `Settings()` | all three fields are `True` | holdout |
| AC-3 | The AC-3 fixture, all three switches off, `small_to_big_enabled` True and then False, `rerank_enabled` False | `field_evidence` | the returned `chunk_id`s, in order, equal those main returns for the same inputs and settings | holdout |
| AC-4 | Same fixture, all three switches off, `small_to_big_enabled=True`, `rerank_enabled=True`, stub scorer recording its calls | `field_evidence` | the returned `chunk_id`s in order, and every (query, texts) pair the scorer received, equal main's | holdout |
| AC-5 | Same fixture, all three switches off, `hybrid_retrieval_enabled=True`, stub embedder recording its calls | `field_evidence` | the returned `chunk_id`s in order, and the `embed_texts` call whose argument is a one-element list whose element is not the text or index text of any candidate (the query call), equal main's | holdout |
| AC-6 | All three switches `True` in the environment; fixture chunks with overlapping spans; stub scorer | `select_relevant_chunks` called with only main's parameters (incl. `rerank_candidates=40`, `parents` map) | result `chunk_id`s in order, and the scorer's (query, texts) calls, equal main's for the same call | holdout |
| AC-7 | `retrieval_field_query_enabled=True`, `rerank_enabled=True`, field `name="Scope 1 emissions"`, `description=" Direct GHG emissions. "`, `extraction_instructions="Use the group total."`, `seed_keywords=["scope 1"]`, a fixture document containing `scope 1` | `field_evidence` | the stub scorer is called at least once, and every query it receives is exactly `"Scope 1 emissions\nDirect GHG emissions.\nUse the group total."` | holdout |
| AC-8 | AC-7's field and document, `retrieval_field_query_enabled=True`, `hybrid_retrieval_enabled=True`, the dict-backed store (empty), stub embedder | `field_evidence` | the query call to `embed_texts` (one-element list whose element is not the text or index text of any candidate) has exactly the element `"Scope 1 emissions\nDirect GHG emissions.\nUse the group total."` | holdout |
| AC-9 | Same field and fixture, `hybrid_retrieval_enabled=False`, `retrieval_field_query_enabled` False, then True | `field_evidence(..., explain={})` | the `bm25` score of every chunk id in `explain["scores"]` is identical in both runs | holdout |
| AC-10 | `retrieval_field_query_enabled=True`, `rerank_enabled=True`, field with `name=""`, `description="  "`, `extraction_instructions=""`, `seed_keywords=["revenue"]`, a fixture document containing `revenue` | `field_evidence` | the stub scorer is called at least once, and every query it receives equals the scorer query of the same call with the switch off | holdout |
| AC-11 | `retrieval_field_query_enabled=True`, `rerank_enabled=True`, field with `seed_keywords=[]` and a non-empty description | `field_evidence` | returned `chunk_id`s equal those with the switch off, and the stub scorer is not called | holdout |
| AC-12 | `rerank_small_pieces_enabled=True`, `rerank_enabled=True`, `small_chunk_chars=800`, fixture whose ranked parents include sections longer than 800 characters and a table passage longer than 800 characters | `field_evidence` | the stub scorer is called at least once, and every text it receives has `len(text) <= 800` | holdout |
| AC-13 | Same settings; a parent section with pieces P1 and P2 where P2 has the higher BM25 score, hybrid off | `field_evidence` | the scorer's text for that parent is exactly P2's text (the `small_pieces` piece text, no header line) | holdout |
| AC-14 | Same settings; a parent section with two pieces that have identical text (so equal BM25 scores) | `field_evidence` | the scorer's text for that parent equals the piece with the lower `char_start` | holdout |
| AC-15 | Same settings; a table passage of 1,500 characters among the pool | `field_evidence` | the scorer's text for it is exactly the passage's first 800 characters | holdout |
| AC-16 | Same settings; stub scorer giving each text a distinct score | `field_evidence` | every returned chunk is a parent (its `chunk_id` is a value's id in the `piece_parents` map or a table passage), ordered by the score its rerank piece got, highest first, at most `evidence_max_chunks` | holdout |
| AC-17 | Same settings, hybrid off | `field_evidence` | the stub scorer is called exactly once, with exactly `min(rerank_candidates, P)` texts, where P is the number of distinct parents of pieces (and table passages) with BM25 score > 0 | holdout |
| AC-18 | `rerank_small_pieces_enabled=True`, `rerank_enabled=True`, `small_to_big_enabled=False` | `field_evidence` | the scorer's (query, texts) calls equal those with `rerank_small_pieces_enabled=False` | holdout |
| AC-19 | `rerank_small_pieces_enabled=True`, `rerank_enabled=True`, stub scorer raising `RuntimeError` | `field_evidence` | no exception; returned `chunk_id`s equal the same call with `rerank_enabled=False` | holdout |
| AC-20 | Fixture chunks of one document ranked A above B, B = chars 100-200, A covers chars 120-200 of it (80 of 100) | `select_relevant_chunks(chunks, ["capex"], require_hit=False, max_chunks=12, drop_overlaps=True)`, chunks ranked A, B as in the preamble | B is not returned | holdout |
| AC-21 | As AC-20 but A covers chars 121-200 (79 of 100) | same call as AC-20 | both A and B are returned, A first | holdout |
| AC-22 | As AC-20 but A and B have the same offsets and different `doc_id`s | same call as AC-20 | both are returned | holdout |
| AC-23 | Overlap on; A ranked first is chars 0-100, B ranked second is chars 0-400 of the same document | same call as AC-20 | both are returned (A covers 25 % of B) | holdout |
| AC-24 | Ranked A, B, C, D, E; B is 90 % covered by A; no other pair overlaps | `select_relevant_chunks(chunks, ["capex"], require_hit=False, max_chunks=3, drop_overlaps=True, explain={})` | returned `chunk_id`s are exactly `[A, C, D]`; `explain["near_misses"] == ["E"]` | holdout |
| AC-25 | Ranked A, B, C; B and C each fully covered by A | `select_relevant_chunks(chunks, ["capex"], require_hit=False, max_chunks=3, drop_overlaps=True)` | returned `chunk_id`s are exactly `[A]` | holdout |
| AC-26 | Ranked A, B, C; B covers 90 % of A; C overlaps neither; stub scorer giving B > A > C | `select_relevant_chunks(chunks, ["capex"], require_hit=False, max_chunks=2, rerank_candidates=3, drop_overlaps=True)` | returned `chunk_id`s are exactly `[B, C]` | holdout |
| AC-27 | Ranked A, B, C; B 90 % covered by A; C overlaps neither; stub scorer raising `RuntimeError` | `select_relevant_chunks(chunks, ["capex"], require_hit=False, max_chunks=2, rerank_candidates=3, drop_overlaps=True)` | returned `chunk_id`s are exactly `[A, C]` | holdout |
| AC-28 | The AC-20 chunks | the AC-20 call without `drop_overlaps` | both A and B are returned, A first | holdout |
| AC-29 | `evidence_overlap_removal_enabled=True`, `small_to_big_enabled=False`, a field whose fixture document yields two chunks with one 90 % covered by the better-ranked one | `field_evidence` | the covered chunk is not returned; with the switch `False` it is | holdout |
| AC-30 | Ranked A, B with B fully covered by A | `select_relevant_chunks(chunks, [], max_chunks=12, drop_overlaps=True)` | both A and B are returned, in input order | holdout |

Must not change: picks, order and reranker inputs with every switch off (AC-3, AC-4, AC-5); callers that pass
only main's parameters (AC-6); BM25's query (AC-9); fail-open reranking (AC-19, AC-27); behaviour of
keyword-less fields (AC-11).
