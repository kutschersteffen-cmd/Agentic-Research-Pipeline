# Retrieval gold set and question-based queries

Spec slug: `retrieval-gold-set-and-question-queries`. Items #1 and #3 of the RAG improvement plan
(https://claude.ai/artifact/RnMhVmhQNmJPwY8UCaY38t). Research: `docs/RAG_SYSTEMS_LANDSCAPE_RESEARCH.md`.

## Why

1. **Nothing measures retrieval in CI.** `arp golden-set retrieval` exists, but it reads a reviewed run from
   Postgres, so CI cannot run it, and no retrieval change is checked against a number.
2. **The transition-plan search ignores the indicator text.** Each of the 64 indicators has a question and
   a guideline of several sentences (`transition_plan/data/indicators.json`), but evidence is searched with
   only the ~5 hand keywords in `presets/data/transition_plan_keywords.json`. The source paper searched with
   the question itself (Colesanti Senni et al. 2024, supplement S.5: "each question is embedded",
   ada-002, 350-token chunks, top 8), and its expert pilot's main criticism was missed pages
   (supplement, pilot questions Q5–Q8).

## What changes

### Part A: a gold set CI can read

1. **Cases file** `backend/tests/golden/retrieval/cases.json`, a list of:
   `{case_id, schema_id, field_id, company_id, document, gold: [{span_text}], labelled_by: "agent"|"owner", spot_checked: bool}`.
   `document` is a filename under `backend/tests/golden/retrieval/documents/<company_id>/`. Gold is stored as
   text, not offsets, so a parser upgrade does not invalidate it.
2. **Hit rule.** A gold span is hit at rank *r* when the evidence chunk at rank *r* contains the span text
   after `grounding.py`'s normalisation (whitespace, dashes, quotes, ligatures, hyphen breaks). A span whose
   text is not found in the parsed document is *stale*: it is left out and counted, as in the run mode today.
3. **CLI.** `arp golden-set retrieval` gains `--cases <file>` and `--min-recall <0..1>`. `--cases` and
   `--run-id` are mutually exclusive and one is required. `--documents-dir` defaults to the cases file's
   `documents/` sibling in cases mode. `--min-recall` applies to recall@`evidence_max_chunks`. Output line
   and JSON report are the same shape as the run mode.
4. **Labelling** (done in a separate session, not by the implementer): two public sustainability reports,
   with a public, redistributable licence or explicit permission recorded in `backend/tests/golden/retrieval/LABELS.md`.
   Claude labels, for each transition-plan indicator the report answers YES to, the shortest passage(s)
   that answer it. Indicators answered NO get no case. The owner then spot-checks 10 random cases; those get
   `spot_checked: true`, and any rejected one is fixed or removed before commit.
5. **CI job** "Retrieval recall" in `.github/workflows/ci.yml`. It runs on PRs touching `backend/arp/retrieval/**`,
   `backend/arp/ingestion/**`, `backend/arp/planning/doc_routing.py`, `backend/arp/extraction/field_graph.py`,
   `backend/arp/presets/**` or `backend/tests/golden/retrieval/**`. It runs cases mode with the default
   settings (hybrid on, rerank off) and `--min-recall` set to a floor stored in the workflow file:
   the recall@12 measured on `main` when this ships, minus 0.02. Raising the floor is a manual edit. No API key is needed.

### Part B: search with the question

1. **`FieldDefinition.retrieval_query: str | None = None`**: a natural-language query for the embedding
   ranking. When set and hybrid retrieval is on, the vector ranking in `select_relevant_chunks` and the
   reranker (when on) use it instead of the joined keywords. BM25 keeps using `seed_keywords` (+ German).
   When it is `None`, behaviour is exactly today's.
2. **Transition-plan preset:** every `tp_a_*` field sets `retrieval_query` to its indicator's `question`.
   The eight `tp_h_*` helper fields leave it `None`.
3. **Guideline include-terms:** a one-off, reviewed edit of `transition_plan_keywords.json` adds the
   concepts each guideline says count as a YES (for example "net zero", "carbon neutrality" and "return to
   2020 levels" for `A_headline_1`). Exclusion phrases ("intensity targets are not ...") are **not** added;
   they belong to plan item #12.
4. **No field version bumps.** Retrieval inputs change, the question each field answers does not.
5. **API contract:** the schema response gains `retrieval_query`. Regenerate `openapi` and the frontend types.

### Out of scope

- The false-support rate (plan #1's second number): it needs review decisions, so it waits for the review export.
- Query expansion for schemas other than the transition plan (plan #3's LLM-generated synonyms).
- Exclusion terms and the scope check (plan #12).

## Acceptance

Conventions for every row: ranks count from 0, so the top 12 are ranks 0–11. `evidence_max_chunks` is 12.
"Hybrid off" means `ARP_HYBRID_RETRIEVAL_ENABLED=false` (`--no-hybrid`): BM25 only, deterministic. Tests
that need to see the embedding or rerank query replace `arp.retrieval.embeddings.embed_texts` and
`arp.retrieval.rerank.rerank` with recording stand-ins (monkeypatch); no other seam is added. No prefix
or instruction text is added to any query.

| ID     | Given | When | Then (observable, exact) | Checked by |
|--------|-------|------|--------------------------|------------|
| AC-1   | A cases file with 3 cases in 3 fields; each document is built so BM25 ranks the chunk holding the gold text at rank 0 | `arp golden-set retrieval --cases <file> --no-hybrid` | Exit 0; stdout starts `3 gold span(s) over 3 field(s): recall@5 100.0%, recall@12 100.0%` | holdout |
| AC-1b  | Same as AC-1 with `--out <json>` | the command runs | The JSON has the keys `run_id` (null in cases mode), `settings`, `gold_spans`, `stale_spans`, `fields_ranked`, `recall_at_5`, `recall_at_12`, `median_seconds_per_field`, `max_seconds_per_field`, `misses` | holdout |
| AC-2   | As AC-1, but one document is built so its gold chunk ranks at 12 | `... --no-hybrid --min-recall 0.9` | Exit 1; stderr contains `recall@12 66.7% is below the minimum 90.0%` | holdout |
| AC-2b  | Same as AC-2 without `--min-recall` | the command runs | Exit 0; stdout starts `3 gold span(s) over 3 field(s): recall@5 66.7%, recall@12 66.7%` | holdout |
| AC-3   | 3 cases, one of whose gold text does not occur in its parsed document; the other two rank 0 | cases mode, `--no-hybrid` | Exit 0; stdout starts `2 gold span(s) over 2 field(s): recall@5 100.0%` | holdout |
| AC-3b  | Same as AC-3 | the command runs | stderr contains `Left out 1 span(s) whose text no longer matches the current parse.` | holdout |
| AC-4   | 1 case whose gold text differs from the document only by line breaks, an en dash and curly quotes; that chunk ranks 0 | cases mode, `--no-hybrid` | stdout starts `1 gold span(s) over 1 field(s): recall@5 100.0%` | holdout |
| AC-5   | Both `--cases` and `--run-id` passed | the command runs | Exit 2; stderr contains `Pass exactly one of --cases or --run-id.` | holdout |
| AC-5b  | Neither passed | the command runs | Exit 2; stderr contains `Pass exactly one of --cases or --run-id.` | holdout |
| AC-6   | The run-mode fixture used by `tests/test_retrieval_eval.py` (needs `ARP_TEST_POSTGRES_DSN`) | `--run-id` mode | stdout and JSON report are byte-identical to `main`'s for the same fixture | holdout |
| AC-7   | The committed `backend/tests/golden/retrieval/cases.json` | loaded | It names ≥ 2 distinct documents, each existing under `documents/<company_id>/` | holdout |
| AC-7b  | Same | loaded | ≥ 40 gold spans across ≥ 20 distinct `field_id`s, all from schema `transition_plan_indicators` | holdout |
| AC-7c  | Same | loaded | Every case has `labelled_by`; ≥ 10 cases have `spot_checked: true` | holdout |
| AC-7d  | Same and `LABELS.md` | read | `LABELS.md` names each document in `cases.json` with its licence or the permission given | evaluator |
| AC-8   | A PR changing only `backend/arp/retrieval/select_evidence.py` | CI runs | A check named `Retrieval recall` runs | evaluator |
| AC-8b  | A PR changing only files under `frontend/` | CI runs | No `Retrieval recall` check runs (or it reports skipped) | evaluator |
| AC-8c  | A `Retrieval recall` run | finished | The job summary contains the CLI's `gold span(s) over` line | evaluator |
| AC-8d  | The workflow file | read | Its `--min-recall` equals the `main` recall@12 stated in the PR description minus 0.02 | evaluator |
| AC-8e  | The repo without `ARP_ANTHROPIC_API_KEY` | `Retrieval recall` runs | It passes or fails on recall only, never on a missing key | evaluator |
| AC-9   | A field with `retrieval_query="Does the company report X?"`, hybrid on, recording `embed_texts` | evidence is selected | The query string passed to `embed_texts` is exactly `Does the company report X?` | holdout |
| AC-10  | The same field with `retrieval_query=None` | evidence is selected | The query string passed to `embed_texts` is `" ".join(with_german(seed_keywords))` | holdout |
| AC-11  | A field with `retrieval_query` set, hybrid off | evidence is selected | Returned chunk_ids and order equal those for the same field with `retrieval_query=None` | holdout |
| AC-12  | Rerank on, `retrieval_query` set, recording `rerank` | evidence is selected | `rerank`'s query argument is exactly the `retrieval_query` text | holdout |
| AC-13  | `build_transition_plan_schema()` | built | There are exactly 64 `tp_a_*` fields, each with `retrieval_query` equal to its indicator's `question` in `indicators.json` | holdout |
| AC-13b | Same | built | Every non-`tp_a_*` field has `retrieval_query` `None` | holdout |
| AC-13c | Same | built | Every field's `version` equals its value on `main` | holdout |
| AC-14  | The transition-plan schema through the API | `GET` | `tp_a_a_headline_1.retrieval_query` is `Does the company report an absolute GHG emission reduction target for the company?`; `tp_h_target_pct.retrieval_query` is `null` | holdout |
| AC-14b | The generated frontend API types | `cd frontend && npx tsc -b` | Exit 0, and the field type has `retrieval_query?: string \| null` | unit |
| AC-15  | `presets/data/transition_plan_keywords.json` | read | `A_headline_1` contains `net zero`, `carbon neutrality` and `return to 2020 levels` | holdout |
| AC-15b | Same | read | No keyword list contains `intensity target` for `A_headline_1` | holdout |
| AC-16  | The committed gold set, default settings | cases mode on the PR and on `main` | PR recall@12 ≥ `main` recall@12 | golden |
| AC-16b | Same | Same | PR recall@5 ≥ `main` recall@5 | golden |
| AC-17  | The bundled extraction golden set | `arp golden-set run` | Every case passes, as on `main` | golden |

Must not change: the run mode of `golden-set retrieval` (AC-6); retrieval for fields without
`retrieval_query` (AC-10); BM25-only retrieval (AC-11); field versions (AC-13c); extraction golden set (AC-17).

PR checklist (not ACs): the PR description lists `main`'s and the PR's recall@5 and recall@12.
