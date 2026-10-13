# Jina reranker for ARP: research note

Researched 2026-10-13 from primary sources only (jina.ai, Jina's Hugging Face cards, Jina's arXiv paper, Elastic's press release). Items I could not confirm are marked **not found**.

## Summary and recommendation

**Do not adopt Jina rerankers as a production default. Keep the local `bge-reranker-v2-m3-int8` path, and at most use Jina's hosted API as an opt-in experiment behind the existing `rerank_enabled` flag.**

- Current flagship is **jina-reranker-v3.5** (0.6B, listwise, released 2026-08-03). v3 (0.6B), m0 (2.4B multimodal) and v2-base-multilingual (0.3B) remain listed.
- Quality is good: BEIR 63.20 and MIRACL 74.11 nDCG@10 for v3.5, ahead of bge-reranker-v2-m3 in Jina's own v3 table (BEIR 61.94 vs 56.51). These are Jina's numbers; no independent check was done.
- **Blocker for self-hosting: every open-weight Jina reranker we found is CC BY-NC 4.0.** Using the weights inside a commercial ARP deployment needs a paid commercial license from Jina (annual fee, per a search snippet; exact terms **not found** on a primary page). Only the legacy v1 models are Apache-2.0.
- **Blocker for the hosted API: no per-token price could be found on a primary page**, and every document chunk (company disclosures) would leave our infrastructure. Jina's terms say inputs are not used for training, but the same page says it predates the Elastic acquisition and may be stale.
- The repo already has a working local multilingual (EN/DE) reranker slot. The real open question there is CPU latency (47-75 s per field), which a hosted API or a GPU would fix.

## Fit for ARP

### What exists today
- `backend/arp/retrieval/rerank.py`: `rerank(query, chunks, top_n)` using fastembed `TextCrossEncoder` with `BAAI/bge-reranker-v2-m3-int8`. Fails soft (keeps retrieval order, warns once).
- `backend/arp/retrieval/select_evidence.py` (`select_relevant_chunks`): BM25 (in-memory LlamaIndex, or OpenSearch) fused by RRF with MiniLM multilingual embeddings (`hybrid_retrieval_enabled`, default on). When `rerank_candidates` is set, the top N of the final ranking go through `rerank()` and the best `max_chunks` are returned (lines ~150-172).
- `backend/arp/config.py` lines 135-142: `rerank_enabled` (default **false**), `rerank_candidates` (40), `evidence_max_chunks` (12). Docstring: ~0.57 GB download, ~47 s for 40 chunks on 4 CPUs.
- `docs/superpowers/plans/2026-10-13-retrieval-quality.md` already measured 40 chunks x 3,500 chars on 4 CPUs: bge-reranker-v2-m3-int8 75 s; `jina-reranker-v2-base-multilingual` 51 s (via fastembed, no new dependency). It plans an eval harness (Phase 0) to choose the model.
- No pgvector query-time retrieval in this path; embeddings are cached in the content store.

### Integration point
Single seam: swap the body of `_score()` in `rerank.py` (or add a model switch in `Settings`) so it calls `POST https://api.jina.ai/v1/rerank` with `model`, `query`, `documents=[c.text ...]`, `top_n`, and maps `index`/`relevance_score` back to chunks. Everything upstream (BM25 + RRF) and downstream (`evidence_max_chunks`) stays unchanged. The existing fail-soft behavior already covers API outages.

### Effort
About half a day for the API variant: one HTTP call (`httpx`/`requests`, whichever the backend already uses), an `ARP_JINA_API_KEY` setting, a model-name setting, a test with the HTTP call monkeypatched (same style as the planned `test_rerank.py`), and the eval run from the retrieval-quality plan. Local Jina v3/v3.5 via `transformers` (`trust_remote_code=True`) adds a heavy dependency (torch) and wants a GPU; not recommended on the CPU-only deployment.

### Risks
1. **License:** CC BY-NC 4.0 on v3.5, v3, m0, v2 (self-hosting). Note the existing plan lists `jina-reranker-v2-base-multilingual` via fastembed as a candidate: that model is also CC BY-NC per Jina's reranker page, so it should not become a default without a license check. (The licenses of the bge model and the fastembed ONNX repackaging were not checked here.)
2. **Data protection:** sending sustainability-report chunks to a third-party API. Jina GmbH (Berlin) is controller; DPA is Elastic's. API data location is **not stated** (only an experimental per-request "EU residency" flag on the Reader API, not confirmed for rerank). A German corporate user will want a DPA and EU processing confirmed in writing.
3. **Ownership:** Elastic owns Jina (see below). Elastic's release says nothing about API continuity or price stability.
4. **Pricing unknown**, rate limits inconsistent across Jina pages (see evidence).
5. **German quality not specifically published.** v3.5 is "trained on 24 languages, supports 93"; German is not named. MIRACL contains no German subset, so MIRACL gains do not prove German quality. Our own eval set (Phase 0) is the only reliable check.
6. Listwise models are fixed-capacity: v3 handles up to 64 documents per context window. Our 40 candidates fit; 100+ would need batching.

### Alternatives
- Keep `bge-reranker-v2-m3-int8` (current), optionally on a GPU or with chunks truncated to 800-1,500 chars (planned measurements show 20 s and 10 s per 40 chunks).
- Cohere Rerank, Voyage rerank: hosted, not researched here (outside the requested Jina primary sources); Jina publishes no comparison to them.
- Qwen3-Reranker (0.6B or 4B) and mxbai-rerank-v2: open weights, appear in Jina's own tables; licenses not checked here. Qwen3-Reranker-4B beats v3.5 on MIRACL (76.56 vs 74.11) in Jina's table.
- Elastic Inference Service (Stack 9.3+) hosts Jina models, relevant only if ARP moves to Elastic/OpenSearch-based search. ARP's OpenSearch backend is optional and off by default.

## Evidence

### Model lineup
| Model | Params | Context | Languages | Multimodal | License | Source |
|---|---|---|---|---|---|---|
| jina-reranker-v3.5 | 0.6B | 131K tokens (card/model page) | trained on 24, supports 93 | no | CC BY-NC 4.0 | [HF card](https://huggingface.co/jinaai/jina-reranker-v3.5), [model page](https://jina.ai/models/jina-reranker-v3.5/) |
| jina-reranker-v3 | 0.6B (Qwen3-0.6B base, 28 layers) | 131K; up to 64 docs per pass | multilingual (no list) | no | CC BY-NC 4.0 | [HF card](https://huggingface.co/jinaai/jina-reranker-v3) |
| jina-reranker-m0 | 2.4B in table / 2B in metadata (Qwen2-VL-2B base) | 10,240 query+doc tokens | 29+ | yes, visual documents | CC BY-NC 4.0 | [HF card](https://huggingface.co/jinaai/jina-reranker-m0) |
| jina-reranker-v2-base-multilingual | 278M (0.3B) | 1,024 via API page; 8,192 per m0 card | 100+ | no | CC BY-NC 4.0 (per API page) | [reranker page](https://jina.ai/reranker/), [m0 card](https://huggingface.co/jinaai/jina-reranker-m0) |
| jina-reranker-v1-* | n/a | n/a | n/a | no | Apache-2.0 | [reranker page](https://jina.ai/reranker/) |

v3.5 is a drop-in replacement for v3 and the card recommends it for new projects ([v3 card](https://huggingface.co/jinaai/jina-reranker-v3)). v3.5 released 2026-08-03; paper arXiv 2607.18152 ([Jina post](https://jina.ai/news/jina-reranker-v3-5-faster-listwise-reranking-hybrid-attention-self-distillation)). The v2 context figure differs between two Jina pages; not resolved.

### Architecture
v3: listwise, "last but not late interaction": causal attention over query plus all candidates in one window, embedding taken from each document's last token; MLP projector 1024->512->256 ([paper, arXiv 2509.25085](https://arxiv.org/abs/2509.25085), [HF card](https://huggingface.co/jinaai/jina-reranker-v3)). v3.5: hybrid Qwen3-0.6B with sliding-window (1,024) and global layers, self-distillation ([Jina post](https://jina.ai/news/jina-reranker-v3-5-faster-listwise-reranking-hybrid-attention-self-distillation)).

### Benchmarks (nDCG@10, Jina-reported)
From the v3 card ([source](https://huggingface.co/jinaai/jina-reranker-v3)):

| Model | BEIR | MIRACL | MKQA | CoIR |
|---|---|---|---|---|
| jina-reranker-v3 | 61.94 | 66.83 | 67.92 | 70.64 |
| jina-reranker-v2 | 57.06 | 63.65 | 67.90 | 56.14 |
| jina-reranker-m0 | 58.95 | 66.75 | 68.19 | 63.55 |
| bge-reranker-v2-m3 | 56.51 | 69.32 | 67.88 | 36.28 |
| Qwen3-Reranker-4B | 61.16 | 67.52 | 67.52 | 73.91 |

From the v3.5 post ([source](https://jina.ai/news/jina-reranker-v3-5-faster-listwise-reranking-hybrid-attention-self-distillation)), top-100 candidates: v3.5 BEIR 63.20, MIRACL 74.11, RTEB 70.95, Struct-IR 48.3; v3 (re-measured) 62.10 / 72.20 / 68.01 / 38.7; Qwen3-Reranker-4B 62.28 / 76.56 / 77.68 / 55.6; mxbai-rerank-large-v2 62.45 / 69.65 / 70.81 / 43.0. The v3 numbers differ between the card (61.94 / 66.83) and the v3.5 post (62.10 / 72.20), so a different eval setup was used; do not mix the two tables. Jina states Struct-IR numbers are not comparable to the SSRB leaderboard. **No Jina page compares against Cohere Rerank or Voyage rerank.** The v3.5 post and card report no MKQA or CoIR numbers.

### Latency
- v3.5 on one A100, batch 1, FlashAttention-2: BEIR NQ mean 371 ms -> 305 ms (1.22x); long context (AILACasedocs) 16.1 s -> 10.3 s (1.56x) ([Jina post](https://jina.ai/news/jina-reranker-v3-5-faster-listwise-reranking-hybrid-attention-self-distillation)).
- API FAQ: 100 ms to 7 s depending on lengths; example 100 docs x 256 tokens plus 64-token query about 150 ms, at 4,096 tokens per doc about 3.5 s. Which model this refers to is not stated ([reranker page](https://jina.ai/reranker/)).
- CPU numbers for ARP are in the repo plan (above), not from Jina.

### API
- `POST https://api.jina.ai/v1/rerank`, header `Authorization: Bearer $JINA_API_KEY`, JSON `{model, query, documents, top_n, return_documents}`; results carry `index` and `relevance_score` ([reranker page](https://jina.ai/reranker/), [v3 card](https://huggingface.co/jinaai/jina-reranker-v3)).
- FAQ: "no hard limit on the number of documents per request"; inputs batched internally by token count ([reranker page](https://jina.ai/reranker/)). The page's FAQ lists models `jina-reranker-v3.5`, `v3`, `m0`, `v2-base-multilingual`. The full response schema was not shown on the page; the OpenAPI reference is at https://api.jina.ai/redoc (not fetched).

### Pricing and rate limits
- Billing is per total tokens processed, shared across Jina APIs on one key; new keys get free tokens; failed requests are not charged ([reranker page](https://jina.ai/reranker/)).
- **Per-token price: not found** on reranker, model, or pricing pages (jina.ai/pricing returned 404). Free-token amounts conflicted across search snippets (1M vs 10M); a roughly 18-month-old Reader post cited 0.02 USD per 1M tokens, likely stale. Treat as unknown.
- Rate limits on the reranker page: Free 100 RPM / 100K TPM; Paid 500 RPM / 2M TPM; Premium 5,000 RPM / 50M TPM; IP limit 10,000 requests per 60 s. A search snippet of the API reference showed different tiers (Free 500 RPM / 1M TPM), so verify before relying on a number.

### Licensing
- All v3.5/v3/m0 cards: CC BY-NC 4.0; "for commercial usage inquiries ... contact us" ([v3.5](https://huggingface.co/jinaai/jina-reranker-v3.5), [v3](https://huggingface.co/jinaai/jina-reranker-v3), [m0](https://huggingface.co/jinaai/jina-reranker-m0)). The v3 and m0 cards say the models are listed on AWS and Azure (v3 also GCP); the v3.5 card lists AWS/Azure/GCP with placeholder links, so availability there is unconfirmed. Marketplace pricing was not found.
- Commercial license structure (annual fee, scoped by models and hardware) comes from a search-result summary of a Jina page, not from a page I read directly; confirm at https://jina.ai/contact-sales/.

### Self-hosting
- Hugging Face via `transformers`, `AutoModel.from_pretrained(..., trust_remote_code=True)` ([v3 card](https://huggingface.co/jinaai/jina-reranker-v3)).
- GGUF: [jina-reranker-v3-GGUF](https://huggingface.co/jinaai/jina-reranker-v3-GGUF), [m0-GGUF](https://huggingface.co/jinaai/jina-reranker-m0-GGUF); MLX: [v3-mlx](https://huggingface.co/jinaai/jina-reranker-v3-mlx). vLLM is not mentioned on any card read.
- Hardware: no minimum stated. Jina's speed figures use an A100 with FlashAttention-2; m0 card says FlashAttention-2 needs Ampere/Ada/Hopper GPUs and that CPU works without it. 0.6B in BF16 is about 1.2 GB of weights (my arithmetic, not a Jina claim).
- Elastic Inference Service from Stack 9.3 hosts v3.5 ([Jina post](https://jina.ai/news/jina-reranker-v3-5-faster-listwise-reranking-hybrid-attention-self-distillation)).

### Data privacy
From Jina's terms ([jina.ai/legal](https://jina.ai/legal/)): inputs/outputs stored only as needed to provide the service (4.6); "does not use Customer request data, inputs, prompts, or uploaded content to train its models" (10.4); GDPR Art. 28 processor, DPA is the Elastic DPA (11.2); encrypted in transit and at rest. Not addressed: API data location, retention period, zero-retention option, SOC 2. The page itself warns it predates the Elastic acquisition. A "Do Not Cache or Track" and an experimental "EU Residency" option are documented for the Reader API only ([dashboard](https://jina.ai/api-dashboard/)); rerank support not confirmed.

### Ownership
Elastic completed its acquisition of Jina AI, announced 2025-10-09, terms undisclosed. Elastic says it will keep releasing models on Hugging Face and publishing research, and offer them via Elastic Inference Service ([Elastic IR release](https://ir.elastic.co/News--Events/news/news-details/2025/Elastic-Completes-Acquisition-of-Jina-AI-a-Leader-in-Frontier-Models-for-Multimodal-and-Multilingual-Search/default.aspx)). The release says nothing on API continuity or licensing changes; the observable effect since is the Elastic DPA in Jina's terms, EIS hosting, and weights that stayed non-commercial.

## Not verified
Per-token price; v2 license on its own HF card; German-specific scores; any Cohere/Voyage comparison by Jina; Marketplace pricing; the `/v1/rerank` response schema beyond `index` and `relevance_score`; the v3.5 paper text (only Jina's blog summary was read).
