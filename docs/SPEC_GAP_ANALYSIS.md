# Portfolio Risk Exposure Agent — Spec Gap Analysis

Compares the "Portfolio Risk Exposure Agent — Functional Requirements
Specification" (DWS Group, Investment Intelligence & Positioning / Xtrackers
ETF Business — Stewardship & Sustainability, September 2026) against what is
actually built in this repository's Portfolio Risk & Exposure Monitoring
pillar (`backend/arp/portfolio/`, `backend/arp/api/routers/{portfolio,climate}.py`,
`frontend/src/pages/{PortfolioRisk,ClimateAnalytics}.tsx` — see
[`PORTFOLIO_RISK_EXPOSURE_PLAN.md`](PORTFOLIO_RISK_EXPOSURE_PLAN.md) for that
pillar's own design doc).

Every verdict below is evidence-based (file:function references), not a
summary of intentions. Three verdict levels are used: **Built**, **Partial**,
**Not built**.

## Sibling-system dependencies the spec assumes exist

Before the section-by-section comparison: the spec repeatedly instructs
reusing capability from two systems it treats as already existing elsewhere
in the organization —

- an **"engagement/voting agentic system"**, with an **Engagement Record
  Store** (single source of truth for engagement/voting history) and a
  **Trigger & Detection layer** (calendar-driven triggers), referenced in
  §3, §5, and §6;
- an **"Emerging Themes Screening tool" ("Tool 0")**, whose news
  burst-detection/clustering methodology §6 says should filter a company
  profile's news.

**Both now exist in this repository** (`backend/arp/engagement/` +
`backend/arp/voting/`, and `backend/arp/emerging_themes/` respectively) —
built independently on other branches and merged into `main` after this
document was first written, so the reuse the spec assumes is genuinely
possible where it says so. One nuance found while building §3's Monitoring
& Alerting against it: the **Engagement Record Store is real** (`EngagementStore`,
matches the spec's description closely — `EscalationStage`, an append-only
per-company audit log), but the **"Trigger & Detection layer" only has
file-based controversy-signal ingestion and an elapsed-time SLA-stall sweep
(`engagement/triggers.py`) — no calendar/cron logic anywhere**, so §3's
calendar-driven triggers could not actually be reused from it and were
built fresh instead (see §3 below). The Emerging Themes Scanner's own
burst-detection/clustering hasn't yet been wired into §6's company profile
news feed — still a real, closeable gap, just no longer a missing sibling
system.

## §1 Risk Identification & Classification — Partial (climate risk only)

**Built:** a fixed, built-in climate `DataPointSchema`
(`backend/arp/portfolio/climate/schemas.py`, `sch_climate_core_v1`) with six
fields: Scope 1 (`climate_scope1_tco2e`), Scope 2 (`climate_scope2_tco2e`),
Scope 3 (`climate_scope3_tco2e`, optional), carbon intensity
(`climate_carbon_intensity`), enterprise value including cash
(`climate_evic_eur_m`, the PCAF attribution denominator), and a green-revenue
share (`climate_green_revenue_pct`, optional). WACI itself isn't a stored
field — it's computed on demand from carbon intensity
(`climate/metrics.py::compute_waci`).

**Not built:** factor exposure (style/sector/country/currency/rates/credit
spread), concentration risk, liquidity risk, counterparty/derivatives
exposure, physical risk (facility-level hazard → balance-sheet impact),
patent-intensity/transition-readiness scoring, Implied Temperature Rise /
Paris alignment, SFDR Principal Adverse Impact indicators (zero references
anywhere in the codebase), EU Taxonomy alignment % (the implemented
`climate_green_revenue_pct` is explicitly a green-revenue *proxy* reusing the
existing revenue-exposure cascade, not a real Taxonomy eligibility/alignment
calculation — no CapEx/OpEx KPI split exists), TCFD/ISSB scenario-alignment
reporting, and exclusionary/controversial-weapons screening.

Controversy/norms-based risk is **partially** represented:
`schemas/portfolio.py::NewsRiskFlag` carries a category (including
`climate_controversy`, `regulatory`, `litigation`) and a severity
(low/medium/high), produced by `news/classifier.py` from ingested articles.
But it's a free-standing object, not a `DataPointSchema` field — you cannot
run a `weighted_avg_datapoint` aggregation or pivot on "controversy score"
the way you can on carbon intensity, and there's no incident-frequency
tracking (the spec's "~1,500/month across 19,000+ issuers" scale) or
remediation scoring, only per-article classification.

## §2 Data Model — Portfolios, Holdings, and the Issuer-ID Join — Built

This is the strongest match in the spec, and two of the spec's own listed
scope items are *already* satisfied by design rather than left as gaps:

- **No look-through** — the spec's own stated assumption. This codebase's
  `Holding` (`schemas/portfolio.py`) is exactly the flat, one-row-per-holding
  shape the spec describes.
- **Benchmark decomposition deliberately deferred** — the spec itself says
  this is conditional on benchmark holdings being confirmed as an available
  input. Nothing here provides it yet, which matches the spec's own framing,
  not a shortfall against it.

**Built:** the issuer-ID join (`portfolio/entity_resolution.py::resolve_security`,
exact ISIN match or confidence-scored name-fuzzy fallback), with unmatched/
low-confidence matches explicitly routed to a review queue rather than
silently assumed
(`storage/portfolio_store.py::list_resolutions_needing_review`,
`GET /api/portfolio/securities-needing-review`) — precisely the validation
behavior §2 asks for. Point-in-time versioning is real and append-only on
both sides of the join: holdings snapshots
(`storage/portfolio_store.py::save_snapshot`/`load_holdings_as_of`, one
immutable file per `(portfolio_id, as_of_date)`) and per-field ESG
observations (`append_observation`/`load_observations`, one immutable row
per `(company_id, field_id, observed_at)`) — so "what did the portfolio look
like on 30 June" is a real, correctly-dated query today
(`aggregation.py::aggregate`'s `as_of` parameter), not a latest-value
approximation.

**Not built:** a **portfolio group** as the spec defines it — "a saved,
named set of portfolio IDs." Every query today accepts an ad hoc
`portfolio_filter: list[str]`, which covers the *aggregation* half (querying
several portfolios at once, asset-weighted by construction since it's a
straight sum/weighted-average over the underlying holdings — never a naive
average of portfolio-level numbers, so the spec's aggregation-rule concern is
already satisfied), but there's no way to save that set under a name and
reuse it later. Sector taxonomy consistency is likewise informal:
`CompanyRef.sector` is a flat string with no explicit GICS-normalization
step, so a sector tag arriving in a different taxonomy than the ESG feed's
own sector breakdowns would not be caught today.

## §3 Continuous Monitoring & Alerting — Built (climate + concentration thresholds)

`arp/portfolio/monitoring/evaluator.py` implements threshold/breach
monitoring for three rule types built entirely on the existing aggregation
engine: a company climate field vs. an absolute limit
(`field_threshold`), a company's weight of portfolio NAV vs. a limit
(`concentration_threshold`, the spec's own literal example), and a
WACI-style portfolio-weighted metric vs. a limit
(`portfolio_aggregate_threshold`). Event-driven triggers are new
`NewsRiskFlag`s at/above a configured severity floor. Calendar-driven
triggers are fixed-interval re-evaluation
(`PortfolioMonitoringScheduler`, cloned from the other four APScheduler
wrappers already in this codebase) — not true calendar windows (proxy
season, PAI deadlines); APScheduler supports a `"cron"` trigger natively,
so this is a moderate upgrade, not a structural block. Drift detection
(`breach_type`: `holdings_caused` / `data_caused` / `mixed` / `unknown`)
is real for the one rule type where it's actually ambiguous
(`portfolio_aggregate_threshold`) — the other two are single-caused by
construction. Escalation is a 4-stage ladder
(`open → acknowledged → escalated → resolved | false_positive`); every
status transition requires `decided_by` (non-optional), mirroring the
engagement module's escalation checkpoint.

**Gaps**: no factor/PAI/benchmark-relative thresholds (§1/§2's own data-
model gaps), no rating-downgrade/index-reconstitution triggers (no such
data exists anywhere in this codebase), and no true calendar-specific
triggers yet (see above).

## §4 Analytical Views & Exploration — Built (strongest section)

The deterministic aggregation engine (`portfolio/aggregation.py`) is close
to a literal implementation of what §4 asks for: `aggregate()` groups any
metric by any one of seven dimensions (`DIMENSIONS`: `portfolio_id`,
`asset_class`, `company_id`, `company_name`, `sector`, `country`,
`currency`) with three metrics (`market_value_sum`, `weighted_avg_datapoint`,
`count`); `pivot()` does the same across two dimensions at once as a
cross-tab; `aggregate_trend()` runs either across every snapshot date for a
time series — all without a rebuild, exactly the "pivot an Excel table"
interaction model §4 specifies. `AnalyticSpec`/`PivotSpec`
(`schemas/portfolio.py`) already carry a `name` and are designed to be
persisted (`analytics.py::save_analytic`/`list_analytics`,
`GET /api/portfolio/analytics`).

**Gaps:** the save/list plumbing above has no UI — nothing in
`PivotExplorer.tsx` ever sets `save: true` or lists a saved analytic, so
"saved, role-based views" don't exist as a reachable feature, only as unused
backend capacity. There's no benchmark-relative/absolute toggle anywhere
(no `Benchmark` concept exists at all — consistent with §2's benchmark
deferral). There's no scenario/what-if overlay (carbon-price shock, physical
hazard stress) — that's explicitly Phase 5, "not started," in this pillar's
own plan doc. And there's no structured export endpoint for a query result
(CSV/etc.) — a gap made more notable by the fact that other parts of this
same codebase already have this pattern (e.g. `GET /api/runs/{id}/export.csv`
for the Thematic Universe/Extraction pipelines) that simply hasn't been
extended to portfolio aggregation/pivot results.

## §5 Governance & Workflow — Built

`arp/portfolio/governance.py` extends §3's `AlertTransition`-style human-
checkpoint pattern to the two older flags: entity-resolution matches below
confidence and climate values where the internal API disagrees with an
independent extraction. `accept`/`reject` are pure audit annotations —
the underlying flag (`needs_review` / `conflicting_sources`) is never
mutated, only a `decision_recorded` event is appended (folded, latest per
item wins, same "later JSONL rows win" approach as
`orchestration/review_queue.py::latest_decisions`, which stays unused
here since it's hard-coupled to `RunStore`/`run_id` and these items don't
live inside a run). `override` has real computational effect, not just an
audit note: an entity-resolution override writes a fresh
`SecurityResolution(method="manual")` **and** updates the `SecurityRef`'s
`company_id` directly (a real gap found while building this — nothing
previously read a resolution's `company_id` back into the `SecurityRef`
the aggregation engine actually groups by, so a plain review record would
have been a no-op); a climate-conflict override appends a new, non-
conflicting `internal_api` observation, which `resolve_field_value`'s
existing source-priority cascade picks up going forward.

Named ownership per risk category and logged methodology-version history
are both built the same way: `RiskCategoryOwner`/`PolicyChange` events in
the same unified append-only log, current state folded (latest per
category / per setting wins) rather than a separate mutable snapshot. The
two governance settings (`portfolio_confidence_review_threshold`,
`climate_validation_tolerance_pct`) are now live-configurable through this
mechanism instead of env-only.

**Gap, stated explicitly**: entity resolution and climate cross-checking
each only run once, at demo-seed time — changing a policy value affects
future seeds, not already-resolved securities/observations. This matches
existing behavior (nothing ever re-ran these passes before either), not a
regression introduced here.

## §6 Company-Level Risk & Intelligence Profiles — Built (as an assembly of existing endpoints)

`CompanyProfiles.tsx` combines `GET /api/portfolio/companies`,
`GET /api/portfolio/news` (`?company_id=`), `GET /api/portfolio/news/flags`
(`?company_id=`), and per-company climate figures (the existing
aggregation engine filtered to one `company_id`) into a single issuer
view — an assembly exercise against endpoints that already existed and
already accepted a company scope server-side, not new backend work.

**Still not built**: `CompanyProfiles.tsx` doesn't yet read from the
Engagement Record Store or the voting module, even though both now exist
in this repository (see "Sibling-system dependencies" above) — wiring in
engagement history/voting-record sections is a real, closeable gap now,
not a missing-system blocker. Filtering the profile's news by the "Tool 0"
Emerging Themes Scanner's burst-detection/clustering methodology is the
same story: the tool exists, just isn't wired into this page yet. This
codebase's own portfolio news pipeline (`news/mock_source.py` →
`news/classifier.py`) still does per-article LLM classification only, with
no clustering or burst detection of its own.

## §7 Custom Analysis via Jupyter Notebook Integration — Not built

Zero references to notebooks or Jupyter anywhere in the repository. The one
precondition the spec calls out — "API-first access to the governed data
model" — is genuinely satisfied (the full REST API in
`api/routers/{portfolio,climate}.py` is exactly the kind of governed,
function-level surface a notebook layer would query instead of
re-deriving its own copy of the join), but the managed-environment,
shared-kernel, and promotion-path pieces are all unbuilt.

## §8 AI/LLM Q&A Layer — Built (matches the spec's design principle closely)

`portfolio/qa_agent.py::answer_question` already follows the exact pattern
§8 prescribes: the LLM's only output is a structured `AnalyticSpec`
(function-calling, never free-form calculation), the deterministic
aggregation engine computes the actual number, and the answer always
returns the executed `spec` and `result` alongside the natural-language
`answer_text` — so an AI-generated answer is exactly as inspectable as a
manual query, per §8's stated bar. There's a real refusal path too: an
unresolvable question comes back as `resolvable: false` with a
`clarification_needed` message rather than an improvised answer.

**Gaps:** no persisted audit record of which questions were asked, by whom,
against which data vintage (the response carries this information, but
nothing writes it to a log) — so the letter of §8's "every answer carries
its own audit trail" is met per-response but not as a durable record. And
there's no permission model at all in this codebase yet, so "permission-
aware by construction" has nothing to be constructed against.

## §9 Front-End Architecture — Structural mismatch (addressed in this same change)

The spec wants one top-level tool ("Portfolio Risk Monitoring Tool") with a
persistent selection pane (portfolio/group + as-of date) that carries across
every sub-tab, and seven MECE sub-tabs. Before this change, the app had two
separate top-level tabs (Portfolio Risk, Climate Analytics) totaling nine
sub-tabs, each independently holding its own portfolio-picker and date
state — meaning switching sub-tabs reset the selection, exactly the failure
mode §9 calls out ("moving from one function to another never means
re-selecting"). This gap is closed by the front-end restructuring shipped
alongside this document — see the plan referenced in the PR/commit for the
new `PortfolioRiskMonitoringTool` page, `PortfolioPaneContext`, and the
seven sub-tabs (Standard Analytics & Visuals, Pivot Explorer, Monitoring &
Alerts, Company Profiles, Custom Analysis, Ask the Portfolio, Governance &
Audit).

## Market-mapping table and suggested build sequence

The spec's "How This Maps to What Already Exists in the Market" table
describes third-party vendor tools, not this codebase, and needs no
correction. Its "Suggested Build Sequence" is worth noting as independent
validation of the order this pillar was actually built in: data model → risk
taxonomy → pivot/exploration engine landed first and are the most complete
sections above; monitoring, governance, and company profiles — sequenced
next in the spec — are exactly the sections with the largest gaps today;
and the AI/LLM Q&A layer, which the spec insists on building *last*, is
already built here, but only because its "function-calling over
already-trustworthy functions" design was table stakes for the aggregation
engine itself, not because the sequencing advice was disregarded.

## Summary table

| Section | Verdict |
|---|---|
| §1 Risk Identification & Classification | Partial — climate only |
| §2 Data Model | Built |
| §3 Continuous Monitoring & Alerting | Built — climate/concentration thresholds; no true calendar triggers yet |
| §4 Analytical Views & Exploration | Built |
| §5 Governance & Workflow | Built — decisions, ownership, and policy history; doesn't retroactively re-flag past items |
| §6 Company-Level Risk & Intelligence Profiles | Built (as an assembly of existing endpoints); engagement/voting + Tool 0 exist in this repo now but aren't wired into the profile yet |
| §7 Jupyter Notebook Integration | Not built |
| §8 AI/LLM Q&A Layer | Built |
| §9 Front-End Architecture | Was a structural mismatch; addressed in this change |
