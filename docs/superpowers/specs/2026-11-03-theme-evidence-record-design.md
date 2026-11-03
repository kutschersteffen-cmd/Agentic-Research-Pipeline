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
  (`finalize_from_revenue`, debate skipped by a hard number) and pairs built outside the match graph.
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
- `finalize_from_revenue` sets neither field.

With the A2 funnel on, pairs that pass the funnel reach the match graph as today and get these fields. A2's spec
keeps "No documents → unchanged (`finalize_no_evidence`)", which this spec refines without changing the verdict.

### API contract

`CompanyMatch` is served by the runs API. Regenerate `openapi.json` and the frontend types
(`.claude/CLAUDE.md`, Checks: API contract).

## Left to the builder

Where `EvidenceRef` is declared inside `thematic.py`; whether the no-documents opinion is a parameter of
`_no_evidence_opinion` or a second helper.

## Acceptance

Rows use a stand-in LLM that returns a fixed advocate, opposing and adjudicator answer and counts calls, and
fixture theme `T` with one activity `a1` whose seed keyword is `electrolyser`. No revenue resolver,
indirect model or R&D resolver unless a row says so. Funnel setting off unless a row says so.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | Company A with zero documents | theme run on `T` | A's match for `a1` has `evidence_status` `"no_documents"` | holdout |
| AC-2  | Same as AC-1 | theme run on `T` | A's `adjudicator_rationale` starts with `No documents were available for this company.` | holdout |
| AC-3  | Same as AC-1 | theme run on `T` | A's `advocate.rationale` and `opposing.rationale` both equal `No documents were available for this company.` | holdout |
| AC-4  | Same as AC-1 | theme run on `T` | A's `evidence` is `[]` | holdout |
| AC-5  | Company B with one document whose text never contains `electrolyser` | theme run on `T` | B's match has `evidence_status` `"no_matching_chunks"` | holdout |
| AC-6  | Same as AC-5 | theme run on `T` | B's `adjudicator_rationale` equals `No evidence of this activity was found in the available documents.` | holdout |
| AC-7  | Same as AC-5 | theme run on `T` | B's `advocate.rationale` equals `No document chunks matched this activity's seed keywords in the available disclosures.` | holdout |
| AC-8  | Company C with one document `d1` containing `electrolyser` in 3 separate chunks | theme run on `T` | C's match has `evidence_status` `"selected"` | holdout |
| AC-9  | Same as AC-8 | theme run on `T` | C's `evidence` has 3 entries, each `doc_id` is `d1`, and the `chunk_id` list equals the ids of the chunks the stand-in advocate received, in the same order | holdout |
| AC-10 | Same as AC-8 | read the run JSON | Each entry of C's `evidence` has exactly the keys `chunk_id` and `doc_id` | holdout |
| AC-11 | Company D with documents containing `electrolyser` in 20 chunks | theme run on `T` | D's `evidence` has 12 entries | holdout |
| AC-12 | Company E with a revenue catalogue entry that resolves `a1` to a hard percentage | theme run on `T` with the revenue resolver | E's match has `evidence_status` `null` and `evidence` `[]` | holdout |
| AC-13 | Company A as in AC-1, with an indirect model giving structural exposure above `indirect_exposure_review_threshold` | theme run on `T` | A's `adjudicator_rationale` starts with `No documents were available for this company.` and contains `input-output propagation shows structural exposure` | holdout |
| AC-14 | Companies A, B and C as above | theme run on `T`, once on `main` and once on this branch | For each company, `verdict`, `confidence`, `flagged_for_review` and `citations` are equal between the two runs | holdout |
| AC-15 | A run JSON written on `main` (no `evidence_status`, no `evidence`) | load it as `CompanyMatch` | Loads without error; `evidence_status` is `null` and `evidence` is `[]` | holdout |
| AC-16 | Funnel setting on, stand-in models making C pass the funnel | theme run on `T` | C's match has `evidence_status` `"selected"` and a non-null `funnel` record | unit |
| AC-17 | The regenerated `openapi.json` | inspect the `CompanyMatch` schema | It lists `evidence_status` and `evidence` | unit |
| AC-18 | The existing backend test suite on `main` | `python3 -m pytest backend/tests` on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |

Must not change: verdicts, confidence, review flags and citations (AC-14); the no-matching-chunks wording (AC-6,
AC-7); loading old runs (AC-15); the existing suite (AC-18).

AC-16 depends on A2's `theme-funnel` being merged; until then it is owed and listed as such in the PR.
