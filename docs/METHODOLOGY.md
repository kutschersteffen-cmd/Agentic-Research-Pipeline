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

## Transition Plan Assessment

**Colesanti Senni, Schimanski, Bingler, Ni & Leippold, ["Using AI to assess
corporate climate transition
disclosures"](https://iopscience.iop.org/article/10.1088/2515-7620/ad9e88)**
(Environmental Research Communications, 2024; working paper:
[SSRN 4826207](https://ssrn.com/abstract=4826207)). This is a direct
replication of the paper's tool, as `backend/arp/transition_plan/`
(`arp transition-plan run` / `POST /api/transition-plan/runs`).

The paper defines 64 fixed yes/no indicators across four categories
(Target, Governance, Strategy, Tracking), each classified as **"talk"**
(future targets / general management approach) or **"walk"** (concrete,
already-verifiable activity), and answers every indicator for a company
with a single RAG call: retrieve the top-K report chunks for the question,
ask an LLM playing a "senior sustainability analyst" persona -- instructed
to be skeptical of greenwashing and "cheap talk" -- for a YES/NO/NA verdict,
an explanation, and source references. The paper's headline finding, using
this tool on 143 Climate Action 100+ companies, is that disclosure skews
heavily toward "talk" (target-setting) and away from "walk" (concrete
implementation) -- i.e., companies talk more than they walk.

The 64 indicators (identifier, exact question text, expert-centric
guideline, walk/talk classification) are bundled verbatim in
`backend/arp/transition_plan/data/indicators.json`, sourced from the
paper's own reference implementation
([github.com/tobischimanski/transition_NLP](https://github.com/tobischimanski/transition_NLP))
rather than retyped from the PDF, so wording exactly matches what the
paper's tool asked. The persona, greenwashing-skepticism, and precision
guidelines in `backend/arp/transition_plan/indicator_agent.py`'s system
prompt are likewise verbatim from the paper's Figure S.2 prompt template.

Two deliberate deviations from the paper, both existing precision controls
this codebase already applies everywhere else:

- **Programmatic citation grounding, not an LLM-self-reported source
  list.** The paper's tool asks the model to report which numbered source
  chunk it used; this system asks for verbatim `quote` + `doc_id`
  citations and independently re-verifies each one against the original
  document text (`arp/grounding.py`) before it's trusted -- consistent
  with every other extraction pipeline in this codebase (see "The
  precision controls, concretely" below). A YES/NO verdict with no
  independently-grounded citation is routed to the review queue instead
  of accepted at face value.
- **BM25 evidence selection, not OpenAI embeddings.** The paper's RAG
  pipeline (LlamaIndex + `text-embedding-ada-002`, top-8) is replicated
  behaviorally -- always retrieve the top-8 chunks regardless of keyword
  overlap, so a genuinely silent report answers "NA" rather than being
  skipped -- using this codebase's deterministic, embedding-free BM25
  retriever (`arp/retrieval/select_evidence.py`) instead, matching every
  other pipeline here and adding no extra API cost.

Everything else matches the paper's design: one indicator, one evidence
retrieval, one LLM call (no independent-verifier second pass, unlike the
extraction/financials pipelines -- the paper's tool is a single-pass RAG
system and this replication keeps that shape); a 200-word answer-length
cap; and per-company output of a walk/talk-annotated verdict grid plus the
disclosed-count-out-of-64 metric the paper uses as its core
disclosure-completeness score.

## The precision controls, concretely

1. **Programmatic grounding, not LLM self-report** (`backend/arp/grounding.py`).
   Every citation an agent produces must be an exact (or near-exact,
   whitespace-normalized) substring of the document it claims to quote.
   This is checked in code with string matching, not by asking the model
   "are you sure?" — a model that fabricates a quote is caught
   mechanically, every time, regardless of how confident its prose sounds.
   The same discipline extends to *where* a grounded quote lives: its PDF
   page number or xlsx sheet name is computed from the verified match's
   real character offset in the source text (never asked of the model),
   so a "view source" link only ever appears for a location that was
   actually checked, and always points at the right page.

2. **Adversarial verification, not single-pass judgment.**
   - Thematic matching: Advocate argues for inclusion, Opposing
     specifically hunts for aspirational/marketing language, out-of-scope
     activity, and greenwashing, Adjudicator weighs both against the
     evidence.
   - Data-point extraction: an independent Verifier agent re-reads the same
     evidence and is instructed to disagree with the Extractor whenever it
     finds a problem — wrong fiscal year, wrong unit/scale, a
     "not-disclosed" case mis-reported as a number, etc. The Verifier runs
     on a deliberately different model than the Extractor
     (`Settings.llm_verifier_model`, `backend/arp/llm/factory.py::
     build_verifier_llm_client` — defaults to `claude-opus-5` against the
     Extractor's `claude-sonnet-5`) — a Verifier on identical weights can
     share the Extractor's blind spots and repeat its mistake instead of
     catching it, which an adversarial *prompt* alone doesn't fix.

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
   batch or is silently swallowed (it's logged to `errors.jsonl`). This
   resumability is also exposed directly as a control, not just an
   internal recovery mechanism: `POST /api/runs/{id}/cancel` /
   `arp runs cancel` requests a cooperative stop (`RunManifest
   .cancel_requested`, polled by `run_batch` before each new item --
   in-flight items still finish and checkpoint, nothing is left half-
   written), and `POST /api/themes/runs/{id}/resume` / `arp theme resume`
   picks a stopped, failed, or interrupted run back up from exactly where
   it left off, reconstructed from what `create_theme_run` persisted
   (`theme.json`, the universe path, and any revenue-catalogue mapping) --
   no need to redo already-completed companies or re-supply the original
   inputs by hand.

6. **Provenance + a golden-set regression test, not "trust the latest
   prompt."** Every `ExtractedField`/`CompanyFinancialsRecord` carries a
   `provenance` block (`backend/arp/schemas/common.py::ProvenanceInfo`):
   which model extracted it, which model verified it, and a content hash
   of each one's system prompt (`backend/arp/llm/langchain_client.py`,
   computed automatically from the prompt text, so it changes the moment
   the prompt does — never a hand-maintained version number that can go
   stale). This makes a later prompt or model change detectable against
   already-persisted output instead of silently blending pipeline
   versions. `backend/arp/golden_set/` bundles a small set of manually
   verified (evidence, correct answer) cases and runs them through the
   real extractor → verifier → grounding pipeline (`arp golden-set run`)
   — intended to run before a prompt or model change reaches a real
   batch, since a regression caught there is far cheaper than one first
   noticed in the review queue at 4,000-company scale.

7. **Structured facts before LLM extraction, everywhere it's available —
   not just for the revenue/CapEx catalogue.** SEC's XBRL companyfacts API
   (`backend/arp/ingestion/xbrl.py`) is queried for CapEx/R&D totals ahead
   of the LLM pipeline for EDGAR filers (`Settings.xbrl_facts_enabled`,
   on by default, no configuration needed — a free, no-key SEC endpoint).
   When SEC's own machine-tagged figure is present, it replaces the LLM's
   read of prose outright (`financials_pipeline.py::_overlay_xbrl_facts`)
   — the same "a hard disclosed number is never second-guessed by a
   categorical LLM judgment" precedence the revenue/CapEx cascade below
   already applies, extended to the structured data SEC filers themselves
   already publish. Segment-level figures and the plain-language
   description of what CapEx/R&D is going toward still always go through
   the LLM pipeline, since XBRL tagging isn't standardized enough across
   filers for those.

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

## Revenue/CapEx-based exposure resolution

Off by default; enabling it requires a structured revenue/capex data
catalogue and a confirmed taxonomy->catalogue mapping (below). Where the
indirect-exposure tier *adds* a structural signal alongside the qualitative
debate, this tier can *replace* it for a given company x activity pair: if
a hard revenue number is found, the qualitative Advocate/Opposing/
Adjudicator debate is skipped entirely for that pair, both because it's
cheaper and because a real disclosed number shouldn't be second-guessed by
a categorical judgment over the same question.

This implements the three-path structure described earlier in this
project's design discussion of how MSCI actually uses revenue data:
structured/tagged data first, LLM extraction from prose second, and the
existing qualitative debate only as the last resort.

**Path 1 — structured catalogue (no LLM call for the number itself).**
`arp/research/revenue_exposure/catalogue.py` loads a user-supplied CSV of
revenue/capex line items (`data_point_id, company_id, metric, label,
value, unit, period, as_pct_of_total`) — a vendor's revenue-by-product-line
feed, or a company's own internal segment database, in whatever export
format is available. Nothing about this catalogue is fetched or fabricated;
same "bring your own data" posture as every other external dataset in this
system. Before it can be used, `mapping.py::suggest_catalogue_mapping`
proposes which catalogue labels correspond to which taxonomy activity — one
structured call per (activity, metric) against the catalogue's closed label
list, with a required rationale and hallucinated-label filtering, the same
discipline as `standards_mapping/gics.py::classify_gics`. This mapping is a
**reviewable draft, never auto-applied** — `resolver.py::
resolve_from_catalogue` only ever computes against the confirmed mapping
the caller passes in, and is pure arithmetic (a row either matches a
confirmed label or it doesn't).

**Path 2 — extraction from disclosures.** When the catalogue has no data
for a company x activity x metric, `resolver.py::resolve_from_extraction`
builds an ad hoc single-field `DataPointSchema` on the fly (mirrors
`taxonomy_sources/empirical.py::_activity_description_schema`'s pattern)
and runs it through the *exact same* Extractor -> independent Verifier ->
programmatic grounding check the Extraction Engine already uses for every
other data point — this is not a separate extraction mechanism, it's the
existing one applied to a dynamically-generated field. A missing/null
extracted value is treated the same way "not disclosed" already is
everywhere else in this system: reported plainly, never estimated.

**Path 2 is gated by sector relevance, as a cost control.** Before spending
an extraction call, `resolver.py::is_sector_relevant` checks whether the
company's own resolved ISIC code (reusing `indirect_exposure/
company_mapper.py::resolve_company_isic`) plausibly overlaps the activity's
`core_isic_codes`, by digit-prefix containment. This only gates path 2 —
path 1 (a free dict lookup) and the path-3 fallback (today's existing,
unchanged recall behavior) are unaffected, since a company outside an
activity's obvious sector can still have a real, disclosed revenue line
there; the gate exists only to avoid an unconditional per-company-per-
activity extraction call across a 4,000-company x N-activity grid.

**Path 3 — the existing qualitative debate**, unchanged, run only when
paths 1 and 2 both come back empty for the `revenue` metric specifically
(revenue is the gating metric, since MSCI's exposure bands are revenue-
percentage bands; a CapEx-only resolution doesn't by itself establish
theme relevance and so doesn't suppress the debate on its own). `capex` is
resolved through the same path-1/path-2 cascade independently and attached
to the result either way.

**Banding.** A resolved revenue share is converted to the same
`pure_play/significant/minor/none` categories used everywhere else in this
system, via configurable thresholds (`revenue_exposure_pure_play_threshold`
etc. in `Settings`, defaulting to the MSCI-style 50%/20%/5% bands) — so
`CompanyMatch.exposure_estimate` means the same thing regardless of which
path produced it.

CLI: `arp revenue-catalogue suggest-mapping <taxonomy_ref> <catalogue.csv>
--out mapping.json` (review the draft, then) `arp theme run --taxonomy
<ref> --universe <csv> --revenue-catalogue <catalogue.csv>
--catalogue-mapping mapping.json`. API: `POST /api/revenue-catalogue/
suggest-mapping`, then `revenue_catalogue_path`/`catalogue_mapping` on
`POST /api/themes/runs`.

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

### The research step: discovering and ranking candidate sources

Two of the methods below (`authority_source`, `etf_index_holdings`) need a
real, named external reference before they can run -- an actual IEA
publication, an actual ETF ticker -- and the tool doesn't expect the user
to already know which one. `POST /api/taxonomies/discover-sources` /
`arp taxonomy discover-sources <name>` web-searches for candidates (varied
query phrasings per type: "{theme} official taxonomy classification",
"{theme} IEA definition taxonomy", "{theme} ETF", "{theme} thematic index
fund", ...) and returns a `SourceCandidate` list -- name, URL, snippet --
for the user to read and choose from. **Nothing is fetched or used
automatically here**; discovery only proposes, selection is a separate,
explicit step (`--authority-url` / `authority_urls`, or downloading a
selected fund's holdings export and passing it as `--holdings` /
`holdings_path`).

Authority candidates are then scored and explained
(`taxonomy_sources/discovery.py::rank_authority_sources`): one structured
LLM call reads each candidate's title/URL/snippet and returns an
`authority_score` (0-1) plus plain-language `authority_reasoning` -- *why*
this looks like (or doesn't look like) a credible reference for the theme,
not just a bare relevance rank. This deliberately isn't a hardcoded
domain allowlist (`iea.org`, `ec.europa.eu`, ...): the right authority for
"electrification" isn't the right one for "gene therapy", so the judgment
call is made per-theme and shown to the user rather than baked into a
fixed list. Ranking degrades gracefully -- if no LLM is configured, the
unranked search results are still returned rather than failing discovery
outright.

Before selecting a source, the user can inspect it in its original form:
`GET /api/taxonomies/sources/inspect?url=` streams the cached/fetched
original bytes (PDF or HTML, whatever the source actually is) with the
right content-type, and the frontend renders it in an in-app viewer --
so "authoritative" is judged by reading the actual document, not a
search-result snippet. Fetched originals are cached to disk by
`sha256(url)` (`fetch.py::fetch_source_original`) so re-inspecting a
source doesn't refetch it.

The default search backend is the same no-API-key DuckDuckGo client the
document-discovery crawler uses (`arp/discovery/site_finder.py`) --
`WebSearchClient` is an interface specifically so a paid search API can be
swapped in without touching the discovery logic itself if a deployment
needs more reliable results than a free HTML-scrape search provides.

### Seven derivation methods, chosen per `arp taxonomy create --method`

1. **`llm_draft`** — the freeform decomposition: theme name and
   description in, MECE activities out. Fast, flexible, but the boundary
   the model draws is only as good as its own background knowledge.
2. **`industry_anchored`** — the same drafting call, grounded against a
   real, closed industry reference list (today: the ISIC codes from a
   loaded input-output model) instead of letting the model invent
   categories freely. Populates `core_isic_codes` directly where a clean
   match exists and leaves it empty otherwise, so the result is
   immediately usable by the indirect-exposure tier with no separate
   `classify-sectors` pass.
3. **`authority_source`** — grounded against one or more user-selected
   authoritative documents (an official taxonomy, a standards body's
   definition) found via the research step above. Rather than stuffing
   fetched text into a freeform prompt, each source is chunked
   (`arp/ingestion/parsing.py::chunk_document`, the same chunker the
   Extraction Engine uses) and run through a schema-forced extraction call
   that must attach a verbatim `source_quote` per proposed activity --
   checked against the fetched text with the same non-LLM
   `arp/grounding.py::is_grounded` gate every other pipeline in this
   system uses. An activity whose quote fails grounding is **dropped**,
   not flagged: authority-sourced activities are supposed to be
   traceable to the document, not the model's paraphrase of it, so a
   failed check disqualifies rather than warns. A grounded activity keeps
   its citation as `ActivityDefinition.source_citation`, visible end-to-
   end through to the taxonomy library UI. When more than one source is
   selected, each is extracted independently and the results are
   consolidated by the same merge primitive `merged` (below) uses. A
   source that fails to fetch is skipped, not fatal, and every URL used
   (or skipped) is recorded in `source_notes`; the whole derivation only
   fails if *no* selected source yields any grounded activity.
4. **`etf_index_holdings`** — bottom-up synthesis from an existing
   thematic ETF or index's holdings. Fetching holdings automatically isn't
   attempted: fund-provider export formats aren't standardized and several
   financial-data domains are unreachable from some network environments,
   so a user-downloaded holdings CSV (name/ticker/sector/description
   columns, in whatever variant the provider uses) is the robust input.
   The research step points the user at candidate funds to download from.
   The same holdings CSV parser also backs two other things: building a
   reusable company universe straight from a fund's constituents
   (`load_universe_from_holdings`, `POST /api/universe/from-holdings`,
   `arp universe from-holdings`) instead of a hand-written list, and
   computing deterministic **holdings overlap** across two or more funds
   (`taxonomy_sources/overlap.py::compute_holdings_overlap`,
   `POST /api/etf-overlap`, `arp universe overlap`) -- which tickers are
   common core holdings, and a weight-adjusted pairwise overlap percentage
   when weight data is available (falling back to a ticker-count ratio
   otherwise). Overlap is pure set/weight math, no LLM, the same
   preference for non-LLM computation wherever possible as the Leontief
   exposure tier.
5. **`news_transcript_mining`** — bottom-up synthesis from current news
   search results plus keyword-in-context passages mined from any
   earnings-call transcripts already available for a supplied sample of
   companies (the same Sautner et al.-style approach cited above, applied
   to taxonomy construction instead of exposure scoring).
6. **`empirical`** — bottom-up synthesis from the Extraction Engine's own
   readings: a lightweight ad-hoc schema ("describe this company's primary
   business activities, especially anything related to the theme") is run
   across a sample of the universe, and the resulting per-company
   descriptions become the corpus.
7. **`merged`** — consolidated from two or more *existing, saved*
   taxonomies rather than derived from a fresh source. `POST
   /api/taxonomies/merge` / `arp taxonomy merge` takes each taxonomy's
   activity list and asks the model to identify near-duplicates and
   propose one MECE set with a rationale -- the same primitive
   (`taxonomy_sources/activity_merge.py::merge_activity_sets`) that
   consolidates multiple `authority_source` documents above, since
   "combine several activity lists into one" is the same operation either
   way. The result is always handed back as an **editable draft, never
   auto-saved**: the caller reviews/edits it in the output panel and then
   explicitly saves it as a new taxonomy. A lighter-weight `POST
   /api/taxonomies/compare` / `arp taxonomy compare` is available first,
   for just seeing the diff (activities unique to each side, and
   LLM-flagged likely-duplicate pairs with a similarity note) without
   committing to a merge.

Methods 4-6 share one synthesis step
(`taxonomy_sources/corpus_synthesis.py`): a corpus of real snippets in,
activities out, with every proposed activity expected to trace back to
something that actually appears in the corpus, and an honest
`corpus_assessment` when the material is too thin to support a real
taxonomy rather than padded-out activities. They differ only in how the
corpus is gathered, which is also why adding a further corpus source later
(e.g. regulatory filings search) means writing one gathering function, not
a whole new pipeline.

A version created by hand (`arp taxonomy new-version --theme edited.json`)
is recorded as `manual`. As a rule of thumb across all seven: an industry
classification or an authority source scaffolds a well-understood theme
fastest and most defensibly; ETF holdings and news/transcript mining are
worth their extra cost for a theme where you specifically want the
taxonomy to reflect how the market or the companies themselves currently
talk about it, which can drift from any official definition; empirical
extraction is the fallback for a genuinely novel theme with no existing
reference to anchor to at all; merging is for once two or more of the
above already exist and need reconciling into one canonical version.

### The taxonomy library UI

`TaxonomyLibrary.tsx` is the browser-based front end for all of the
above: a library list with inline edit-and-save-new-version and ratify
actions; a new-taxonomy wizard covering all six creatable methods with
method-specific inputs (source discovery cards with score/reasoning and
an "Inspect" button opening the original-document viewer, for
`authority_source`; a holdings-CSV upload for `etf_index_holdings`; the
existing universe picker for `empirical`/`news_transcript_mining`); a
compare & merge view; a universe builder (fund/sector search plus a
holdings-CSV-to-universe upload); and an ETF holdings overlap view
(upload two or more funds' holdings, compute overlap, inspect each
fund's raw holdings client-side). Every draft the wizard or the merge
view produces goes through the same editable `ActivityEditorTable`
before being saved, so "the model proposed it" and "it's now part of the
taxonomy" are always separated by an explicit human review-and-save step.

### Cross-referencing to NACE, NAICS, SIC and GICS

Once a taxonomy's activities carry `core_isic_codes` (from `industry_anchored`
derivation, or `arp theme classify-sectors`), `arp taxonomy map-standards` /
`POST /api/taxonomies/{id}/map-standards` cross-references each activity into
four widely-used external classification standards and saves the result as a
new taxonomy version -- so "which NACE/GICS code does this activity belong
to" is answered per taxonomy, not re-derived by hand for every downstream
use (fund mandates, regulatory reporting, index construction).

The four standards are **not** all handled the same way, deliberately:

- **NACE Rev.2, NAICS, SIC** are derived by a **deterministic crosswalk**
  from `core_isic_codes` (`standards_mapping/crosswalk.py::CrosswalkTable`),
  never guessed by the model. NACE Rev.2 aligns almost exactly with ISIC
  Rev.4 at the 2-digit division level by design (same codes, near-identical
  titles), so the bundled sample crosswalk is a close correspondence, not
  just illustrative; NAICS and SIC don't align numerically with ISIC at all,
  so the bundled sample there is a small, explicitly-illustrative set of
  hand-picked matches for the 10 divisions in the sample ICIO dataset. For
  production use, point `ARP_NACE_CROSSWALK_PATH` / `ARP_NAICS_CROSSWALK_PATH`
  / `ARP_SIC_CROSSWALK_PATH` at the real official UN Statistics Division /
  Eurostat RAMON / US Census correspondence tables -- same "bundled sample,
  replace for production" pattern as the OECD ICIO data itself.
- **GICS** has no public official correspondence table from ISIC (or
  anything else) -- it's a proprietary MSCI/S&P classification assigned by
  a company's principal business activity, not derivable by table lookup.
  So GICS is a **closed-list LLM classification** instead
  (`standards_mapping/gics.py::classify_gics`), the exact same pattern as
  the indirect-exposure tier's `classify_core_sectors`: one call per
  activity against a fixed reference list spanning all four GICS levels
  (sector/industry group/industry/sub-industry), instructed to prefer the
  most specific level that genuinely fits, a rationale required for every
  match, and any code the model returns that isn't actually in the
  reference list is dropped. **The bundled sample's sector level (11
  codes) is stable and public; everything below sector level was
  reconstructed from LLM training knowledge, not fetched from MSCI's
  official structure, and is explicitly flagged as unverified** (see
  `sample_data/README.md`) -- GICS below sector level is MSCI/S&P-licensed
  and revised periodically (most recently 2023), so treat it as a draft
  for testing the pipeline, not a citable classification, until you
  supply a verified `ARP_GICS_REFERENCE_PATH` file.

Each of the four standards resolves independently -- a deployment with a
real NACE table but no GICS license is normal; that standard just comes
back empty for every activity rather than blocking the other three.
`arp taxonomy export-standards` / `GET /api/taxonomies/{id}/standards.csv`
flattens the result into one CSV row per activity
(`activity_id, activity_name, isic_codes, nace_codes, naics_codes,
sic_codes, gics_codes, gics_labels, gics_rationale, unmapped_isic_codes`)
for use outside the tool.

## Hybrid retrieval and the optional Postgres/pgvector store

`select_relevant_chunks` (`backend/arp/retrieval/select_evidence.py`)
defaults to fusing BM25 with a local, multilingual embedding model
(`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` --
`backend/arp/retrieval/embeddings.py`) via reciprocal rank fusion, on by
default (`Settings.hybrid_retrieval_enabled`). Pure keyword/BM25 matching
misses the case a company describes a theme or field in vocabulary its
seed keywords don't cover (e.g. "e-mobility transition" vs. seed keyword
"electrification"), and a fixed English-only embedding model couldn't rank
DE-language disclosures meaningfully at all. Set the flag `false` to fall
back to the old pure-BM25 behavior (e.g. to reproduce a prior run exactly).
Transition Plan Assessment stays BM25-only regardless of this flag --
`backend/arp/transition_plan/indicator_graph.py` -- to keep its
replication of the source paper's retrieval behavior exact (see above).

Every store in this system is file-based by default. An **opt-in**
Postgres/pgvector backend (`backend/arp/storage/postgres*.py`,
`Settings.postgres_dsn`) is available for exactly two places a relational/
vector engine earns its cost at this system's scale: Portfolio Risk &
Exposure Monitoring's holdings (`PostgresPortfolioStore` --
`aggregate_market_value_eur` does a real three-way join across holdings x
securities x companies, grouped by sector/issuer/portfolio, in one SQL
query instead of loading every JSONL snapshot into Python) and the
hybrid-retrieval chunk-embeddings cache (`PgVectorEmbeddingsStore`, the
same two-method interface as the default SQLite cache, so it's a drop-in
swap with no changes anywhere hybrid retrieval is wired up). Every other
store -- run manifests, review queues, engagement/voting audit trails --
stays file-based JSONL regardless of whether Postgres is configured: an
append-only file is simpler to keep fully auditable than a table with
`UPDATE`s, and none of those stores have the multi-way join access pattern
that would justify a relational engine's added operational cost. `arp db
init-postgres` creates the `vector` extension and every table, idempotently.

## What's deliberately out of scope

This system does not invent a company universe — the user supplies it
(ticker/name list, e.g. index constituents), because getting that
authoritative source wrong would undermine every downstream precision
control. It also does not estimate or infer undisclosed figures: both the
extractor and verifier prompts explicitly instruct "not found" over any
computed or inferred value, because a plausible-looking estimate is exactly
the kind of error that is hardest for a human reviewer to catch downstream.
