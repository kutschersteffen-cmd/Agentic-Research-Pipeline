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
| 10 | **Portfolio Risk & Exposure Monitoring** | Deterministic holdings aggregation, an NL Q&A agent (LLM drafts the query, the engine computes the number), a **Dashboards (Superset)** tab that embeds every `arp-` dashboard (a provisioned exposure dashboard with Fund/Sector/Country filters, hand-built ones, and drafts from the Superset designer), and **Climate Analytics** (WACI, PCAF-style financed emissions, coverage). |
| 11 | **Investment Strategy Replication** | Reduces a strategy paper to an executable spec, then backtests it deterministically in- and out-of-sample, with deflated Sharpe, PBO via purged/embargoed CSCV, and regime stratification. |
| 12 | **Emerging Themes Scanner** | Bottom-up theme discovery from EDGAR full-text search, GDELT and regulatory RSS, with cross-period cluster lineage and an action-score promotion gate (corporate action, not mention counts). |
| 13 | **Presentation & Reporting Tool** | One LLM call drafts a report plan; deterministic renderers emit pptx/docx/pdf, reusing an ingested `.pptx` template's layouts, colors and fonts. House decks (`house_deck`) draft a storyline for you to approve, then fill, lint, fit and visually check each slide in the app's own design system, and can be re-run on fresh pipeline data. |
| 15 | **Decision Studio** | Turns any per-entity table the functions above produce into a scored, ranked and tiered decision — entities are companies, sectors in a jurisdiction, themes or strategies, since the engine scores rows. Correlated criteria are grouped so one theme measured seven ways doesn't earn seven times the weight; criteria are normalised within peer cohorts; direction is inferred and *flagged where it is a guess*. Gates resolve before the average, a sufficiency gate precedes scoring, and every entity carries its rank *range* across four specifications. Frameworks are versioned and ratifiable; the audit log separates what the data proposed from what a person changed. Zero LLM calls. |
| 16 | **Equity Index Construction** | Builds an index methodology by composing named rules — ordered screens, one selection rule (best-in-class to a market-cap *or* count coverage target with hysteresis buffers, an absolute threshold, or top-N), a weighting scheme, bounded multiplicative tilts, a deterministic capping waterfall (single-name, group, UCITS 5/10/40) and the path-dependent EU PAB/CTB decarbonisation trajectory. Zero LLM calls in the numbers: a model-derived thematic score enters only as a frozen, effective-dated snapshot. The composition saves as a versioned, effective-dated **calibration**, and a review resolves the version *in force on its review date*, so today's parameters cannot rewrite a past one. Optionally (`.[optimize]`) swaps the waterfall for a convex programme — least-squares projection, minimum tracking error, or score maximisation under a TE budget on an estimated or vendor risk model — or a mixed-integer one on SCIP for cardinality limits and a genuinely enforced minimum weight. Every constraint is re-verified in plain Python afterwards; a solver's own "optimal" is never taken as proof. |
| 14 | **Standing agents** | Taxonomy Researcher and Calibration Agent run on a schedule and *propose* changes for human review — they never apply them. |
| 17 | **Superset BI Designer** *(opt-in)* | Describe a dashboard in words and get an unpublished draft in Apache Superset. The LLM plans, deterministic code compiles, Superset computes: a closed catalogue of datasets and metrics bounds the plan, a validator rejects anything outside it, and the model never writes SQL or sees a number. Reads only the `bi` views over Postgres, so company facts are the reviewed ones. Drafts only; a person publishes. |
| 18 | **XBRL Facts** | Separate from Data-Point Extraction, which it does not touch. Downloads each company's SEC `companyfacts` JSON and latest 10-K (inline XBRL) as filed, or for EU companies (`--market esef`, keyed by LEI; the default `--market auto` routes each company by country, ISIN prefix or identifiers and marks the rest `no_source` or `unrouted`) the latest ESEF annual report's xBRL-JSON and package from filings.xbrl.org, extracts every tagged fact (or only a chosen set), always resolves revenue and capex, and offers a searchable dropdown over the full us-gaap / ifrs-full / dei / esrs taxonomies. Files and facts show in tables (flat and by year), and an extraction run can be verified against the filer's tagged values (a run that copied XBRL is refused). CLI, API and page; files only, no database. |
| 19 | **Argus Universe** | Landing page of both Argus processes: bring a universe, map it through the security master by exact identifier, see what is already stored per company (identity, documents, extraction runs, XBRL files) and the suggested XBRL source, then hand the whole universe or a selection to Extraction or XBRL Facts. Read-only; it starts no run. |

## Architecture

```
backend/   Python (FastAPI + Typer CLI) — every agent pipeline
frontend/  React + TypeScript (Vite) — authoring, monitoring, review UI
runs/      file-based run state: manifest, results, errors, review queue
taxonomies/ portfolios/ reports/ report_templates/ data/documents/
frameworks/ versioned decision frameworks + the tables they are applied to
indices/   index construction calibrations (versioned, effective-dated) + reviews
```

- The **Anthropic SDK** (`anthropic`) is the LLM client, behind one narrow
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
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11
pip install -e ".[dev]"
cp .env.example .env            # fill in ARP_ANTHROPIC_API_KEY
pytest -q                       # no API key or network required
uvicorn arp.api.main:app --reload            # API on :8000

# Frontend
cd frontend && npm install
cp .env.example .env            # VITE_API_BASE, VITE_SUPERSET_URL
npm run dev                                   # UI on :5173
```

### Sign-in

Every API route except `/api/health` (and the proxy-voting routes) needs a
signed-in user, and every review, ratification and approval is recorded
against that user.

**Current default: dev mode** (`ARP_AUTH_MODE=dev`). Every request from
127.0.0.1/::1 is signed in as an approver named `ARP_DEV_USER` (default `dev`)
without a token; the sidebar shows "Signed in as dev (approver)". Use it only on
your own machine, or with the provided `docker-compose.yml`, which publishes the
API on 127.0.0.1 only and adds the Docker bridge range (`172.16.0.0/12`) to
`ARP_DEV_TRUSTED_NETWORKS` because the browser's requests reach the container
from the bridge, not loopback. That range also covers every other container on
the compose network (e.g. Superset): while dev mode is on, they get dev approver
access too. On Docker hosts whose compose subnets come from `192.168.0.0/16`
(check `docker network inspect`), adjust `ARP_DEV_TRUSTED_NETWORKS` to match.
The bypass trusts the socket address: never run dev mode behind a proxy on the
same host (every proxied request would arrive from loopback) and never publish
the port on a LAN-reachable address. Requests from anywhere else still need a
token. Dev mode also refuses browser requests from foreign origins (an `Origin`
header not in `ARP_ALLOWED_ORIGINS` gets no bypass, so another website cannot
act as you), and the API only answers the host names in `ARP_TRUSTED_HOSTS`
(default `localhost`, `127.0.0.1`, `[::1]`, `backend`), which blocks DNS
rebinding; this host check applies to every route, voting included. Dev mode has a single user, so four-eyes
steps (calibration approval, co-sign) need local mode.

**Switching to local mode** (real per-person sign-in):

1. `cp config/users.example.json config/users.json` and give each person a long
   random token (`openssl rand -hex 24`), a unique `user_id`, a name and a role:
   `viewer` (read), `analyst` (change), `approver` (also approve calibrations
   and co-sign). Tokens and `user_id`s must be unique and non-empty, or the API
   refuses to start. `config/users.json` is gitignored; `ARP_USERS_FILE` points
   elsewhere.
2. Set `ARP_AUTH_MODE=local` in `backend/.env` (Docker: in the `backend`
   service's `environment:` in `docker-compose.yml`, and remove
   `ARP_DEV_TRUSTED_NETWORKS` there).
3. Restart the API (also after every later edit of the users file: it is read once).
4. Each person pastes their token into the sidebar; the UI keeps it in the
   browser's `localStorage` until they sign out (or the API rejects it).
5. CLI commands that write (`arp index calibration-save`, `arp index approve`, …)
   need `ARP_CLI_TOKEN` set to the person's token, in either mode.

`ARP_ALLOWED_ORIGINS` is the CORS allow-list for the browser UI, as JSON, e.g.
`ARP_ALLOWED_ORIGINS='["https://arp.example.com"]'`.

`[dev]` is enough to run the app, but **not** enough for a green test suite —
the reporting tests render through headless Chromium and a few storage tests
need the optional backends. For the full suite, as CI installs it:

```bash
pip install -e ".[dev,postgres,opensearch,object_storage,emerging_themes]"
python -m playwright install chromium
```

Budget **~1.8 GB** and around ten minutes: `docling` pulls in torch,
torchvision, transformers, onnxruntime and opencv (217 packages for `[dev]`
alone). Nothing is downloaded at import time — `docling` and `fastembed` are
both imported lazily — but they are hard dependencies, so the install pays for
them regardless.

No conda needed. `environment.yml` and `scripts/windows/setup.ps1` use it to
supply Python 3.11 and Node 22, but any 3.11 interpreter works; `uv venv
--python 3.11` fetches one in seconds if the system Python is a different
version. Python 3.11 is what CI and `environment.yml` pin and the only version
verified here.

On a first extraction or theme-matching run, hybrid retrieval downloads a
~120 MB embedding model (it is on by default); `ARP_HYBRID_RETRIEVAL_ENABLED=false`
keeps a first run fully offline.

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

## Superset BI

Optional. Needs Postgres as the portfolio store, with the projections the `bi` views read switched on (`backend/.env.example` lists them):
`ARP_PORTFOLIO_BACKEND=postgres`, `ARP_POSTGRES_DSN`, `ARP_COMPANY_RECORDS_PROJECTION_ENABLED=true`, `ARP_COMPANY_FACTS_PROJECTION_ENABLED=true`
(and the document-registry and engagement projections if you want those views filled).

Set `ARP_SUPERSET_PASSWORD`, `ARP_BI_READER_PASSWORD`, `SUPERSET_SECRET_KEY` and `SUPERSET_GUEST_TOKEN_JWT_SECRET` in
`backend/.env`. None has a default and the `change-me` placeholders are refused; the two Superset secrets need 32+
characters. Generate each with `openssl rand -base64 42`. `ARP_SUPERSET_URL` (default `http://127.0.0.1:8088`) and
`ARP_SUPERSET_USER` (default `arp_designer`) have defaults; `ARP_BI_SUPERSET_DB_HOST` (default `postgres:5432`) is the
host:port Superset uses to reach Postgres.

```bash
docker compose --env-file backend/.env up -d postgres superset   # first start builds superset/Dockerfile
arp db init-postgres                                             # schema + `bi` views
ARP_PORTFOLIO_BACKEND=postgres arp portfolio seed-demo           # demo holdings into Postgres (with ARP_POSTGRES_DSN set)
arp bi bootstrap                                                 # views, bi_reader role, Superset database, datasets, metrics, descriptions, templates (idempotent)
arp golden-set bi                                                # planner eval; needs an API key, not run in CI
```

`arp bi bootstrap` re-applies the `bi` views (including `holdings_history`), registers the six datasets and their
metrics, and copies descriptions from `backend/arp/bi/catalog.py`. Each run overwrites the dataset description and the
descriptions of catalogue-named columns, so edit them there, not in Superset. It then provisions the standard
dashboards in `backend/arp/bi/templates/` (today `arp-risk-exposure`: 8 charts, native filters Fund, Sector and Country)
and prints `{"templates": {"arp-risk-exposure": "created" | "rebuilt" | "unchanged"}}` with the rest of its output.
The dashboard is created unpublished; publish it in Superset. One that has at least the template's charts is left alone.
One with fewer is deleted and rebuilt (its old charts stay), and the rebuild is unpublished again. Existing
deployments must re-run `arp bi bootstrap` after upgrading: the AI designer needs every catalogue dataset, including
`holdings_history`.

Upgrading to the monthly run's published datasets: run `arp db init-postgres` (creates the `bi_published` table and its `bi` views), then
`arp bi bootstrap` (bi_reader is granted per existing object, and the climate, alerts, triggers and company-profile
datasets and dashboards are registered there). Until then Company Profile embeds fail closed with a 502 ("Superset has
no dataset bi.alerts"). The published datasets fill only when a monthly run (`arp portfolio monthly-run --month
YYYY-MM`) succeeds, and a month runs only with an ok holdings load for every portfolio and an ok ESG load for that month
(upload it, or `arp portfolio esg-pull --month YYYY-MM`). Holdings Intake shows what a month is still missing.

News comes from Refinitiv News over the Refinitiv Data Platform: set `ARP_NEWS_API_CLIENT_ID` and
`ARP_NEWS_API_CLIENT_SECRET` (an RDP service account; `ARP_NEWS_API_URL` defaults to `https://api.refinitiv.com`), then
pull from Data Hub · Feeds ("Pull now") or on a schedule with `arp portfolio news-pull`. Only issuers with a `permid`
in the security master are asked for, and each story is tied to them by PermID exact match only (see
`backend/arp/portfolio/news/api_source.py`). ESG can be pulled the same way from Feeds once `ARP_ESG_API_URL` and
`ARP_ESG_API_TOKEN` are set.

Set `VITE_SUPERSET_URL` in `frontend/.env`, then open Risk Monitoring, Dashboards (Superset). This one tab replaces
Pivot Explorer, Generative BI and Superset BI (old links land on it), and it is the default Risk Monitoring tab. The
in-app Standard Analytics tab is gone; Monitoring & Alerts, Company Profiles and Ask the Portfolio are unchanged. The picker lists every Superset dashboard whose slug
starts with `arp-` and opens on `arp-risk-exposure`. To add a dashboard you built by hand, set its slug to `arp-<name>`
in Superset's dashboard Properties and reload the tab. The weighted-average climate pivots Pivot Explorer had are
available through the climate API endpoints.

The UI embeds a draft through `POST /api/bi/embed-token {dashboard_id}`, which answers `{token, embedded_id}`
(`service.embed_token` returns `(embedded_id, token)`). Only arp- dashboards (slug `arp-...`, the scratch one and
hand-built ones included) are embeddable: another dashboard id gets 403, an unknown one 404.

Caveats:
- Drafts only. Publishing a dashboard is a human step in Superset.
- The `superset/Dockerfile` build (adds psycopg2 to `apache/superset:5.0.0`) is unverified end to end: the sandbox proxy's TLS blocked it, and it was tested with an equivalent local image. Run `docker compose build superset` on a normal machine before relying on it.
- Embedding is verified in Chromium only.
- The first-embed lock is in-process, so run a single uvicorn worker.
- Demo data lives in files; seed it into Postgres (`ARP_PORTFOLIO_BACKEND=postgres arp portfolio seed-demo`) before the views have anything to show.
- Postgres 15 or later is assumed (compose runs pg16). Before 15, every role, `bi_reader` included, gets CREATE on schema `public` through PUBLIC, which bootstrap's REVOKE does not remove.
- `frame-ancestors` lists only `http://localhost:5173` and `http://127.0.0.1:5173` (the dev UI). Add production origins in `superset/superset_config.py`.

### Projects

A project is a folder under `ARP_PROJECTS_DIR` (default `projects/`, git-ignored) holding replayable data sources
(uploaded DWS constituent `.xlsx` files plus the assumed notional) and the dashboards stored for it. The data
files are user data and are never committed. Opening a project re-imports its files into Postgres (tagged
`project:<id>`, portfolio ids `<project>-dws-<fund isin>`) and provisions its dashboards, both idempotently.

UI (Risk Monitoring, Dashboards): pick a project in the selector or choose New project, upload the files and
notional, and the project opens automatically. A generated dashboard is saved to the project with Save to project.
Dashboards you built by hand in Superset (slug `arp-...`) appear under Other arp- dashboards and can be exported
into a project from there; opening the project re-imports one that is missing (always unpublished, never over an
existing slug). Saving the same title again is an explicit Save and rebuilds that dashboard in Superset (only the
dashboard is deleted, charts stay; it comes back unpublished); opening a project never changes an existing dashboard.

```
arp project create alpha --name "Alpha review"
arp project add-data alpha Constituent_IE00B4L5Y983.xlsx --notional-eur 50000000
arp project list
arp project open alpha          # import data, provision dashboards; prints created / rebuilt / unchanged
```

API (`/api/projects`): `GET ""`, `POST ""`, `GET /{id}`, `POST /{id}/data` (multipart: file, notional_eur),
`POST /{id}/open`, `POST /{id}/dashboards` (save a designed dashboard plan), `POST /{id}/dashboards/export` (store a hand-built
dashboard).

Scoping: `bi.holdings` and `bi.holdings_history` have a trailing `project_id` column taken from the portfolio tag.
Project dashboards carry the chart filter `project_id == <id>` and their native filters (Fund, Sector, Country)
are pre-filtered the same way, so options list only that project's data. The STANDARD dashboards (such as
`arp-risk-exposure`) stay unfiltered and show ALL data in the shared Postgres, every opened project included.
Securities and companies are global and keyed by ISIN: the last import wins for sector and country labels, so a
conflicting file in project B can change project A's sector/country breakdowns (holdings themselves never mix).
Hand-built dashboards are stored as Superset export bundles and are not auto-scoped; filter them on `project_id`
yourself if they must be.

Upgrade: re-run `arp bi bootstrap` so the views gain `project_id`. Project dashboards created before the
native-filter scoping fix keep global filter options until rebuilt: delete the dashboard in Superset and open the
project again.

Limits: the only data kind is the DWS constituent `.xlsx`; uploads are `.xlsx` up to 50 MB; there is no project
delete, versioning or authentication; opening needs the Postgres portfolio backend. `ARP_BI_READER_PASSWORD`
(not a placeholder) is needed only to re-import stored hand-built bundles.

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
arp climate waci --group-by portfolio_id
arp decision derive --source transition_plan_run --run-id <run_id> --save   # no API key: zero LLM calls
arp decision score --source transition_barrier --region "European Union"  # entity = sector, not company
arp decision score --dataset <dataset_id> --framework <fw_id>
arp report run --title "Electrification Review" --notes notes.txt --format pptx --out review.pptx
arp report plan --title "Q3 Review" --notes notes.txt --format house_deck --out storyline.json   # drafts headlines, no slides yet
arp report approve <report_id>      # builds output.pdf + output.pptx and findings; later: arp report rerun <report_id>
arp discover run --universe companies.csv
arp xbrl fetch --universe companies.csv     # market auto (default): SEC companyfacts or ESEF per company, files only; also: arp xbrl screen (routing preview) | arp xbrl taxonomy update | tags | select | files | verify
arp golden-set run                # regression-test before a prompt/model change
arp runs list                     # also: arp runs show <run_id>, arp runs cancel <run_id>

# Index construction (see docs/EQUITY_INDEX_CONSTRUCTION_PLAN.md)
arp index presets                                        # the named methodology shapes
arp index preview --preset eu_pab --review-date 2026-03-31 --show trace
ARP_CLI_TOKEN=<your token> arp index calibration-save --name "DWS Electrification PAB" \
    --effective-from 2026-01-01 --preset eu_pab --approved-by "IC-2026-01-14"   # --approved-by is kept as a note
ARP_CLI_TOKEN=<a second approver's token> arp index approve <cal_id>         # four-eyes: not the author
ARP_CLI_TOKEN=<your token> arp index run --index-id dws_pab --review-date 2026-03-31 --calibration-id <cal_id>
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
| [`INDEX_CONSTRUCTION.md`](docs/INDEX_CONSTRUCTION.md) | How the index engine builds a review, stage by stage, with a verified UI walkthrough |
| [`TRANSITION_BARRIER_ASSESSMENT.md`](docs/TRANSITION_BARRIER_ASSESSMENT.md) | The 35 criteria and their source lists |
| [`EMERGING_THEMES_VOCABULARY.md`](docs/EMERGING_THEMES_VOCABULARY.md) | How each scored dimension maps to the research vocabulary |
| [`THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md`](docs/THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md), [`DATABASE_STORAGE_REVIEW.md`](docs/DATABASE_STORAGE_REVIEW.md), [`SPEC_GAP_ANALYSIS.md`](docs/SPEC_GAP_ANALYSIS.md) | Architecture reviews and gap analyses |
