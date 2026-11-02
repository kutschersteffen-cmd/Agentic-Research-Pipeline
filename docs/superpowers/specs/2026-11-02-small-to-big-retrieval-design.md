# Small-to-big retrieval

Spec slug: `small-to-big-retrieval`. Item 5d of the RAG improvement plan
(https://claude.ai/artifact/RnMhVmhQNmJPwY8UCaY38t). Builds on spec `section-chunks-context-headers-document-tree`
(the outline in `arp/ingestion/outline.py`, context headers in `arp/retrieval/index_text.py`) and is measured
with spec `retrieval-gold-set-and-question-queries` (the `Retrieval recall` gate).

## Why

Today one ~3,500-character chunk is both the unit that is ranked and the unit the extractor reads. Those want
different sizes:

1. **Ranking wants small units.** A 3,500-character chunk mixes several topics; its BM25 statistics and its
   embedding are an average of all of them, so the one sentence that answers a field is diluted.
2. **Reading wants large units.** The extractor needs the surrounding sentences, the heading and the table
   the figure belongs to.

Small-to-big ranks small pieces and hands the extractor each winning piece's larger parent.

### Why section-bounded chunking lowered recall@5 (and what this design does about it)

`section_chunking_enabled` (5b) measured recall@5 42.6% against 47.1% on `main` and stayed off. Not proven,
but the likely causes are:

1. **Less text per slot.** Section-bounded chunks are often much shorter than 3,500 characters (short sections,
   the short tail of a long section). Recall@k counts slots, so the top 5 then hold less text and contain fewer
   gold spans.
2. **Short chunks win BM25.** BM25's length normalisation favours a short chunk that repeats a query term (a
   heading plus two lines) over a long chunk that holds the answer, so short, thin chunks crowd the top 5.
3. **Measured before context headers.** 5b was measured with headers off; a chunk that starts at an inner
   heading lost the outer headings' words. Headers (on since #309) now add them back.

This design answers each: (1) a parent is never a short section; a section shorter than `section_min_chars`
(800) hands back today's chunk instead, so every slot holds about as much text as today. (2) Small pieces are
only *ranked*; several hits in one parent count once, so a parent cannot fill several slots with thin pieces.
(3) Pieces are indexed with context headers.

## What changes

One new setting, **off by default**: `small_to_big_enabled: bool = False` (env `ARP_SMALL_TO_BIG_ENABLED`),
plus `small_chunk_chars: int = 800` (about 200 tokens at ~4 characters per token). With it off nothing changes.

### Scope

Only extraction fields: `field_evidence` in `arp/extraction/field_graph.py` (what `arp golden-set retrieval`
replays). The other callers of `select_relevant_chunks` (financials, TNFD, theme matching, RFP, replication,
news mining, engagement) are unchanged. With `retrieval_backend == "opensearch"` the setting has no effect:
the `arp-chunks` index holds today's chunks, not pieces.

### 1. Small pieces

New public function `arp.ingestion.parsing.small_pieces(doc, settings) -> list[DocumentChunk]`:

1. The document is cut at its outline's headings (`outline(doc)`; text before the first heading is one more
   section; a document without headings is one section). Short sections are **not** joined.
2. Each section is split with the existing `_sentence_aware_split(text, small_chunk_chars, 0)`: sentence-aligned,
   no overlap, never across a heading. Together the pieces cover every character of `full_text` (the existing
   coverage fill), including text inside tables.
3. A piece is a `DocumentChunk` with the same id format (`chk_{doc_id}_{start}_{end}`), offsets into
   `full_text`, and `section` set the same way today's chunks get it (the last heading at or before its start).
   Pieces are cached like today's spans (`ChunkSpanCache`, with `small_chunk_chars` in the key).
4. Whole-table passages are not cut: they stay as they are, are ranked as themselves (with their `Table:` header
   line) and are their own parent.

### 2. Parents

Each piece has exactly one parent, a `DocumentChunk` whose offsets are `full_text` offsets:

1. The outline section that holds the piece, when that section is at least `section_min_chars` (800) and at most
   `chunk_chars` (3,500) long. Its `section` is the section's title; its id is `chk_{doc_id}_{start}_{end}`.
2. Otherwise (shorter, longer, or no headings): the chunk from today's `chunk_document` that holds the whole
   piece; if no chunk holds all of it, the one that overlaps it most; on a tie, the earlier one.

A whole-table passage is its own parent.

### 3. Ranking with pieces

In `field_evidence`, with the setting on (and backend `bm25`):

1. Candidates are the pieces plus the whole-table passages of the routed documents. `section_filter` runs on them
   as it runs on today's chunks; no new code routes, filters or drops anything by structure.
2. Index text: `index_text(piece, doc, settings)`, so context headers apply to pieces exactly as to chunks.
3. BM25 ranks the candidates (`require_hit` as today). With hybrid on, the embedding ranking ranks them too,
   embeddings cached per piece as today (`_embedding_key`).
4. **Collapse per ranking, before fusion:** each ranking becomes a ranking of parents: a parent takes the rank of
   its best piece in that ranking, and its later pieces are dropped from that ranking. With hybrid on, the two
   parent rankings are fused by RRF exactly as chunk rankings are today.
5. The reranker (when on) scores the parents' own `text`, then the best `evidence_max_chunks` parents are kept.
   Without it, the top `evidence_max_chunks` parents of the (fused) ranking are kept.
6. `fallback_to_all` with no hit returns today's chunks in document order, as with the setting off.
7. `explain`: `scores`, `near_misses` and `near_miss_chunks` are keyed by parent ids. A parent's `bm25` is its best
   piece's score; `vector_rank` is its rank in the collapsed vector ranking; `rrf` is its fused score. `explain`
   also gets `small_to_big: true`.

Evidence passed to the extractor, grounding (`arp/grounding.py`, unchanged) and citations all use parents, whose
offsets are `full_text` offsets.

### 4. Run settings

`small_to_big_enabled` joins the run settings that change extraction output (`arp/extraction/pipeline.py`, the
`**({"…": True} if …)` list), so `input_hash` differs between on and off and cached results are not replayed.

### Switching it on

A separate one-line PR flips the default, only if `arp golden-set retrieval --cases
backend/tests/golden/retrieval/cases.json` with the setting on shows **recall@12 ≥ `main`** (64.7% today) and
**recall@5 ≥ `main` − 3 points** (`main` 45.6% today, so ≥ 42.6%). This PR does not switch it on.

## Approaches considered

1. **Small pieces ranked, parents returned (chosen).** Ranking precision of small units, reading context of
   large ones; slots keep today's size.
2. **Smaller chunks everywhere.** Rank and read the same small unit. Rejected: it is what lowered recall@5 in 5b,
   and the extractor would lose context.
3. **Today's chunks plus a neighbour window ("sentence window").** Rank today's chunks and add the chunks before
   and after. Rejected: ranking stays as diluted as today, and context per field triples.

Owner decisions (2026-11-02): parent = the section only when it is 800–3,500 characters, otherwise today's chunk;
pieces collapse to parents per ranking before RRF; only extraction fields get the setting.

## Non-goals

- Switching it on (separate PR, gated as above).
- OpenSearch indexing of pieces; other callers of `select_relevant_chunks`.
- Changing `section_chunking_enabled`, the outline, context headers, grounding or whole-table passages.
- Any routing, filtering or dropping of chunks by structure.

## Left to the builder

- How pieces and their parent map are cached (the span cache or a sibling), as long as the off path is untouched.
- Embedding cost: roughly 4× more vectors per document on first use, cached afterwards. The PR reports the
  `golden-set retrieval` wall time on and off.

## Acceptance

Conventions for every row: ranks count from 0. "Off" is `small_to_big_enabled=False`; "on" is
`small_to_big_enabled=True`. "Hybrid off" is `hybrid_retrieval_enabled=False` (BM25 only, deterministic).
`chunk_chars` 3,500, `section_min_chars` 800, `small_chunk_chars` 800 unless a row says otherwise. Tests that need
the embedding ranking replace `arp.retrieval.embeddings.embed_texts` with a stand-in (monkeypatch); tests that need
the reranker replace `arp.retrieval.rerank.rerank` with a recording stand-in. "Evidence" is `field_evidence(field,
documents, settings)`. A filler sentence is a distinct sentence of about 80 characters with none of the field's
keywords.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-0  | Off; the documents and fields of `backend/tests/golden/retrieval/cases.json`, hybrid off | evidence for each case | The same chunk ids in the same order as on `main` (snapshot) | holdout |
| AC-1  | Settings default | `Settings()` | `small_to_big_enabled is False` and `small_chunk_chars == 800`; with env `ARP_SMALL_TO_BIG_ENABLED=true`, `small_to_big_enabled is True` | unit |
| AC-2  | `# A` with 3,000 chars of filler sentences, then `# B` with 3,000 chars of filler sentences | `small_pieces(doc, settings)` | Every piece is ≤ 800 chars; no piece contains the `# B` line's offset unless it starts there; the pieces' spans cover every offset `0 … len(full_text)-1` | holdout |
| AC-3  | Doc: `# Intro` (2,000 chars of filler), `# Targets` (1,500 chars: filler plus one sentence with `net zero 2040`), `# Other` (2,000 chars of filler); field keyword `net zero`; on, hybrid off, `evidence_max_chunks` 1 | evidence | One chunk, with `char_start` = offset of the `# Targets` line, `char_end` = offset of the `# Other` line, `section == "Targets"` | holdout |
| AC-4  | As AC-3, but `# Targets` is 300 chars (filler plus the `net zero 2040` sentence) | evidence | One chunk whose id is in `[c.chunk_id for c in chunk_document(doc)]` and whose text contains `net zero 2040` | holdout |
| AC-5  | As AC-3, but `# Targets` is 8,000 chars with the `net zero 2040` sentence at about char 5,000 of it | evidence | One chunk whose id is in `[c.chunk_id for c in chunk_document(doc)]` and whose text contains `net zero 2040` | holdout |
| AC-6  | Doc: `# P` (1,500 chars: two separate sentences with `net zero`, at its start and end), `# Q` (1,500 chars: one sentence with `net zero`), each between filler sections; on, hybrid off, `evidence_max_chunks` 2 | evidence | Two chunks: the `# P` section and the `# Q` section, each once | holdout |
| AC-7  | A doc with one table span whose caption holds `emissions`; field keyword `emissions`; on, hybrid off | evidence | Contains the chunk `chk_{doc_id}_table_{start}_{end}` of that table, text equal to `full_text[start:end]` | holdout |
| AC-8  | Doc titled `Zephyr Report 2024`; a 1,500-char section whose body never says `zephyr`; field keyword `zephyr`; context headers on, on, hybrid off | evidence | Contains that section's chunk; with `context_headers_enabled=False` the evidence is empty | holdout |
| AC-9  | Pieces such that BM25 ranks `p1`, `p2` (both in section P), then `q1` (section Q); the embedding stand-in ranks `q1`, `r1` (section R), then `p1`; sections P, Q, R each 1,500 chars; on, hybrid on, `explain={}` | evidence | Order is Q, P, R; `explain["scores"][Q]["rrf"] == 1/61 + 1/62`; `explain["small_to_big"] is True` | holdout |
| AC-10 | As AC-3, rerank on, recording stand-in | evidence | Every chunk the stand-in receives is a parent: the `# Targets` section's chunk is among them and no received chunk is shorter than 800 chars | holdout |
| AC-11 | A doc whose only `net zero` sentence sits in a parent section | extraction with a stand-in model quoting that sentence, on | The citation is `grounded: true` and `full_text[char_start:char_end]` normalises to the quote | holdout |
| AC-12 | A high-risk field (`fallback_to_all`), no keyword in the doc; on, hybrid off | evidence | The same chunk ids in the same order as with off | holdout |
| AC-13 | `retrieval_backend="opensearch"` with a stand-in client; on | evidence | The same chunk ids in the same order as with off | unit |
| AC-14 | The same field and documents | `input_hash` with on vs off | The two hashes differ; with off it equals `main`'s hash | holdout |
| AC-15 | Off, the bundled extraction golden set | `arp golden-set run` | Every case passes, as on `main` | golden |
| AC-16 | Off, the retrieval gold set | the `Retrieval recall` CI job | Passes with the floor in the workflow file, unchanged | golden |

Must not change: evidence with the setting off (AC-0, AC-16), whole-table passages (AC-7), grounding (AC-11),
the high-risk fallback (AC-12), OpenSearch retrieval (AC-13), the extraction golden set (AC-15).

PR checklist (not ACs): the PR description lists `main`'s and the PR's recall@5 and recall@12 from
`arp golden-set retrieval --cases backend/tests/golden/retrieval/cases.json` with the setting on and off, the
eval's wall time for both, and whether the switch-on gate is met.
