# Agentic Research Pipeline

Agent pipelines for investment research at scale: build thematic company
universes, extract schema-defined data points from disclosures, and analyse
portfolios — designed for up to ~4,000 companies per run.

Two design rules hold everywhere: **the LLM plans, deterministic code
computes**, and **every citation is re-verified programmatically** against
the source document rather than trusted from the model's self-report.

Python (FastAPI + Typer CLI) backend, React/TypeScript (Vite) frontend,
file-based state by default — no database required.

## Functions

| # | Function | What it does |
|---|---|---|
| 1 | **Thematic Universe Builder** | Turns a macro theme into business activities, matched companies, exposure estimates and cited rationale via an Advocate/Opposing/Adjudicator debate. |
| 2 | **Taxonomy Library** | Reusable, versioned theme definitions with an explicit ratification step; five derivation methods (industry-anchored, authority-source, empirical, news/transcript mining, ETF holdings) plus compare/merge and NACE/NAICS/SIC/GICS crosswalks. |
| 3 | **Data-Point Extraction Engine** | Pulls schema-defined figures (e.g. green capex) from disclosures with an independent verifier on a *different* model, programmatic grounding, review/override/reject with a permanent per-field audit trail. |
| 4 | **Company Financials Extraction** | Business segments + total CapEx + R&D in one combined pass per company, each figure with a grounded description of what it funds. SEC XBRL facts resolve CapEx/R&D totals ahead of the LLM where available. |
| 5 | **Company Identity Resolution** | Agentic resolution of messy company identifiers to a single canonical entity. |
| 6 | **Document Discovery** | Finds each company's IR site, crawls it (bounded, same-domain, robots.txt-respecting), downloads new/changed disclosures. Manual or scheduled. |
| 7 | **Indirect Exposure Tier** *(opt-in)* | Structural supply-chain exposure via OECD ICIO input-output propagation. Purely quantitative, zero LLM calls. |
| 8 | **Transition Plan Assessment** | Replication of Colesanti Senni et al. (2024): 64 fixed indicators scored "walk" vs. "talk", each with a grounded RAG verdict. |
| 9 | **Transition Barrier Assessment** | Sector-level counterpart: a 105-cell matrix (35 criteria × 9 hard-to-abate sectors × EU/US/China) backed by 86 verified sources, with staleness tracking and a propose-never-apply EUR-Lex refresh pipeline. |
| 10 | **Portfolio Risk & Exposure Monitoring** | Deterministic holdings aggregation, an NL Q&A agent (LLM drafts the query, the engine computes the number), a **Generative BI** layer that plans whole dashboards, and **Climate Analytics** (WACI, PCAF-style financed emissions, coverage). |
| 11 | **Investment Strategy Replication** | Reduces a strategy paper to an executable spec, then backtests it deterministically in- and out-of-sample, with deflated Sharpe, PBO via purged/embargoed CSCV, and regime stratification. |
| 12 | **Emerging Themes Scanner** | Bottom-up theme discovery from EDGAR full-text search, GDELT and regulatory RSS, with cross-period cluster lineage and an action-score promotion gate (corporate action, not mention counts). |
| 13 | **Presentation & Reporting Tool** | One LLM call drafts a report plan; deterministic renderers emit pptx/docx/pdf, reusing an ingested `.pptx` template's layouts, colors and fonts. |
| 15 | **Decision Studio** | Turns any per-entity table the functions above produce into a scored, ranked and tiered decision — entities are companies, sectors in a jurisdiction, themes or strategies, since the engine scores rows. Correlated criteria are grouped so one theme measured seven ways doesn't earn seven times the weight; criteria are normalised within peer cohorts; direction is inferred and *flagged where it is a guess*. Gates resolve before the average, a sufficiency gate precedes scoring, and every entity carries its rank *range* across four specifications. Frameworks are versioned and ratifiable; the audit log separates what the data proposed from what a person changed. Zero LLM calls. |
| 16 | **Equity Index Construction** | Builds an index methodology by composing named rules — ordered screens, one selection rule (best-in-class to a market-cap *or* count coverage target with hysteresis buffers, an absolute threshold, or top-N), a weighting scheme, bounded multiplicative tilts, a deterministic capping waterfall (single-name, group, UCITS 5/10/40) and the path-dependent EU PAB/CTB decarbonisation trajectory. Zero LLM calls in the numbers: a model-derived thematic score enters only as a frozen, effective-dated snapshot. The composition saves as a versioned, effective-dated **calibration**, and a review resolves the version *in force on its review date*, so today's parameters cannot rewrite a past one. Optionally (`.[optimize]`) swaps the waterfall for a convex programme — least-squares projection, minimum tracking error, or score maximisation under a TE budget on an estimated or vendor risk model — or a mixed-integer one on SCIP for cardinality limits and a genuinely enforced minimum weight. Every constraint is re-verified in plain Python afterwards; a solver's own "optimal" is never taken as proof. |
| 14 | **Standing agents** | Taxonomy Researcher and Calibration Agent run on a schedule and *propose* changes for human review — they never apply them. |

## Architecture

```
backend/   Python (FastAPI + Typer CLI) — every agent pipeline
frontend/  React + TypeScript (Vite) — authoring, monitoring, review UI
runs/      file-based run state: manifest, results, errors, review queue
taxonomies/ portfolios/ reports/ report_templates/ data/documents/
frameworks/ versioned decision frameworks + the tables they are applied to
indices/   index construction calibrations (versioned, effective-dated) + reviews
```

- **LangChain** (`langchain-anthropic`) is the LLM client, behind one narrow
  interface (`arp/llm/base.py`) — schema-forced structured output, a bounded
  validation-retry loop, and a disk-backed response cache.
- **LangGraph** models each per-company multi-step flow as an explicit state
  graph (the classification debate, the extractor/verifier pair, …). Batch
  fan-out, checkpointing and resumability stay outside the graphs, in the
  file-based run store.
- **LlamaIndex** backs chunking and BM25 evidence selection; hybrid
  (BM25 + local multilingual embedding) retrieval is on by default.
- **`arp/grounding.py`** is independent of all three and re-verifies every
  citation against the original document text.

Every run type is checkpointed and resumable — results append to
`runs/<run_id>/results.jsonl` as each company finishes, so an interrupted
batch picks back up without redoing completed work. Runs can be cancelled
cooperatively (`arp runs cancel`) and resumed later.

## Setup

Windows / corporate proxy / VS Code + conda: see
[`docs/INSTALLATION.md`](docs/INSTALLATION.md), which ships scripts under
`scripts/windows/` that automate everything below.

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11+
pip install -e ".[dev]"
cp .env.example .env            # fill in ARP_ANTHROPIC_API_KEY
pytest -q                       # no API key or network required
uvicorn arp.api.main:app --reload            # API on :8000

# Frontend
cd frontend && npm install
cp .env.example .env            # VITE_API_BASE
npm run dev                                   # UI on :5173
```

Docker is an alternative to both:

```bash
cp backend/.env.example backend/.env
docker compose up backend frontend --build    # same ports, state in named volumes
```

There is no authentication in front of either path today — see
[`docs/CORPORATE_READINESS_PLAN.md`](docs/CORPORATE_READINESS_PLAN.md).

Contributors: `pre-commit install` enables the secret-scanning hook that
also runs in CI.

**Data handling.** Document text and company data go to Anthropic's API;
outbound requests reach SEC EDGAR, GDELT, regulatory RSS and crawled IR
sites. Everything else stays on local disk. Review this against your
organization's data-handling policy before pointing it at real holdings.

## CLI

The CLI drives the same pipelines as the API and is the intended path for
large unattended batches. `arp --help` lists every command; a representative
slice:

```bash
arp theme decompose "Electrification" --out theme.json
arp theme run --theme theme.json --universe companies.csv
arp taxonomy create "Electrification" --method industry_anchored
arp extract run --schema schema.json --universe companies.csv
arp extract financials-run --universe companies.csv
arp transition-plan run --universe companies.csv
arp transition-barrier scores --region China --pillar Regulation
arp emerging-themes run --universe companies.csv
arp replicate backtest --spec spec.json --prices prices.csv --tickers universe.csv
arp portfolio bi generate "climate risk overview of the leaders fund" --save
arp climate waci --group-by portfolio_id
arp decision derive --source transition_plan_run --run-id <run_id> --save   # no API key: zero LLM calls
arp decision score --source transition_barrier --region "European Union"  # entity = sector, not company
arp decision score --dataset <dataset_id> --framework <fw_id>
arp report run --title "Electrification Review" --notes notes.txt --format pptx --out review.pptx
arp discover run --universe companies.csv
arp golden-set run                # regression-test before a prompt/model change
arp runs list                     # also: arp runs show <run_id>, arp runs cancel <run_id>

# Index construction (see docs/EQUITY_INDEX_CONSTRUCTION_PLAN.md)
arp index presets                                        # the named methodology shapes
arp index preview --preset eu_pab --review-date 2026-03-31 --show trace
arp index calibration-save --name "DWS Electrification PAB" --effective-from 2026-01-01 \
    --preset eu_pab --approved-by "IC-2026-01-14"
arp index run --index-id dws_pab --review-date 2026-03-31 --calibration-id <cal_id>
# Optional convex / integer paths (pip install -e ".[optimize]")
arp index preview --preset eu_pab --review-date 2026-03-31 --solver-method min_tracking_error
arp index preview --preset eu_pab --review-date 2026-03-31 --max-constituents 20
```

Every `arp index` command runs against a built-in, deterministic demo
universe unless `--universe-file` supplies one, so the engine is usable
before any data feed is connected. `--spec-file` takes a `ConstructionSpec`
JSON exactly as the UI saves it, so a methodology composed in the browser
runs headless without retyping.

`companies.csv` columns: `company_id, name, ticker, website, cik, country,
sector` — only `company_id`/`name` are required.

## Data sources

- **SEC EDGAR** — free, no API key; US 10-K/DEF-14A filings.
- **SEC XBRL companyfacts** — free; resolves CapEx/R&D totals ahead of the
  LLM for EDGAR filers.
- **Local file store** — anything under `data/documents/<company_id>/<doc_type>/`;
  manual uploads and crawler downloads land here identically.
- **Document discovery crawler** — bounded, same-domain, robots.txt-respecting;
  unreachable companies are reported distinctly from "crawled fine, nothing
  matched" and routed to the review queue.
- Earnings-call transcripts have no free public API — supply them via the
  local file store or add a `DocumentSource` connector.

## Precision controls

- Programmatic (non-LLM) grounding check on every citation
- Advocate/Opposing/Adjudicator debate for thematic classification
- Extractor/Verifier pair on deliberately different models, to decorrelate errors
- Schema-first structured output with a validation-retry loop
- Confidence scoring plus a mandatory human review queue for anything uncertain
- `provenance` (model + prompt-content hash) on every extracted record
- Golden sets that run the real pipelines before a prompt/model change ships
  (`arp golden-set run`, `run-roles`, `planner`; `arp replicate golden-set`)
- Structured data resolved before LLM judgment wherever it exists — XBRL
  facts, the revenue/CapEx catalogue cascade, ISIC correspondence tables
- Generated BI commentary is checked figure by figure against what the
  deterministic engine actually computed; unsupported sentences are dropped
- Scoring decisions: direction inference flagged rather than silently applied, correlated criteria grouped before weighting, hard gates resolved before the average, a sufficiency gate ahead of scoring (optionally keyed to *grounded* rather than merely present values), peer-cohort normalisation, and rank stability reported across four specifications
- Resumable, checkpointed, per-company-isolated batch execution

Full detail in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Optional backends

Every store is file-based by default. Three opt-in backends are additive
read-model projections — the file/SQLite stores remain the only writable
source of truth:

```bash
pip install -e ".[postgres,opensearch,object_storage]"
docker compose up -d postgres opensearch minio
arp db init-postgres && arp db check-postgres    # idempotent; check gates a deploy
arp db init-opensearch && arp db init-object-store
arp db reindex company-records    # also: company-facts, documents, opensearch, object-store
```

- **Postgres/pgvector** — portfolio holdings joins and the chunk-embeddings cache
- **OpenSearch** — full-text/vector search over documents and chunks
- **Object storage** (S3-compatible, MinIO locally) — immutable copies of source documents

Re-run `arp db init-postgres` after upgrading, not only on a fresh database.

## Documentation

| Doc | Covers |
|---|---|
| [`TECHNICAL_REFERENCE.md`](docs/TECHNICAL_REFERENCE.md) | Full inventory of every module, the agent stack, and all dependencies |
| [`METHODOLOGY.md`](docs/METHODOLOGY.md) | The research this is built on and what each precision control catches |
| [`INSTALLATION.md`](docs/INSTALLATION.md) | From-scratch Windows/VS Code/conda install behind a corporate proxy |
| [`CORPORATE_READINESS_PLAN.md`](docs/CORPORATE_READINESS_PLAN.md) | Phased plan to a corporate deployment (auth, secrets, GCP target) |
| [`PORTFOLIO_RISK_EXPOSURE_PLAN.md`](docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md) | Portfolio monitoring design |
| [`STRATEGY_REPLICATION_METHODOLOGY.md`](docs/STRATEGY_REPLICATION_METHODOLOGY.md) | Backtest design, in/out-of-sample meaning, current limitations |
| [`DECISION_MECHANISM.md`](docs/DECISION_MECHANISM.md) | The scoring/ranking/tiering engine: every control, what it catches, and its known limits |
| [`TRANSITION_BARRIER_ASSESSMENT.md`](docs/TRANSITION_BARRIER_ASSESSMENT.md) | The 35 criteria and their source lists |
| [`EMERGING_THEMES_VOCABULARY.md`](docs/EMERGING_THEMES_VOCABULARY.md) | How each scored dimension maps to the research vocabulary |
| [`THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md`](docs/THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md), [`GENBI_LANDSCAPE_REVIEW.md`](docs/GENBI_LANDSCAPE_REVIEW.md), [`DATABASE_STORAGE_REVIEW.md`](docs/DATABASE_STORAGE_REVIEW.md), [`SPEC_GAP_ANALYSIS.md`](docs/SPEC_GAP_ANALYSIS.md) | Architecture reviews and gap analyses |
