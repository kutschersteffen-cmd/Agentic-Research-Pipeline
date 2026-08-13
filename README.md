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
   with an independent verifier pass and a hard programmatic grounding
   check on every citation. A grounded citation carries its exact source --
   PDF page number or xlsx sheet name, resolved programmatically from the
   verified match position, never LLM-reported -- with a "view source"
   link that opens the original document straight to that location. Every
   extracted field can be marked reviewed, overridden with a corrected
   value, or rejected, each with an optional comment; every decision is
   appended to a permanent, per-field audit trail (nothing is ever
   overwritten) and shown in a History panel.
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

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the research this is
built on and exactly what each precision control catches.

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
```

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

# Document discovery
arp discover run --universe companies.csv
arp discover schedule --universe companies.csv --interval-hours 24 --enable

# Inspect runs
arp runs list
arp runs show <run_id>
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

Full detail in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).
