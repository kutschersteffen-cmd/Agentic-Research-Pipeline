# Portfolio Risk & Exposure Monitoring — Plan

Status: **Phases 0-2 built** (schemas, storage, entity resolution,
deterministic aggregation engine, data-point mapping, Analytics Builder,
NL Q&A agent) plus most of **Phase 4** (climate schemas, mock internal-API
+ extraction cross-check, WACI/financed-emissions/coverage), all against
the mock connectors decision 4 stands in for -- see `backend/arp/portfolio/`,
`backend/arp/api/routers/{portfolio,climate}.py`, and `arp portfolio
--help` / `arp climate --help`. Real custodian/ESG-API/news-vendor
connectors (replacing the `mock_*` modules) and the frontend UI are not
built yet. This document scopes the pillar end to end; the rest of this
status block aside, it otherwise describes the target design.

This document scopes a third pillar for
the Agentic Research Pipeline, alongside the existing Thematic Universe
Builder and Data-Point Extraction Engine: a **portfolio-level** aggregation
and analytics layer, plus a dedicated **climate analytics** section, that
sits on top of the company-level research those two pillars already
produce.

**Scope decisions (2026-08-13)**, superseding the open questions this
document originally posed — see §10 for the remaining ones:

1. Holdings are pulled via a **custodian/PMS API integration**, not just
   file upload — in scope from v1.
2. FX conversion is **supplied per position** by the feed, not looked up
   separately from a reference table.
3. **No look-through** for fund/ETF positions — a fund is one opaque
   position for now.
4. Climate/ESG data comes from an **internal structured API** as the
   primary source, **cross-validated against LLM analysis of company
   reports** (the existing Extraction Engine), plus a **news data feed**
   for company-specific news (controversy/risk-event monitoring).
5. **EUR is the only reporting currency.** In addition, portfolios,
   holdings, and their ESG data must be **tracked over time** (historical
   snapshots + metric trends), not just as a current-state snapshot.

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
    """One position: one security, in one portfolio, as of one date. A
    Holding is never mutated in place -- see the snapshot model below."""
    portfolio_id: str
    security_id: str
    as_of_date: str              # ISO date -- the snapshot this row belongs to
    quantity: float
    price: float
    market_value: float          # in the security's native currency
    fx_rate_to_eur: float        # as supplied by the custodian feed for this as_of_date
    market_value_eur: float      # = market_value * fx_rate_to_eur; the only cross-portfolio unit
    weight_pct: float | None = None  # of portfolio NAV, if supplied/derivable

class Portfolio(BaseModel):
    portfolio_id: str
    name: str
    tags: list[str] = Field(default_factory=list)  # e.g. "mandate:equity", "client:X"
```

Reporting is EUR-only end to end (decision 5), so `market_value_eur` — not
a per-portfolio base currency — is the one figure every aggregation in §3
sums or weights by; `Portfolio.base_currency`/`nav` from the earlier draft
are dropped as unnecessary since nothing downstream needs a currency other
than EUR.

**Time series, not a snapshot.** Decision 5 also requires tracking
portfolios/holdings/ESG data *over time*, so storage is append-only by
design rather than overwrite-in-place — the same principle
`RunManifest`/`results.jsonl` already use for run history:

```
portfolios/
  <portfolio_id>/
    snapshots/<as_of_date>.jsonl   # one immutable Holding[] snapshot per custodian pull
  registry.json                     # Portfolio metadata, one row per portfolio_id
```

Every data point resolved for a company (§4) is likewise stamped with an
`observed_at`/`as_of` and appended to a per-`(company_id, field_id)` series
rather than overwritten, so "how has BMW's disclosed carbon intensity
moved over the last 4 quarters" and "how has our WACI moved over the last
12 months" (§6) are both just a time-range query against existing rows —
see §3's `as_of`/`date_range` aggregation parameter below.

Ingestion is connector-based, mirroring the existing
`DocumentSource`/`DocumentSourceRegistry` pattern
(`backend/arp/ingestion/base.py`, `registry.py`) rather than a single file
format: a `PortfolioSource` ABC with one `fetch(as_of_date) -> list[Holding]`
method, implemented first by a custodian/PMS API connector (decision 1) and
a CSV/XLSX fallback for manual overrides/backfills, both landing in the
same append-only snapshot store above so the rest of the system can't tell
which produced a given snapshot.

`SecurityRef.company_id` is the join key into everything the pipeline
already computes — `CompanyRef`, `ExtractionRecord`, `RevenueExposureResult`,
`IndirectExposureResult`, taxonomy match results. Resolving it is an
explicit, reviewable step (an ISIN→`company_id` crosswalk, user-supplied or
LLM-assisted fuzzy-matched with mandatory human confirmation for anything
below a confidence threshold — same review-queue pattern as everything
else in this codebase, never a silent auto-match) because a wrong issuer
match silently corrupts every euro figure downstream of it.

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
- security native currency (informational only — everything sums in EUR)
- any ratified `Taxonomy` (thematic exposure, reusing
  `RevenueExposureResult`/match verdicts already computed for that issuer)
- any custom tag the user attaches to a portfolio or security

Every query also takes an `as_of` (single snapshot date, default latest) or
`date_range` (a **trend** mode, returning one grouped result per snapshot
date instead of one) — the mechanism decision 5's time-tracking
requirement needs, and otherwise the same code path.

Two aggregation modes, matching how these numbers are actually used:
1. **Sum of market value** grouped by dimension (a plain exposure figure —
   "EUR 4.2m in BMW equity, across 3 portfolios").
2. **Value-weighted average of a data point** grouped by dimension (e.g.
   weighted-average carbon intensity, weighted-average thematic exposure %)
   — `Σ(holding.market_value_eur × datapoint.value) / Σ(holding.market_value_eur)`,
   with holdings missing the data point either excluded and the coverage
   % reported (never silently treated as zero) — same "don't fabricate an
   absence into a number" principle as `grounding.py`'s citation checks.
   When run in trend mode, this also picks the data-point observation
   whose `as_of` most closely precedes each snapshot date, so a WACI trend
   line reflects "the best information known as of that date," not a
   look-ahead from a later restatement.

This engine is what answers "how many million euro is the exposure to
stocks from BMW": filter holdings to `asset_class == equity` and
`company_id == <BMW>`, sum `market_value_eur` across all portfolios at the
latest snapshot date. No LLM call is needed for that question at all —
which matters for the next section.

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
    as_of: str | None = None          # single snapshot date; None = latest
    date_range: tuple[str, str] | None = None  # trend mode over §3's date_range
```

**5b. Natural-language Q&A agent** (`backend/arp/portfolio/qa_agent.py`).
For direct questions like *"how many million euro is the exposure to
stocks from BMW?"*: the LLM's only job is to parse the question into an
`AnalyticSpec` (tool-call / structured-output style, reusing
`llm/base.py`'s `complete_structured`), the deterministic engine executes
it and returns the real number, and the LLM's final answer is templated
from that real, computed result plus the spec that produced it (so the
answer is always inspectable: "this is `Σ market_value_eur` for
`company_id=BMW, asset_class=equity` across 3 portfolios, as of the
2026-08-13 snapshot"). This mirrors the grounding discipline already
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
- Controversy/climate-risk-event flag (derived from the news feed, §6b)

### 6a. Sourcing and validation (decision 4)

The **internal structured ESG/emissions API** is the primary source for
every climate data point above — a new `PortfolioDataSource` in
`backend/arp/portfolio/climate/esg_api_source.py`, same `source="internal_api"`
tier as `CatalogueDataPoint` in the §4 mapping cascade, so it slots in
ahead of extraction with zero new plumbing in the cascade itself.

What *is* new is **validation**: since the requirement is to check the
internal API's figures against company disclosures, not just trust them,
every internal-API value for a company also gets an independent
Extractor→Verifier pass against that company's actual reports (reusing the
Extraction Engine exactly as it runs today, just with a field built from
the climate schema — same precedent `revenue_exposure/resolver.py`'s
`resolve_from_extraction` already sets for building an ad hoc field on the
fly). The two values are compared with a configurable tolerance:

- **Match** → high-confidence, both values recorded, internal-API value
  used for computation.
- **Mismatch** → internal-API value is still used for computation (it's
  the operational source of truth), but the record is stamped
  `conflicting_sources=True` (the field already exists on `ExtractedField`
  in `schemas/datapoints.py`) and routed to the review queue, with both
  values and the extracted citation shown side by side — never silently
  reconciled.
- **API has no value, report does** → extracted value used, tagged as
  such (source="extracted", not "internal_api"), so coverage reporting
  distinguishes "no data anywhere" from "only found in disclosures."

This validation pass runs as a background batch job (checkpointed/resumable,
same `RunManifest` pattern as every other run type), not synchronously per
query, since it's an LLM-cost operation and the aggregation engine (§3)
must stay zero-LLM and fast.

### 6b. News-derived risk signals (decision 4)

A new connector type, `NewsSource` (`backend/arp/portfolio/news/source.py`),
mirrors `DocumentSource`/`DocumentSourceRegistry` exactly (`fetch(company,
since) -> list[NewsItem]`) rather than inventing a new ingestion shape.
Company-specific articles are resolved to `company_id` the same way
securities are (§2), then an LLM classification pass (Advocate/Adjudicator
is overkill here; a single schema-constrained classification call per
article, same shape as `taxonomy_sources/empirical.py`'s field-on-the-fly
pattern) tags each article for climate/controversy relevance and severity.
Every resulting risk flag carries a **grounded citation to the source
article** (headline + verbatim excerpt, checked by the same programmatic
grounding checker as every other citation in this codebase —
`grounding.py`) so a flag is always traceable to real text, never an
LLM paraphrase presented as fact. Flags feed the controversy data point in
§6, and (§3's trend mode) a time series of flag counts/severity per issuer
or portfolio.

### 6c. Portfolio-level climate metrics

Computed by `backend/arp/portfolio/climate/metrics.py` on top of the §3
aggregation engine (financed-emissions math per the
[PCAF](https://carbonaccountingfinancials.com/) standard, since that's the
accepted methodology and shouldn't be reinvented):

- **WACI** (weighted-average carbon intensity): the weighted-average
  aggregation mode from §3, applied to the carbon-intensity data point —
  and, via `date_range`, a WACI trend line over time.
- **Financed emissions**: `Σ (holding.market_value_eur / company.EVIC) × company.scope_1_2_emissions`,
  attribution factor per PCAF; `EVIC` (enterprise value incl. cash) is
  itself a data point sourced via the same §6a cascade.
- **Data coverage %**: always reported alongside every climate number —
  what fraction of portfolio market value has a value from the internal
  API, from extraction only, from the structural proxy, or is missing
  entirely — because a climate number with silent 40% coverage is actively
  misleading.
- **Estimated (proxy) emissions for non-disclosing issuers**: an *opt-in*,
  clearly-flagged tier reusing the existing indirect-exposure I-O
  machinery (`indirect_exposure/leontief.py` already carries sector-level
  economic intensity data) as a sector-average proxy — same
  opt-in/clearly-labeled-as-a-proxy pattern the indirect exposure tier
  already uses for thematic exposure, never blended into the disclosed
  number without a visible "estimated" tag.

This becomes its own frontend tab ("Climate Analytics") with a portfolio
picker, WACI/financed-emissions summary tiles with trend charts, a
coverage breakdown (internal API / extracted / estimated / missing), a
controversy/news feed panel per issuer, and drill-down to the same
Analytics Builder from §5 pre-filtered to climate data points — it's a
skinned, pre-configured application of the general engine, not a parallel
implementation.

## 7. Backend layout (new)

```
backend/arp/portfolio/
  __init__.py
  sources/
    base.py               # PortfolioSource ABC: fetch(as_of_date) -> list[Holding]
    custodian_api.py       # primary connector (decision 1)
    file_import.py          # CSV/XLSX fallback for manual overrides/backfills
    registry.py               # fan-out + snapshot de-dup, mirrors ingestion/registry.py
  entity_resolution.py  # ISIN/ticker -> company_id crosswalk + review queue
  aggregation.py         # dimensions, grouping, weighted-avg, as_of/date_range engine (no LLM)
  datapoint_mapping.py   # per-issuer data point resolution cascade + history series
  analytics.py            # AnalyticSpec store/executor
  qa_agent.py              # NL question -> AnalyticSpec -> executed answer
  news/
    source.py                # NewsSource ABC + connector, mirrors ingestion/base.py
    classifier.py             # per-article climate/controversy relevance + grounding
  climate/
    __init__.py
    schemas.py            # built-in climate DataPointSchemas
    esg_api_source.py       # internal structured ESG/emissions API connector
    validation.py             # internal-API vs extracted-from-reports cross-check
    metrics.py             # WACI, financed emissions, coverage (incl. trend mode)
backend/arp/schemas/portfolio.py   # Portfolio, Holding, SecurityRef, AnalyticSpec
backend/arp/api/routers/portfolio.py   # holdings sync, aggregation, analytics, Q&A
backend/arp/api/routers/climate.py     # climate-specific endpoints, news feed
backend/tests/test_portfolio_*.py
portfolios/
  <portfolio_id>/snapshots/<as_of_date>.jsonl   # append-only holdings snapshots
  registry.json                                   # Portfolio metadata
  # (same file-based, no-DB pattern as taxonomies/, runs/)
```

CLI additions (`arp portfolio ...`, `arp climate ...`), mirroring the
existing `arp theme ...` / `arp taxonomy ...` command families, since the
CLI is the documented path for unattended/batch operation — in particular
a scheduled custodian-API pull that appends a new dated snapshot, the same
recurring-job shape `discovery/scheduler.py` already implements for
document discovery.

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
| Review queue for low-confidence matches | `orchestration/review_queue.py` as-is | entity-resolution + API/report mismatches routed into it |
| Connector fan-out (multi-source, per-item, one failure doesn't block others) | `ingestion/base.py` + `registry.py` pattern | `PortfolioSource`/`NewsSource` connectors (§2, §6b) |
| Extractor → Verifier → grounding check for a field | `extraction/` pipeline as-is | applied to climate fields + news articles (§6a, §6b) |
| `conflicting_sources` flag on a resolved field | `schemas/datapoints.py::ExtractedField` as-is | populated by internal-API-vs-extraction cross-check (§6a) |
| File-based, resumable, checkpointed runs | `storage/run_store.py` pattern | `portfolios/` snapshot store, append-only (§2) |
| Holdings, positions, portfolios, custodian/news connectors | — | new schemas + connectors (§2, §6a, §6b) |
| Deterministic aggregation/weighting engine incl. time-range trend mode | — | new, zero-LLM (§3) |
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
- Internal-API climate figures that disagree with what the Extraction
  Engine independently reads out of the company's own reports are flagged
  (`conflicting_sources=True`) and routed to review, not silently
  reconciled in either direction (§6a).
- News-derived risk/controversy flags always carry a grounded, checkable
  citation to the source article — an LLM summary is never presented as a
  fact without the excerpt it came from (§6b).
- Historical snapshots and data-point observations are append-only; a
  later correction adds a new observation rather than rewriting history,
  so a trend chart reflects what was actually known at each point in time.
- Saved `AnalyticSpec`s are versioned and inspectable, same as the
  taxonomy library, so a recurring report's definition can't silently
  drift.

## 10. Remaining open questions

The five original questions are resolved (see the decisions block at the
top). What's still needed before implementation can start on the
API-dependent pieces:

1. **Custodian/PMS API**: which system, what's the auth mechanism
   (API key, OAuth, mTLS), what's the response schema, and what's the
   intended pull frequency (daily/real-time)?
2. **Internal ESG/emissions API**: endpoint, auth, response schema, and
   which of the climate fields in §6 it actually covers today vs. what
   still has to fall back to extraction.
3. **News feed**: which vendor/API, how articles are already tagged to a
   company (ticker/ISIN/name — determines how much entity-resolution work
   `news/source.py` needs to do), and expected volume (affects the
   classification pass's batching/cost).
4. **Snapshot retention/backfill**: how far back does historical tracking
   need to go at launch — start the time series from day one only, or
   backfill from an existing data source?
5. **Validation tolerance**: what threshold between the internal API's
   figure and the extracted figure should count as a "mismatch" worth
   flagging (§6a), and does that threshold vary by metric (e.g. tighter
   for Scope 1/2 than Scope 3, which is inherently estimated upstream)?

## 11. Phased roadmap

- **Phase 0 — Foundations** ✅ *(built, mock connector)*: `schemas/portfolio.py`,
  `PortfolioSource` connector interface + `MockCustodianSource` standing in
  for the real custodian API, entity resolution + review queue,
  append-only `portfolios/` snapshot store (`storage/portfolio_store.py`).
- **Phase 1 — Aggregation & direct answers** ✅ *(built)*: deterministic
  aggregation engine (`portfolio/aggregation.py`) incl. `as_of`/`date_range`,
  built-in dimensions, API + CLI for grouped market-value queries. This
  alone answers "how many EUR million exposure to BMW," at the latest
  snapshot or any past one -- verified against the mock dataset.
- **Phase 2 — Data-point mapping & Analytics Builder** ✅ *(built)*:
  datapoint mapping cascade (`portfolio/datapoint_mapping.py`),
  `AnalyticSpec` + saved analytics (`portfolio/analytics.py`), API/CLI
  query execution. The Analytics Builder *UI* itself is not built.
- **Phase 3 — NL Q&A agent** ✅ *(built, needs a live API key to run)*:
  `qa_agent.py`, question → spec → grounded answer, `arp portfolio ask` /
  `POST /api/portfolio/ask`. Unit-tested via the existing `FakeLLMClient`
  convention; a chat-style UI panel is not built.
- **Phase 4 — Climate Analytics** ✅ *(mostly built, mock connectors)*:
  built-in climate schemas (`climate/schemas.py`), a mock internal-ESG-API
  connector (`climate/mock_esg_source.py`) + report-validation cross-check
  (`climate/validation.py`), a mock news connector + LLM classifier
  (`news/mock_source.py`, `news/classifier.py`), WACI/financed-emissions/
  coverage engine (`climate/metrics.py`) incl. trend mode. Trend *charts*
  and the dedicated dashboard tab (both frontend) are not built; the real
  ESG-API/news-vendor connectors (replacing the `mock_*` modules) are not
  built.
- **Phase 5 — Estimated/proxy tier & scenario analysis**: opt-in
  structural climate proxy, what-if reweighting ("if we exit BMW, how does
  portfolio WACI change" — a pure re-run of §3's engine on a hypothetical
  holdings set, still zero-LLM). Not started.

Phases 0–2 are the minimum viable version of the request; Phase 3 is what
makes it feel "agentic" end-to-end; Phase 4 is the explicitly-requested
separate climate section; Phase 5 is stretch. What remains everywhere
above: the React frontend (no UI was built this pass -- everything is
reachable via the CLI and the FastAPI routers), and swapping each `mock_*`
connector for a real one once decision 4's actual API/vendor details
(§10) are available.
