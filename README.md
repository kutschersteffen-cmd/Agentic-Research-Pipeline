# Agentic Research Pipeline

Two coupled tools for building thematic investment universes and
researching specific data points across large company sets, built for
precision at scale (designed for up to ~4,000 companies per run).

1. **Thematic Universe Builder** — turn a macro theme ("electrification",
   "AI") into a defensible list of business activities, matched companies,
   exposure estimates, and cited rationale, via an Advocate/Opposing/
   Adjudicator agent pipeline. Results are filterable/sortable in the UI
   (verdict, activity, flagged-only, confidence/exposure), and a filtered
   result set can be sent straight into the Extraction Engine as a new
   company universe with one click.
2. **Data-Point Extraction Engine** — pull specific, schema-defined data
   points (e.g. "green capex", forward-looking business outlook) out of
   sustainability reports, annual reports, and earnings-call transcripts,
   with an independent verifier pass -- on a deliberately different model
   than the extractor, to decorrelate errors -- and a hard programmatic
   grounding check on every citation. A grounded citation carries its exact
   source -- PDF page number or xlsx sheet name, resolved programmatically
   from the verified match position, never LLM-reported -- with a "view
   source" link that opens the original document in a docked split-screen
   panel next to the extracted value, not a new tab, so checking a citation
   never navigates the reviewer away from what they're reviewing. Every
   extracted field can be marked reviewed, overridden with a corrected
   value, or rejected, each with an optional comment; every decision is
   appended to a permanent, per-field audit trail (nothing is ever
   overwritten) and shown in a History panel. Every field/record also
   carries `provenance` (extractor/verifier model + prompt-content hash),
   and a golden set of manually verified extractions (`arp golden-set run`)
   regression-tests the real pipeline before a prompt/model change ships.
3. **Company Financials Extraction** — pulls a company's disclosed business
   segments (name, description, revenue, operating income, assets), total
   CapEx, and total R&D -- each spend figure with a grounded plain-language
   description of what it's going toward and any category/program
   breakdown the company discloses (e.g. maintenance vs. growth capex,
   green capex, R&D focus areas) -- broader than a single "green capex"
   field. These three are almost always wanted together, so they're
   extracted in a single combined pass per company: one document fetch, one
   evidence-gathering step, and one extractor + one independent-verifier
   LLM call pair instead of three separate round trips, with the same
   programmatic grounding check on every citation and per-section review
   flagging (a problem in one section doesn't block review of the others).
   A segment/figure not explicitly disclosed is left null rather than
   estimated or backed into from a total. Pulls from annual reports,
   sustainability reports, investor decks, and earnings-call transcripts.
   Designed so a structured vendor data feed can be plugged in ahead of the
   LLM pass later, mirroring the revenue/CapEx catalogue cascade.
4. **Document Discovery** — finds each company's investor-relations site,
   crawls it for disclosure documents, downloads new/changed ones, and
   raises an event the moment something new appears. Runs manually or on
   an automatic schedule.
5. **Indirect Exposure Tier** *(opt-in)* — scores a company's *structural*
   supply-chain exposure to a theme via input-output propagation (OECD
   ICIO), catching companies whose disclosures are silent about a theme but
   whose economic position says otherwise. Purely quantitative, zero LLM
   calls in the computation itself.
6. **Engagement & Voting (stewardship module)** — company engagement
   tracking (issue milestones, an escalation ladder, contacts, commitments)
   and proxy voting (proposal extraction from proxy statements, policy-rule
   + LLM-judgment vote recommendations, and ballot casting), sharing one
   file-based engagement record store and gated by human checkpoints at
   every send/decide/vote point. Backend + CLI + API only, no frontend UI
   yet. See [`docs/ENGAGEMENT_VOTING_ARCHITECTURE.md`](docs/ENGAGEMENT_VOTING_ARCHITECTURE.md)
   for the full design and an implementation file index.
7. **Portfolio Risk & Exposure Monitoring** — aggregates holdings across
   every portfolio, with a deterministic (zero-LLM) engine for grouping by
   portfolio, asset class, issuer, sector, or country, an Analytics
   Builder + natural-language Q&A agent ("how many EUR million of
   exposure to BMW") where the LLM only drafts the query and the engine
   computes the real number, and a dedicated **Climate Analytics** section
   (WACI, PCAF-style financed emissions, coverage reporting) sourced from
   an internal ESG API and cross-validated against the Extraction Engine's
   independent read of company disclosures. See
   [`docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md`](docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md)
   for the full design and `arp portfolio --help` / `arp climate --help`
   below to try it against the built-in mock dataset.
8. **Transition Plan Assessment** — a direct replication of Colesanti
   Senni, Schimanski, Bingler, Ni & Leippold (2024), *"Using AI to assess
   corporate climate transition disclosures"*: scores a company's
   sustainability disclosures against the paper's 64 fixed indicators
   (Target/Governance/Strategy/Tracking), each classified as "talk"
   (future targets) or "walk" (concrete, verifiable activity), with one
   grounded RAG verdict (YES/NO/NA) per indicator — critical of
   greenwashing and "cheap talk" per the paper's own prompt guidelines,
   and, unlike the paper's tool, with every citation independently
   re-verified against the source document by the same programmatic
   grounding check used everywhere else in this codebase rather than
   trusted from the model's self-report. Surfaces the paper's headline
   "walk vs. talk" disclosure-completeness metric per company. See
   [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md#transition-plan-assessment)
   for the full mapping from paper to implementation.

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the research this is
built on and exactly what each precision control catches, and
[`docs/THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md`](docs/THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md)
for a layer-by-layer comparison of this system against a proposed
seven-layer target architecture (Postgres/pgvector, Temporal, per-role
model tiering) — what already exceeds it, and which of its gaps
(decorrelated critic model, XBRL ingestion, a golden set) are genuinely
worth adopting.

## Architecture

```
backend/   Python (FastAPI + Typer CLI) — all agent pipelines
frontend/  React + TypeScript (Vite) — theme/schema authoring, taxonomy
           library (derivation wizard, source inspector, compare/merge,
           universe builder, ETF holdings overlap), run monitoring,
           review queue, run history
data/documents/   local document store (manual uploads + discovery downloads)
runs/             file-based run state: manifest, results, errors,
                   review queue — no database
engagements/      per-company engagement record store: current state
                   (record.json) + an append-only audit log (events.jsonl)
ballots/           voting-instruction files written by the (stub) manual
                   ballot-casting platform, one per cast vote
portfolios/       portfolio holdings snapshots, security/company registries,
                   and climate data-point observations
```

### Agent stack

- **LangChain** (`langchain-anthropic`) is the LLM client (`arp/llm/langchain_client.py`),
  behind a single narrow interface (`arp/llm/base.py::LLMClient.complete_structured`) every
  agent in the codebase calls through — schema-forced structured output via tool calling,
  a bounded self-correction retry loop on validation failure, and a disk-backed response
  cache (`arp/llm/cache.py`), all provider-agnostic from the pipelines' point of view.
- **LangGraph** models each pipeline's per-company (or per-company-per-field/activity)
  multi-step agent flow as an explicit state graph — the Advocate/Opposing/Adjudicator
  debate (`arp/research/match_graph.py`), the extractor/verifier pair
  (`arp/extraction/field_graph.py`, `financials_graph.py`), and proposal extraction +
  policy application (`arp/voting/ballot_graph.py`) — with short-circuit branches (no
  evidence, a resolved hard exposure number, etc.) as conditional edges. The company-level
  batch fan-out, checkpointing, and resumability stay outside the graphs, in the existing
  file-based `run_batch`/`RunStore` layer described above — no database was introduced.
- **LlamaIndex** backs document chunking (`SentenceSplitter`, wrapped in
  `arp/ingestion/parsing.py::chunk_document`) and evidence selection
  (`arp/retrieval/select_evidence.py`, a BM25-ranked retriever) — deterministic and
  embedding-free, consistent with the zero-LLM-cost-in-retrieval design below.
- The programmatic citation-grounding check (`arp/grounding.py`) is independent of all
  three and untouched by them: it re-verifies every citation against the original fetched
  document text, never against a chunk or an LLM's self-report.

Every run type (`theme`, `extraction`, `discovery`) is checkpointed and
resumable: results are appended to `runs/<run_id>/results.jsonl` as soon as
each company finishes, so a batch interrupted partway through picks back up
without redoing completed work. Any running/pending run can also be
cancelled cooperatively (`arp runs cancel <run_id>` /
`POST /api/runs/{id}/cancel`) and later picked back up
(`arp theme resume <run_id>` / `POST /api/themes/runs/{id}/resume`,
theme runs only for now) without redoing already-completed companies.

## Setup

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in ARP_ANTHROPIC_API_KEY
pytest -q              # unit tests, no API key/network required
uvicorn arp.api.main:app --reload   # serves the API on :8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE, defaults to http://localhost:8000
npm run dev             # serves the UI on :5173
```

### CLI (headless path for real 4,000-company batch runs)

The CLI drives the exact same pipelines as the API/UI and is the intended
way to run large batches unattended:

```bash
source backend/.venv/bin/activate

# Thematic universe
arp theme decompose "Electrification" --description "..." --out theme.json
arp theme run --theme theme.json --universe companies.csv

# ...with the indirect (input-output) exposure tier enabled
arp theme classify-sectors --theme theme.json --out theme.json --use-sample-icio
arp theme run --theme theme.json --universe companies.csv --use-sample-icio

# The taxonomy library -- a reusable, versioned theme instead of a one-off file
arp taxonomy discover-sources "Electrification"          # research & rank candidate authority sources + thematic ETFs
arp taxonomy create "Electrification" --description "..." --method industry_anchored --use-sample-icio
arp taxonomy create "Electrification" --method authority_source --authority-url https://...  # from discover-sources, grounded extraction
arp taxonomy create "Electrification" --method empirical --universe companies.csv
arp taxonomy create "Electrification" --method news_transcript_mining --universe companies.csv
arp taxonomy create "Electrification" --method etf_index_holdings --holdings holdings.csv     # a fund's downloaded export
arp taxonomy list
arp taxonomy ratify tax_xxxxxxxxxxxx --by "jane.analyst"
arp taxonomy compare tax_aaaaaaaaaaaa tax_bbbbbbbbbbbb                 # diff two taxonomies' activities
arp taxonomy merge tax_aaaaaaaaaaaa tax_bbbbbbbbbbbb --name "Merged" --out merged.json  # draft only, review then save
arp taxonomy map-standards tax_xxxxxxxxxxxx --use-sample-standards    # cross-reference activities into NACE/NAICS/SIC/GICS
arp taxonomy export-standards tax_xxxxxxxxxxxx --out standards.csv    # flat CSV: activity -> codes per standard
arp theme run --taxonomy tax_xxxxxxxxxxxx --universe companies.csv

# Universe builder + ETF holdings overlap (reuses the same holdings CSV parser)
arp universe from-holdings fund_holdings.csv --out universe.json
arp universe overlap fund_a_holdings.csv fund_b_holdings.csv --name "Fund A" --name "Fund B"

# Revenue/CapEx-based exposure: structured catalogue -> extraction -> qualitative debate cascade
arp revenue-catalogue suggest-mapping tax_xxxxxxxxxxxx revenue_catalogue.csv --out mapping.json  # draft, review it
arp theme run --taxonomy tax_xxxxxxxxxxxx --universe companies.csv \
  --revenue-catalogue revenue_catalogue.csv --catalogue-mapping mapping.json

# Cancel / resume a long-running batch
arp runs cancel <run_id>       # cooperative stop -- in-flight items still finish and checkpoint
arp theme resume <run_id>      # picks back up; already-completed companies are skipped

# Data-point extraction
arp extract draft-schema "green capex" --out schema.json
arp extract run --schema schema.json --universe companies.csv

# Company financials: business segments + CapEx + R&D, one combined pass per company
arp extract financials-run --universe companies.csv

# Golden-set regression test -- run before a prompt/model change ships
arp golden-set run

# Transition Plan Assessment: 64-indicator walk/talk climate disclosure scoring (Colesanti Senni et al. 2024)
arp transition-plan indicators                          # inspect the 64 fixed indicators
arp transition-plan run --universe companies.csv

# Document discovery
arp discover run --universe companies.csv
arp discover schedule --universe companies.csv --interval-hours 24 --enable

# Inspect runs
arp runs list
arp runs show <run_id>

# Engagement (stewardship): open an issue, run triggers, draft a dossier, escalate
arp engagement issue-open AAPL "Apple Inc." --theme executive_compensation --severity high
arp engagement trigger-scan --universe companies.csv --signals controversy_signals.json
arp engagement dossier-draft AAPL <issue_id> --universe companies.csv --out dossier.json
arp engagement issue-escalate AAPL <issue_id> --stage joint_engagement --by "jane.pm"
arp engagement record-show AAPL
arp engagement report --period-label "2026-Q3"

# Proxy voting: analyze a universe's ballots, review every item, then cast
arp voting run --universe companies.csv
arp voting ballots <run_id>
arp voting review <run_id> "AAPL:3" --decision approve --by "jane.pm"
arp voting cast <run_id>

# Portfolio risk & exposure monitoring (see docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md)
arp portfolio seed-demo                             # seeds the built-in illustrative multi-portfolio dataset
arp portfolio list                                    # 4 mock portfolios
arp portfolio review-queue                              # the one deliberately unresolved demo instrument
arp portfolio aggregate --group-by portfolio_id --metric market_value_sum --company-id bmw
arp portfolio aggregate --group-by sector --metric market_value_sum
arp portfolio ask "How many EUR million is our exposure to BMW?"   # requires ARP_ANTHROPIC_API_KEY
arp portfolio classify-news                              # requires ARP_ANTHROPIC_API_KEY

# Climate analytics
arp climate waci --group-by portfolio_id
arp climate financed-emissions
arp climate coverage climate_carbon_intensity
```

`companies.csv` columns: `company_id, name, ticker, website, cik, country,
sector` (only `company_id`/`name` required — supply `website`/`cik` when
known for the most precise document discovery and EDGAR lookup).

## Data sources

- **SEC EDGAR** (`backend/arp/ingestion/edgar.py`): free, no API key, US
  10-K/DEF-14A filings only.
- **Local file store** (`backend/arp/ingestion/local_files.py`): anything
  placed under `data/documents/<company_id>/<doc_type>/` — manual uploads
  or documents found by the discovery crawler land here identically, so
  the extraction pipeline treats them the same way.
- **Document discovery crawler** (`backend/arp/discovery/`): resolves a
  company's IR site (from a supplied URL, or a best-effort web search
  fallback), does a bounded, same-domain, robots.txt-respecting crawl for
  annual reports / sustainability reports / proxy statements / investor
  presentations / transcripts, and downloads matches. A company whose
  homepage/IR URL is known but could not actually be fetched (DNS/network
  failure, 4xx/5xx) is reported as `homepage_unreachable: true` with a
  `crawl_error` message and routed to the review queue -- this is kept
  distinct from a genuine "crawled fine, nothing matched" result of zero
  documents, and from `homepage_used: null` (no URL known at all). Failures
  on links found *deeper* in a crawl (not the root URL) stay a routine,
  silent skip, since that's expected at scale and not evidence the whole
  company was unreachable. `arp discover run` prints a `WARNING` block
  listing any unreachable companies; the Document Discovery page's results
  table shows the same per-company status.
- Earnings-call transcripts have no free public API; supply them via the
  local file store or extend `DocumentSource` with a paid connector.
- **SEC XBRL companyfacts** (`backend/arp/ingestion/xbrl.py`): free, no API
  key. A "Path 0" ahead of the LLM extractor for `Company Financials`'s
  CapEx/R&D totals specifically -- if SEC's own structured, machine-tagged
  figure is available for an EDGAR filer, it's used directly instead of
  extracted from prose (`ARP_XBRL_FACTS_ENABLED`, on by default).
  Segment-level figures and the plain-language description of what
  CapEx/R&D is going toward still always go through the LLM pipeline --
  XBRL tagging isn't standardized enough across filers for those.

## The indirect exposure tier

Off by default. Enable it by pointing at a real, pre-aggregated OECD ICIO
extract:

```bash
# .env
ARP_ICIO_MATRIX_PATH=/path/to/icio_matrix.csv
ARP_ICIO_INDUSTRIES_PATH=/path/to/industries.csv
ARP_ICIO_EDITION_LABEL=oecd-icio-2025
```

or use `--use-sample-icio` (CLI) / `use_sample_icio: true` (API) to try it
against the small bundled illustrative dataset first. Company universe rows
can supply `isic_code` directly for the most precise mapping; see
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the exact CSV format, the
upstream/downstream exposure definitions, and the classification steps
around the input-output math.

## Precision controls at a glance

- Programmatic (non-LLM) grounding check on every citation
- Advocate/Opposing/Adjudicator debate for thematic classification
- Independent Extractor/Verifier pass for data-point extraction
- Schema-first structured output with a validation-retry loop
- Confidence scoring + mandatory human review queue for anything uncertain
- Resumable, checkpointed, per-company-isolated batch execution
- Disk-backed LLM response cache (idempotent, free reruns during dev)
- Opt-in indirect (input-output) exposure tier for companies with no direct
  textual evidence but real structural supply-chain linkage
- Versioned taxonomy library with an explicit ratification step, so a
  theme's activity boundaries are a recorded, auditable decision rather
  than an implicit assumption baked into a one-off run
- Authority-source-derived activities carry a verbatim, grounding-checked
  citation into the source document; ungrounded quotes are dropped, not
  just flagged
- Deterministic (non-LLM) holdings overlap across ETFs/indices, and a
  reusable company universe built straight from a fund's constituents
- NACE/NAICS/SIC codes are cross-referenced via deterministic ISIC
  correspondence tables, never guessed by the model; only GICS (no public
  ISIC crosswalk exists) is LLM-classified, against a fixed reference list
  with a required rationale
- Opt-in revenue/CapEx exposure cascade: a structured data catalogue
  resolves exposure with zero LLM judgment where possible, falling back to
  grounded extraction from disclosures and only then to the qualitative
  debate -- a hard disclosed number is never second-guessed by a
  categorical LLM judgment over the same question
- The independent Verifier runs on a different model than the Extractor
  (`ARP_LLM_VERIFIER_MODEL`, distinct from `ARP_LLM_MODEL`) -- decorrelates
  errors an identical extractor/verifier model pair would otherwise be
  prone to repeat
- Every extracted field/financials record carries `provenance`: the exact
  extractor/verifier model and a content hash of their system prompts, so
  a later prompt or model change is detectable against previously
  persisted output instead of silently mixing pipeline versions
- A golden set of manually verified extractions (`arp golden-set run`) runs
  the real extractor/verifier/grounding pipeline against known-correct
  answers -- run it before a prompt or model change reaches a real batch
- XBRL structured-facts resolution ahead of the LLM for EDGAR filers'
  CapEx/R&D totals (see "Data sources" above) -- never estimated by an
  LLM what SEC's own filing data already answers
- Hybrid (BM25 + local multilingual embedding) evidence retrieval is on by
  default, closing vocabulary gaps between seed keywords and how a company
  actually phrases a disclosure -- including DE-language disclosures

Full detail in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Optional Postgres/pgvector store

Every store in this system is file-based by default -- no database
required. An opt-in Postgres/pgvector backend (`backend/arp/storage/postgres*.py`)
is available for the two places a relational/vector engine genuinely earns
its cost: **Portfolio Risk & Exposure Monitoring**'s holdings (real joins
across portfolios × securities × companies × time) and the hybrid-retrieval
chunk-embeddings cache. The run/review-queue/audit-trail stores everywhere
else stay file-based JSONL regardless -- an append-only file is simpler to
keep fully auditable than a table with `UPDATE`s, and none of those stores
have the multi-way join access pattern that justifies a relational engine;
see [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the full reasoning.

```bash
pip install -e ".[postgres]"   # sqlalchemy, psycopg, pgvector

# .env
ARP_POSTGRES_DSN=postgresql+psycopg://user:pass@localhost:5432/arp
ARP_PORTFOLIO_BACKEND=postgres   # optional -- default stays "file"
ARP_EMBEDDINGS_BACKEND=postgres  # optional -- default stays "sqlite"

arp db init-postgres   # creates the pgvector extension + every table, idempotent
```

A local Postgres+pgvector for development:

```bash
docker run -d --name arp-postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg16
```
