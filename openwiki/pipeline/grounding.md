---
type: pipeline subsystem
title: Citation grounding
description: How backend/arp/grounding.py checks every model-reported quote against the cited document's real text (exact, then normalised, then fuzzy, with strict rules for short and numeric quotes), restricts matches to the passages the model saw, resolves page, sheet, table and character offsets from the verified match only, and where the same check is reused in extraction, review and publishing.
tags: [grounding, citations, precision, normalisation, fuzzy-match, provenance]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-07e1021d4b7b6b7207c06144
    resource: repo://backend/arp/config.py
  - id: openwiki-source-88bc712a147e351ba5cc9e96
    resource: repo://backend/arp/extraction/pipeline.py
  - id: openwiki-source-aba379072b740ddddafb7888
    resource: repo://backend/arp/grounding.py
  - id: openwiki-source-a16b9c10e2200d67be750020
    resource: repo://backend/arp/orchestration/reground.py
  - id: openwiki-source-953fdbd214da2cf081497d9b
    resource: repo://backend/arp/publish/gate.py
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# Citation grounding

`backend/arp/grounding.py` is the repository's hard precision control. A citation counts as **grounded** only if its
`quote` actually occurs in the cited document's text. The module never relies on the model's own claim that it quoted
correctly, so a paraphrased or hallucinated quote is caught by code. The module depends only on the schemas in
`backend/arp/schemas/common.py` (`Citation`, `SourceDocument`, `DocumentChunk`, `TableRef`), not on any LLM or
retrieval code.

## Public functions

| Function | Use |
|---|---|
| `is_grounded(quote, source_text, fuzzy_threshold=0.92)` | Yes/no check for one quote. |
| `ground_citations(citations, documents_by_id, fuzzy_threshold, *, passages=None)` | Returns *new* citations with `grounded` set and, for grounded ones only, location and span fields resolved from the real match. |
| `ground_claim(citations, documents_by_id, ..., claim_is_empty, passages=None)` | `ground_citations` plus the per-claim roll-up used by the segment, spend and other aggregators. |

The threshold comes from `grounding_fuzzy_threshold` in `backend/arp/config.py` (default 0.92) and is part of every
extraction field's input hash, so changing it re-extracts instead of reusing old rows.

## Matching

`_find_match` tries three methods in order and returns a `Match(char_start, char_end, method, score)` whose offsets
always index the **original** text:

1. **exact**: a raw substring search.
2. **normalised**: both sides are normalised, then searched. Normalisation maps the various Unicode dashes and the minus
   sign to `-`, curly quotes to straight ones, and ligatures through NFKC. It drops soft hyphens and zero-width
   characters, joins PDF line-break hyphenation (`<alnum>-` newline `<alnum>`), collapses runs of whitespace,
   lowercases, and trims. `_normalize_with_offsets` also records, for every output character, the offset of its source
   character, so a match in normalised text maps back to a real span. This holds even when lowercasing expands one
   character into two.
3. **fuzzy**: `difflib.SequenceMatcher` finds the longest common block. The quote grounds if that block covers at
   least `fuzzy_threshold` of the normalised quote **and** no digit lies outside the block. The digit rule stops a
   near-match from hiding a changed number, such as 2025 against 2026.

### Short quotes

Below `SHORT_QUOTE_CHARS` (20 normalised characters):

- a numeric quote must also carry a label of three or more letters, so a bare "42" never grounds;
- a non-numeric quote must contain a word of two or more letters, so "-" and "n/a"-style punctuation never ground,
  while "Yes" can;
- short quotes **never** take the fuzzy path.

### Performance

The normalised form of a document is cached in an `lru_cache` of 16 entries keyed on the source text. A company's
filing set is normalised once rather than once per citation. The code comment measures 531 ms for a 2.1 MB 10-K,
which made 20 citations cost about 10 s before the cache. Quotes are normalised without the cache so they cannot evict
documents.

## Passage restriction

With `passages` (the evidence chunks the model was shown), a quote only grounds if the match lies **inside** one of
the shown passages of its own document. The passage named by the citation's `passage_id` is searched first, which
matters when the same quote appears more than once. On success, `passage_id` is rewritten to the passage that actually
contains the match. Without `passages`, the whole document is searched. Extraction always passes the evidence it
showed (`build_extracted_fields` in `backend/arp/extraction/aggregator.py`), so a quote the model could not have seen
is ungrounded.

## What a grounded citation carries

`ground_citations` clears every location field first and fills them only from the verified match. `Citation` is also
the schema the LLM fills in, so nothing it reported is trusted. An ungrounded citation keeps only its reported
`passage_id`. A grounded one gets:

- `company_id`, `source_filename`, `content_key` and `parser_version` from the document;
- `page`, from `page_breaks` by bisection;
- `sheet`, from the nearest `## Sheet: <name>` header for spreadsheets;
- `table_ref`, which names the table the match starts in and the first data cell it overlaps. A quote like
  "Revenue | 1,234.5" therefore points at the number cell, not the row label;
- `span_text`, `char_start`, `char_end`, `match_method` and `match_score`.

These offsets, together with `content_key` and `parser_version`, are what later stages use to find the quote again.

## The claim roll-up

`ground_claim` states the rule once for every aggregator. A claim is grounded when **every** citation grounds. A claim
with **no** citations is grounded only if the claim itself is empty, which the caller signals with `claim_is_empty`,
for example `value is None`. A real value with zero citations is exactly the unsourced assertion this module exists to
catch, so it is ungrounded and needs review. The main extraction aggregator applies the same rule inline: `grounded`
is true when all final citations ground, or when there is no value.

## Where grounding is applied

- **Extraction**: `backend/arp/extraction/aggregator.py` grounds extractor, verifier and adjudicator citations and only
  lets a correction or adjudicated value through with a grounded citation. Routing then sends any found value that is
  not grounded to review (`backend/arp/extraction/routing.py`). See
<!-- openwiki: broken internal link [/openwiki/pipeline/extraction.md] link "/openwiki/pipeline/extraction.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
  [Data-point extraction engine](/openwiki/pipeline/extraction.md). The financials, TNFD, segment and spend
  aggregators and other pipelines (transition plan, voting, research, emerging themes, replication) import the same
  functions.
- **Review**: a reviewer's correction citation is grounded server-side against the stored text, and any offsets the
  client sent are discarded (`ground_correction` in `backend/arp/review/decide.py`).
- **Publishing**: `reground_match` in `backend/arp/publish/gate.py` grounds a published citation again against the
  stored text for its `parser_version`. It looks first within ±200 characters of the stored span, then in the whole
  text, and reports `ok`, `offset_moved`, `not_grounded` or `text_unavailable`. The daily publishing job samples
  published facts this way, and `backend/arp/orchestration/reground.py` uses it after a parser upgrade. See
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
  [Publishing facts](/openwiki/pipeline/publish.md).

Retrieval choices do not change any of this. Hybrid or reranked evidence only decides which passages the model sees,
and grounding is always checked against the document text.

## Tests

`backend/tests/test_grounding.py` covers exact, whitespace, hyphenation, typographic and ligature variants, the
digit-outside-block rejection, every short-quote rule, offset alignment, passage restriction and `passage_id`
correction, and the guarantee that an ungrounded citation drops the location fields the LLM reported.
`backend/tests/test_table_grounding.py` and `backend/tests/test_segment_grounding.py` cover table cells and
segment claims.
