# Tree context for chunks

Spec slug: `tree-context-for-chunks`. Item 2b of the RAG improvement plan
(https://claude.ai/artifact/RnMhVmhQNmJPwY8UCaY38t). Builds on spec `section-chunks-context-headers-document-tree`
(merged in #294): the index text seam (`arp/retrieval/index_text.py`, Part B, on by default since #309) and the
document tree (`arp/ingestion/doc_tree.py`, Part C, `doc_tree_enabled` off).

## Why

Context headers give a chunk its document, period and heading path. They do not say what the section is
*about*: a chunk under `Our approach › Progress` that reports "down 12% against 2019" still has no word like
"Scope 3" or "upstream emissions" for BM25 or the embedding to match. The document tree already stores, per
section and per table, a 2–3 sentence summary and 5–10 key terms, written once per document version. Adding
them to the index text is Anthropic's Contextual Retrieval idea at a fraction of its cost: one summary per node
(~46 calls for a 197-page report) instead of one LLM call per chunk.

## Goals, non-goals, anti-goals

- **Goal:** BM25 and embeddings rank a chunk by its text, its header lines **and** its tree node's summary and
  key terms, behind `tree_context_enabled` (default **off**).
- **Goal:** the switch-on is decided by measurement only (see *Switch-on rule*).
- **Non-goal:** section picking (#6), using the tree in prompts, per-chunk LLM context, changing the tree build.
- **Anti-goals (a failure even if recall goes up):**
  - tree text reaching evidence, prompts, grounding, citations, offsets or the UI. Those use `chunk.text` only;
  - anything routing, filtering or dropping chunks by structure (tree, outline or heading). The tree only
    adds words to what is ranked;
  - retrieval making LLM calls (only fetch/warm and the retrieval eval build trees).

## Approaches considered

1. **Both BM25 and embeddings (chosen by the owner 2026-11-03).** Two more lines in `index_text`. One seam, the
   OpenSearch index stays equal to `index_text(chunk)`, smallest diff. Risk: summary words dilute BM25 for short
   chunks; the recall@5 limit in the switch-on rule catches that.
2. Embeddings only. Keeps BM25 precision, but needs a second index text per chunk and breaks the
   "OpenSearch `text` = `index_text`" rule from the previous spec.
3. Key terms only. Least dilution, but drops the summary the plan asks for.

## What changes

### 1. Setting

`tree_context_enabled: bool = False` in `arp/config.py` (`ARP_TREE_CONTEXT_ENABLED`). It has an effect only when
`context_headers_enabled` is also on (default on): `field_evidence` computes index texts only then, and keeping it
that way avoids a fourth combination nobody will run (builder's call, recorded here).

### 2. Index text

With both settings on, `index_text(chunk, doc, settings)` returns, in order, one line each:

1. the header line (unchanged),
2. the `Table:` line for a table passage (unchanged),
3. `Summary: <node.summary>`,
4. `Terms: <node.key_terms joined with ", ">`, left out when `key_terms` is empty,
5. `chunk.text`.

**The chunk's node** (owner decision 2026-11-03): for a table passage (`table_id` set), the table leaf with that
`table_id`; otherwise the deepest non-root, non-table node whose `[char_start, char_end)` holds `chunk.char_start`.
A chunk that runs past its node's end still gets only that one node's lines.

**No summary** (owner decision 2026-11-03): when the node's `summary` is `null` (its call failed, the tree is
`incomplete`), or no node holds the chunk, lines 3 and 4 are left out. The index text then equals the
headers-only text exactly. The node's parent is **not** used instead.

**No stored tree** (owner decision 2026-11-03): `index_text` only **reads** the tree stored for the document's
`(content_key, parser_version, TREE_VERSION)` (the key `build_doc_tree` stores under); it never builds one and
never calls a model. With no stored tree, lines 3 and 4 are left out for every chunk of that document. A tree
stored under an older `TREE_VERSION` counts as no tree. The builder must not read the database once per chunk:
read once per document per call path (for example a small per-process cache keyed by that triple; a miss must
not be cached, so a tree built later in the same process is picked up).

### 3. Where trees get built

- `DocumentSourceRegistry.fetch_all` (so also `arp documents warm`) builds or reads trees when
  `doc_tree_enabled` **or** `tree_context_enabled` is on (owner decision 2026-11-03), so the switch-on PR flips
  one setting.
- `arp golden-set retrieval` gets `--tree-context/--no-tree-context`, overriding `tree_context_enabled` like
  `--hybrid`. With it on, the eval calls `build_doc_tree` for each document it parsed before ranking (a stored
  complete tree costs nothing), then prints one stderr line
  `Tree context: <k> of <n> nodes have no summary.` (`n` counts non-root nodes over all the eval's documents).
  With it off, the eval makes no model calls, as today.
- Nothing else builds trees. The OpenSearch indexer (`arp/retrieval/search_indexer.py`) uses `index_text` as
  today and so gets tree lines only for documents whose tree is stored.

### 4. Unchanged

Evidence passages, the extractor's prompt, `grounding.py`, citations, offsets and the UI use `chunk.text`. A quote
that matches only tree text is not grounded (it is not in `full_text`). The embedding cache is already keyed by a
hash of the embedded text, so switching tree context on re-embeds each chunk once and switching off reuses the
headers-only vectors. `section_filter`, `route_documents` and `require_hit` are not touched; tree lines can only
make more chunks match a query, never fewer.

## Cost per document

Tree summaries run on `tree_summary_model` (Haiku 4.5, $1 / $5 per million input / output tokens in
`arp/orchestration/cost_tracker.py`), once per document version, never per field or run.

| Report | Calls | Input tokens (est.) | Output tokens (est.) | Cost (est.) |
|--------|-------|---------------------|----------------------|-------------|
| 197 pages | ~46 | ~170k (leaf text capped at 6,000 chars per node, plus child summaries for parents) | ~50k (~100 per node) | ~$0.45 |

Index-time cost after that: one database read per document, a few hundred more characters per chunk for BM25 and
the embedding, and one re-embedding of every chunk the first time the setting is on. The retrieval eval's two
documents cost about $1 once, then nothing while their trees stay stored. The PR records the real calls and tokens
for both eval documents (from the `Tree summaries for …` log lines).

## Switch-on rule

`tree_context_enabled` is switched on by a separate one-line PR only if, on the same commit,
`arp golden-set retrieval --cases backend/tests/golden/retrieval/cases.json --tree-context` shows **recall@12 ≥
main's** (64.7% today) **and recall@5 at most 3 points below main's** (45.6% today, so ≥ 42.6%), with
`Tree context: 0 of <n> nodes have no summary.` (a measurement on incomplete trees does not count).
This spec's PR ships the setting off whatever the numbers are and lists them in its description.

## Left to the builder

The cache shape, where the read lives (`index_text` or `field_evidence`), and the helper that finds a chunk's node.

## Acceptance

Conventions:
- Test document `T`: markdown `full_text` with `# A` (p.1), `## A1` (p.2) holding one table `t1`, `## A2` (p.3),
  `# B` (p.4–5), `page_breaks` set explicitly, title `R`, no `fiscal_period`. "T's tree" is its tree built by
  `build_doc_tree` with the stand-in `model/TreeSummaries.json` giving every node `summary` `"<title> summary."`
  and `key_terms` `["<title> term 1", "<title> term 2"]` (the table leaf's title is its caption `Emissions table`).
- `context_headers_enabled` is on unless a row says otherwise. "Headers-only text" is what `index_text` returns
  with `tree_context_enabled` off.
- Seams: `index_text`, `build_doc_tree`, `TREE_VERSION` (monkeypatched), `chunk_document`, the `embed_texts`
  stand-in, `ARP_STANDINS_DIR`, `calls.jsonl`.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | T's tree stored, `tree_context_enabled` on, a non-table chunk starting inside A1 | `index_text` | Returns the headers-only text with `Summary: A1 summary.\nTerms: A1 term 1, A1 term 2\n` inserted directly before `chunk.text` | holdout |
| AC-2  | Same, the table passage of `t1` | `index_text` | Returns the headers-only text with `Summary: Emissions table summary.\nTerms: Emissions table term 1, Emissions table term 2\n` inserted directly before `chunk.text` | holdout |
| AC-3  | Same, a chunk starting in A's text before the `## A1` line | `index_text` | The `Summary:` line is `Summary: A summary.` | holdout |
| AC-4  | Same, a chunk built in the test (not from `chunk_document`) with `char_start` inside A1 and `char_end` inside A2 | `index_text` | Contains `Summary: A1 summary.`; does not contain `A2 summary.` or `A2 term` | holdout |
| AC-5  | T's tree stored with A1 `summary: null`, `key_terms: []`, `incomplete: true`; setting on; a chunk starting inside A1 | `index_text` | Equals the headers-only text (no `Summary:` or `Terms:` line, and not `A summary.`) | holdout |
| AC-5b | T's tree stored with A1 `summary` `"A1 summary."` and `key_terms: []`; setting on | `index_text` for a chunk inside A1 | Returns the headers-only text with `Summary: A1 summary.\n` inserted directly before `chunk.text` (no `Terms:` line) | holdout |
| AC-6  | No tree stored for T, setting on | `index_text` for every chunk of `chunk_document(T)` | Each equals its headers-only text; no `TreeSummaries` line is added to `calls.jsonl` | holdout |
| AC-6b | T's tree stored, then `arp.ingestion.doc_tree.TREE_VERSION` monkeypatched to its current value + 1 (the lookup reads it from that module at call time), setting on | `index_text` for a chunk inside A1 | Equals the headers-only text; no `TreeSummaries` line is added | holdout |
| AC-6c | No tree stored, setting on; `index_text` called for a chunk of T; then T's tree built in the same process | `index_text` for the same chunk | Contains `Summary: A1 summary.` (for a chunk inside A1) | holdout |
| AC-7  | T's tree stored, `tree_context_enabled` off | `index_text` for each chunk | Equals the headers-only text | holdout |
| AC-7b | T's tree stored, `tree_context_enabled` on, `context_headers_enabled` off | `index_text` | Returns `chunk.text` | holdout |
| AC-8  | All chunks of `chunk_document(T)` plus all chunks of a second document with a stored tree, T's tree stored, BM25 only, `require_hit` on, `evidence_max_chunks` 20, query terms `["zebrafish", "emissions"]` (stand-in key term as in AC-9) | evidence selected with the setting off, then on | The set of chunk ids returned with the setting on is a superset of the set returned with it off | holdout |
| AC-9  | T's tree stored with A1's `key_terms` `["zebrafish"]` (a word in no chunk text, heading or other node), BM25 only (`ARP_HYBRID_RETRIEVAL_ENABLED=false`), `require_hit` on, query terms `["zebrafish"]` | evidence selected, setting on | A chunk whose node is A1 is returned at rank 0 | holdout |
| AC-9b | Same, setting off, field not `high_risk` | evidence selected | No chunk whose node is A1 is returned | holdout |
| AC-10 | Setting on, T's tree stored, an extraction of one field on T with stand-in answers | the extractor's prompt is built | Each evidence passage's text equals its `chunk.text`; the prompt contains no `Summary:` or `Terms:` line and no `A1 summary.` | holdout |
| AC-10b | Same, the run finishes | the run's results are read through the API | Each evidence passage's text equals its chunk's `text`; no citation `quote` or evidence passage contains `Summary:`, `Terms:` or `A1 summary.` | holdout |
| AC-11 | Setting on, T's tree stored (so the A1 chunk's index text contains `A1 summary.`), a citation on T whose quote is `A1 summary.` | grounding | `grounded` is `false` | holdout |
| AC-12 | T's tree stored, T's chunks embedded once with the setting off, hybrid on, recording `embed_texts` stand-in | setting switched on, evidence selected twice for the same field | Each chunk's tree-context index text is passed to `embed_texts` exactly once over both selections | holdout |
| AC-12b | Same, after AC-12 | setting switched off again, evidence selected | `embed_texts` receives no texts (the headers-only vectors are reused) | holdout |
| AC-13 | Setting on, T's tree stored, `retrieval_backend=opensearch` (test container) | T indexed | Each indexed chunk document's `text` equals `index_text(chunk, T, settings)` and the A1 chunk's contains `Summary: A1 summary.` | holdout |
| AC-14 | `tree_context_enabled` on, `doc_tree_enabled` off, local documents dir holding T | `arp documents warm --universe <file>` | `arp documents tree <doc_id>` then exits 0 | holdout |
| AC-14b| Both settings off | a document is fetched through the registry | No `doc_tree` row is written and no `TreeSummaries` line is logged | holdout |
| AC-15 | Cases file with one case on T, no stored tree, stand-ins | `arp golden-set retrieval --cases <file> --tree-context` | Exit 0; at least one `TreeSummaries` line in `calls.jsonl`; stderr contains `Tree context: 0 of 5 nodes have no summary.`; then `arp documents tree <doc_id>` exits 0 | holdout |
| AC-15b| Same, run a second time | Same command | No `TreeSummaries` line is added | holdout |
| AC-15c| Same cases, stand-in without an entry for A2, no stored tree | Same command | stderr contains `Tree context: 1 of 5 nodes have no summary.` | holdout |
| AC-15d| Same cases, setting off, no `--tree-context` | `arp golden-set retrieval --cases <file>` | No `TreeSummaries` line is logged; stderr has no `Tree context:` line | holdout |
| AC-17 | No `ARP_TREE_CONTEXT_ENABLED` set, T's tree stored | `Settings()`, then `index_text` for a chunk inside A1 | `tree_context_enabled` is `false`; the index text equals the headers-only text | holdout |
| AC-16 | The bundled extraction golden set, `tree_context_enabled` off | `arp golden-set run` | Every case passes, as on `main` | golden |

Must not change: index text with the setting off (AC-7, AC-7b), evidence text, prompts, citations and grounding (AC-10,
AC-10b, AC-11), the default off (AC-17), no chunk lost to tree context (AC-8), no model calls at retrieval (AC-6, AC-15d), ingest with both
settings off (AC-14b), the extraction golden set (AC-16).

PR checklist (not ACs): the PR description lists, from `arp golden-set retrieval --cases
backend/tests/golden/retrieval/cases.json`, `main`'s recall@5 and recall@12 and the PR's with `--tree-context`,
the `Tree context: k of n` line, and the tree build's calls and tokens for each eval document.
