# Superset as the dashboard foundation: Phase 1

Status: draft for review. Date: 2026-10-03. Builds on
`2026-10-03-superset-integration-design.md` (shipped on this branch).

## Goal

Superset becomes the single place dashboards live in Risk Monitoring, for both
hand-built and AI-built ones. Phase 1 replaces the old Generative BI tab and
Pivot Explorer with Superset. Phases 2 and 3 (climate observations, news flags,
alerts, governance views) are **not** touched: Standard Analytics, Company
Profiles, Monitoring & Alerts, Governance & Audit and Ask the Portfolio stay
exactly as they are.

## Scope

1. **Remove the old Generative BI** (`arp/portfolio/genbi/`).
2. **One Superset tab** replaces Generative BI, Pivot Explorer and the current
   "Superset BI" tab: a dropdown of every `arp-` dashboard, the "describe a
   dashboard" box, and the embed.
3. **Provisioned standard dashboard `arp-risk-exposure`**, created idempotently by
   `arp bi bootstrap` from a committed template, with Superset native filters.
4. **Bootstrap copies catalogue descriptions** (dataset and column) into Superset.
5. **Opt-in embedding for hand-built dashboards:** a dashboard is embeddable and
   listed when its slug starts with `arp-` (a human sets the slug in Superset's
   dashboard Properties). No new mechanism.

Out of scope: Phases 2 and 3; Standard Analytics' climate charts; per-mandate
row-level security; native filters in AI-designed dashboards.

## Requirements

- Nothing outside `arp/portfolio/genbi/` and its direct consumers is deleted;
  `AnalyticSpec`, `PivotSpec`, `analytics.py`, `aggregation.py` and saved analytics
  stay (Ask the Portfolio and the stores use them).
- Every dashboard the code creates stays unpublished, including the provisioned
  one (a person publishes it).
- The provisioned template uses only the 8 allowlisted viz types and catalogue
  datasets; the validator and compiler are the same ones the AI path uses.
- Re-running bootstrap changes nothing when the dashboard already exists with
  all its charts; a dashboard a person extended is left alone.

## Design

### 1. Removal (mechanical)

Delete: `backend/arp/portfolio/genbi/*`, `api/routers/genbi.py`,
`frontend/.../GenerativeBI.tsx`, the Generative BI types/API block in
`frontend/src/types.ts` and `api/client.ts`, `golden_set/planner_runner.py`,
`planner_schema.py`, `data/planner_cases.json`, the `planner` command in
`cli/golden_set.py` (keep `bi`), the `bi` group in `cli/portfolio.py`,
`test_genbi_*.py`, `docs/GENBI_LANDSCAPE_REVIEW.md`. Remove
`save_dashboard/list_dashboards/get_dashboard` (and `dashboards_path`) from
`PortfolioStore` and `PostgresPortfolioStore` together (the parity test compares
their public surface). Update docs that mention it (METHODOLOGY, PORTFOLIO_RISK_
EXPOSURE_PLAN, README, the two Superset specs/plans). Saved Generative BI
dashboards (`dashboards.json`) are discarded.

### 2. Data layer

New view `bi.holdings_history`: the columns of `bi.holdings` for every snapshot
(no "latest" filter), same safe-date handling. New catalogue dataset
`holdings_history` with the same metrics as `holdings`; `as_of_date` is its
temporal column. `bi.holdings` stays the latest-snapshot view.

### 3. Dashboard templates and native filters

A template is a committed JSON file (`backend/arp/bi/templates/*.json`):
`{slug, title, goal, charts: [ChartSpec], native_filters: [{name, dataset,
column}]}`. `compile_native_filters(filters, dataset_ids) -> dict` produces
Superset's `json_metadata.native_filter_configuration`; the dashboard create
call accepts an optional `json_metadata`. Native filters are for provisioned
templates only (the AI plan has none). `arp bi bootstrap` provisions each
template: look up the slug; create charts and the dashboard when absent; rebuild
only when the dashboard has fewer charts than the template; otherwise leave it.

`arp-risk-exposure` (all on `holdings` unless noted): total exposure (big
number), exposure by fund (bar), by sector (treemap), by country (table), by
currency (bar), asset class (pie), sector x fund (pivot), and exposure over
time by fund (line on `holdings_history`). Native filters: portfolio_name,
sector, country.
Open risk: whether one native filter can scope charts on two datasets in
Superset 5.0. The plan starts with a live spike; if it fails, the time chart
gets its own portfolio filter on `holdings_history`.

### 4. Descriptions

`arp bi bootstrap` writes each dataset's `description` and each column's
`description` from `catalog.VIEW_DATASETS` (idempotent PUT), next to the existing
metric sync.

### 5. API and UI

`GET /api/bi/dashboards` -> `[{id, slug, title, published}]` for slugs starting
with `arp-` (Superset list API filtered server-side; no secrets). The embed
endpoint is unchanged (slug rule). The frontend replaces the `genbi`, `pivot`
and `superset` sub-tabs with one `dashboards` tab labelled "Dashboards
(Superset)": a picker (defaults to `arp-risk-exposure`), the existing brief box
and embed. The portfolio/date selection pane still serves the remaining tabs;
on this tab the Superset filter bar replaces it.

## Trade-offs

- Pivot Explorer's weighted-average climate pivots go away (WACI stays in
  Standard Analytics, unchanged).
- Saved portfolio groups do not apply on the Superset tab.
- The provisioned dashboard exists only after `arp bi bootstrap`.

## Testing

Unit: native-filter compiler (golden JSON), list endpoint, description sync
(mock client), bootstrap provisioning idempotency (fake client: absent / present
/ fewer charts / extended). Postgres: `bi.holdings_history` equals `holdings`
row-for-row across snapshots, junk dates excluded. Live (marker
`live_superset`): bootstrap provisions `arp-risk-exposure`, every chart returns
rows, native filters present in the dashboard, descriptions visible via the
dataset API, an `arp-` hand-made dashboard appears in the list and a non-`arp-`
one does not. Removal: full backend suite equals the known pre-existing
failures; frontend lint/build/test pass; grep finds no `genbi` outside history.

## Decisions taken

- Phase 1 only; Standard Analytics and the workflow tabs untouched.
- One Superset tab replaces three tabs.
- Hand-built dashboards opt in to embedding via an `arp-` slug.
