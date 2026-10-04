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
| `cli/` | Typer entry point (`arp ...`) — the intended path for large unattended batch runs; drives the identical pipeline functions the API does. One module per domain (mirroring `api/routers/`), each defining its own Typer sub-app; `__init__.py` wires them onto the top-level `app` (the `arp` console-script target). `_shared.py` holds the handful of store/registry constructor helpers used across more than one domain. |
| `config.py` | `pydantic-settings`-based `Settings`, all overridable via `ARP_`-prefixed env vars / `.env`. |
| `grounding.py` | Programmatic citation-grounding check — re-verifies every LLM-claimed quote against the actual fetched document text and resolves its real page/location; independent of, and never trusts, any of the three agent-orchestration libraries below. |
| `net_safety.py` | SSRF-hardening helpers shared by the discovery crawler and source inspector (blocks internal/link-local targets before any outbound fetch). |
| `universe.py` | Company-universe CSV/JSON loading shared across every pipeline entry point. |
| `agents/` | Standing (schedule-driven) agents that propose rather than apply: the Taxonomy Researcher (`taxonomy_researcher.py`, surfaces candidate activity/source updates for a human to accept) and the Calibration Agent (`calibration_agent.py`, re-checks confidence calibration against reviewed outcomes). |
| `discovery/` | Document discovery crawler (site finder, robots.txt-respecting same-domain crawl, change detection, scheduler) **and** the agentic company-identity-resolution pipeline (`identity_agents.py`, `identity_graph.py`, `identity_pipeline.py`). |
| `emerging_themes/` | The Emerging Themes Scanner: mention ingestion (`ingestion/` — EDGAR full-text search, GDELT, regulatory RSS), evidence tagging (`extraction.py`), clustering (`clustering.py`), cross-period lineage (`lineage.py`), discovery/materiality/contradiction scoring (`scoring.py`), XBRL action corroboration (`action_evidence.py`), the company role + exposure engine (`company_role.py`, `company_exposure.py`), candidate synthesis (`synthesis.py`) and the weekly scheduler. |
| `engagement/` | Stewardship: issue tracking, controversy-trigger scanning, dossier drafting, reporting agents. |
| `extraction/` | Three parallel extraction pipelines (general data-point, company financials, and their respective segment/spend sub-extractors), each as an extractor-agent + independent-verifier-agent pair wired through a LangGraph state graph, plus per-field aggregation. |
| `golden_set/` | Bundled regression sets run against the real pipelines before a prompt/model change ships: extraction (`runner.py`), the Superset chart planner (`arp golden-set bi`), and emerging-themes company-role classification (`role_runner.py`). |
| `ingestion/` | `DocumentSource` implementations — SEC EDGAR (`edgar.py`) and local files (`local_files.py`) — plus chunking (`parsing.py`, `chunk_spans.py`) and a source registry. |
| `llm/` | The single `LLMClient` interface (`base.py`) every agent calls through; `langchain_client.py` is the concrete LangChain/Anthropic implementation with a disk-backed response cache (`cache.py`) and a client factory (`factory.py`). |
| `orchestration/` | Cross-pipeline batch execution: `batch_runner.py` (per-company fan-out, checkpointing, resumability), `job_manager.py` (run manifests/lifecycle), `review_queue.py` (queue, decision rows and the item state machine), `cost_tracker.py`. |
| `portfolio/` | Deterministic (zero-LLM) holdings aggregation and analytics engine, the NL Q&A agent (LLM drafts the query, the engine computes the number), climate metrics (WACI, financed emissions, coverage), news classification, and mock connector implementations standing in for a real custodian/ESG-vendor feed. |
| `replication/` | Investment Strategy Replication: paper discovery, spec extraction, the deterministic (zero-LLM) backtest engine and rebalance calendar, pluggable price/characteristics data sources, composite and text-sentiment signals, and the statistical-rigor layer (deflated Sharpe, purged/embargoed CSCV for PBO, regime stratification). |
| `reporting/` | Presentation & Reporting Tool: the one LLM call that drafts a `ReportPlan` (`content_planner.py`), then deterministic renderers for pptx/docx/pdf (`deck_builder.py`, `report_builder.py`, `pdf_builder.py`), native + matplotlib chart building, and `.pptx` template style extraction (`style_profile.py`, python-pptx, never LLM-guessed). |
| `research/` | The Advocate/Opposing/Adjudicator thematic-matching debate (`match_graph.py`, `matcher_agents.py`), the taxonomy library's five creation methods, standards crosswalks (NACE/NAICS/SIC/GICS), the opt-in indirect (input-output/Leontief) exposure tier, and the opt-in revenue/CapEx exposure cascade. |
| `retrieval/` | BM25 evidence selection (default) plus an opt-in hybrid semantic layer (`embeddings.py`, fastembed-backed) and its on-disk index cache. |
| `review/` | The review workbench (§3.18): `items.py` (every item of a run, with its kind and state), `context.py` (the decision-ready bundle and the stored snapshots), `decide.py` (constrained decisions, citation grounding, second-reviewer rules). `api/routers/review.py` is its one router, `/api/review/...`. |
| `schemas/` | Every Pydantic model in the system — one module per domain, all LLM structured-output shapes included. |
| `storage/` | File-backed stores for runs, portfolios, engagements, taxonomies, plus `DocumentContentStore` (the one SQLite exception, itself split into three focused collaborators — parsed-content cache, document registry, chunk-embeddings cache — behind a thin facade) and `KeyedLock` (per-key reentrant locking against read-modify-write races between concurrent request handlers and background batch threads). |
| `transition_barrier/` | Transition Barrier Assessment: the bundled 105-cell sector x region feasibility matrix (`data/*.json` + `dataset.py` loaders), staleness tracking independent of confidence (`staleness.py`), and the EUR-Lex source-refresh slice (`refresh/`) whose reconciler may propose an H/M/L change but never apply one. |
| `transition_plan/` | Transition Plan Assessment: the paper's 64 fixed indicators (`indicators.py`), the per-indicator RAG agent + independent verifier wired through `indicator_graph.py`, and per-company walk/talk aggregation. |
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

**Planning, checks and routing (E62–E68, no model calls).** Before extracting, the pipeline plans per company (`planning/`): *entity confirmation* marks each document `confirmed`, `ambiguous` or `mismatch` against the company's identifiers, and mismatched documents are held out (listed as `held_documents`; if every document is held, every field routes `hold` with `entity_mismatch`); *applicability* rules (sector codes, countries, regimes) skip a field that cannot apply, with route reason `not_applicable_by_rule`; a *period plan* per document fixes which fiscal periods to extract; *document routing* sends each field to its preferred document types and sections. A field whose input hash (field version, document content keys, planned periods and the effective models, thresholds, retrieval mode and XBRL setting) matches the last run's reuses that run's rows with no model call — unless those rows failed a check, a reviewer rejected one, or the run is a "Restart from here" (cache refresh). A rejected value is re-extracted, and if the answer is the same value it fails the `prior.rejected` check and routes to review, until a reviewer approves or corrects that item in a later run. After extraction, layered checks run on every value (`checks/`: 1 format, 2 numeric, 3 plausibility, 4 cross-source incl. prior period, 5 model), each `pass`, `fail` or `not_applicable` at severity `info`, `warn` or `block`; a failed `warn`/`block` check adds `check_failed`. Checks only add failures and never relax grounding. Then each row routes three ways (`extraction/routing.py`): `hold`, `review`, or `auto_accept` — the last only when the field version is released, its first audit is recorded (`POST /api/extraction/fields/{id}/versions/{v}/first-audit`), every check passes, confidence clears `auto_accept_min`, the value is grounded, and the run is not a trial (a trial sends every non-held row to review with `unreleased_version`). The route is the system's decision and lives only as `route`/`route_reasons` on the result row; `review_decisions.jsonl` stays human-only. In `company_facts` an undecided auto-accepted value shows as `auto_accepted` (no reviewer) and a held one as `held`.

**Review of extracted values (step 4).** A routed `review` row opens in the workbench (§3.18) as a decision-ready *context bundle* (`review/context.py`): the value, its source text with the cited span highlighted, failed checks in plain words, the route reasons, any conflict alternatives, the prior period, what is already published, the confidence components, the item's decisions so far, and an `etag`. Spans come from the stored parsed text of the cited document, never from a re-fetch. The `ReasonCode` values the aggregator attaches are `not_grounded`, `verifier_disagrees`, `conflict`, `low_confidence` and `check_failed`; routing (`extraction/routing.py`) also queues for `unreleased_version`, `first_audit_pending`, `below_auto_accept_min`, `high_risk_not_found`, `not_applicable_by_rule` (on trial runs) and `check:<check_id>`. (`match_ambiguous` is an identity reason.) A decision is one of four strings, each with a reason code from a fixed list:
- `approve` takes reason `confirmed` and no other decision may use it; `correct`, `reject` and `escalate` take one of `wrong_value`, `wrong_unit_or_scale`, `wrong_period`, `wrong_entity`, `not_disclosed`, `bad_source`, `needs_expert`, `other`.
- `correct` carries a `corrected_value` limited to the kind's keys (a value: `value`, `unit`, `period_end`) and, for a value, a *correction citation*. The server grounds that citation against the item's stored source text with `grounding.py` and the configured fuzzy threshold, discarding any offsets the client sent. A correction is refused unless the citation grounds in one of the item's own documents; for a numeric field the corrected number must also appear in the cited text.
- The request carries the bundle's `context_etag`. If the item changed since it was loaded, the decision is refused with 409, and the decision runs under the run lock.

*Second-reviewer rules.* A first decision sets `second_required` with the reasons that hit (`escalate` never does): `correction` (any `correct`), `high_risk` (the field is `high_risk`), `published_change` (a restatement candidate, or the decision changes the last decided value of an earlier run, or overturns this item's own final outcome), `first_audit_pending` (the field version has no recorded first audit; not applied to kinds without a field or runs without a schema snapshot) and `sample` (an `approve` chosen by `sha256(item_key)` against `second_review_sample_rate`, default 0.1, so the same item key is always or never in the sample). The second review must be a different person and agrees only with the same decision (and, for `correct`, the same value). A disagreement is resolved by an approver who took part in neither review.

*Snapshots.* Every decision first writes the exact bundle the reviewer saw to `runs/<id>/snapshots/<snapshot_id>.json` and stores the `snapshot_id` on its decision row; `GET /api/review/runs/{id}/snapshots/{snapshot_id}` returns those bytes unchanged.

**Pipeline view (Extraction screen).** Every profile (custom schema, Financials, TNFD, Transition Plan) starts from `POST /api/extraction/start`, on an uploaded list or a single company. The screen draws the profile's steps as a node diagram, read from the compiled per-item LangGraph (`extraction/steps.py::pipeline_shape`) so it cannot drift from what runs, followed by the company record and the rules step.
- *Steps before extraction* (`extraction/pre_steps.py`), each switched on per run and off by default: **Identity** (website and SEC CIK via the identity resolver; a rule match — exact LEI, identifier map, supplied identifier or a single exact EDGAR name match — is used even when it is flagged for identity review, and an adjudicated match only when resolved at or above `identity_resolution_confidence_threshold`; entity confirmation still checks every fetched document), **Content search** (homepage, then a crawl for report links), **Document management** (download what was found into the company's folder, record new and changed documents, count documents and bytes), **Parse & index** (parse and chunk every document once, so each item's evidence step reads the cached text). They run per company ahead of the per-item graph and reuse the Identity Resolution and Document Discovery code. A step fails when it raises or produces nothing the next step can use: an unclear identity, no homepage or report links, no documents, nothing parsed. The company then stops at that step, with no extraction, and an error report goes to the run's review queue (`PreStepFailed`, a `batch_runner.ReviewRequired`). The report names the step and the error, and includes what the earlier steps found. The company shows as "review", not "failed"; once the cause is fixed, restart it from that step. Each step reports what it found to the step view.
- *Before a run*, clicking a step edits its settings for that run only (`StepSettings`: hybrid search, XBRL facts, extractor and verifier models, quote-match and review thresholds). The run stores what it used in `step_settings.json`.
- *During and after a run*, each step shows items, share, and time per item, for the whole run or one company. `orchestration/step_tally.py` counts node visits as items stream through their graphs; the counts are live in memory and saved to `step_counts.json` when the run finishes.
- *Stop and restart.* Stop is the run's soft cancel: companies in flight finish, and no new ones start. "Restart from here" (`POST /api/extraction/runs/{id}/restart`) starts a new run with the same inputs, for every company or only the selected one. Steps before the chosen one replay from the document and LLM caches; the chosen step and every later one run afresh (`restart_overrides`: document cache off from Find evidence, LLM cache refresh from Extract/Answer, verifier-only refresh from Verify). A refresh skips reading the cache but still writes to it. Restarting from the rules step rescores the same run instead.

### 3.4 Company Financials Extraction
Pulls disclosed business segments (name, description, revenue, operating income, assets), total CapEx, and total R&D — each spend figure with a grounded description of what it funds and any disclosed category breakdown (e.g. maintenance vs. growth capex) — in a single combined pass per company (one document fetch, one evidence-gathering step, one extractor+verifier LLM call pair instead of three separate ones). A segment/figure not explicitly disclosed is left null, never estimated.

### 3.5 Company Identity Resolution *(agentic, added this session)*
Resolves a list of bare company names to a real, verified website/CIK before any document-discovery run. Match rules run first with **zero LLM calls** (`discovery/match_rules.py`): a supplied website/CIK, an exact LEI, or an entry in the identifier map resolves the company (`match_rule` `supplied`, `exact_lei`, `identifier_map`). A single exact SEC EDGAR title match is `name_only`: it fills the CIK but is always flagged for review. Only genuine ambiguity (no match, multiple matches, or a non-exact single match) escalates to one `adjudicate_identity` LLM call (`discovery/identity_graph.py`, a LangGraph state graph), whose result (`ambiguous`) is always flagged too. The LLM's self-reported website/CIK is itself re-verified against real signals in code and force-downgraded to `UNCERTAIN` if unbacked. Nothing ambiguous is ever silently guessed — it lands in the Review Queue.

Identity items review through the workbench like any other kind (§3.18): `approve`, `correct` (a `corrected_value` of `resolved_website` and/or `resolved_cik`, with a comment naming the source, since there is no source text to cite), `reject` or `escalate`. The run-level review routes for identity are gone; `arp identity review` (§8) uses the same decision rules.

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

### 3.12 Transition Plan Assessment
A direct replication of Colesanti Senni, Schimanski, Bingler, Ni & Leippold (2024): scores a company's climate disclosures against the paper's 64 fixed indicators (Target/Governance/Strategy/Tracking), each classified "talk" (future target) or "walk" (concrete, verifiable activity), one grounded RAG verdict (YES/NO/NA) per indicator. Unlike the paper's tool, every citation is independently re-verified against the source document by the same programmatic grounding check used everywhere else here, rather than trusted from the model's self-report.

### 3.13 Transition Barrier Assessment
The sector-level counterpart to 3.12: where that asks whether a company is credible about transitioning, this asks whether transition is feasible in that sector and region at all. A curated 105-cell matrix — 35 criteria across 9 hard-to-abate sectors x Technology/Regulation/Demand & Economics, each rated H/M/L for the EU, US and China — with per-cell evidence, a confidence tier, a last-verified date and 86 verified sources behind it. Note H means transition is *more* feasible (fewer barriers). Staleness is tracked separately from confidence, since a high-confidence rating can simply be old. The refresh pipeline currently covers only the 15 EUR-Lex `legal_regulatory_text` sources (stable ELI/CELEX identifiers); `GET /api/transition-barrier/refresh/coverage` reports the other 71 as manual rather than silently skipping them. A refresh may propose a rating change but never applies one — candidates go to the run's review queue. See `docs/TRANSITION_BARRIER_ASSESSMENT.md` for the full criteria and source lists.

### 3.14 Presentation & Reporting Tool
Turns qualitative findings and uploaded CSV/XLSX datasets into a pptx/docx/pdf for a stated audience. Exactly one LLM call (the Content Planner) drafts a structured `ReportPlan`; everything after it is deterministic rendering, and the plan can be reviewed or hand-edited via `GET`/`PUT /api/reports/{id}/plan` before the final render. A `.pptx` template can be ingested first so the output reuses its layouts, theme colors and fonts, extracted deterministically via python-pptx.

**House decks.** With `output_format=house_deck` the tool builds a slide deck in the app's own design system (`reporting/style/tokens.json`, Geist and Hanken Grotesk embedded, rules in `DESIGN.md`) instead of a `ReportPlan`. `LayoutInstructions.theme` is `light` or `dark`.

1. **Storyline.** `create_and_plan` makes one LLM call for a draft storyline (a headline and a purpose per slide) and stops at `STORYLINE_READY`. `arp report plan` drafts it; people edit it in the UI or with `PUT /api/reports/{id}/storyline` (there is no CLI edit command).
2. **Approve.** `POST /api/reports/{id}/storyline/approve` or `arp report approve <id>` runs the build in `house_pipeline.py`: fill each slide (`slide_fill.py`, headlines are kept as approved), lint and rewrite (`lint.py`), fit to the layout (`fit.py`), render PNGs, one vision QA call (`visual_qa.py`), then write `output.pdf` and `output.pptx` (`house_pptx.py`).
3. **Findings.** Every stage's findings are saved in `findings.json` (`GET /api/reports/{id}/findings`); files download with `GET /api/reports/{id}/download?file=`.
4. **Re-run.** `rerun` (`arp report rerun <id>`, or `ReportScheduler` via `arp report schedule`) makes a new report from an approved storyline, reloads the datasets behind its `run_refs` (`adapters.py`) and sets `rerun_of`. If a number in an approved headline is no longer in the data it stops at `STORYLINE_READY` for a person to fix.
5. **No-LLM paths.** `render_from_plan` on a house deck re-renders its saved `deck.json` (approving a `FAILED` report that has one does the same). Separately, `deck_compat.deck_from_plan` turns a hand-built `ReportPlan` into a house `Deck`, which the stewardship client report (`stewardship/client_report.py`) renders with the house renderers.

Limits: 3 fit passes, 2 lint-rewrite rounds, 1 QA round, and QA looks at no more than 20 slides. Known gaps: the pptx names the fonts but does not embed them, so a machine without Geist falls back to its default; a decision ref points at an immutable published snapshot, so a re-run on a newer decision needs a new ref; there is no adapter for portfolio or climate analytics, which are computed on request and have no stored result. `tests/test_reporting_golden_briefs.py` runs one deck of each kind (free-form, pipeline, periodic, stewardship) through real Chromium.

### 3.15 Investment Strategy Replication
Reduces an academic outperformance paper to an executable `StrategySpec` through the same extractor/independent-verifier/grounding pipeline used elsewhere, then backtests it deterministically (zero LLM calls in the computation) in-sample against the paper's own reported numbers and out-of-sample over any later window. Carries a multiple-testing-aware significance hurdle, a Deflated/Probabilistic Sharpe Ratio, PBO via purged and embargoed CSCV, and a regime-stratified breakdown. Human gates: a drafted spec must be reviewed and approved (re-checked server-side) before a backtest can run.

### 3.16 Emerging Themes Scanner
The bottom-up counterpart to the Thematic Universe Builder. Ingests EDGAR full-text search, GDELT and regulatory RSS across a universe, tags each mention into grounded evidence, clusters the tags, and tracks cluster lineage across ISO weeks (birth/continuation/merge/split) so novelty is measured against the prior period. Clusters are scored on velocity, breadth, persistence, novelty, materiality and contradiction; the promotion gate is the **action score** — the share of evidence describing something a company *did*, optionally corroborated against real SEC XBRL capex/R&D movement — so mention counts alone cannot produce a candidate. A two-tier engine classifies each company's role in a candidate theme with a risk/momentum/evidence-quality triple, leaving the full Revenue/CapEx/Demand/Enablement cascade to Tool 1 once promoted. Promote, reject and disconfirm are all human decisions and all require a recorded written reason; contradiction evidence is retained and displayed even on promoted candidates. See [`EMERGING_THEMES_VOCABULARY.md`](EMERGING_THEMES_VOCABULARY.md).

### 3.17 Standing agents (propose, never auto-apply)
The **Taxonomy Researcher** and the **Calibration Agent** (`agents/`) run on a schedule and surface proposals — candidate taxonomy activity/source updates, and confidence-calibration drift against reviewed outcomes — for a human to accept or discard. Neither writes to the taxonomy library or to settings on its own.

### 3.18 Cross-cutting: orchestration, review, monitoring
Every run type (`theme`, `extraction`, `financials`, `voting`, `identity`, `discovery`) shares one checkpointed/resumable batch-runner: results append to `runs/<run_id>/results.jsonl` per company as they complete, so an interrupted batch resumes without redoing finished work. Any running/pending run can be cooperatively cancelled and (for theme runs) resumed. The **Review Queue** is the single human checkpoint for anything flagged, ungrounded, or low-confidence across all five review-producing run types; for extraction runs it holds the rows routed `review` (see §3.3), while `auto_accept` rows skip it and `hold` rows wait on their held documents. The **Dashboard** leads with what waits on a person (ballot items and flagged items awaiting a decision), then gives a live cross-pipeline view (escalations, SLA breaches, open engagement issues, currently executing and recently finished runs), polling every 3 seconds while open. Every review decision is recorded against the one "Reviewing as" name set in the sidebar, and each view has a URL (`#/voting/<run id>`, `#/review/<kind>/<run id>`) so refresh, Back and shared links land on the same place.

**Review workbench (step 4).** One router, `api/routers/review.py`, serves every item that waits on a person: `GET /api/review/items` (open items, optional `run_id`), `.../runs/{id}/items/{key}/context`, `.../source?doc_id=&page=`, `POST .../decision` and `GET .../runs/{id}/snapshots/{snapshot_id}`. It replaced the extraction and identity `runs/{id}/review-queue` and `runs/{id}/review` routes, which are removed; the other run types keep their own routes.
- *Kinds.* `value` (extraction rows routed `review`; any other field of an extraction run's results, such as an auto-accepted value, can be opened and decided by its field item key but is never listed as open), `sector_code` (theme runs), `identity`, `quarantined_document` (a held document; `approve` releases it and needs the approver role, no `correct`), `restatement_candidate`, plus `other` for the legacy kinds (theme, financials, transition plan, TNFD), which still decide through their run's own review endpoint and where any decision is final. Extraction failure reports (`PreStepFailed`) are also `other` items but decide through the workbench endpoint with `approve`, `reject` or `escalate` (no `correct`, no second review): the decision is final at once, except `escalate`, which keeps the item pending until an approver decides. A sector-code decision has no consumer yet, and publishing a restatement is step 5.
- *States*, derived by folding the item's decision rows: `pending`, `first_done` (waiting for a second review), `second_done` (two reviewers agree), `disagreed` and `final`. `second_done` and `final` are the final states; an `escalate` leaves the item `pending` with `escalated` set, and an escalated item is decided by an approver. A later decision on a final item starts a new round; an item an approver resolved is re-decided only by an approver. A legacy `escalate` row now reads as `pending`.
- *Blind view.* While a `high_risk` item is `first_done`, anyone other than the first reviewer or an approver sees no first decision, so the second review is independent.
- *Roles.* Clients see a decision's role and date, its reason, comment, value and snapshot id, never the reviewer's name or user id; they get only `mine` for their own rows. Both stay in `review_decisions.jsonl` for audit.
- *Source view.* The highlight in a table cell is the cited span inside its text line; no table structure is parsed.
- *Unchanged.* Voting review (`voting/`, `#/voting/<run id>`, `arp voting review`) is outside the workbench and works as before, and `voting` runs are never listed in it.
- *Legacy rows.* Old decision rows keep their meaning. A legacy `edit` is read as `correct` (its `edited_value` as the corrected value) and, on extraction runs, still needs its co-sign (`review_cosigns.jsonl`, bound to that decision's `decided_at`) before it counts as `second_done`; other legacy decisions without a `step` are final at once. The UI no longer offers a co-sign button and offers no *Agree* for an `edit`, so an uncosigned legacy `edit` is resolved by an approver: a second reviewer's decision that does not repeat the same value as a grounded `correct` makes the item `disagreed`, and an approver who took part in neither review decides it. A second reviewer of a new `correct` can press *Agree* when the first decision is visible to them (not a blind high-risk item): it resubmits the first correction's value and its grounded span as the quote, which the server grounds again. `effective_decisions` returns `edited_value` for a `correct` row so existing readers keep working.

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
data/documents/_captures.jsonl, _intake.jsonl  download log; files intake did not accept
data/blobs/<key[:2]>/<key>                   verified original bytes (blob_store_dir)
schemas/                                     versioned data-point schemas (schema_registry_dir)
runs/<run_id>/manifest.json                  run metadata: type, status, cost, progress
runs/<run_id>/results.jsonl                  per-company results, appended as they complete
runs/<run_id>/errors.jsonl                   per-company failures, isolated from the batch
runs/<run_id>/review_queue.jsonl             flagged/ungrounded/low-confidence items
runs/<run_id>/review_decisions.jsonl         append-only decision rows: item_key, decision, reason_code, reviewer,
                                              user_id, role, corrected_value, correction_citation, snapshot_id,
                                              comment, step (first|second|resolution), second_required,
                                              second_reasons, decided_at (legacy rows: edit/edited_value, no step)
runs/<run_id>/snapshots/<snapshot_id>.json   the context bundle a reviewer saw, written before the decision
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

### Captured originals, intake and schema release

Settings (env prefix `ARP_`, see `backend/arp/config.py`):

| Setting | Default | What it holds |
|---|---|---|
| `blob_store_dir` | `data/blobs` (`/app/data/blobs` in Docker, volume `arp_blobs`) | Each collected document's original bytes, at `<dir>/<sha256[:2]>/<sha256>`. Used unless the object store is enabled (`ARP_OBJECT_STORE_LIVE_UPLOAD_ENABLED` plus an endpoint), in which case the bytes go to the bucket instead. |
| `schema_registry_dir` | `schemas/` | Versioned data-point schemas (`SchemaRegistry`); each extraction run also keeps the exact registered copy as `runs/<run_id>/schema.json`. |
| `documents_dir` | `data/documents/` | Working copies by `<company_id>/<doc_type>/`, plus two append-only logs at its root. |

- **Store or skip.** A document is collected only once its bytes are stored and read back with a matching sha256 (`upload_or_fail`). A store failure (disk, bucket, hash mismatch) means the document is *not collected* in that fetch and is retried next time; it never enters a run without a verified copy. A file already stored and still present in the store is not re-uploaded or re-read on later fetches. EDGAR filings are re-fetched and re-archived when the registry names a copy that is no longer in the store.
- **`documents_dir/_captures.jsonl`** — one row per download attempt by the discovery crawler (`CaptureRecord`: URL chain, status, response headers minus cookies, `content_key`, `storage_uri`, rights tag, `fetched_at`, `collected`, `error`). The latest row for a content key supplies the document's `published_at` when its identity is first assigned.
- **`documents_dir/_intake.jsonl`** — one row per local file intake did *not* accept: `quarantined` (empty, corrupt archive, unreadable PDF, intake error), `ocr_needed` (scanned PDF with no text layer) or `duplicate` (same bytes as another file, `duplicate_of`). These files stay on disk and are skipped by extraction. Accepted files are not logged.

Schema routes (`/api/extraction`):

| Route | Role | Notes |
|---|---|---|
| `POST /schemas/draft` | signed in | LLM draft from plain language; nothing is saved. |
| `POST /schemas` | `analyst` | Saves a new version in the registry (fields start `draft`). |
| `GET /schemas`, `GET /schemas/{schema_id}?version=` | signed in | Index, and one schema (latest version unless `version`). |
| `POST /schemas/{schema_id}/versions/{version}/release` | `approver` | Sets the version's release flag, releases its draft fields, and records `released_by` (the approver's user id) and `released_at`. |

**Trial runs.** An extraction run on a schema that is not released (any field still draft, or no release flag) is refused unless it is started as a trial. The Extraction screen sends `trial: true` automatically for an unreleased custom schema and says so before the start; on the CLI pass `arp extraction run --trial`. The flag is stored in the run manifest (`params.trial`); trial results are visible in the run views (a *trial* badge on the run in run lists and on its results) but are not projected to the Postgres company facts, so a trial never replaces a company's current fact. Restarting a custom run saved before this gate existed (its `start_request.json` has no `trial`) runs it as a trial.

**Fiscal year end.** A universe file may carry a `fiscal_year_end` column (`MM-DD`, e.g. `03-31`). Period labels such as `FY2024`, `FY24`, `Fiscal 2024`, `2023/24` or `FY2023-24` resolve to that company's fiscal year (the year it ends in); without the column a calendar year is assumed and the value carries the `fiscal_year_end_assumed` qualifier.

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
arp identity resolve | review-queue | review
arp discover run | schedule
arp engagement issue-open | trigger-scan | dossier-draft | issue-escalate | record-show | report
arp voting run | ballots | review | cast
arp portfolio seed-demo | list | review-queue | aggregate | ask | classify-news
arp climate waci | financed-emissions | coverage
arp emerging-themes run | candidates | show | promote | reject | disconfirm | schedule
arp transition-plan indicators | run
arp transition-barrier criteria | scores | sources | staleness | coverage | refresh
arp report draft | plan | render | templates
arp replicate extract | backtest | compare | discover-papers | score-sentiment | pbo | regime-report | sanity-check | golden-set
arp taxonomy-researcher run | schedule
arp calibration run | schedule
arp golden-set run | run-roles | planner
arp db init-postgres | project
arp runs list | show | cancel
```

`arp identity review <run_id> <item_key> --decision approve|correct|reject|escalate [--reason R] [--website W] [--cik C] [--comment T]`: `--reason` is required unless approving (default `confirmed`); `correct` needs `--website` and/or `--cik` and a `--comment` naming the source.

Full flag-level detail is in the project [`README.md`](../README.md); design rationale for every precision control is in [`METHODOLOGY.md`](METHODOLOGY.md).
