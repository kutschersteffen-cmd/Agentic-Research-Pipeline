# Matcher on the shared retrieval path: grounded claims, judge reads the evidence

Status: Draft, for owner approval
Slug: `matcher-shared-retrieval`
Risk: `risk:normal` (backend only: `arp/research/match_graph.py`, `arp/research/matcher_agents.py`,
`arp/schemas/thematic.py`; optional fields on a model stored as JSON, no migration, no auth, money or UI)
Size: `S`, one PR, no slices (see `## Slices`)
Covers: R&D Lab plan item 2 ("adjudicator reads evidence"), narrowly: the judge gets the evidence; and R&D Lab plan
item 3 ("theme evidence record"), by absorbing the approved, never-built `theme-evidence-record` spec (see
Supersedes). Running the opposing agent on another model and blind opinions stay out (Non-goals).

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them. The one
that changes what a reviewer sees: an ungrounded advocate or opposing quote is now marked `grounded: false` but
does **not** by itself flag the match for review (D5). Say "Not approved" if it should.

## Why

Review of 2026-11-25 (`/mnt/project-files/extraction-precision/review-and-ideas.md`, ideas 3, 13, 14 and
Addendum 2) found these gaps in the theme matcher, all still on `main` at `7e2e955`:

1. **Older retrieval path.** `match_graph._select_evidence` chunks each document with `chunk_document` and calls
   `select_relevant_chunks` with the seed keywords only. Extraction uses `field_evidence`
   (`arp/extraction/field_graph.py`): German keyword expansion, small-to-big, context headers, the
   `evidence_max_chunks` cap and the optional reranker. A German report that says "Ökostrom" gives the matcher
   no evidence for the seed keyword "renewable"; extraction finds it.
2. **Judge without evidence.** `run_adjudicator` gets only the two opinions. Its system prompt already says "You
   are given ... the evidence".
3. **Half the claims are unchecked.** Only the adjudicator's citations are grounded, and against the whole
   document. Advocate and opposing citations are stored as the model wrote them. The planned Company dossier
   ("FOR / AGAINST ... FOUND IN SOURCE") and Run quality ("Quotes found in source") screens would show check
   marks that nothing set.
4. **No record of what was read** (the `theme-evidence-record` gaps G13/G14). The passages handed to the agents
   are not stored, so the dossier's "Passages read (12)" tab has no data; and nothing machine-readable says
   whether a pair had no documents, no matching passage, or passages.

## What the user can do afterwards that they cannot do today

- Get matcher evidence from German reports through the same German terms extraction uses.
- See, per match in `GET /api/runs/{run_id}/results`, which passages the agents read (`evidence`) and why a pair
  had none (`evidence_status`).
- Trust `grounded` on every advocate, opposing and adjudicator citation: true only when the quote lies in a
  passage the agents were shown.

## What exists today (main `7e2e955`)

- `match_company_activity` (`arp/research/match_graph.py`) runs a LangGraph: indirect, revenue, R&D, then either
  `finalize_from_revenue` (a hard revenue number), or `gather_evidence` → (`finalize_no_evidence` | `funnel` →
  (`finalize_screened_out` | debate) | debate). Debate = `run_advocate` → `run_opposing` → `run_adjudicator`.
- `_select_evidence`: keywords are `funnel_query.keywords` when a `FunnelQuery` is passed, else
  `activity.seed_keywords`; `chunk_document(doc, keywords=keywords)` for every document; then
  `select_relevant_chunks(all_chunks, keywords, max_chunks=12, hybrid/opensearch from settings)`. No reranker,
  no German terms, no small-to-big, no context headers. Cap: module constant `_MAX_EVIDENCE_CHUNKS_PER_CALL = 12`.
- `_finalize_no_evidence`: no documents → `verdict` `uncertain`, `confidence` 0.0, rationale
  `No documents were found for this company, so this activity could not be assessed.`, flagged. Documents but no
  evidence → `exclude`, rationale `No evidence of this activity was found in the available documents.`,
  confidence 1.0 (0.5 with the structural flag). Both use `_no_evidence_opinion()` for advocate and opposing.
  `_finalize_screened_out` copies that result and sets the rationale `screened out by funnel`.
- `field_evidence(field, documents, settings, on_unranked_fallback=None, explain=None)` is the extraction path.
  It reads `field.seed_keywords` (through `with_german`), `field.document_routing`, `field.source_doc_types` and
  `field.high_risk`, and the settings `small_to_big_enabled`, `small_chunk_chars`, `context_headers_enabled`,
  `hybrid_retrieval_enabled`, `retrieval_backend`, `evidence_max_chunks` (default 12), `rerank_enabled`,
  `rerank_candidates`, `embed_model`, `rerank_model`. With `explain={}` it fills `explain["scores"]`
  (chunk id → score dict) for the returned chunks.
- `matcher_agents.py`: `run_advocate` and `run_opposing` put
  `Evidence:\n{format_evidence(chunks, ('doc_id', 'doc_type', 'section', 'speaker'))}` in their prompts.
  `run_adjudicator(company_name, activity, advocate, opposing, llm)` has no evidence.
- `_run_adjudicator_node`: `ground_citations(adjudication.citations, documents_by_id, threshold)` with no
  `passages=`, so a quote anywhere in the document grounds. `match.advocate` / `match.opposing` are the raw
  `AgentOpinion`s; their citations keep `grounded` at its schema default (`False`) or whatever the model wrote.
- `ground_citations(..., passages=dict)` (`arp/grounding.py`) grounds a quote only inside a shown passage of its
  document and sets `page`, `passage_id`, offsets; extraction already calls it this way.
- `trace.passage(chunk, scores)` (`arp/walkthrough/trace.py`) is the walkthrough's per-passage record:
  `doc_id`, `char_start`, `char_end`, `section`, and `scores` when scores are given.
- `CompanyMatch` (`arp/schemas/thematic.py`) is stored as JSON in each theme run's `results.jsonl` and returned by
  `GET /api/runs/{run_id}/results` as `model_dump(mode="json")`. That endpoint is declared `-> dict` with no
  response model, and `frontend/src/api/openapi.json` contains no `CompanyMatch` schema, so this change needs no
  OpenAPI export or `gen:api`.

## Goals

- G1. The matcher picks evidence with `field_evidence`, from a field built from the activity (Design).
- G2. The adjudicator prompt contains the same evidence block the advocate and opposing agents see.
- G3. Advocate, opposing and adjudicator citations are all grounded against the shown passages.
- G4. Every match that went through evidence selection stores the passages selected, in rank order: chunk id,
  document, rank, page, offsets, section, retrieval scores (`evidence`).
- G5. Every match says in one field whether documents were missing, no passage was selected, or passages were
  selected (`evidence_status`).

## Non-goals

- Blind or independent opinions; the opposing agent still sees the advocate's case.
- Running any agent on `verifier_llm` or another model.
- Calibrated confidence; changing the flag rule (D5); funnel scoring or thresholds; any UI.
- Changing any verdict, confidence, rationale or opinion text of the no-documents and no-evidence paths (main's
  wording stays, see Supersedes).
- Changing `field_evidence` or `select_relevant_chunks` (their signatures, return values and behaviour for
  extraction stay as they are), the agents' system prompts, or the advocate and opposing prompts. No extraction
  file is edited.
- Storing passage text in the run JSON.
- A walkthrough trace file for theme runs.

## Anti-goals (must stay true)

- A1. No documents: `verdict` `uncertain`, `confidence` 0.0, the "could not be assessed" rationale, flagged, and
  no LLM call.
- A2. Documents but no evidence: `verdict` `exclude`, no LLM call (rationale and confidence as today).
- A3. A hard revenue number still short-circuits: no evidence is gathered and no debate runs.
- A4. Old stored runs load unchanged.
- A5. A pair with no documents and a pair with documents but no selected passage never end with the same
  `evidence_status`.

## Design

### Evidence (`match_graph._select_evidence`)

Replace the body with one `field_evidence` call; keep `_gather_evidence`'s `asyncio.to_thread`:

```python
keywords = state["funnel_query"].keywords if state["funnel_query"] else activity.seed_keywords
field = FieldDefinition(
    name=activity.name, description=activity.in_scope_description, data_type=FieldDataType.STRING,
    extraction_instructions="", seed_keywords=keywords,
)
explain: dict = {}
evidence = field_evidence(field, state["documents"], state["settings"], explain=explain)
```

All other `FieldDefinition` fields keep their defaults (`document_routing` None, `source_doc_types` [],
`high_risk` False), so every document is searched and a pair with no keyword hit gets no evidence, as today.
`settings` is never None here. The node returns `evidence` and `explain` (new state key `evidence_explain`,
default `{}`). Delete `_MAX_EVIDENCE_CHUNKS_PER_CALL` and the imports the change leaves unused.

Because the matcher now goes through `field_evidence`, the `extraction-retrieval-bundle` switches (PR #733:
`retrieval_field_query_enabled`, `rerank_small_pieces_enabled`, `evidence_overlap_removal_enabled`, all default
off) apply to it too. With `retrieval_field_query_enabled` on, the dense and rerank query is
`"{activity.name}\n{activity.in_scope_description}"` (empty instructions are skipped). This spec adds no setting.

### Judge reads the evidence (`matcher_agents.run_adjudicator`)

`run_adjudicator` gains a `chunks: list[DocumentChunk]` parameter after `activity` (same position as in
`run_advocate`). Its prompt becomes today's prompt with this block inserted directly before `Advocate opinion:`:

```
Evidence:\n{format_evidence(chunks, ('doc_id', 'doc_type', 'section', 'speaker'))}\n\n
```

So the prompt reads `...Activity (OUT OF SCOPE): {out}\n\nEvidence:\n{block}\n\nAdvocate opinion:\n...`. Nothing
else in the prompt changes: the opinions' `Citations:` lines still dump the citations as the models wrote them.
`_ADJUDICATOR_SYSTEM` does not change. `_run_adjudicator_node` passes `state["evidence"]`.

### Grounding (`_run_adjudicator_node`)

With `passages = {c.chunk_id: c for c in state["evidence"]}`, after the adjudicator call:

- `citations=ground_citations(adjudication.citations, documents_by_id, threshold, passages=passages)` (today:
  no `passages=`).
- `advocate=state["advocate"].model_copy(update={"citations": ground_citations(state["advocate"].citations, ...,
  passages=passages)})`, and the same for `opposing`.

`flagged_for_review` keeps today's rule (adjudicator citations only, D5).

### Evidence record (`arp/schemas/thematic.py`, `CompanyMatch`)

Add a new class `EvidenceRef` to `arp/schemas/thematic.py` (it does not exist on `main`; the never-built
`theme-evidence-record` spec defined it with `chunk_id` and `doc_id`) and two fields on `CompanyMatch`; the optional
`EvidenceRef` fields below are added to that schema, nothing is renamed:

```python
class EvidenceRef(BaseModel):
    chunk_id: str
    doc_id: str
    rank: int | None = None          # 1-based position in the order shown to the agents
    page: int | None = None          # 1-based PDF page of char_start; None without page_breaks
    char_start: int | None = None
    char_end: int | None = None
    section: str | None = None
    scores: dict = Field(default_factory=dict)  # select_relevant_chunks' explain["scores"] for this chunk
    ranks: dict[str, int] = Field(default_factory=dict)  # explain["ranks"] for this chunk (trace spec, #735)

# on CompanyMatch
evidence_status: Literal["selected", "no_documents", "no_matching_chunks"] | None = None
evidence: list[EvidenceRef] = Field(default_factory=list)
```

For the `i`-th chunk `c` of `state["evidence"]` (`i` from 1), the entry is
`EvidenceRef(**trace.passage(c, scores.get(c.chunk_id, {})), chunk_id=c.chunk_id, rank=i,
page=_page_for_offset(documents_by_id[c.doc_id].page_breaks, c.char_start), ranks=ranks.get(c.chunk_id, {}))`,
where `scores = explain.get("scores", {})` and `ranks = explain.get("ranks", {})`. `trace.passage` is the
walkthrough's per-passage record; `ranks` is the per-ranking rank dict (`bm25`, `vector`, `fused`, `rerank`) that
the `extraction-trace-parse-report` spec (PR #735) adds to `explain`. This spec defines neither key, it copies them.
`page` uses the grounding module's existing `_page_for_offset`, the same rule as a citation's `page`.

Who sets what:

| Path | `evidence_status` | `evidence` |
|---|---|---|
| `_finalize_from_revenue` | `None` | `[]` |
| `_finalize_no_evidence`, no documents | `"no_documents"` | `[]` |
| `_finalize_no_evidence`, documents but nothing selected | `"no_matching_chunks"` | `[]` |
| `_finalize_screened_out` (funnel said no) | `"selected"` | the selected passages |
| `_run_adjudicator_node` (debate ran) | `"selected"` | the selected passages |

Verdict, confidence, rationale, opinions and `flagged_for_review` on every path stay as on `main`.

Storage: `results.jsonl` rows are JSON; a stored match without the keys loads with `evidence_status None` and
`evidence == []` through `GET /api/runs/{run_id}/results` (it re-parses `CompanyMatch`). The second reader,
`GET /api/themes/runs/{run_id}/results` (`arp/api/routers/themes.py`), returns the stored dicts as they are and
stays unchanged: old rows there simply lack the two keys. No migration. No OpenAPI change (see What exists today).

### Ordering

The builder starts after `extraction-trace-parse-report` (spec PR #735; only its slice A matters here) and
`extraction-retrieval-bundle` (spec PR #733) merge, and merges `origin/main` first. This spec reuses their keys
(`explain["scores"]`, `explain["ranks"]`) and settings and defines none of its own. If either spec changes those
keys before it merges, `EvidenceRef.scores` / `ranks` follow them.

### Tests (builder)

No test on `7e2e955` calls `run_adjudicator` directly. Add unit tests as the builder sees fit; never weaken or
delete an existing test.

## Defaults taken

- D1. The activity's field is `name=activity.name`, `description=activity.in_scope_description`,
  `extraction_instructions=""`, `data_type=string`. Out-of-scope text is not part of the retrieval query (it would
  pull in exactly the passages the activity excludes).
- D2. With the funnel's `FunnelQuery` passed, its keywords still choose the evidence (theme-funnel amendment B).
- D3. The cap is `evidence_max_chunks` (default 12, so unchanged by default); the reranker runs when
  `rerank_enabled` is on, as in extraction.
- D4. The adjudicator sees the evidence with the same header fields as the advocate (`doc_id`, `doc_type`,
  `section`, `speaker`); no `passage_id` in the header, so the advocate and opposing prompts stay byte-identical.
- D5. Advocate and opposing citations get `grounded` set, but only the adjudicator's citations feed
  `flagged_for_review`, as today. An `include` verdict whose own citations ground is not flagged because the
  advocate quoted something outside the passages.
- D6. Grounding happens after the adjudicator call, so the adjudicator sees the opinions' citations as written.
- D7. A funnel-screened pair records `"selected"` and its passages: evidence was selected, the `funnel` field says
  why the debate did not run.
- D8. `rank` is the 1-based position in the order shown to the agents, not a retrieval-score rank (those live in
  `scores`).

## Supersedes

- **`theme-evidence-record`** (`docs/superpowers/specs/2026-11-03-theme-evidence-record-design.md`, approved
  2026-11-03, never built). This spec takes over its goals 1 and 3 and its schema. Its goal 2 (own rationale for
  no documents) is already met on `main` by the "could not be assessed" rationale; `main`'s verdict
  (`uncertain`, 0.0) and wording win over that spec's (`exclude`, 1.0, "No documents were available for this
  company."). Its rows map as follows; all were `unit`, so no hidden test is retired:
  - AC-1, AC-5, AC-8, AC-12, AC-13b, AC-15b, AC-16 → AC-26 to AC-30 here (AC-16's funnel-pass case is the debate
    row AC-28; the screened-out case is D7 and AC-35).
  - AC-4, AC-9 to AC-11, AC-12b → AC-1, AC-6, AC-9, AC-22 here.
  - AC-10 (exactly the keys `chunk_id`, `doc_id`) → retired: `EvidenceRef` has the optional fields above.
  - AC-2, AC-3, AC-3b, AC-13, AC-14, AC-14d, AC-14e, AC-14c (no-documents wording, verdict, confidence) →
    retired, `main` wins; AC-20 here pins `main`'s behaviour.
  - AC-6, AC-7, AC-7b, AC-13c, AC-14f to AC-14k → unchanged behaviour on `main`, covered by the existing tests.
  - AC-15 → AC-23. AC-17 (OpenAPI) → retired: `CompanyMatch` is not in the OpenAPI schema. AC-18 → "Must not change".
  That spec's file is left as it is (this PR holds only this spec file); this section is the record that it is
  superseded, and nobody builds it.
- No holdout row is known to assert the matcher's old evidence path or whole-document grounding of adjudicator
  citations. The test writer checks `regression/` for rows asserting a matcher citation grounds from outside the
  shown passages, and retires any it finds in the same holdout PR.

## Slices

One PR. About 60 changed lines in three files.

## Acceptance

All rows are `holdout` rows. Rows AC-1 to AC-22 and AC-26 to AC-35 call
`arp.research.match_graph.match_company_activity` directly with a stub `LLMClient` whose
`complete_structured(system, prompt, output_model)` records every `(system, prompt)` and returns a scripted answer
per call (advocate, opposing, adjudicator, in that order). No network, no LLM credits.

Common "Given" unless the row says otherwise:
- `S` = `Settings()` with defaults, `hybrid_retrieval_enabled=False`, `retrieval_backend="bm25"`,
  `rerank_enabled=False` (so `small_to_big_enabled=True`, `context_headers_enabled=True`, `evidence_max_chunks=12`).
- Activity `A`: `name="EV manufacturing"`, `in_scope_description="Designs and manufactures battery electric
  vehicles."`, `out_of_scope_description="ICE-only vehicles."`, `seed_keywords=["battery electric"]`.
- `F(A)` = `FieldDefinition(name=A.name, description=A.in_scope_description, data_type="string",
  extraction_instructions="", seed_keywords=A.seed_keywords)`.
- No revenue resolver, no R&D resolver, no indirect model, no funnel thresholds, no `funnel_query`.
- Company `C = CompanyRef(company_id="c1", name="Acme AG")`. For rows with `D1`: `documents=[D1]`,
  `documents_by_id={D1.doc_id: D1}`. Every stub citation has `doc_id=D1.doc_id`, `doc_type=D1.doc_type` and no
  `passage_id`.
- `D1`: one 10-K `SourceDocument` of company `c1`, about 9,000 characters with `page_breaks` set, mentioning "battery electric" in
  at least two places more than 4,000 characters apart.
- `H` = `('doc_id', 'doc_type', 'section', 'speaker')`; `E` = `field_evidence(F(A), documents, S)`.
- Stub answers: advocate and opposing `AgentOpinion` with no citations and adjudicator `AdjudicatorOutput` with
  `verdict=include`, `exposure_estimate=pure_play`, `confidence=0.9`, no citations, unless the row says otherwise.
- `Q1`: a substring of `E[0].text` of at least 20 characters. `Q2`: a sentence of at least 20 characters that
  occurs exactly once in `D1.full_text`, whose whole span is disjoint from every `[E[i].char_start, E[i].char_end)`,
  and for which `ground_citations([Citation(doc_id=D1.doc_id, doc_type=D1.doc_type, quote=Q2)], {D1.doc_id: D1},
  0.92, passages={c.chunk_id: c for c in E})[0].grounded is False` (the test asserts both preconditions; filler
  text must not fuzzy-match `Q2`).

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | `D1` | `match_company_activity` | `[e.chunk_id for e in match.evidence] == [c.chunk_id for c in E]`, in that order | holdout |
| AC-2  | `D1` | same | the advocate prompt contains `"Evidence:\n" + format_evidence(E, H)` | holdout |
| AC-3  | `D1` | same | the adjudicator prompt equals `f"Company: {C.name}\n\nActivity (IN SCOPE): {A.name}\n{A.in_scope_description}\n\nActivity (OUT OF SCOPE): {A.out_of_scope_description}\n\nEvidence:\n{format_evidence(E, H)}\n\nAdvocate opinion:\n"` followed by the advocate and opposing lines built exactly as `run_adjudicator` builds them on `main` `7e2e955` from the stub opinions | holdout |
| AC-4  | `D1` | same | the adjudicator call's `system` equals `_ADJUDICATOR_SYSTEM` as on `main` `7e2e955` | holdout |
| AC-5  | `D1` | same | `match.evidence[i].rank == i + 1` for every `i` | holdout |
| AC-6  | `D1` | same | for every `i`, `match.evidence[i]` has `doc_id`, `char_start`, `char_end`, `section` equal to `E[i]`'s | holdout |
| AC-7  | `D1` | same | `match.evidence[i].page == bisect.bisect_right(D1.page_breaks, E[i].char_start)` for every `i` | holdout |
| AC-8  | `D1` with `page_breaks == []` | same | every `match.evidence[i].page is None` | holdout |
| AC-9  | One document of 20 sections, each over 4,000 characters and each containing "battery electric" once; `S` with `evidence_max_chunks=3` | same | `len(match.evidence) == 3` | holdout |
| AC-10 | One document whose whole text is "Wir verkaufen Ökostrom an Haushalte und Gewerbe."; activity `A` with `seed_keywords=["renewable"]` | same | `match.verdict == "include"` (the stub's verdict: the debate ran; today `exclude`, no evidence) | holdout |
| AC-11 | One document starting with "We build battery electric vans." and ending with "Our fleet runs on Ökostrom.", with more than 5,000 characters of filler between them that contain neither "battery", "electric", "renewable" nor any term `with_german(["renewable"])` adds; `funnel_query=FunnelQuery(keywords=["renewable"], query="q", rerank_query="q", positives=[])`, no funnel thresholds | same | the advocate prompt contains "Ökostrom" and does not contain "We build battery electric vans." | holdout |
| AC-12 | `D1`; the stub advocate cites `Q1` | same | `match.advocate.citations[0].grounded is True` and its `passage_id == match.evidence[0].chunk_id` | holdout |
| AC-13 | `D1`; the stub advocate cites `Q2` | same | `match.advocate.citations[0].grounded is False` and its `page is None` | holdout |
| AC-14 | `D1`; the stub opposing opinion cites `Q1` | same | `match.opposing.citations[0].grounded is True` | holdout |
| AC-15 | `D1`; the stub opposing opinion cites `Q2` | same | `match.opposing.citations[0].grounded is False` | holdout |
| AC-16 | `D1`; the stub adjudicator cites `Q1` (verdict `include`, confidence 0.9) | same | `match.citations[0].grounded is True` and `match.flagged_for_review is False` | holdout |
| AC-17 | `D1`; the stub adjudicator cites `Q2` (verdict `include`, confidence 0.9) | same | `match.citations[0].grounded is False` and `match.flagged_for_review is True` (today: grounded, since `Q2` is in the document) | holdout |
| AC-18 | `D1`; the stub advocate cites `Q2`, the stub adjudicator cites `Q1`, verdict `include`, confidence 0.9 | same | `match.flagged_for_review is False` (D5) | holdout |
| AC-19 | `D1`; the stub advocate cites `doc_id=D1.doc_id`, quote `"this sentence is not in the document"`, with `grounded=True` and `page=99` filled in by the stub | same | `match.advocate.citations[0].grounded is False` and its `page is None` | holdout |
| AC-20 | `documents=[]`, `documents_by_id={}` | same | `verdict == "uncertain"`, `confidence == 0.0`, `adjudicator_rationale` starts with `"No documents were found for this company, so this activity could not be assessed."`, `flagged_for_review is True`, and the stub recorded 0 calls (unchanged) | holdout |
| AC-21 | One document whose text contains neither "battery", "electric" nor any term `with_german(["battery electric"])` adds | same | `verdict == "exclude"`, `adjudicator_rationale` starts with `"No evidence of this activity was found in the available documents."`, and the stub recorded 0 calls, and `confidence == 1.0` (unchanged) | holdout |
| AC-22 | `D1` plus a `RevenueResolverContext` whose catalogue resolves the pair to a hard `value_pct` of 0.4 (as in `tests/test_research_pipeline.py`'s catalogue case) | same | `match.advocate is None` and the stub recorded no call whose `system` is `_ADVOCATE_SYSTEM`, `_OPPOSING_SYSTEM` or `_ADJUDICATOR_SYSTEM` (unchanged) | holdout |
| AC-23 | A theme run whose `results.jsonl` row holds a `company_matches` entry written without `evidence_status` and `evidence` | `GET /api/runs/{run_id}/results` | HTTP 200, `body["matches"][0]["evidence_status"] is None` and `body["matches"][0]["evidence"] == []` | holdout |
| AC-24 | `S` with `models_universe_funnel_enabled=False`; theme `T` with the single activity `A`; company `C`; a registry stub whose `fetch_all(C)` returns `[D1]`; a run made with `create_theme_run`, then `execute_theme_run(run_id, T, [C], llm=stub, registry=..., settings=S, run_store=...)` | `GET /api/runs/{run_id}/results` | `body["matches"][0]` has `"evidence_status": "selected"` and an `evidence` list whose `chunk_id`s equal, in order, `[c.chunk_id for c in E]` | holdout |
| AC-25 | Same as AC-24 | same | every entry of `body["matches"][0]["evidence"]` has exactly the keys `chunk_id`, `doc_id`, `rank`, `page`, `char_start`, `char_end`, `section`, `scores`, `ranks` (no passage text) | holdout |
| AC-26 | Same as AC-20 | `match_company_activity` | `match.evidence_status == "no_documents"` and `match.evidence == []` | holdout |
| AC-27 | Same as AC-21 | same | `match.evidence_status == "no_matching_chunks"` and `match.evidence == []` | holdout |
| AC-28 | `D1` | same | `match.evidence_status == "selected"` | holdout |
| AC-29 | Same as AC-22 | same | `match.evidence_status is None` and `match.evidence == []` | holdout |
| AC-30 | Same as AC-20, with `A.core_isic_codes=["2790"]`, `company_isic="2790"` and an indirect model `M` giving `max(upstream_exposure, downstream_exposure) >= indirect_exposure_review_threshold` (fixture `M` of `2026-11-03-theme-evidence-record-design.md`) | same | `"structural exposure" in match.adjudicator_rationale` (precondition asserted) and `match.evidence_status == "no_documents"` | holdout |
| AC-31 | `D1` | same | for every `i`, `match.evidence[i].ranks["bm25"] == i + 1` (BM25 only, no reranker: the order shown is the BM25 order) | holdout |
| AC-32 | `D1`; `X = {}`, `E = field_evidence(F(A), [D1], S, explain=X)` | same | for every `i`, `match.evidence[i].scores == X["scores"].get(E[i].chunk_id, {})`, and `match.evidence[0].scores["bm25"] > 0` | holdout |
| AC-33 | `D1` | same | the advocate prompt equals `run_advocate`'s prompt on `main` `7e2e955` for `C.name`, `A`, `E` (unchanged) | holdout |
| AC-34 | `D1` | same | the opposing prompt equals `run_opposing`'s prompt on `main` `7e2e955` for `C.name`, `A`, `E` and the stub advocate opinion (unchanged) | holdout |
| AC-35 | `D1`; `funnel_thresholds` any dict; `arp.research.match_graph.score_pair` monkeypatched to return a `FunnelRecord` with `passed=False` | same | `match.adjudicator_rationale == "screened out by funnel"`, `match.evidence_status == "selected"` and `[e.chunk_id for e in match.evidence] == [c.chunk_id for c in E]` | holdout |

Must not change: no-documents and no-evidence outcomes (AC-20, AC-21), the revenue short-circuit (AC-22), the
adjudicator system prompt (AC-4), the advocate and opposing prompts (AC-33, AC-34), the flag rule on the adjudicator's own citations (AC-16, AC-17, AC-18), old
stored results (AC-23). The tests in `backend/tests/test_research_pipeline.py`,
`backend/tests/test_funnel_integration.py` and `backend/tests/test_funnel_cli.py` stay unchanged and green.
