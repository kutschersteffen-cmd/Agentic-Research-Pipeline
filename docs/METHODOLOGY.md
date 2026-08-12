# Methodology

This system is designed around one priority stated up front: **precision**,
even at the cost of extra LLM calls, because the output feeds investment
decisions across thousands of companies. Every design choice below traces
back to a specific way LLM-based financial research goes wrong, and a
specific, checkable control against it.

## What this draws on

**MSCI, ["Leveraging Language Models to Capture Investment
Strategies"](https://www.msci.com/research-and-insights/blog-post/leveraging-language-models-to-capture-investment-strategies)
(Oct 2025).** MSCI describes defining an investment theme as plain-language
in-scope/out-of-scope activity descriptions, and cross-examining an LLM's
classification with an **"opposing agent"** for robustness and rationale
transparency. This system implements that directly: `ActivityDefinition`
carries both an `in_scope_description` and an `out_of_scope_description`
(see `backend/arp/schemas/thematic.py`), and every company/activity match
goes through an **Advocate → Opposing → Adjudicator** pipeline
(`backend/arp/research/matcher_agents.py`) rather than a single one-shot
LLM judgment.

**MSCI, ["How the Biggest Investors Are Finding Opportunity in
AI"](https://www.msci.com/research-and-insights/blog-post/how-the-biggest-investors-are-finding-opportunity-in-ai).**
MSCI Institute's screen ingests multiple document types per company
(annual report, sustainability report, product descriptions, earnings
transcripts) rather than one source. This system's ingestion layer
(`backend/arp/ingestion/`) and document discovery crawler
(`backend/arp/discovery/`) are built the same way: every pipeline reads
across whatever document types are available for a company and reconciles
them, rather than trusting a single filing.

**Sautner, Van Lent, Vilkov & Zhang, ["Firm-Level Climate Change
Exposure"](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13219)
(Journal of Finance, 2023).** Their method discovers firm-level exposure by
searching earnings-call transcripts for keyword/bigram matches expanded
from a seed list, rather than running an expensive model over full
transcripts unfiltered. This system uses the same keyword-in-context
prefilter before any LLM call (`backend/arp/research/candidate_sourcer.py`,
`backend/arp/extraction/chunk_selector.py`): activities and extraction
fields both carry `seed_keywords`, and evidence chunks are ranked/filtered
by keyword hits before being shown to a model. This is both a cost control
(no LLM call on companies/documents with zero keyword relevance) and a
precision control (the model's context stays narrow and on-topic instead of
diluted across an entire filing).

Classic thematic-index methodology (revenue-exposure thresholds, "pure
play" vs. partial exposure, as used by index providers building thematic
baskets) motivates the `ExposureEstimate` enum (`pure_play` / `significant`
/ `minor` / `none`) rather than a flat include/exclude — thematic exposure
is rarely binary, and collapsing it to a boolean discards information a
portfolio manager needs.

## The precision controls, concretely

1. **Programmatic grounding, not LLM self-report** (`backend/arp/grounding.py`).
   Every citation an agent produces must be an exact (or near-exact,
   whitespace-normalized) substring of the document it claims to quote.
   This is checked in code with string matching, not by asking the model
   "are you sure?" — a model that fabricates a quote is caught
   mechanically, every time, regardless of how confident its prose sounds.

2. **Adversarial verification, not single-pass judgment.**
   - Thematic matching: Advocate argues for inclusion, Opposing
     specifically hunts for aspirational/marketing language, out-of-scope
     activity, and greenwashing, Adjudicator weighs both against the
     evidence.
   - Data-point extraction: an independent Verifier agent re-reads the same
     evidence and is instructed to disagree with the Extractor whenever it
     finds a problem — wrong fiscal year, wrong unit/scale, a
     "not-disclosed" case mis-reported as a number, etc.

3. **Schema-first structured output.** Every agent call is a forced
   tool-use call against a Pydantic model's JSON schema
   (`backend/arp/llm/anthropic_client.py`), with a bounded
   validation-retry loop that re-prompts with the exact Pydantic error on
   failure. Nothing downstream ever parses free-text model output.

4. **Confidence scoring + mandatory human review queue.** Low-confidence
   verdicts, "uncertain" thematic calls, ungrounded citations, and
   verifier disagreements are never silently included in the trusted
   output — they're written to a per-run review queue
   (`backend/arp/orchestration/review_queue.py`) that a human clears via
   the API/UI before those items count as final.

5. **Resumable, isolated, checkpointed batch execution**
   (`backend/arp/orchestration/batch_runner.py`). At 4,000-company scale,
   partial failure is the normal case, not the exception: one company's
   fetch timing out, a malformed filing, a transient rate limit. Every
   successful result is flushed to disk immediately; a re-run skips
   already-completed companies; one company's exception never aborts the
   batch or is silently swallowed (it's logged to `errors.jsonl`).

## What's deliberately out of scope

This system does not invent a company universe — the user supplies it
(ticker/name list, e.g. index constituents), because getting that
authoritative source wrong would undermine every downstream precision
control. It also does not estimate or infer undisclosed figures: both the
extractor and verifier prompts explicitly instruct "not found" over any
computed or inferred value, because a plausible-looking estimate is exactly
the kind of error that is hardest for a human reviewer to catch downstream.
