---
type: pipeline subsystem
title: Data-point extraction engine
description: How backend/arp/extraction turns a released data-point schema into one grounded, checked and routed value per company, field and period. Covers reuse by input hash, the XBRL tagged-value shortcut, the LangGraph extract, verify, adjudicate and aggregate graph, how aggregation applies grounding, record checks, three-way routing (auto_accept, review, hold) and derived fields.
tags: [extraction, langgraph, verifier, adjudicator, aggregation, routing, xbrl, review]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-b7f3c5cef64fbcbf671e92aa
    resource: repo://backend/arp/checks/runner.py
  - id: openwiki-source-4f3a2539c0f611dd5dbeb606
    resource: repo://backend/arp/extraction/adjudicator.py
  - id: openwiki-source-12dce128089231b9b75b36aa
    resource: repo://backend/arp/extraction/aggregator.py
  - id: openwiki-source-a5d7b996dd3eda8f7d5b99a9
    resource: repo://backend/arp/extraction/derived.py
  - id: openwiki-source-40a025f818fc1d495c071c90
    resource: repo://backend/arp/extraction/extractor_agent.py
  - id: openwiki-source-81b18e1c7ad40a56b094e1ee
    resource: repo://backend/arp/extraction/field_graph.py
  - id: openwiki-source-f6c9c874632ce4702b2b9a1b
    resource: repo://backend/arp/extraction/graph_shape.py
  - id: openwiki-source-88bc712a147e351ba5cc9e96
    resource: repo://backend/arp/extraction/pipeline.py
  - id: openwiki-source-e93a2b3851ffe11026e80bab
    resource: repo://backend/arp/extraction/routing.py
  - id: openwiki-source-0e97249b26e446b6246c8909
    resource: repo://backend/arp/extraction/verifier_agent.py
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# Data-point extraction engine

The Data-Point Extraction Engine (function 3 in `README.md`) pulls schema-defined figures, such as green capex, from
company disclosures. Its main idea is to treat the model's answer as a draft. A second model checks it, a third settles
any typed disagreement, and code then re-verifies every citation against the source (`backend/arp/grounding.py`)
before a rules-only router decides whether a person must look at the value.

Entry points: `create_extraction_run`, `execute_extraction_run` and `run_extraction` in
`backend/arp/extraction/pipeline.py`. These are reached from `POST /api/extraction/start` or `/api/extraction/runs`
(`backend/arp/api/routers/extraction.py`) and the `arp extract` CLI. The financials, TNFD and transition-plan profiles
have their own pipelines but compile the same graph shape (see below).

## Run creation: only released schemas

`create_extraction_run` registers the schema (`SchemaRegistry` in `backend/arp/db/fields.py`) and raises
`UnreleasedFieldError` unless the schema is released and every field has status `released`. A `trial` run skips that
check, but routing then sends every non-held row to review (`unreleased_version`), and publishing skips trial runs
entirely. The registered schema is saved as the run's `schema.json`, and `execute_extraction_run` reloads it, so a run
always uses the snapshot it started with.

## Per company: `_extract_company`

For each company, run through the shared batch runner (see
<!-- openwiki: broken internal link [/openwiki/operations/runs-and-review.md] link "/openwiki/operations/runs-and-review.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Runs, persistence and review](/openwiki/operations/runs-and-review.md)):

1. **Documents and entity check.** `registry.fetch_all` returns the company's documents, and `confirm_entity`
   (`backend/arp/planning/entity_check.py`) marks each one. A document with `MISMATCH` status, meaning it is about
   another entity, is *held*: it is listed in `held_documents` and not used, unless a person released it in an earlier
   run. If every document is held, every field becomes a held no-evidence row.
2. **Planning.** `plan_fields` (`backend/arp/planning/applicability.py`) skips fields that do not apply. Derived fields
   never go to the model. `plan_periods` builds the reporting periods to extract, informed by periods already recorded
   for the issuer.
3. **Reuse.** For each field, an `input_hash` covers the field definition, the routed documents, the planned periods
   and the settings that affect the answer (`input_settings`: models, grounding threshold, review threshold, retrieval
   options). If the last run's rows share that hash and field version, were not rejected by a human, and have no
   failing non-rule check, they are reused with `reused_from_run` set and no model call. A cache-refresh restart turns
   reuse off.
4. **XBRL facts.** When `xbrl_facts_enabled` is set and any field has `xbrl_tags`, a `ChainedFactSource` is built from
   SEC companyfacts and any ESEF filing among the documents. ESEF comes first for a company without a CIK.
5. **Field graphs**, run concurrently under a run-wide semaphore (`max_concurrent_llm_calls`). With
   `extraction_group_size > 1`, low-risk fields without XBRL tags share one extract call over merged evidence. Each field
   is still verified, adjudicated and grounded on its own, and a failed group call falls back to one call per field.
6. **Checks.** `check_record` (`backend/arp/checks/runner.py`) runs the record checks: numeric, plausibility,
   consistency, prior period, round trip, cross-source and schema rules. Cross-source references come from
   `build_references`: a tagged XBRL fact for an extracted value, an earlier text extraction for a tagged value, and
   the currently published value from `backend/arp/publish/reader.py`. A failing non-rule check adds `check_failed`.
7. **Routing**, then **derived fields** (see below), then an `ExtractionRecord` with `needs_review`, the documents used
   and the held documents. Cost is estimated per call against the model that produced it.

## The per-field graph

`backend/arp/extraction/graph_shape.py` builds the one LangGraph topology that every extractor/verifier pipeline uses.
`backend/arp/extraction/field_graph.py`, `backend/arp/extraction/financials_graph.py`,
`backend/arp/extraction/tnfd_graph.py` and `backend/arp/replication/spec_graph.py` supply only their node bodies.
The custom-schema graph is compiled once and reused for every company and field:

```
try_tagged ──(all planned periods tagged)──► END
    │ else
gather_evidence ──(no evidence)──► finalize_no_evidence ──► END
    │
extract ──► verify ──(typed disagreement)──► adjudicate ──► aggregate ──► END
                 └──────(agrees)──────────────────────────► aggregate
```

- **`try_tagged`.** When the filer's own XBRL fact exists for *every* planned period (the period end may drift by up
  to 7 days for 52/53-week years), the field takes those values with `method="tagged"`, confidence 1.0, the fact
  itself as the citation, and no model call. Otherwise the graph continues normally, all or nothing.
- **`gather_evidence`.** `field_evidence` routes documents and sections, chunks them and ranks the passages (see
<!-- openwiki: broken internal link [/openwiki/integrations/llm-and-retrieval.md] link "/openwiki/integrations/llm-and-retrieval.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
  [LLM clients and evidence retrieval](/openwiki/integrations/llm-and-retrieval.md)). With no evidence the field is
  reported plainly as not found (`no_evidence_field`), without review, because at a scale of 4,000 companies most
  fields are undisclosed for most companies.
- **`extract`.** `extract_field` (`backend/arp/extraction/extractor_agent.py`) returns one value per reported period,
  most recent first. Each value carries verbatim quotes tagged with `doc_id` and `passage_id`. The prompt forbids
  estimating values and forbids unit conversion: the value is the number as printed, and the app converts.
- **`verify`.** This step runs on the separate verifier model. For normal fields, `verify_extraction` sees the draft
  and must classify any problem (`value`, `unit_or_scale`, `period`, `entity`, `not_disclosed`) and back a correction
  with verbatim citations. For **high-risk** fields, `blind_verify` re-extracts without seeing the draft, and *code*
  (`compare` in `backend/arp/extraction/verifier_agent.py`) decides the disagreement type. That includes detecting
  values that are a power of ten apart as a unit or scale error.
- **`adjudicate`.** Only a typed disagreement reaches this third call (`backend/arp/extraction/adjudicator.py`), which
  also runs on the verifier client. It settles `values[0]` only when the evidence decides the question, and must cite
  verbatim.
- **`aggregate`.** `build_extracted_fields` (`backend/arp/extraction/aggregator.py`) merges everything into one
  `ExtractedField` per period and attaches provenance: the models and prompt versions of extractor, verifier and
  adjudicator, plus the schema and field version. An optional vision fallback re-checks values that failed grounding
  against the rendered page.

## Aggregation: grounding decides what becomes the value

`build_extracted_fields` grounds every citation with `ground_citations(..., passages=evidence)`, so a quote only
counts if it lies inside a passage the model was actually shown. The rules:

- A verifier correction replaces the extractor's value only when at least one of its citations grounds. An uncited or
  ungrounded correction leaves the extractor's value in place and adds `verifier_correction_uncited`.
- An adjudicator value is applied only with a grounded citation (`method="adjudicated"`). If it is unresolved, the
  extractor's, verifier's and adjudicator's values are all kept as `alternatives` for the reviewer.
- The final confidence is `min(extractor, verifier)` for a claimed value and 0 otherwise.
- `grounded` is true only when every final citation grounds, or when there is no value to ground.
- The review reasons are `not_grounded`, `verifier_disagrees` (dropped when a disagreement was settled on a low-risk
  field whose value converted to the field's unit), `verifier_correction_uncited`, `adjudicator_unresolved`,
  `conflict` (conflicting sources or two values for one period), `low_confidence`, plus the typing and normalisation
  reasons from `typed_value` (`backend/arp/normalise/value.py`).
- Periods are deduplicated by resolved `period_end`. Any further values for the same period become `duplicate`
  alternatives.

## Three-way routing

`route` in `backend/arp/extraction/routing.py` is rules only, with no model call. Its output is the system's decision
and is stored on the result row, never as a review decision:

- **hold**: the documents were another entity's (`entity_mismatch`).
- **auto_accept**: a field skipped by an applicability rule, or a field with no reasons at all.
- **review**, with reasons, when any of the following holds:
  - the run is a trial or the field version is unreleased;
  - the field carries any review reason;
  - a found or zero value is not grounded (checked again here as defence in depth);
  - a boolean field is not applicable;
  - a check failed;
  - the field's first audit has not passed;
  - confidence is below the field's `auto_accept_min`;
  - a high-risk field reads not found without a verifier pass.

`review_items` in `backend/arp/extraction/pipeline.py` turns every review-routed field into a review item keyed by
`issuer_key:field_id:period` (`field_item_key`).

## Derived fields

A field with a `derived_rule` is computed after routing by `evaluate_derived` (`backend/arp/extraction/derived.py`).
It is a company-level yes/no over boolean inputs (`all_of` / `any_of`) using three-valued logic: an undisclosed input
never counts as false. An input that failed a check or was not auto-accepted holds the derived row back.

## Tests

The rules above are pinned in `backend/tests/test_aggregator.py` (grounding, corrections, alternatives, periods),
`backend/tests/test_routing.py` (every route reason), `backend/tests/test_extraction_pipeline.py`,
`backend/tests/test_field_graph_high_risk.py` (blind verification) and `backend/tests/test_doc_routing.py`. The golden
set (`arp golden-set run`, `backend/arp/golden_set`) runs real-model cases. CI runs it on PRs that touch
`backend/arp/extraction`, `backend/arp/llm` or `backend/arp/grounding.py`.

<!-- openwiki: broken internal link [/openwiki/pipeline/grounding.md] link "/openwiki/pipeline/grounding.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
Next: [Citation grounding](/openwiki/pipeline/grounding.md) for the matching itself, and
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Publishing facts](/openwiki/pipeline/publish.md) for what happens to accepted values.
