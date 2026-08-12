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

**OECD [Inter-Country Input-Output (ICIO)
Tables](https://www.oecd.org/en/data/datasets/inter-country-input-output-tables.html)**
(45 industries, ISIC Rev.4). The Advocate/Opposing/Adjudicator debate above
answers "does this company's own disclosed activity fall in scope" — it has
nothing to say about a company that is structurally entangled with a theme
through its supply chain but never mentions the theme in its own words (a
specialty-chemicals supplier three hops upstream of battery manufacturing,
say). The indirect-exposure tier (`backend/arp/research/indirect_exposure/`)
answers that second question with a **purely quantitative, non-LLM** signal:
a Leontief inverse `L = (I - A)⁻¹` computed from an industry x industry
flow table gives, for any industry, the direct-plus-indirect share of its
inputs/outputs that traces to a theme's core sectors. It's the same
underlying mathematics EEIO models use for Scope 3 emissions accounting,
applied to a thematic value chain instead of carbon. This tier is opt-in
(off unless an ICIO dataset is configured) and its results are kept in a
separate `indirect_exposure` field on `CompanyMatch`, deliberately not
blended into the qualitative `exposure_estimate` the debate produces — see
"The indirect (input-output) exposure tier" below.

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

## The indirect (input-output) exposure tier

Disabled by default; enabling it requires an industry x industry
intermediate-flows table (see below). When enabled, it runs alongside —
never instead of — the qualitative Advocate/Opposing/Adjudicator pipeline,
and its main practical effect is on the *no-evidence* path: a company whose
disclosures never mention an activity is normally excluded at full
confidence with zero LLM calls (the correct default at scale, since that's
the overwhelmingly common outcome). With this tier enabled, that shortcut
is upgraded: if the company's own industry shows structural exposure to
the activity's core sectors above `confidence_review_threshold`'s sibling
setting (`indirect_exposure_review_threshold`, default 0.3), it's routed to
the review queue instead of silently excluded.

**Two directions are tracked separately** rather than blended into one
score, because they answer different portfolio questions:
- `upstream_exposure` — how much of this industry's own input requirement
  traces back to the theme's core sectors (a mining company supplying
  battery manufacturers).
- `downstream_exposure` — how much of this industry's output flows into the
  theme's core sectors as an input (a utility whose demand is increasingly
  driven by EV charging load).

**Data format.** The loader (`icio_loader.py`) intentionally does not parse
the raw OECD release (a country x industry x country x industry matrix,
hundreds of megabytes) — it expects a pre-aggregated industry x industry
table:
- `industries.csv`: `isic_code,label,total_output` (one row per industry).
- `icio_matrix.csv`: a square matrix, header row and first column both
  equal to the industry codes in `industries.csv`, same order; cell
  `[i, j]` is intermediate flow value from supplying industry `i` to using
  industry `j`.

Technical coefficients are computed as `A[i,j] = flow[i,j] / total_output[j]`
— the standard formula, using only intermediate flows (no separate final-
demand series required, since `total_output` is supplied directly per
industry). A small illustrative sample dataset (10 industries, real ISIC
Rev.4 codes, plausible but not official flow values) ships in
`arp/research/indirect_exposure/sample_data/` for demos and tests; replace
it with a real OECD ICIO extract, aggregated across countries, for
production use.

**Two classification steps sit around the math**, both designed to be cheap
because they're one-time, not per-company: `core_sectors.py` maps a theme's
activities to the model's ISIC codes (one LLM call per activity, or
zero if supplied by hand via `arp theme classify-sectors`), and
`company_mapper.py` maps a company to its ISIC code (supplied directly on
the company universe file is the precise, zero-cost path; an LLM fallback
against the model's fixed, closed industry list otherwise). Both reject a
code the model doesn't actually contain rather than silently coercing it,
since a wrong industry code would corrupt every exposure number computed
from it.

## The taxonomy library: defining and deriving activities

A `ThemeDefinition` produced by `arp theme decompose` is, by itself, a
one-off run parameter: drafted, maybe edited, used once, then whatever the
user does with the JSON file. That's fine for exploration but wrong for a
theme worth reusing, auditing, or improving over multiple research cycles
— which is most of them in practice. `arp/schemas/taxonomy.py` and
`arp/storage/taxonomy_store.py` promote the definition to a **named,
versioned artifact** (`Taxonomy`, wrapping a `ThemeDefinition`) with:

- a stable `taxonomy_id` across edits, so "the electrification taxonomy"
  is one thing with a history, not a series of unrelated JSON files;
- `derivation_method` and `source_notes` recorded on every version, so how
  the boundary was drawn is answerable later, not just what the boundary
  currently is;
- an explicit **ratification** step (`status`, `ratified_by`,
  `ratified_at`) — the recorded-fact version of the domain-expert sign-off
  MSCI describes doing with GARI for their adaptation taxonomy, rather
  than an implicit assumption that whoever last edited the file knew what
  they were doing.

**Two derivation methods today**, chosen per `arp taxonomy create`:

1. **`llm_draft`** — the freeform decomposition `activity_generator.py`
   always did: theme name and description in, MECE activities out. Fast,
   flexible, but the boundary the model draws is only as good as its own
   background knowledge of the theme.
2. **`industry_anchored`** — the same drafting call, but grounded against
   a real, closed industry reference list (today: the ISIC codes from a
   loaded input-output model) instead of letting the model invent
   categories freely. It's instructed to populate `core_isic_codes`
   directly where a clean match exists and leave it empty otherwise —
   never force-fit the closest-sounding code — which means a taxonomy
   drafted this way is immediately usable by the indirect-exposure tier
   with no separate `classify-sectors` pass required.

A version created by hand (`arp taxonomy new-version --theme edited.json`)
is recorded as `manual`. A **bottom-up / empirical** method — clustering
real segment and product descriptions pulled via the Extraction Engine
from a sample of the universe, letting the activity categories emerge from
what companies actually say rather than an a-priori list — is defined in
the schema (`DerivationMethod.EMPIRICAL`) as a placeholder for future work
but not implemented yet. As a rule of thumb across all four: an industry
classification or published literature scaffolds a well-understood theme
fastest; empirical clustering is worth its extra cost specifically for a
genuinely novel theme with no existing reference to anchor to.

## What's deliberately out of scope

This system does not invent a company universe — the user supplies it
(ticker/name list, e.g. index constituents), because getting that
authoritative source wrong would undermine every downstream precision
control. It also does not estimate or infer undisclosed figures: both the
extractor and verifier prompts explicitly instruct "not found" over any
computed or inferred value, because a plausible-looking estimate is exactly
the kind of error that is hardest for a human reviewer to catch downstream.
