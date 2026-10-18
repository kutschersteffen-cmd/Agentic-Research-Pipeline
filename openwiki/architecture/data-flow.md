---
type: data flow
title: "Data flow: documents to UI"
description: End-to-end path of a value in the Agentic Research Pipeline, from a source document through ingestion, extraction and grounding, the per-company Postgres transaction, human review and publishing, to the API and the React UI.
tags: [data-flow, architecture, ingestion, extraction, postgres, review, publish]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-ff65d30b749b1ae6c22f8f1f
    resource: repo://backend/arp/api/deps.py
  - id: openwiki-source-c73f1700e3a276fc929ee905
    resource: repo://backend/arp/api/routers/companies.py
  - id: openwiki-source-0a0878f7a78cfb8cf6cb9434
    resource: repo://backend/arp/api/routers/publish.py
  - id: openwiki-source-a989f81f471aadf065d43bd9
    resource: repo://backend/arp/api/run_scheduling.py
  - id: openwiki-source-df85c6c0a076c4c0b6b761a3
    resource: repo://backend/arp/db/observations.py
  - id: openwiki-source-5f3fcfb2040b636f88345e57
    resource: repo://backend/arp/db/runs.py
  - id: openwiki-source-88bc712a147e351ba5cc9e96
    resource: repo://backend/arp/extraction/pipeline.py
  - id: openwiki-source-40c2b2ee0603b72d794f5a1b
    resource: repo://backend/arp/ingestion/local_files.py
  - id: openwiki-source-ab77b64af40ff607e4934e59
    resource: repo://backend/arp/ingestion/registry.py
  - id: openwiki-source-f74b8e52a604e5aa1c5c5497
    resource: repo://backend/arp/orchestration/batch_runner.py
  - id: openwiki-source-e1203af9dfebfe1b0264745d
    resource: repo://frontend/src/api/client.ts
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# Data flow: documents to UI

This page follows one extracted value from the document it came from to the screen that shows it. Each stage has
its own page; this one shows how they connect and where a value is stored at each step.

```
documents (data/documents, EDGAR, ESEF)
  └─ DocumentSourceRegistry.fetch_all ── parse → SourceDocument(full_text, page_breaks, table_spans, content_key)
       └─ execute_extraction_run → run_company_batch → _extract_company (per company)
            └─ per field: tagged XBRL? → evidence → extract → verify → [adjudicate] → aggregate+ground
            └─ checks → route (auto_accept | review | hold) → ExtractionRecord
       └─ RunStore.record_company_result (ONE transaction per company)
            run_results · field_observations + value_citations · company_facts · review_items
  └─ human review (POST /api/review/runs/{run}/items/{key}/decision) → review_decisions → company_facts
  └─ publish_run (POST /api/publish/runs/{run}) → releases · published_facts · fact_events
  └─ API reads (/api/companies/{ref}/facts, /api/publish/facts, run results) → frontend/src/api/client.ts → pages
```

## 1. Source documents

Documents come from several `DocumentSource`s fanned out by `DocumentSourceRegistry` in
`backend/arp/ingestion/registry.py`. The sources are fetched concurrently. One failing source is logged and skipped,
and documents are de-duplicated by their text hash, in source order. The API wires three sources in
`backend/arp/api/deps.py` (`build_registry`):

- `LocalFileDocumentSource` (`backend/arp/ingestion/local_files.py`) reads `documents_dir/<company_id>/<doc_type>/*`.
  Manual uploads and the discovery crawler both write to this layout, so a crawled file is visible to extraction
  without any extra step.
- `EdgarDocumentSource` (`backend/arp/ingestion/edgar.py`) fetches SEC filings.
- `EsefDocumentSource` handles EU ESEF filings and is only added when `esef_enabled` is set.

Parsing produces a `SourceDocument` (`backend/arp/schemas/common.py`) with `full_text`, `page_breaks`,
`table_spans`, a `content_key` and the `parser_version`. With a content store configured, the local source parses
through `get_or_parse` (a cache keyed by content and parser version), registers the document, and archives the
original bytes in a blob store. The archive step is mandatory: a failed or unverified upload drops the file from that
fetch. These archived originals are what the publish lineage gate checks later (see
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Publishing facts](/openwiki/pipeline/publish.md)).

## 2. Starting a run

The UI and API start extraction through `POST /api/extraction/start` (a `profile` picks custom, financials, TNFD or
transition plan) or `POST /api/extraction/runs`, both in `backend/arp/api/routers/extraction.py`.
`schedule_llm_run` in `backend/arp/api/run_scheduling.py` builds the extractor and verifier LLM clients *before*
creating the run manifest, so a missing API key fails without leaving an orphaned "running" run. It then launches the
run in the background. `create_extraction_run` (`backend/arp/extraction/pipeline.py`) registers the schema and refuses
to start unless every field is released or the run is a trial. It also writes the registered schema to the run's
`schema.json` side file.

## 3. Extraction, per company

`execute_extraction_run` hands the company universe to `run_company_batch`
(`backend/arp/orchestration/batch_runner.py`). For each company the worker runs the optional pre-steps (`prepare_company`
in `backend/arp/extraction/pre_steps.py`: identity, content search, document management, parse/index) and then
`_extract_company`, which:

1. fetches documents and confirms the entity. Documents of another entity are *held*, not used.
2. plans the reporting periods and, for each field, either reuses the previous run's rows (when the input hash,
   field version and checks allow it) or runs the per-field LangGraph graph.
3. runs record checks, routes every field (`auto_accept`, `review`, `hold`), evaluates derived fields last, and
   builds an `ExtractionRecord`.

Inside the per-field graph every model citation is re-checked by `backend/arp/grounding.py` against the document
<!-- openwiki: broken internal link [/openwiki/pipeline/extraction.md] link "/openwiki/pipeline/extraction.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
text before the value is accepted. See [Data-point extraction engine](/openwiki/pipeline/extraction.md) and
<!-- openwiki: broken internal link [/openwiki/pipeline/grounding.md] link "/openwiki/pipeline/grounding.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Citation grounding](/openwiki/pipeline/grounding.md).

## 4. The per-company transaction into Postgres

When a company finishes, `_commit` in `run_company_batch` converts the result row to observations
(`to_observations` in `backend/arp/db/to_observations.py`) and calls `RunStore.record_company_result`
(`backend/arp/db/runs.py`) with retry. In **one transaction** that call writes:

- the `run_results` row. A `_key` that is already stored writes nothing, which makes resume idempotent.
- run errors for values that did not fit their field.
- `field_observations` with their `value_citations`. These form an insert-only ledger. Citations to documents that
  are not registered are dropped and reported as run errors.
- updates to `company_facts`, the current-fact layer, through the `decide` rule in
  `backend/arp/db/observations.py`.
- held documents, and the review items for every field routed to review.

Progress, token use and cost are recorded after the transaction. Interrupting a run therefore never leaves a stored
<!-- openwiki: broken internal link [/openwiki/operations/runs-and-review.md] link "/openwiki/operations/runs-and-review.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
result without its observations or review items. See [Runs, persistence and review](/openwiki/operations/runs-and-review.md).

The current-fact rule (`decide`) is conservative. A not-found value never removes a fact, a value still pending review
never displaces one, and a held value never displaces an accepted fact. Only an accepted value that differs in value or
status supersedes the current row.

## 5. Human review

Fields routed to `review` appear in the review queue UI. A decision is posted to
`POST /api/review/runs/{run_id}/items/{item_key}/decision` (`backend/arp/api/routers/review.py`). The store appends
it to `review_decisions` (append-only, so the audit trail is kept) and applies it to `company_facts`
(`observations_db.apply_review`). An approve, edit or correct sets the fact to approved or edited, and a hold sets
it to held. A reject retires a pending fact that the rejected observation had made current, and an escalate changes
nothing. Decisions on trial runs never produce facts (`apply_decision` in `backend/arp/db/observations.py`).

## 6. Publishing

Publishing is a separate, explicit step that only an approver can take: `POST /api/publish/runs/{run_id}` or
`arp publish` (`backend/arp/cli/publish.py`). `publish_run` (`backend/arp/publish/release.py`) selects candidates
from the run (auto-accepted rows and final review decisions), blocks any document whose archived original is missing or
whose hash does not match, and writes one release per (issuer, document). Each release carries versioned
`published_facts` and `fact_events` outbox rows. In the current frontend source, no page calls the publish endpoints;
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
they are used from the API and CLI. See [Publishing facts](/openwiki/pipeline/publish.md).

## 7. Reading it back

- **Company facts**: `GET /api/companies/{ref}/facts` and `GET /api/facts/{fact_id}/trail`
  (`backend/arp/api/routers/companies.py`, backed by `backend/arp/db/company_view.py`) read `company_facts`, their
  observations and their citations. The Company page calls them through `getCompanyFacts` and `getFactTrail` in
  `frontend/src/api/client.ts`.
- **Run results**: `/api/extraction/runs/{run_id}/results` and `/api/runs/...` read `run_results`, which the
  Extraction and Run History screens use.
- **Published facts**: `GET /api/publish/facts?as_of=` reads as-of views over `published_facts`
  (`backend/arp/publish/reader.py`). The extraction pipeline also reads them back as one reference in its
  cross-source checks (`_published_values` in `backend/arp/extraction/pipeline.py`).

The frontend reaches the API through one `request<T>()` helper with a bearer token. See
<!-- openwiki: broken internal link [/openwiki/architecture/frontend.md] link "/openwiki/architecture/frontend.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Frontend application](/openwiki/architecture/frontend.md).
