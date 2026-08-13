# Portfolio Risk & Exposure Monitoring — Plan

Status: **proposal**, not yet built. This document scopes a third pillar for
the Agentic Research Pipeline, alongside the existing Thematic Universe
Builder and Data-Point Extraction Engine: a **portfolio-level** aggregation
and analytics layer, plus a dedicated **climate analytics** section, that
sits on top of the company-level research those two pillars already
produce.

## 1. Why this is a new pillar, not a new page

Everything built so far answers *company-level* questions: "is BMW exposed
to electrification," "what's BMW's green capex share." Nothing today
answers *portfolio-level* questions: "how many EUR million of exposure to
BMW do we hold, across every fund," "what's our weighted-average carbon
intensity across the multi-asset mandate." That requires a second axis the
codebase doesn't have yet — **holdings** (position, quantity, market
value, currency, portfolio) — cross-joined against the **company-level**
research this pipeline already knows how to produce (GICS sector, thematic
exposure %, revenue/capex exposure %, extracted data points, indirect I-O
exposure).

The design goal is to add that axis and the join, and reuse everything
else: LLM client/cache/orchestration, the `FieldDefinition`/
`DataPointSchema` structured data-point framework, the taxonomy library,
the revenue-exposure resolution cascade, and the file-based, no-DB,
resumable run pattern the rest of the codebase already follows.

## 2. Core data model (new)

New Pydantic schemas under `backend/arp/schemas/portfolio.py`, following the
existing style (`CompanyRef` in `schemas/common.py` is the precedent for a
minimal, user-supplied reference object):

```python
class SecurityRef(BaseModel):
    """A tradeable instrument, resolved to an issuer where possible."""
    security_id: str            # ISIN preferred; ticker/internal ID fallback
    isin: str | None = None
    name: str
    asset_class: Literal["equity", "corporate_bond", "government_bond",
                          "fund", "etf", "derivative", "cash", "other"]
    currency: str                # ISO 4217
    company_id: str | None = None  # resolved issuer -> joins to CompanyRef

class Holding(BaseModel):
    """One position: one security, in one portfolio, as of one date."""
    portfolio_id: str
    security_id: str
    as_of_date: str              # ISO date
    quantity: float
    price: float
    market_value: float          # in the security's native currency
    market_value_base_ccy: float # normalized to the portfolio's reporting currency
    weight_pct: float | None = None  # of portfolio NAV, if supplied/derivable

class Portfolio(BaseModel):
    portfolio_id: str
    name: str
    base_currency: str
    nav: float | None = None
    tags: list[str] = Field(default_factory=list)  # e.g. "mandate:equity", "client:X"
```

`SecurityRef.company_id` is the join key into everything the pipeline
already computes — `CompanyRef`, `ExtractionRecord`, `RevenueExposureResult`,
`IndirectExposureResult`, taxonomy match results. Resolving it is an
explicit, reviewable step (an ISIN→`company_id` crosswalk, user-supplied or
LLM-assisted fuzzy-matched with mandatory human confirmation for anything
below a confidence threshold — same review-queue pattern as everything
else in this codebase, never a silent auto-match) because a wrong issuer
match silently corrupts every euro figure downstream of it.

Ingestion (`backend/arp/portfolio/ingestion.py`) accepts CSV/XLSX holdings
exports (the common custodian/PMS export shape: portfolio, ISIN/ticker,
quantity, price, market value, currency, as-of date) the same way
`universe.py` accepts a company CSV today — one loader function, used
identically by API, CLI, and any scheduled refresh.

## 3. Aggregation engine (new, deterministic — no LLM in the numbers)

`backend/arp/portfolio/aggregation.py`. This is the load-bearing piece and
is intentionally **zero-LLM**, same philosophy as `indirect_exposure/leontief.py`:
a portfolio risk number must be reproducible and auditable, not regenerated
slightly differently on every LLM call.

Core primitive: given a set of holdings (optionally pre-filtered to one or
many portfolios) and a **grouping dimension**, produce grouped market-value
sums, weights, and — when a data point is attached — weighted exposure
figures.

Built-in dimensions, each just a column/lookup on the joined
holding+security+company row:
- `portfolio_id`, `tags` (multi-portfolio consolidation)
- `asset_class`
- `company_id` / issuer name ("BMW exposure across all portfolios")
- GICS sector/industry (via `standards_mapping`)
- country/domicile
- currency
- any ratified `Taxonomy` (thematic exposure, reusing
  `RevenueExposureResult`/match verdicts already computed for that issuer)
- any custom tag the user attaches to a portfolio or security

Two aggregation modes, matching how these numbers are actually used:
1. **Sum of market value** grouped by dimension (a plain exposure figure —
   "EUR 4.2m in BMW equity, across 3 portfolios").
2. **Value-weighted average of a data point** grouped by dimension (e.g.
   weighted-average carbon intensity, weighted-average thematic exposure %)
   — `Σ(holding.market_value_base_ccy × datapoint.value) / Σ(holding.market_value_base_ccy)`,
   with holdings missing the data point either excluded and the coverage
   % reported (never silently treated as zero) — same "don't fabricate an
   absence into a number" principle as `grounding.py`'s citation checks.

This engine is what answers "how many million euro is the exposure to
stocks from BMW": filter holdings to `asset_class == equity` and
`company_id == <BMW>`, sum `market_value_base_ccy` across all portfolios,
convert to EUR via the FX rates supplied with the ingestion batch. No LLM
call is needed for that question at all — which matters for the next
section.

## 4. Data-point mapping ("select from a defined list, map to holdings")

Reuses the existing `DataPointSchema`/`FieldDefinition` framework
(`schemas/datapoints.py`) as-is: it's already "a named, structured,
user-authored list of fields with a data type and unit." What's new is a
**mapping layer** (`backend/arp/portfolio/datapoint_mapping.py`) that
resolves a field's value **per issuer** and joins it onto holdings by
`company_id`, from whichever of these already exists for that company,
in priority order (identical cascade philosophy to
`revenue_exposure/resolver.py`'s catalogue → extraction → qualitative
path, because a disclosed number should never be second-guessed by an
inferred one):

1. An `ExtractionRecord` already produced by the Extraction Engine for
   that field/schema.
2. A `RevenueExposureResult`/`IndirectExposureResult` already produced for
   a relevant taxonomy.
3. A user-supplied reference/catalogue value (e.g. a purchased ESG data
   feed row), same shape as `CatalogueDataPoint`.
4. Missing — reported as missing, contributing to a coverage % metric,
   never imputed silently.

The UI-facing flow: user picks a `DataPointSchema` (or the built-in climate
one, §6) from a list, picks a grouping dimension, picks the portfolios in
scope, and gets a table/chart — this is "developing new analytics" without
writing any code, just composing existing primitives (dimension × data
point × aggregation mode × filter), the same drag-and-drop-of-known-parts
spirit as the existing Extraction Builder / Universe Picker UI.

## 5. On-the-fly analytics + natural-language Q&A

Two related but distinct capabilities, both LLM-assisted but **never
LLM-computed**:

**5a. Analytics Builder.** A UI where the user assembles an analytic from
the primitives in §3–4 (filter → group-by → data point → aggregation mode)
directly, or asks the LLM to draft one from a plain-language description
("show me equity exposure by GICS sector for the flagship fund"). The LLM's
job is strictly **query composition** — it emits a small structured
`AnalyticSpec` (Pydantic-validated, same schema-first pattern as
`schema_builder.py`), which is then executed by the deterministic engine
in §3. The user sees and can edit the generated spec before running it, and
saved specs become reusable "analytics" (persisted the same way taxonomies
are — file-based, versioned, listable) rather than one-off prompts.

```python
class AnalyticSpec(BaseModel):
    name: str
    portfolio_filter: list[str] = Field(default_factory=list)  # empty = all
    security_filter: dict = Field(default_factory=dict)         # e.g. {"asset_class": "equity"}
    group_by: str                                                # dimension name
    metric: Literal["market_value_sum", "weighted_avg_datapoint", "count"]
    data_point_field_id: str | None = None
    currency: str = "EUR"
```

**5b. Natural-language Q&A agent** (`backend/arp/portfolio/qa_agent.py`).
For direct questions like *"how many million euro is the exposure to
stocks from BMW?"*: the LLM's only job is to parse the question into an
`AnalyticSpec` (tool-call / structured-output style, reusing
`llm/base.py`'s `complete_structured`), the deterministic engine executes
it and returns the real number, and the LLM's final answer is templated
from that real, computed result plus the spec that produced it (so the
answer is always inspectable: "this is `Σ market_value_base_ccy` for
`company_id=BMW, asset_class=equity` across 3 portfolios, converted at the
FX rate as of 2026-08-13"). This mirrors the grounding discipline already
used everywhere else in the codebase (citations checked programmatically,
never trusted from the LLM's own claim) — here the "citation" is the
underlying holdings query, and it's always shown, not just claimed.
Ambiguous questions (unresolvable company name, ambiguous dimension) are
surfaced back to the user for clarification rather than guessed.

## 6. Climate analytics (separate section)

A dedicated set of built-in `DataPointSchema`s under
`backend/arp/portfolio/climate/schemas.py` (shipped, not user-authored, so
every deployment starts with a consistent definition — but editable the
same way any `DataPointSchema` is):

- Scope 1 / Scope 2 / Scope 3 GHG emissions (absolute, tCO2e)
- Carbon intensity (tCO2e / EUR M revenue)
- Green revenue / green capex share (**reuses `revenue_exposure/` directly**
  — "green" is just another `ActivityDefinition`/taxonomy, no new
  machinery needed)
- EU Taxonomy alignment %, if disclosed
- Physical/transition risk flags, if disclosed

Portfolio-level climate metrics, computed by `backend/arp/portfolio/climate/metrics.py`
on top of the §3 aggregation engine (financed-emissions math per the
[PCAF](https://carbonaccountingfinancials.com/) standard, since that's the
accepted methodology and shouldn't be reinvented):

- **WACI** (weighted-average carbon intensity): the weighted-average
  aggregation mode from §3, applied to the carbon-intensity data point.
- **Financed emissions**: `Σ (holding.market_value / company.EVIC) × company.scope_1_2_emissions`,
  attribution factor per PCAF; `EVIC` (enterprise value incl. cash) is
  itself an extractable/user-suppliable data point.
- **Data coverage %**: always reported alongside every climate number —
  what fraction of portfolio market value has a disclosed emissions figure
  vs. estimated vs. missing — because a climate number with silent 40%
  coverage is actively misleading.
- **Estimated (proxy) emissions for non-disclosing issuers**: an *opt-in*,
  clearly-flagged tier reusing the existing indirect-exposure I-O
  machinery (`indirect_exposure/leontief.py` already carries sector-level
  economic intensity data) as a sector-average proxy — same
  opt-in/clearly-labeled-as-a-proxy pattern the indirect exposure tier
  already uses for thematic exposure, never blended into the disclosed
  number without a visible "estimated" tag.

This becomes its own frontend tab ("Climate Analytics") with a portfolio
picker, WACI/financed-emissions summary tiles, coverage breakdown, and
drill-down to the same Analytics Builder from §5 pre-filtered to climate
data points — it's a skinned, pre-configured application of the general
engine, not a parallel implementation.

## 7. Backend layout (new)

```
backend/arp/portfolio/
  __init__.py
  ingestion.py          # holdings CSV/XLSX loader (parallels universe.py)
  entity_resolution.py  # ISIN/ticker -> company_id crosswalk + review queue
  aggregation.py         # dimensions, grouping, weighted-avg engine (no LLM)
  datapoint_mapping.py   # per-issuer data point resolution cascade
  analytics.py            # AnalyticSpec store/executor
  qa_agent.py              # NL question -> AnalyticSpec -> executed answer
  climate/
    __init__.py
    schemas.py            # built-in climate DataPointSchemas
    metrics.py             # WACI, financed emissions, coverage
backend/arp/schemas/portfolio.py   # Portfolio, Holding, SecurityRef, AnalyticSpec
backend/arp/api/routers/portfolio.py   # holdings upload, aggregation, analytics, Q&A
backend/arp/api/routers/climate.py     # climate-specific endpoints
backend/tests/test_portfolio_*.py
portfolios/               # file-based storage: holdings snapshots, saved analytics
                           # (same pattern as taxonomies/, runs/ — no DB)
```

CLI additions (`arp portfolio ...`, `arp climate ...`), mirroring the
existing `arp theme ...` / `arp taxonomy ...` command families, since the
CLI is the documented path for unattended/batch operation (e.g. a nightly
holdings refresh feeding the discovery scheduler's pattern in
`discovery/scheduler.py`).

Frontend additions: two new tabs in `frontend/src/App.tsx` ("Portfolio
Risk", "Climate Analytics"), new pages `PortfolioHoldings.tsx`,
`AnalyticsBuilder.tsx`, `ClimateDashboard.tsx`, reusing existing UI
patterns (`RunProgress.tsx`-style status, `ConfidenceBadge.tsx` for
coverage/confidence display).

## 8. Reuse map (what's new vs. what already exists)

| Need | Reuse | New |
|---|---|---|
| Structured, user-defined data points | `schemas/datapoints.py` as-is | mapping layer only |
| Sector/industry classification | `standards_mapping/` (GICS/NACE/NAICS/SIC) as-is | — |
| Thematic exposure % per issuer | `taxonomy`, `revenue_exposure/` as-is | — |
| Green revenue/capex | `revenue_exposure/` as-is (green = a taxonomy) | — |
| Structural/estimated exposure for non-disclosers | `indirect_exposure/leontief.py` as-is | climate-specific sector intensity dataset |
| LLM client, caching, retries, structured output | `llm/` as-is | — |
| Review queue for low-confidence matches | `orchestration/review_queue.py` as-is | entity-resolution matches routed into it |
| File-based, resumable, checkpointed runs | `storage/run_store.py` pattern | `portfolios/` store, same shape |
| Holdings, positions, portfolios, FX | — | new schemas + ingestion (§2) |
| Deterministic aggregation/weighting engine | — | new, zero-LLM (§3) |
| NL question → query → grounded answer | pattern precedent only | new `qa_agent.py` (§5b) |
| PCAF financed-emissions math | — | new `climate/metrics.py` |

## 9. Precision controls (extending the existing list in `docs/METHODOLOGY.md`)

- Every portfolio-level number is deterministically computed from holdings
  + resolved data points; the LLM never outputs a number directly, only a
  query spec, mirroring the "programmatic grounding, not LLM self-report"
  principle already in place for citations.
- Every aggregated figure carries a coverage % (what fraction of the
  relevant market value actually had the underlying data point resolved),
  never silently treated as complete.
- Issuer entity resolution (ISIN → `company_id`) below a confidence
  threshold goes to the existing review queue, not an auto-match.
- Estimated/proxy climate figures (from the indirect-exposure sector
  proxy) are visibly tagged as estimated and never combined into the same
  number as disclosed figures without the split being shown.
- Saved `AnalyticSpec`s are versioned and inspectable, same as the
  taxonomy library, so a recurring report's definition can't silently
  drift.

## 10. Open questions (need your decision before implementation)

1. **Holdings source**: manual CSV/XLSX upload only for v1, or does a
   custodian/PMS API integration need to be in scope from the start?
2. **FX rates**: supplied in the holdings file per position, or a separate
   FX-rate reference input keyed by date/currency pair?
3. **Look-through for funds/ETFs held as positions**: v1 treats a fund
   holding as one opaque position (asset_class="fund"), or do you need
   look-through into the fund's own constituents (reusing the
   `taxonomy_sources/etf_holdings.py` parser that already exists for a
   related purpose)?
4. **Climate emissions data**: rely entirely on disclosure-based extraction
   (10-K/sustainability report via the existing Extraction Engine) plus the
   opt-in structural proxy, or is a licensed third-party emissions dataset
   (e.g. CDP, MSCI, Trucost) going to be plugged in as another catalogue
   source (same shape as `CatalogueDataPoint`)?
5. **Multi-currency base reporting**: single reporting currency (EUR) for
   v1, or per-portfolio base currency with a consolidated EUR roll-up?

## 11. Phased roadmap

- **Phase 0 — Foundations**: `schemas/portfolio.py`, holdings
  ingestion, entity resolution + review queue, `portfolios/` file store.
- **Phase 1 — Aggregation & direct answers**: deterministic aggregation
  engine (§3), built-in dimensions, API + CLI for grouped market-value
  queries. This alone answers "how many EUR million exposure to BMW."
- **Phase 2 — Data-point mapping & Analytics Builder**: datapoint mapping
  cascade (§4), `AnalyticSpec` + saved analytics, Analytics Builder UI.
- **Phase 3 — NL Q&A agent**: `qa_agent.py`, question → spec → grounded
  answer, chat-style UI panel.
- **Phase 4 — Climate Analytics**: built-in climate schemas, WACI/financed
  emissions engine, coverage reporting, dedicated dashboard tab.
- **Phase 5 — Estimated/proxy tier & scenario analysis**: opt-in
  structural climate proxy, what-if reweighting ("if we exit BMW, how does
  portfolio WACI change" — a pure re-run of §3's engine on a hypothetical
  holdings set, still zero-LLM).

Phases 0–2 are the minimum viable version of the request; Phase 3 is what
makes it feel "agentic" end-to-end; Phase 4 is the explicitly-requested
separate climate section; Phase 5 is stretch.
