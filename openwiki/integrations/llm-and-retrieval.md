---
type: integration
title: LLM clients and evidence retrieval
description: The single structured-output LLMClient interface and its Anthropic, batch and Gemini implementations, covering the disk cache, prompt versioning, validation retries, the separate verifier model and cost accounting, plus how evidence passages are chunked and ranked (BM25, hybrid embeddings, OpenSearch, rerank) before a model sees them.
tags: [llm, anthropic, cache, cost, retrieval, bm25, embeddings, evidence]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-07e1021d4b7b6b7207c06144
    resource: repo://backend/arp/config.py
  - id: openwiki-source-5fbdedabbedd53f2d251a2ae
    resource: repo://backend/arp/ingestion/parsing.py
  - id: openwiki-source-6be4c107bfed89be7d9d1a4d
    resource: repo://backend/arp/llm/base.py
  - id: openwiki-source-1644e91bb747ad171b51d51f
    resource: repo://backend/arp/llm/batching_client.py
  - id: openwiki-source-0a6d88e6a2e05005324efd30
    resource: repo://backend/arp/llm/cache.py
  - id: openwiki-source-aa1e0c5fe845b9b0b5558eb6
    resource: repo://backend/arp/llm/factory.py
  - id: openwiki-source-d2f87b2c7e00e6f5fc038ece
    resource: repo://backend/arp/llm/langchain_client.py
  - id: openwiki-source-463fc26fcef5015399d9fc51
    resource: repo://backend/arp/orchestration/cost_tracker.py
  - id: openwiki-source-3b5d1bc3b85c193f0eab87ef
    resource: repo://backend/arp/retrieval/select_evidence.py
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# LLM clients and evidence retrieval

Every model call in `backend/arp` goes through one narrow interface, and every extraction prompt contains only a ranked
handful of passages instead of whole filings. This page covers both layers. How their output is used is described in
<!-- openwiki: broken internal link [/openwiki/pipeline/extraction.md] link "/openwiki/pipeline/extraction.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Data-point extraction engine](/openwiki/pipeline/extraction.md).

## The `LLMClient` interface

`backend/arp/llm/base.py` defines `LLMClient` as a `Protocol` with a single method:

```python
async def complete_structured(*, system, prompt, output_model, max_validation_retries=2,
                              temperature=0.0, max_tokens=8192, images=None) -> tuple[T, LLMUsage]
```

Agents never ask for free text. They pass a Pydantic `output_model` and get back a validated instance plus an
`LLMUsage`. `LLMUsage` carries tokens, including the cache read and write tokens, which are already counted inside
`input_tokens`. It also carries `cached`, `batch`, `attempts`, the producing `model`, and a `prompt_version`, a short
hash of the system prompt. Provenance records the model and prompt version of every extracted value, so output from a
later prompt edit can be told apart from earlier output.

## Anthropic client

`LangChainAnthropicClient` (`backend/arp/llm/langchain_client.py`) is the main implementation. Despite its name, it
calls the `anthropic` SDK's `AsyncAnthropic` directly. A call works as follows:

1. **Disk cache lookup.** `DiskLLMCache` (`backend/arp/llm/cache.py`) keys on the sha256 of model, system, prompt,
   output schema name and shape, temperature and image hashes. A hit returns at once with `cached=True` and costs
   nothing. A "refresh" mode never reads the cache but still writes to it, so a step restarted from the UI calls the
   model again and leaves its answer for later steps.
2. **Structured output via one tool.** The output schema is offered as a single tool with `tool_choice: auto`. The
   code comments say current models reject a forced tool choice and a non-default temperature, so `temperature` is not
   sent. It stays in the signature and in the cache key, and the cache is what makes runs reproducible.
3. **Prompt caching.** When enabled (`llm_prompt_cache_enabled`), the system prompt is marked as an Anthropic cache
   breakpoint.
4. **Validation loop.** If the model answers without the tool, it is re-prompted. If the tool input fails Pydantic
   validation, the client first tries to drop just the invalid list items. If that is not possible, it sends the errors
   back as an `is_error` `tool_result` and retries, up to `max_validation_retries` more attempts, then raises the last
   validation error. Network and rate-limit retries are handled by the SDK client (`max_retries`).
5. The validated result and usage are written to the disk cache.

## Factory, verifier model, batch and Gemini

`backend/arp/llm/factory.py`:

- `build_llm_client(settings, model=...)` returns a `GeminiClient` for `gemini-*` model ids (which needs
  `ARP_GEMINI_API_KEY`). Otherwise it returns an Anthropic client and raises at once if `ARP_ANTHROPIC_API_KEY` is
  missing. When `llm_batch` is set, it returns `BatchingLLMClient` instead.
- `build_verifier_llm_client` builds a second client on `llm_verifier_model` (default `claude-opus-5-5`, while
  `llm_model` defaults to `claude-sonnet-5-5`, see `backend/arp/config.py`). The two models are kept different on
  purpose: an extractor and a verifier on identical weights tend to miss the same mistakes. Both clients share one
  cache directory, which is safe because the cache key includes the model id.
- `BatchingLLMClient` (`backend/arp/llm/batching_client.py`) sends requests through the Message Batches API at half
  the price. It queues concurrent calls and flushes them as one batch, matches results back by a deterministic
  `custom_id`, and logs each submitted batch first, so a restarted client reattaches to its own run's batch instead of
  paying twice. `llm_batch` can only be set per run (`batch_settings`). Setting `ARP_LLM_BATCH=true` globally is
  rejected by a settings validator.

API routers never construct clients after creating a run. `schedule_llm_run` builds both clients first (see
<!-- openwiki: broken internal link [/openwiki/architecture/overview.md] link "/openwiki/architecture/overview.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[System architecture](/openwiki/architecture/overview.md)).

## Cost accounting

`estimate_cost_usd` (`backend/arp/orchestration/cost_tracker.py`) prices each call against the model that actually
produced it. A cached call costs 0. Cache reads and writes use their own multipliers, and batch calls are halved.
`combine_usage` sums only the calls that hit the API. The extraction pipeline prices extractor and verifier calls
separately for this reason (`_extract_company` in `backend/arp/extraction/pipeline.py`), and the batch runner adds the
cost to run progress.

## Evidence retrieval

Before an extraction call, `field_evidence` (`backend/arp/extraction/field_graph.py`) builds the passages the model
will see:

1. **Routing.** `route_documents` and `section_filter` (`backend/arp/planning/doc_routing.py`) narrow the documents and
   sections a field reads.
2. **Chunking.** `chunk_document` (`backend/arp/ingestion/parsing.py`) splits each document at sentence and paragraph
   boundaries (LlamaIndex `SentenceSplitter`) and tracks section and speaker. Chunk spans are cached per document, and
   chunk ids are deterministic (`chk_<doc_id>_<start>_<end>`), so citations can name a passage stably. Every table is
   also added as one whole passage, labelled by its caption.
3. **Ranking.** `select_relevant_chunks` (`backend/arp/retrieval/select_evidence.py`) ranks chunks by BM25 over the
   field's seed keywords, with German variants added (`backend/arp/retrieval/keywords_de.py`). It then:
   - optionally fuses a local multilingual embedding ranking via reciprocal rank fusion (`hybrid_retrieval_enabled`,
     on by default);
   - optionally computes the BM25 half in OpenSearch (`retrieval_backend="opensearch"`);
   - optionally reranks the top `rerank_candidates` with a local cross-encoder (`rerank_enabled`, off by default).

   It keeps `evidence_max_chunks` passages (default 12).
4. **Fallback.** Chunks with no keyword hit are dropped. A high-risk field falls back to unranked chunks in document
   order rather than getting no evidence. The extraction graph then flags a "not found" on such evidence for review,
   because agreement between extractor and verifier that nothing is there proves nothing when the evidence was unranked.

Retrieval only decides what the model sees. Whatever was retrieved, every citation is still grounded against the
document's full text (and the passages shown) by `backend/arp/grounding.py`. See
<!-- openwiki: broken internal link [/openwiki/pipeline/grounding.md] link "/openwiki/pipeline/grounding.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Citation grounding](/openwiki/pipeline/grounding.md).
