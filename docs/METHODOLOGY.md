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

## What's deliberately out of scope

This system does not invent a company universe — the user supplies it
(ticker/name list, e.g. index constituents), because getting that
authoritative source wrong would undermine every downstream precision
control. It also does not estimate or infer undisclosed figures: both the
extractor and verifier prompts explicitly instruct "not found" over any
computed or inferred value, because a plausible-looking estimate is exactly
the kind of error that is hardest for a human reviewer to catch downstream.
