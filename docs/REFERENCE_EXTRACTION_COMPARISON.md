# Extraction Pipeline vs. Reference Pipeline: Comparison

Compares this repository's extraction stack with a reference ESG extraction
and scoring pipeline specification. The reference runs an ad-hoc or batch run
per company:

upload → malware scan → embeddings → LLM extraction → rules-based scoring
engine → a four-stage HITL sign-off

It produces a 1–7 transition maturity score across five clusters (Ambition,
Strategy, Governance, Peer comparison, Net Zero pathway).

The closest things here are the **Data-Point Extraction Engine**
(`backend/arp/extraction/`) and the **Transition Plan Assessment**
(`backend/arp/transition_plan/`). Transition Plan Assessment is the closest
analogue to the maturity score: fixed indicators, per-indicator RAG verdicts, citations.

Verdicts use the same three levels as
[`SPEC_GAP_ANALYSIS.md`](SPEC_GAP_ANALYSIS.md): **Built**, **Partial**, **Not built**.

## Summary

The core extraction stage here is at least as rigorous as the reference.
Every value goes through extractor → independent verifier → programmatic
grounding → a review decision based on confidence.

The gaps are in the stages around extraction:

- no deterministic scoring engine that turns verdicts into a maturity score
- no malware scan on upload
- ~~no DOCX parsing~~ (done)
- no client identifiers (ISIN/LEI/internal client ID/NACE) on the company record
- no multi-role approval workflow
- no per-stage run monitoring
- no flags or controversy check

## Stage-by-stage (reference DAG → this repo)

| # | Reference node | Here | Verdict | Evidence / gap |
|---|---|---|---|---|
| 1 | `START_PROCESS` | `JobManager.create_run` → `RunManifest` | Built | `orchestration/job_manager.py`; status enum `JobStatus` (pending/running/completed/partially_completed/failed/cancelled). |
| 2 | `CONTENT_SEARCH` (AI, approved web sources) | Document Discovery | Partial | `discovery/site_finder.py` finds the IR homepage via DuckDuckGo, and `discovery/crawler.py` does a bounded, same-domain crawl that respects robots.txt. The search is deterministic, not AI, and there is no **allowlist of approved sources**. The only restriction is same-domain. |
| 3 | `POPULATE_URL` | `SourceDocument.source_url` | Built | Set by the downloader. |
| 4 | `DOCUMENT_MGMT` | `documents_dir/<company>/<doc_type>/`, document registry, `change_detector.py` | Built | Manual uploads (`POST /api/documents/upload`) and crawled files share one layout. |
| – | Malware scan | — | **Not built** | `api/routers/documents.py::upload_document` writes the uploaded bytes straight to disk. There is no AV scan, no size cap and no MIME/extension check before `write_bytes`. |
| 5 | `EMBED_CHUNK_INDEX` (PDF, DOCX → text) | `ingestion/local_files.py` (docling for PDF and DOCX), `ingestion/parsing.py` chunking, BM25 plus local multilingual embeddings | Built | Handles PDF, DOCX, HTML, text and XLSX. A DOCX has no fixed pages, so its citations carry no page number. The embedding model is local fastembed `paraphrase-multilingual-MiniLM-L12-v2`, not a hosted embedding service. |
| 6 | `INITIALIZE_OUTPUT` | Empty result and review-queue files per run (`RunStore`) | Built | |
| 7 | `EXTRACTION` (AI; metric: combinations extracted, duration) | `extraction/field_graph.py` (gather → extract → verify → aggregate); `transition_plan/indicator_graph.py` | Built (metrics partial) | Extraction logic is stronger than the reference (see below). The manifest tracks completed companies, tokens and cost, but not **combinations extracted per stage** or **stage duration**. |
| 8 | `SCORING` (AI alignment, then rules engine) | — | **Not built** for the maturity score | Transition Plan Assessment stops at counts (`disclosed_count`, walk/talk, `by_category`). Nothing maps verdicts to 1–7 criterion scores or cluster scores. Decision Studio (`arp/decision/`) is a deterministic scoring engine, but it scores tables across entities and has no maturity-score criteria grid. |
| 9 | `FINAL_SCORE` (score, override status, controversy check, priority flags) | — | **Not built** | No maturity score, no priority flags, no controversy check on this path. Controversy logic exists only in stewardship (`stewardship/monitoring.py`). |
| 10 | `END_PROCESS` | `run_company_batch` finalisation | Built | |

## Extraction core: where this repo goes further

| Aspect | Reference | Here |
|---|---|---|
| Verification | A single LLM pass, with humans as the only check | A separate verifier agent on a **different model** (`llm_verifier_model`). It disagrees by returning a corrected value, which drops trust and routes the field to review (`extraction/aggregator.py`). |
| Citation trust | "Traceback links" to source pages | `arp/grounding.py` re-finds every quote in the source text (exact match, then fuzzy) and computes the page itself. The model's self-reported location is not trusted. |
| Review routing | Everything goes to a first-line review team | Only fields that are ungrounded, disputed by the verifier, low-confidence or conflicting go to the review queue. Fields with no evidence are reported as plain "not disclosed" so they don't flood the queue at 4,000-company scale. |
| Failure isolation | Not specified | A schema-invalid answer on one indicator is recorded as `assessment_error`. The other 63 indicators still complete (`transition_plan/indicator_graph.py`). |
| Resumability | Not specified | Results are checkpointed per company to `results.jsonl`, and runs can be cancelled and resumed. |
| Provenance | Not specified | Every field stores the model and prompt version for both extractor and verifier (`ProvenanceInfo`). |

**Inconsistency found while comparing.** Transition Plan Assessment does not use
the extraction engine's decorrelated verifier:

- `indicator_graph.py::_verify` passes `state["llm"]`, the same model as the
  answerer, and `create_transition_plan_run` records no `verifier_model`.
- It also ignores `settings.hybrid_retrieval_enabled` and always uses BM25.

**Fixed:** the verify step now runs on the verifier model, the run records both models, and evidence search follows `hybrid_retrieval_enabled` as in extraction.

## Data model

| Reference field | Here | Verdict |
|---|---|---|
| customerName, country, sector | `CompanyRef.name/country/sector` | Built |
| ISIN | Portfolio holdings only (`schemas/portfolio.py`), not `CompanyRef` | Partial |
| LEI, internal client ID | — | Not built |
| NACE code | `CompanyRef.isic_code`, plus a NACE crosswalk in `research/standards_mapping/` | Partial |
| region | — | Not built |
| assignee | — | Not built. Review uses a free-text `reviewer` name per decision, and there is no assignment. |
| runVersion, runType (Ad Hoc / Batch), runMode (AI / Non-AI) | `run_id`, `run_type` (the function, not ad-hoc vs. batch) | Partial. No Non-AI mode (a manual-entry-only run). |
| run started / completed timestamps | `created_at` / `updated_at` | Partial. No explicit start and completion stamps. |
| Scoring clusters (5) | Indicator categories: target, governance, strategy, tracking | Partial. Different taxonomy (Colesanti Senni et al. 2024). No Peer comparison or Net Zero pathway cluster. |
| Upload categories: Sustainability, Controversies, Green Revenue, Financials, Other | `DocType`: 10-K, DEF-14A, sustainability_report, earnings_transcript, investor_presentation, product_page, research_paper, other | Partial. Missing Controversies, Green Revenue and Financials. |

## Human-in-the-loop

| Reference | Here | Verdict |
|---|---|---|
| Stage 1: system outputs draft scores | Results plus review queue | Built |
| Stage 2: first-line team verification | — | Not built as a role |
| Stage 3: business reviewer check, overrides, targeted recalculation | `record_review_decision`: approve / edit / reject, append-only with full history | Partial. One undifferentiated reviewer. There is no targeted recalculation, i.e. re-running one criterion or company without a new run. |
| Stage 4: final binding approval by a governance team | — | Not built. No four-eyes or final sign-off state. |
| Coverage status (Pending to coverage team → … → Approved / Declined) | — | Not built. No per-customer workflow status. |
| Criteria tab read-only, overrides only in the controlled flow | Overrides go through the review endpoint; the results view doesn't edit in place | Built in effect, but not enforced by role |
| Evidence: open the PDF and **highlight the exact sentence** | `SourcePanel` iframe with `#page=N` and the quote shown above it | Partial. Jumps to the page but does not highlight inside the PDF. |
| Batch monitoring (BATCH / CUSTOMER / CREATED / RUN START / RUN END / STATUS) | `RunHistory.tsx`, `RunProgress.tsx`, `MonitoringDashboard.tsx` | Partial. Shows per-run progress, not per-DAG-node status or duration per customer. |

## Suggested order to close the gaps

1. **Upload hardening.** Add a malware scan (e.g. ClamAV), a size cap and an
   extension allowlist to `upload_document`. This is a security gap, not a
   feature gap.
2. ~~**Align Transition Plan with extraction.**~~ **Done.** The verify step gets
   `verifier_llm`, the run records `verifier_model`, and search honours
   `hybrid_retrieval_enabled`.
3. ~~**DOCX parsing**~~ **Done.** `local_files.py` reads `.docx` through the same
   docling converter as PDFs.
4. **Maturity-score rules engine.** Add a static criteria grid (criterion → 1–7 level
   rules over indicator verdicts and extracted fields), then cluster scores and
   priority flags. Zero LLM calls, following the repo's "LLM plans,
   deterministic code computes" rule.
5. **Identifiers and upload categories.** Optional `isin`, `lei`, `client_id`,
   `nace_code` and `region` on `CompanyRef`, and the three missing `DocType`s.
6. **Workflow roles.** A per-company status machine (the six-state coverage
   enum), assignee, and a role on each review decision, with final approval
   gated to a separate person (four-eyes).
7. **Per-stage run telemetry** (start and end time plus item counts per node)
   on the manifest, then PDF sentence highlighting in `SourcePanel` (pdf.js
   text layer).

Deliberately not proposed: an "AI scoring" step before the rules engine. The
reference's node 8 has the LLM "interpret and align" variables before scoring.
Here that job belongs to the verifier and the grounding check, and letting an
LLM adjust inputs to a deterministic score would undo that separation.
