# Agentic Research Pipeline

Two coupled tools for building thematic investment universes and
researching specific data points across large company sets, built for
precision at scale (designed for up to ~4,000 companies per run).

1. **Thematic Universe Builder** — turn a macro theme ("electrification",
   "AI") into a defensible list of business activities, matched companies,
   exposure estimates, and cited rationale, via an Advocate/Opposing/
   Adjudicator agent pipeline.
2. **Data-Point Extraction Engine** — pull specific, schema-defined data
   points (e.g. "green capex", forward-looking business outlook) out of
   sustainability reports, annual reports, and earnings-call transcripts,
   with an independent verifier pass and a hard programmatic grounding
   check on every citation.
3. **Document Discovery** — finds each company's investor-relations site,
   crawls it for disclosure documents, downloads new/changed ones, and
   raises an event the moment something new appears. Runs manually or on
   an automatic schedule.
4. **Indirect Exposure Tier** *(opt-in)* — scores a company's *structural*
   supply-chain exposure to a theme via input-output propagation (OECD
   ICIO), catching companies whose disclosures are silent about a theme but
   whose economic position says otherwise. Purely quantitative, zero LLM
   calls in the computation itself.

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the research this is
built on and exactly what each precision control catches.

## Architecture

```
backend/   Python (FastAPI + Typer CLI) — all agent pipelines
frontend/  React + TypeScript (Vite) — theme/schema authoring, run
           monitoring, review queue, run history
data/documents/   local document store (manual uploads + discovery downloads)
runs/             file-based run state: manifest, results, errors,
                   review queue — no database
```

Every run type (`theme`, `extraction`, `discovery`) is checkpointed and
resumable: results are appended to `runs/<run_id>/results.jsonl` as soon as
each company finishes, so a batch interrupted partway through picks back up
without redoing completed work.

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
arp taxonomy discover-sources "Electrification"          # research candidate authority sources & thematic ETFs
arp taxonomy create "Electrification" --description "..." --method industry_anchored --use-sample-icio
arp taxonomy create "Electrification" --method authority_source --authority-url https://...  # from discover-sources
arp taxonomy create "Electrification" --method empirical --universe companies.csv
arp taxonomy create "Electrification" --method news_transcript_mining --universe companies.csv
arp taxonomy create "Electrification" --method etf_index_holdings --holdings holdings.csv     # a fund's downloaded export
arp taxonomy list
arp taxonomy ratify tax_xxxxxxxxxxxx --by "jane.analyst"
arp theme run --taxonomy tax_xxxxxxxxxxxx --universe companies.csv

# Data-point extraction
arp extract draft-schema "green capex" --out schema.json
arp extract run --schema schema.json --universe companies.csv

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
  presentations / transcripts, and downloads matches.
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

Full detail in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).
