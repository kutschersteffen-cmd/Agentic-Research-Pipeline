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
   Pieces are cached like today's spans (`ChunkSpanCache`, with `small_chunk_chars` in the key, so a changed
   size never returns stale pieces).
4. Whole-table passages are not cut: they stay as they are, are ranked as themselves (with their `Table:` header
   line) and are their own parent.

### 2. Parents

Each piece has exactly one parent, a `DocumentChunk` whose offsets are `full_text` offsets. A section's length is
`char_end - char_start` of its outline entry, heading line included (for the text before the first heading: its
whole span).

1. The section that holds the piece, when that section's length is at least `section_min_chars` (800) and at most
   `chunk_chars` (`DEFAULT_CHUNK_CHARS` in `arp/ingestion/parsing.py`, 3,500; a constant, not a setting). Its `section` is the section's title (None for text before the first heading); its id is
   `chk_{doc_id}_{start}_{end}`.
2. Otherwise (shorter, longer, or a document without headings): the non-table chunk of `chunk_document(doc)`
   (under the same settings; ids without `_table_`) with the lowest `char_start` that holds the whole piece; if
   none holds all of it, the non-table chunk that overlaps it most, lower `char_start` on a tie. Whole-table
   passages are never a rule-2 parent.

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
   piece's score (a Walkthrough display detail, no AC row); `vector_rank` is its rank in the collapsed vector ranking, 1-based as today; `rrf` is its fused score. `explain`
   also gets `small_to_big: true`.

Evidence passed to the extractor, grounding (`arp/grounding.py`, unchanged) and citations all use parents, whose
offsets are `full_text` offsets.

### 4. Run settings

`small_to_big_enabled` joins the run settings that change extraction output (`arp/extraction/pipeline.py`, the
`input_settings` list), so `input_hash` differs between on and off and cached results are not replayed.

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

Every row is `unit` or `golden`: retrieval has no API or CLI surface a holdout test could drive without importing the app's code (the `test-writer` rule), and several rows need monkeypatched stand-ins. The PR lists no holdout rows as owed.

Conventions for every row: ranks count from 0, except `vector_rank` (1-based, as today). "Off" is
`small_to_big_enabled=False`; "on" is `small_to_big_enabled=True`, set through `ARP_SMALL_TO_BIG_ENABLED` so
`chunk_document` and `field_evidence` see the same settings. "Hybrid off" is `hybrid_retrieval_enabled=False` (BM25
only, deterministic). `chunk_chars` is the constant `DEFAULT_CHUNK_CHARS` (3,500, not a setting); `section_min_chars` 800, `small_chunk_chars` 800,
`section_chunking_enabled` off, `context_headers_enabled` on, unless a row says otherwise. Fields are not high-risk
and have no `document_routing` unless a row says so. Tests that need the embedding ranking replace
`arp.retrieval.embeddings.embed_texts` with a stand-in returning fixed vectors; tests that need the reranker replace
`arp.retrieval.rerank.rerank` with a recording stand-in (monkeypatch). "Evidence" is `field_evidence(field,
documents, settings)`. A filler sentence is a distinct sentence of about 80 characters with none of the field's
keywords and none of the document title's words. "Section X's span" is (offset of the `# X` line, offset of the
next heading line or the end of the text).

**Doc T** (used by several rows): title `Report 2024`; `# Intro` (2,000 chars of filler), `# Targets` (1,500 chars:
filler plus one sentence containing `net zero 2040`), `# Other` (2,000 chars of filler). Field keyword `net zero`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-0  | Off; the documents and fields of `backend/tests/golden/retrieval/cases.json`, hybrid off | evidence for each case | The same chunk ids in the same order as on `main` (snapshot) | unit |
| AC-1  | No env | `Settings()` | `small_to_big_enabled is False` | unit |
| AC-17 | No env | `Settings()` | `small_chunk_chars == 800` | unit |
| AC-18 | Env `ARP_SMALL_TO_BIG_ENABLED=true` | `Settings()` | `small_to_big_enabled is True` | unit |
| AC-2  | `# A` with 3,000 chars of filler, then `# B` with 3,000 chars of filler | `small_pieces(doc, settings)` | Every piece has `len(text) <= 800` | unit |
| AC-2b | As AC-2 | `small_pieces(doc, settings)` | No piece has `char_start < offset(# B) < char_end` | unit |
| AC-2c | As AC-2 | `small_pieces(doc, settings)` | The union of the pieces' `[char_start, char_end)` is exactly `[0, len(full_text))` | unit |
| AC-2d | As AC-2 | `small_pieces(doc, settings)` | Every piece's `chunk_id == f"chk_{doc_id}_{char_start}_{char_end}"` | unit |
| AC-2e | As AC-2 | `small_pieces(doc, settings)` | Every piece with `char_start >= offset(# B)` has `section == "B"` | unit |
| AC-2f | As AC-2, plus a table span inside `# A` | `small_pieces(doc, settings)` | The union of the pieces' `[char_start, char_end)` is exactly `[0, len(full_text))` | unit |
| AC-22 | As AC-2 | `small_pieces` with `small_chunk_chars` 800, then with 400 | Every piece of the second call has `len(text) <= 400` | unit |
| AC-3  | Doc T; on, hybrid off, `evidence_max_chunks` 1 | evidence | `[(c.char_start, c.char_end, c.section)] == [(*span of Targets, "Targets")]` | unit |
| AC-4  | Doc T, but `# Targets` is 300 chars (filler plus the `net zero 2040` sentence); on, hybrid off, `evidence_max_chunks` 1 | evidence | One chunk; its id is the id of the non-table chunk `c` of `chunk_document(doc)` with the lowest `char_start` such that `c.char_start <= p.char_start` and `p.char_end <= c.char_end`, where `p` is the piece of `small_pieces(doc, settings)` that contains the `net zero 2040` sentence | unit |
| AC-5  | Doc T, but `# Targets` is 8,000 chars with the `net zero 2040` sentence at about char 5,000 of it; on, hybrid off, `evidence_max_chunks` 1 | evidence | One chunk; its id is the id of the non-table chunk `c` of `chunk_document(doc)` with the lowest `char_start` such that `c.char_start <= p.char_start` and `p.char_end <= c.char_end`, where `p` is the piece of `small_pieces(doc, settings)` that contains the `net zero 2040` sentence | unit |
| AC-23 | No headings: 1,200 chars of filler plus one `net zero 2040` sentence, then 6,000 chars of filler; on, hybrid off, `evidence_max_chunks` 1 | evidence | One chunk; its id is `chunk_document(doc)[0].chunk_id` | unit |
| AC-24 | 1,200 chars of filler plus one `net zero 2040` sentence, then `# A` with 3,000 chars of filler; on, hybrid off, `evidence_max_chunks` 1 | evidence | `[(c.char_start, c.char_end, c.section)] == [(0, offset(# A), None)]` | unit |
| AC-6  | Filler sections, `# P` (1,500 chars: `net zero` in a sentence at its start and in one at its end), filler, `# Q` (1,500 chars: one `net zero` sentence), filler; on, hybrid off, `evidence_max_chunks` 2 | evidence | The ids, as a set, are exactly {P's section chunk, Q's section chunk} | unit |
| AC-25 | As AC-6, `evidence_max_chunks` 1, `explain={}` | evidence | `[c.chunk_id for c in explain["near_miss_chunks"]] == explain["near_misses"]` | unit |
| AC-25b | As AC-25 | evidence | `explain["near_misses"][0]` is whichever of P's and Q's section chunk ids is not in the evidence | unit |
| AC-26 | As AC-25 | evidence | `set(explain["scores"]) == {P's section chunk id, Q's section chunk id}` | unit |
| AC-7  | A doc with one table span whose caption holds `emissions`; field keyword `emissions`; on, hybrid off | evidence | Contains `chk_{doc_id}_table_{start}_{end}` for that table, with `text == full_text[start:end]` | unit |
| AC-8  | Title `Zephyr Report 2024`; one `# Plan` section of 1,500 chars of filler (no `zephyr` anywhere in the body); field keyword `zephyr`; on, hybrid off | evidence | `[c.chunk_id for c in evidence] == [Plan's section chunk id]` | unit |
| AC-19 | As AC-8, `context_headers_enabled=False` | evidence | `evidence == []` | unit |
| AC-9  | Only sections P, Q, R (1,500 chars each); BM25 ranks pieces `p1`, `p2` (in P), then `q1` (in Q) and nothing else; stand-in vectors put `q1`, `r1` (in R), `p1` first, in that order, ahead of every other piece; on, hybrid on | evidence | `[c.chunk_id for c in evidence] == [Q, P, R]` (section chunk ids) | unit |
| AC-27 | As AC-9, `explain={}` | evidence | `explain["scores"][Q]["rrf"] == 1/61 + 1/62` | unit |
| AC-28 | As AC-9, `explain={}` | evidence | `explain["small_to_big"] is True` | unit |
| AC-31 | As AC-9, `explain={}` | evidence | `explain["scores"][P]["vector_rank"] == 3` | unit |
| AC-32 | As AC-9, `explain={}` | evidence | `explain["scores"][R]["vector_rank"] == 2` | unit |
| AC-10 | Doc T; on, hybrid off, rerank on with a recording stand-in | evidence | The stand-in receives exactly one chunk, with `(char_start, char_end)` = span of Targets | unit |
| AC-11 | Doc T; on, hybrid off | evidence | For every returned chunk, `text == doc.full_text[char_start:char_end]` | unit |
| AC-29 | Doc T plus a field with `document_routing.sections == ["Targets"]`; on, hybrid off, `evidence_max_chunks` 3 | evidence | `[c.chunk_id for c in evidence] == [Targets' section chunk id]` | unit |
| AC-12 | A high-risk field (`fallback_to_all`), no keyword anywhere in the doc; on, hybrid off | evidence | The same chunk ids in the same order as with off | unit |
| AC-13 | `retrieval_backend="opensearch"` with a stand-in client; on | evidence | The same chunk ids in the same order as with off | unit |
| AC-30 | Doc T; on | `select_relevant_chunks(chunk_document(doc, keywords=["net zero"]), ["net zero"], max_chunks=3)` (the call shape of every caller but `field_evidence`) | The same chunk ids in the same order as with off | unit |
| AC-14 | `Settings(anthropic_api_key="x")` with on vs off | `input_settings(settings)` | The two dicts differ | unit |
| AC-21 | Off | `input_settings(Settings(anthropic_api_key="x"))` | Equals `main`'s result for the same call (no new key) | unit |
| AC-15 | Off, the bundled extraction golden set | `arp golden-set run` | Every case passes, as on `main` | golden |
| AC-16 | Off, the retrieval gold set | the `Retrieval recall` CI job | Passes with the floor in the workflow file, unchanged | golden |

Must not change: evidence with the setting off (AC-0, AC-16), whole-table passages (AC-7), evidence offsets and
text, so grounding (AC-11), section routing (AC-29), the high-risk fallback (AC-12), OpenSearch retrieval (AC-13),
other callers of `select_relevant_chunks` (AC-30), run settings with it off (AC-21), the extraction golden set (AC-15).

PR checklist (not ACs): the PR description lists `main`'s and the PR's recall@5 and recall@12 from
`arp golden-set retrieval --cases backend/tests/golden/retrieval/cases.json` with the setting on and off, the
eval's wall time for both, and whether the switch-on gate is met.
