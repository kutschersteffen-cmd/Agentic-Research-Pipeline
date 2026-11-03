# Theme evidence record

Spec slug: `theme-evidence-record`. Gaps G13 and G14 of the universe-to-documents review
(https://claude.ai/artifact/FH7Q7fWJVUpxTRbjyKLx5a). Works alongside spec `theme-funnel` (A2, approved).

Status: draft.

## Why

In the theme run, every company × activity pair that reaches evidence selection either goes to the debate or ends
in `_finalize_no_evidence` (`backend/arp/research/match_graph.py:201-238`). Two problems:

1. **G13.** A company with no documents at all and a company whose documents hold no matching chunk get the same
   rationale, "No evidence of this activity was found in the available documents." A discovery miss reads as a
   negative finding on the activity, and nothing in the result tells the two apart.
2. **G14.** `_gather_evidence` picks up to 12 chunks (`match_graph.py:26, 164-194`) and hands them to the agents.
   That set is not stored. Only the citations the agents chose survive (`schemas/thematic.py:163, 181`). A
   reviewer cannot see what the agents read, or what they read and did not cite.

## Goals

1. Every `CompanyMatch` that went through evidence selection says, in one machine-readable field, whether
   documents were missing, no chunk was selected, or chunks were selected.
2. A pair with no documents gets its own rationale text.
3. Every `CompanyMatch` stores the ids of the chunks handed to the agents, in rank order, with their document ids.

## Non-goals

- G15: document routing, a recency filter or the reranker in theme evidence. These touch the same retrieval code
  as A2 (`theme-funnel`) and the embeddings upgrade spec; they are left to coordination with A2.
- G12: precomputing embeddings (A2).
- Changing verdicts, confidence, `flagged_for_review`, citations, arbitration or the debate.
- Storing chunk text or scores. `select_relevant_chunks` returns chunks without scores; this spec does not add them.
- Any UI change. New fields show under "Full record" in the review list as today for unknown keys.
- Pairs the A2 funnel screens out. Their record is the funnel's `funnel` field; this spec leaves them as A2 builds
  them.

## Anti-goals

- Chunk text copied into the run JSON (the run already stores citations with quotes; the full set would bloat it).
- A pair with no documents and a pair with documents but no selected chunk ending with the same `evidence_status`.

## Design

### Schema (`backend/arp/schemas/thematic.py`)

`CompanyMatch` gains two optional fields:

```python
class EvidenceRef(BaseModel):
    chunk_id: str
    doc_id: str

evidence_status: Literal["selected", "no_documents", "no_matching_chunks"] | None = None
evidence: list[EvidenceRef] = Field(default_factory=list)
```

- `evidence_status` is `None` only when evidence selection did not run: the revenue path
  (`_finalize_from_revenue`, debate skipped by a hard number) and pairs built outside the match graph.
- `evidence` lists the chunks `select_relevant_chunks` returned, in the order it returned them. Empty when
  `evidence_status` is not `selected`.

Names do not clash with A2's `funnel` field. Old run JSON without these fields loads unchanged.

### Match graph (`backend/arp/research/match_graph.py`)

- `_gather_evidence` keeps its selection logic. Nothing about which chunks are picked changes.
- `_finalize_no_evidence`:
  - `state["documents"]` empty → `evidence_status="no_documents"`, `adjudicator_rationale` starts with
    `No documents were available for this company.` and both `_no_evidence_opinion()` rationales read
    `No documents were available for this company.`
  - documents present, no chunk selected → `evidence_status="no_matching_chunks"`; rationale text and opinions
    stay exactly as today.
  - The structural-exposure sentence is still appended in both cases when `structural_flag` is true.
  - Verdict (`exclude`), confidence and `flagged_for_review` are computed as today in both cases.
- The adjudicator path (`_run_adjudicator_node`) sets `evidence_status="selected"` and fills `evidence` from
  `state["evidence"]`.
- `_finalize_from_revenue` sets neither field.

With the A2 funnel on, pairs that pass the funnel reach the match graph as today and get these fields. A2's spec
keeps "No documents → unchanged (`finalize_no_evidence`)", which this spec refines without changing the verdict.

### API contract

`CompanyMatch` is served by the runs API. Regenerate `openapi.json` and the frontend types
(`.claude/CLAUDE.md`, Checks: API contract).

## Left to the builder

Where `EvidenceRef` is declared inside `thematic.py`; whether the no-documents opinion is a parameter of
`_no_evidence_opinion` or a second helper.

## Acceptance

All rows are `unit`: they need a fixture theme, fixture documents and a stand-in LLM fed straight into the match
graph. The e2e stack's `ARP_STANDINS_DIR` covers the LLM only, not a fixture theme, documents or an indirect
model; the test-writer may move rows to `holdout` if it finds a path for those.

Fixtures used by the rows:

- Theme `T`: one activity `a1`, seed keyword `electrolyser`, no contrast statements, `core_isic_codes` `["2790"]`.
- Indirect model `M` (only where a row names it): companies A and B carry `isic_code` `"2790"`, and `M` gives
  `max(upstream_exposure, downstream_exposure)` ≥ `indirect_exposure_review_threshold` for them. `_compute_indirect`
  (`match_graph.py:70`) runs only with a company ISIC or NACE code and a non-empty `core_isic_codes`.
- The structural sentence is the existing text ` However, input-output propagation shows structural exposure to this activity's core sectors above the review threshold -- routed for a second look rather than excluded outright.`
  appended by `_finalize_no_evidence`.
- Stand-in LLM: advocate and opposing return a fixed opinion; the adjudicator returns verdict `include`,
  exposure `high`, confidence `0.8`, `citations` `[]`.
- Settings: `hybrid_retrieval_enabled` false, `section_chunking_enabled` false, funnel off, no revenue
  resolver, indirect model or R&D resolver, unless a row says otherwise.
- Document `d1`: exactly three paragraphs separated by one blank line, each 3,000 characters, nothing else.
  `chunk_document` with the default 3,500-character chunks yields exactly 3 chunks `k1`, `k2`, `k3`, one per
  paragraph. `k1` contains `electrolyser` 3 times, `k2` 2 times, `k3` once; the rest is filler without it.
  The test first asserts that `chunk_document(d1)` returns these 3 chunks.
- "The run's results" means `GET /api/runs/{run_id}/results` (`backend/arp/api/routers/runs.py:180`), field
  `matches`.

| ID     | Given | When | Then (observable, exact) | Checked by |
|--------|-------|------|--------------------------|------------|
| AC-1   | Company A with zero documents | theme run on `T` | A's match for `a1` has `evidence_status` `"no_documents"` | unit |
| AC-2   | Same as AC-1 | theme run on `T` | A's `adjudicator_rationale` equals `No documents were available for this company.` | unit |
| AC-3   | Same as AC-1 | theme run on `T` | A's `advocate.rationale` equals `No documents were available for this company.` | unit |
| AC-3b  | Same as AC-1 | theme run on `T` | A's `opposing.rationale` equals `No documents were available for this company.` | unit |
| AC-4   | Same as AC-1 | theme run on `T` | A's `evidence` is `[]` | unit |
| AC-5   | Company B with one document whose text never contains `electrolyser` | theme run on `T` | B's match has `evidence_status` `"no_matching_chunks"` | unit |
| AC-6   | Same as AC-5 | theme run on `T` | B's `adjudicator_rationale` equals `No evidence of this activity was found in the available documents.` | unit |
| AC-7   | Same as AC-5 | theme run on `T` | B's `advocate.rationale` equals `No document chunks matched this activity's seed keywords in the available disclosures.` | unit |
| AC-7b  | Same as AC-5 | theme run on `T` | B's `opposing.rationale` equals `No document chunks matched this activity's seed keywords in the available disclosures.` | unit |
| AC-8   | Company C with document `d1` only | theme run on `T` | C's match has `evidence_status` `"selected"` | unit |
| AC-9   | Same as AC-8 | read the run's results | C's `evidence` has 3 entries | unit |
| AC-9b  | Same as AC-8 | read the run's results | Every entry of C's `evidence` has `doc_id` equal to `d1`'s doc_id | unit |
| AC-9c  | Same as AC-8 | read the run's results | C's `evidence` `chunk_id` list is `[k1, k2, k3]` in that order | unit |
| AC-10  | Same as AC-8 | read the run's results | Each entry of C's `evidence` has exactly the keys `chunk_id` and `doc_id` | unit |
| AC-11  | Company D with documents yielding 20 chunks that contain `electrolyser` | theme run on `T` | D's `evidence` has 12 entries | unit |
| AC-12  | Company E with a revenue catalogue entry that resolves `a1` to a hard percentage | theme run on `T` with the revenue resolver | E's `evidence_status` is `null` | unit |
| AC-12b | Same as AC-12 | theme run on `T` with the revenue resolver | E's `evidence` is `[]` | unit |
| AC-13  | Company A as in AC-1, with indirect model `M` | theme run on `T` | A's `adjudicator_rationale` equals `No documents were available for this company.` followed directly by the structural sentence | unit |
| AC-13b | Same as AC-13 | theme run on `T` | A's `evidence_status` is `"no_documents"` | unit |
| AC-13c | Company B as in AC-5, with indirect model `M` | theme run on `T` | B's `adjudicator_rationale` equals `No evidence of this activity was found in the available documents.` followed directly by the structural sentence | unit |
| AC-14  | A as in AC-1, B as in AC-5 (no indirect model) | theme run on `T` | A's and B's `verdict` are `exclude` | unit |
| AC-14d | Same as AC-14 | theme run on `T` | A's and B's `confidence` are `1.0` | unit |
| AC-14e | Same as AC-14 | theme run on `T` | A's and B's `flagged_for_review` are `false` | unit |
| AC-14f | Same as AC-14 | theme run on `T` | A's and B's `citations` are `[]` | unit |
| AC-14c | A as in AC-13, B as in AC-13c | theme run on `T` | A's and B's `verdict` are `exclude` | unit |
| AC-14g | Same as AC-14c | theme run on `T` | A's and B's `confidence` are `0.5` | unit |
| AC-14h | Same as AC-14c | theme run on `T` | A's and B's `flagged_for_review` are `true` | unit |
| AC-14b | Company C as above | theme run on `T` | C's `verdict` is `include` | unit |
| AC-14i | Same as AC-14b | theme run on `T` | C's `confidence` is `0.8` | unit |
| AC-14j | Same as AC-14b | theme run on `T` | C's `citations` are `[]` | unit |
| AC-14k | Same as AC-14b | theme run on `T` | C's `flagged_for_review` is `true` | unit |
| AC-15  | A stored theme run whose `results.jsonl` rows were written on `main` (no `evidence_status`, no `evidence`) | `GET /api/runs/{run_id}/results` | Status 200 | unit |
| AC-15b | Same as AC-15 | `GET /api/runs/{run_id}/results` | Every match has `evidence_status` `null` and `evidence` `[]` | unit |
| AC-16  | Funnel setting on, stand-in models making C pass the funnel | theme run on `T` | C's match has `evidence_status` `"selected"` | unit |
| AC-17  | The regenerated `openapi.json` | inspect the `CompanyMatch` schema | It lists `evidence_status` and `evidence` | unit |
| AC-18  | The backend test suite on `main` | `python3 -m pytest backend/tests` on this branch | Every test on `main` that the PR does not list as changed passes; each changed test is listed in the PR description with the AC row that requires it | unit |

Must not change: verdicts, confidence, review flags and citations (AC-14 to AC-14k); the no-matching-chunks wording
with and without the structural sentence (AC-6, AC-7, AC-7b, AC-13c); loading old runs (AC-15, AC-15b); the
existing suite (AC-18).

Existing tests asserting today's no-evidence wording: none found (`grep -rn "No evidence" backend/tests` finds
only a fixture value `"No evidence."` in `tests/test_runs_export.py:63`, which this change does not affect).

AC-16 depends on A2's `theme-funnel` being merged; until then it is owed and listed as such in the PR.
