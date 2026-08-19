# Agentic Research Pipeline — Technical Reference

A comprehensive inventory of every functional module, the AI/agent stack, and every backend and frontend package this application depends on — as of the current state of `kutschersteffen-cmd/Agentic-Research-Pipeline`.

## 1. What this is

Two coupled tools for investment research at scale (designed for up to ~4,000 companies per run, currently tuned toward a ~400-company scale for the document-parsing pipeline):

1. A **Thematic Universe Builder** that turns a macro theme into a defensible, cited list of matched companies.
2. A **Data-Point Extraction Engine** that pulls schema-defined figures out of company disclosures with independent verification and programmatic citation grounding.

Around that core sit five more modules — Company Financials extraction, agentic Identity Resolution, Document Discovery, Engagement & Voting (stewardship), and Portfolio Risk & Climate Analytics — sharing one file-based storage convention and one LLM client interface.

**Storage philosophy:** everything is files — JSON/JSONL under `runs/`, `portfolios/`, `engagements/`, `ballots/`, `taxonomies/`, `data/documents/`. No database. The one deliberate exception is `DocumentContentStore`, a SQLite cache for parsed document text, added specifically to avoid re-parsing the same PDF on every run.

**Precision-first design:** every LLM call that produces a citation is checked programmatically against the source document text (never trusted on the model's say-so), every extraction has an independent verifier pass, and anything below a confidence threshold is queued for mandatory human review rather than silently included.

---

## 2. System architecture

```
backend/   Python — FastAPI (HTTP API) + Typer (CLI) — every agent pipeline lives here
frontend/  React + TypeScript (Vite) — authoring, monitoring, and review UI
data/documents/   local document store: manual uploads + discovery-crawler downloads
runs/             file-based run state — manifest, results, errors, review queue
engagements/      per-company engagement record store (state + append-only audit log)
ballots/          voting-instruction files, one per cast vote
portfolios/       holdings snapshots, security/company registries, climate observations
taxonomies/       versioned, ratifiable theme definitions
```

The backend and frontend are fully decoupled: the CLI and the API call the exact same pipeline functions, so nothing is UI-exclusive or CLI-exclusive. The frontend talks to the backend over a single `VITE_API_BASE`-configured HTTP boundary — no server-rendering, no shared process.

### Backend module map (`backend/arp/`)

| Package | Responsibility |
|---|---|
| `api/` | FastAPI app (`main.py`), one router per domain under `routers/`, plus two shared cross-router helpers: `run_scheduling.py` (`schedule_llm_run` — resolves the LLM client *before* creating a run manifest, closing off the "orphaned running manifest" bug class structurally) and `review_endpoints.py` (shared review-queue CRUD used by five different run types). |
| `cli.py` | Typer entry point (`arp ...`) — the intended path for large unattended batch runs; drives the identical pipeline functions the API does. |
| `config.py` | `pydantic-settings`-based `Settings`, all overridable via `ARP_`-prefixed env vars / `.env`. |
| `grounding.py` | Programmatic citation-grounding check — re-verifies every LLM-claimed quote against the actual fetched document text and resolves its real page/location; independent of, and never trusts, any of the three agent-orchestration libraries below. |
| `net_safety.py` | SSRF-hardening helpers shared by the discovery crawler and source inspector (blocks internal/link-local targets before any outbound fetch). |
| `universe.py` | Company-universe CSV/JSON loading shared across every pipeline entry point. |
| `discovery/` | Document discovery crawler (site finder, robots.txt-respecting same-domain crawl, change detection, scheduler) **and** the agentic company-identity-resolution pipeline (`identity_agents.py`, `identity_graph.py`, `identity_pipeline.py`). |
| `engagement/` | Stewardship: issue tracking, controversy-trigger scanning, dossier drafting, reporting agents. |
| `extraction/` | Three parallel extraction pipelines (general data-point, company financials, and their respective segment/spend sub-extractors), each as an extractor-agent + independent-verifier-agent pair wired through a LangGraph state graph, plus per-field aggregation. |
| `ingestion/` | `DocumentSource` implementations — SEC EDGAR (`edgar.py`) and local files (`local_files.py`) — plus chunking (`parsing.py`, `chunk_spans.py`) and a source registry. |
| `llm/` | The single `LLMClient` interface (`base.py`) every agent calls through; `langchain_client.py` is the concrete LangChain/Anthropic implementation with a disk-backed response cache (`cache.py`) and a client factory (`factory.py`). |
| `orchestration/` | Cross-pipeline batch execution: `batch_runner.py` (per-company fan-out, checkpointing, resumability), `job_manager.py` (run manifests/lifecycle), `review_queue.py` (queue/decide/history for any flagged item), `cost_tracker.py`. |
| `portfolio/` | Deterministic (zero-LLM) holdings aggregation and analytics engine, the NL Q&A agent (LLM drafts the query, the engine computes the number), climate metrics (WACI, financed emissions, coverage), news classification, and mock connector implementations standing in for a real custodian/ESG-vendor feed. |
| `research/` | The Advocate/Opposing/Adjudicator thematic-matching debate (`match_graph.py`, `matcher_agents.py`), the taxonomy library's five creation methods, standards crosswalks (NACE/NAICS/SIC/GICS), the opt-in indirect (input-output/Leontief) exposure tier, and the opt-in revenue/CapEx exposure cascade. |
| `retrieval/` | BM25 evidence selection (default) plus an opt-in hybrid semantic layer (`embeddings.py`, fastembed-backed) and its on-disk index cache. |
| `schemas/` | Every Pydantic model in the system — one module per domain, all LLM structured-output shapes included. |
| `storage/` | File-backed stores for runs, portfolios, engagements, taxonomies, plus `DocumentContentStore` (the one SQLite exception, itself split into three focused collaborators — parsed-content cache, document registry, chunk-embeddings cache — behind a thin facade) and `KeyedLock` (per-key reentrant locking against read-modify-write races between concurrent request handlers and background batch threads). |
| `voting/` | Proxy-ballot pipeline: proposal extraction from proxy statements, policy-rule + LLM-judgment vote recommendations, human review, ballot casting. |

### Frontend structure (`frontend/src/`)

| Path | Contents |
|---|---|
| `pages/` | One page per top-level function: `ThemeBuilder`, `TaxonomyLibrary`, `ExtractionBuilder`, `CompanyFinancials`, `IdentityResolution`, `DocumentDiscovery`, `PortfolioRisk`, `ClimateAnalytics`, `ReviewQueue`, `RunHistory`, `EngagementDashboard`, `VotingRuns`, `MonitoringDashboard`. |
| `components/` | Shared building blocks: `BarChart`/`LineChart` (hand-rolled SVG, no charting library), `PivotTable`, `TrendTable`, `AggregationResultTable`, `RunProgress`, `ReviewControls`, `ConfidenceBadge`, `UniversePicker`, `PortfolioFilterPicker`, `InspectorModal`, `SourceDiscoveryPanel`, `EngagementIssuePanel`, `BallotReview`, `ResultView`, `ActivityEditorTable`. |
| `api/client.ts` | The single HTTP client every page calls through. |
| `lib/palette.ts` | The chart color system — fixed-order categorical slots and a sequential blue ramp, validated against the app's light chart surface. |
| `index.css` | The entire app's theming: one CSS custom-property token set (light theme, single fixed mode — no dark/light toggle). |

---

## 3. Functional modules

### 3.1 Thematic Universe Builder
Turns a macro theme ("electrification", "AI") into a defensible company list. An LLM first decomposes the theme into concrete business activities, then every company in the supplied universe is run through an **Advocate → Opposing → Adjudicator** three-agent debate (`research/match_graph.py`, a LangGraph state graph) per activity, producing a verdict, confidence, exposure estimate, and a cited rationale. Results are filterable/sortable in the UI (verdict, activity, flagged-only, confidence/exposure) and a filtered result set feeds the Extraction Engine as a new universe with one click. Runs are checkpointed and resumable (`arp theme resume`).

### 3.2 Taxonomy Library
A versioned, ratifiable alternative to a one-off theme file. Five creation methods: `industry_anchored`, `authority_source` (grounded extraction from a cited authority document), `empirical` (mined from an actual company universe), `news_transcript_mining`, and `etf_index_holdings` (derived from a fund's holdings export). Supports diffing (`compare`) and drafting a merge (`merge`) of two taxonomies, and cross-referencing every activity into NACE/NAICS/SIC/GICS standards codes — NACE/NAICS/SIC via deterministic ISIC correspondence tables, GICS via LLM classification against a fixed reference list with a required rationale (no public ISIC↔GICS crosswalk exists).

### 3.3 Data-Point Extraction Engine
Pulls specific, schema-defined data points (e.g. "green capex", forward-looking business outlook) from sustainability reports, annual reports, and earnings-call transcripts. Each field goes through an **extractor agent** and an **independent verifier agent** (`extraction/field_graph.py`), and every citation the extractor claims is checked programmatically against the real source text by `grounding.py` — never trusted on the LLM's self-report. A grounded citation resolves to an exact PDF page number or xlsx sheet name and opens a "view source" link straight to that location. Every field can be marked reviewed, overridden, or rejected, with an append-only per-field audit trail.

### 3.4 Company Financials Extraction
Pulls disclosed business segments (name, description, revenue, operating income, assets), total CapEx, and total R&D — each spend figure with a grounded description of what it funds and any disclosed category breakdown (e.g. maintenance vs. growth capex) — in a single combined pass per company (one document fetch, one evidence-gathering step, one extractor+verifier LLM call pair instead of three separate ones). A segment/figure not explicitly disclosed is left null, never estimated.

### 3.5 Company Identity Resolution *(agentic, added this session)*
Resolves a list of bare company names to a real, verified website/CIK before any document-discovery run. A deterministic SEC EDGAR name lookup (exact → substring → fuzzy tiers) resolves the common case with **zero LLM calls**; only genuine ambiguity (no match, multiple matches, or a non-exact single match) escalates to one `adjudicate_identity` LLM call (`discovery/identity_graph.py`, a LangGraph state graph: `check_known → gather_signals → [finalize_clean_match | adjudicate] → finalize`). The LLM's self-reported website/CIK is itself re-verified against real signals in code and force-downgraded to `UNCERTAIN` if unbacked. Nothing ambiguous is ever silently guessed — it lands in the Review Queue.

### 3.6 Document Discovery
Resolves each company's investor-relations site (from a supplied URL or a best-effort web-search fallback), does a bounded, same-domain, robots.txt-respecting crawl for annual reports / sustainability reports / proxy statements / investor presentations / transcripts, and downloads matches — runs manually or on an APScheduler-driven interval, raising a webhook event when something new appears. A reachable-but-unmatched company and an unreachable one are reported distinctly.

### 3.7 Indirect Exposure Tier *(opt-in)*
Scores a company's *structural* supply-chain exposure to a theme via input–output propagation (Leontief inverse over an OECD ICIO extract), catching companies whose disclosures are silent about a theme but whose economic position says otherwise. Purely quantitative — zero LLM calls in the computation itself.

### 3.8 Revenue/CapEx Exposure Cascade *(opt-in)*
A structured revenue/CapEx data catalogue resolves exposure with zero LLM judgment where possible, falls back to grounded extraction from disclosures, and only then falls back to the qualitative Advocate/Opposing/Adjudicator debate — a hard disclosed number is never second-guessed by a categorical LLM judgment over the same question.

### 3.9 Engagement & Voting (stewardship module)
- **Engagement**: per-company issue tracking with milestone progression, an escalation ladder, correspondence, and commitments, plus controversy-trigger scanning and LLM-drafted engagement dossiers (`engagement/`). Every send/decide checkpoint is a human action.
- **Voting**: proposal extraction from proxy statements, policy-rule + LLM-judgment vote recommendations (`voting/policy_agent.py`, `proposal_agent.py`, `ballot_graph.py`), mandatory human review of every ballot item, then casting.

Both share one file-based engagement record store (current state + append-only event log) and are backend/CLI/API-complete; voting has a frontend page, engagement's UI is the dashboard page plus a shared issue panel component.

### 3.10 Portfolio Risk & Exposure Monitoring
Aggregates holdings across every portfolio via a deterministic (zero-LLM) engine, groupable by portfolio, asset class, issuer, sector, or country. Includes an Analytics Builder and a natural-language Q&A agent ("how many EUR million of exposure to BMW") where the LLM only drafts the structured query — the engine computes the actual number. An Entity Resolution layer maps free-text security/issuer references to the internal company registry, surfacing anything below a confidence threshold in a dedicated review queue.

### 3.11 Climate Analytics
A sub-module of Portfolio Risk: weighted-average carbon intensity (WACI), PCAF-style financed emissions, and data-coverage reporting, sourced from a mock internal ESG API and cross-validated against the Extraction Engine's independent read of the same companies' disclosures — a mismatch between the two sources is surfaced, not silently resolved.

### 3.12 Cross-cutting: orchestration, review, monitoring
Every run type (`theme`, `extraction`, `financials`, `voting`, `identity`, `discovery`) shares one checkpointed/resumable batch-runner: results append to `runs/<run_id>/results.jsonl` per company as they complete, so an interrupted batch resumes without redoing finished work. Any running/pending run can be cooperatively cancelled and (for theme runs) resumed. The **Review Queue** is the single human checkpoint for anything flagged, ungrounded, or low-confidence across all five review-producing run types. The **Monitoring Dashboard** gives a live cross-pipeline view (currently executing, recently finished, open engagement issues, SLA breaches, ballot items awaiting decision), polling every 3 seconds while open.

---

## 4. The agent / AI stack

| Layer | Library | Role |
|---|---|---|
| LLM client | **LangChain** (`langchain-anthropic`) | Every agent call in the codebase goes through one interface, `LLMClient.complete_structured()` (`llm/base.py`) — schema-forced structured output via tool calling, a bounded self-correction retry loop on validation failure, and a disk-backed response cache. Fully provider-agnostic from every pipeline's point of view. |
| Multi-step agent control flow | **LangGraph** | Models each pipeline's per-company (or per-field/per-activity) multi-step flow as an explicit state graph with conditional/short-circuit edges: the Advocate/Opposing/Adjudicator debate, the extractor/verifier pairs (general + financials), the identity-resolution graph, and proposal extraction + policy application for voting. Company-level batch fan-out and resumability stay outside the graphs, in the file-based `run_batch`/`RunStore` layer. |
| Document chunking & retrieval | **LlamaIndex** | `SentenceSplitter` backs chunking (`ingestion/parsing.py`); a BM25 retriever backs evidence selection (`retrieval/select_evidence.py`) — deterministic and embedding-free by default, consistent with a zero-LLM-cost-in-retrieval design. |
| Hybrid semantic retrieval | **fastembed** *(opt-in)* | A 384-dim ONNX embedding model (`BAAI/bge-small-en-v1.5`, ~50MB) layered on top of BM25 when enabled — chosen specifically over the torch-based `llama-index-embeddings-huggingface` (~2GB) to keep the default retrieval path free, offline, and deterministic. |
| PDF parsing | **Docling** *(replaced pymupdf4llm this session)* | Layout-model + TableFormer-based PDF-to-markdown conversion, giving materially better table/reading-order extraction than a plain text-layer read — at the cost of a genuine ML pipeline running per page (needs a one-time model download from Hugging Face Hub on first use). Amortized across runs by the content-addressed `DocumentContentStore` cache, so it's a one-time cost per unique file, not per run. |
| Citation grounding | **None (pure Python)** | `grounding.py` is deliberately independent of all of the above: it re-verifies every citation against the original fetched document text and resolves its real location, never trusting an LLM's self-reported source. |

---

## 5. Backend Python packages (`backend/pyproject.toml`)

| Package | Constraint | Purpose |
|---|---|---|
| `anthropic` | `>=0.40.0` | Underlying Claude API client (used beneath LangChain's Anthropic integration). |
| `langchain-core` | `>=0.3` | Core LangChain abstractions the app's `LLMClient` interface is built on. |
| `langchain-anthropic` | `>=0.3` | LangChain's Claude chat-model integration — the concrete LLM client implementation. |
| `langgraph` | `>=0.2` | State-graph orchestration for every multi-step agent pipeline. |
| `llama-index-core` | `>=0.12` | Document chunking (`SentenceSplitter`). |
| `llama-index-retrievers-bm25` | `>=0.5` | BM25-ranked evidence retrieval. |
| `pydantic` | `>=2.7` | Every schema in the system — LLM structured-output shapes, API request/response models, file-backed record shapes. |
| `pydantic-settings` | `>=2.3` | `ARP_`-prefixed environment/`.env`-driven configuration. |
| `fastapi` | `>=0.111` | The HTTP API. |
| `uvicorn[standard]` | `>=0.30` | ASGI server for the API. |
| `typer` | `>=0.12` | The `arp` CLI. |
| `httpx` | `>=0.27` | Outbound HTTP for EDGAR, the discovery crawler, and the LangChain client's transport. |
| `beautifulsoup4` | `>=4.12` | HTML parsing fallback (alongside trafilatura) and crawler link extraction. |
| `lxml` | `>=5.2` | Fast HTML/XML parser backing BeautifulSoup. |
| `pypdf` | `>=4.2` | PDF metadata/encryption handling (e.g. building/reading encrypted-PDF test fixtures) and a taxonomy-source PDF fetch path. |
| `docling` | `>=2.0` | Primary PDF-to-markdown parser (layout model + TableFormer) — see §4. |
| `cryptography` | `>=42.0` | AES backend pypdf uses to open owner-password-encrypted PDFs. |
| `trafilatura` | `>=1.9` | Primary HTML content extraction (EDGAR filings, discovered web pages). |
| `tenacity` | `>=8.3` | Retry/backoff logic in the LangChain client. |
| `APScheduler` | `>=3.10` | Interval-based scheduling for the document-discovery crawler. |
| `python-multipart` | `>=0.0.9` | FastAPI file-upload form parsing (manual document/universe uploads). |
| `python-dotenv` | `>=1.0` | Loads `.env` into `pydantic-settings`. |
| `numpy` | `>=1.26` | Numeric backbone for the portfolio aggregation engine and embedding matrices. |
| `openpyxl` | `>=3.1` | `.xlsx`/`.xlsm` parsing (disclosure tables, ETF holdings exports) and the local-file source's Excel reader. |
| `fastembed` | `>=0.3` | ONNX embedding model for opt-in hybrid semantic retrieval — see §4. |

**Dev-only** (`pip install -e ".[dev]"`): `pytest>=8.2`, `pytest-asyncio>=0.23`.

---

## 6. Frontend packages (`frontend/package.json`)

| Package | Version | Purpose |
|---|---|---|
| `react` | `^19.2.8` | UI framework. |
| `react-dom` | `^19.2.8` | DOM renderer for React. |
| `typescript` | `~6.0.2` | Static typing across the whole frontend. |
| `vite` | `^8.2.0` | Dev server + production bundler. |
| `@vitejs/plugin-react` | `^6.0.4` | React fast-refresh/JSX support for Vite. |
| `oxlint` | `^1.75.0` | Linting (`npm run lint`). |
| `@types/react`, `@types/react-dom`, `@types/node` | latest | Type definitions for React and the Node-based build tooling. |

Notably **no charting library, no CSS framework, no state-management library, no router beyond a hand-rolled tab switch**: `BarChart`/`LineChart` are hand-rolled inline SVG (see `dataviz` design conventions in `lib/palette.ts`), and `index.css` is a single hand-written token system — a deliberately minimal dependency surface for a UI whose real complexity lives in the data it displays, not in its own framework stack.

---

## 7. Data & storage layout

```
data/documents/<company_id>/<doc_type>/*     manual uploads + discovery-crawler downloads
runs/<run_id>/manifest.json                  run metadata: type, status, cost, progress
runs/<run_id>/results.jsonl                  per-company results, appended as they complete
runs/<run_id>/errors.jsonl                   per-company failures, isolated from the batch
runs/<run_id>/review_queue.jsonl             flagged/ungrounded/low-confidence items
portfolios/<portfolio_id>/...                holdings snapshots, security/company registries
portfolios/climate/...                       climate data-point observations
engagements/<company_id>/record.json         current engagement state (milestones, escalation stage)
engagements/<company_id>/events.jsonl        append-only audit log, never overwritten
ballots/<run_id>/<item>.json                 one voting-instruction file per cast vote
taxonomies/<taxonomy_id>.json                versioned, ratifiable theme definitions
backend/.arp_cache/ (configurable)           SQLite DocumentContentStore — parsed-content
                                              cache, document registry, chunk-embeddings cache;
                                              the one non-file-based store in the system
```

Every write to a shared file-backed record that could race a concurrent batch thread (run manifests, engagement records) goes through `storage/locks.py`'s `KeyedLock` — a per-key reentrant lock, so unrelated runs/companies never block each other but the same key's read-modify-write cycle can't interleave.

---

## 8. CLI surface (`arp --help`)

The CLI drives the identical pipeline functions as the API and is the intended path for large unattended batches:

```
arp theme decompose | run | resume | classify-sectors
arp taxonomy discover-sources | create | list | ratify | compare | merge | map-standards | export-standards
arp universe from-holdings | overlap
arp revenue-catalogue suggest-mapping
arp extract draft-schema | run | financials-run
arp identity resolve
arp discover run | schedule
arp engagement issue-open | trigger-scan | dossier-draft | issue-escalate | record-show | report
arp voting run | ballots | review | cast
arp portfolio seed-demo | list | review-queue | aggregate | ask | classify-news
arp climate waci | financed-emissions | coverage
arp runs list | show | cancel
```

Full flag-level detail is in the project [`README.md`](../README.md); design rationale for every precision control is in [`METHODOLOGY.md`](METHODOLOGY.md).
