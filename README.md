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

## Precision controls at a glance

- Programmatic (non-LLM) grounding check on every citation
- Advocate/Opposing/Adjudicator debate for thematic classification
- Independent Extractor/Verifier pass for data-point extraction
- Schema-first structured output with a validation-retry loop
- Confidence scoring + mandatory human review queue for anything uncertain
- Resumable, checkpointed, per-company-isolated batch execution
- Disk-backed LLM response cache (idempotent, free reruns during dev)

Full detail in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).
