# Superset integration: LLM-designed charts and dashboards

Status: draft for review. Date: 2026-10-03.

## Goal

Apache Superset becomes the place to build and browse dashboards over ARP data.
A plain-language brief or question makes an LLM **design** Superset charts and
dashboards. The LLM plans, deterministic code compiles the plan into Superset
objects, and Superset computes every number with SQL on governed views. This
keeps ARP's rule: the LLM plans, deterministic code computes.

The existing Generative BI (`backend/arp/portfolio/genbi/`) is unchanged. It
stays the governed, narrated, portfolio-only path.

## Scope (v1)

In: portfolio holdings, company facts, run records, documents.
Out: narration or grounding of prose, per-mandate row-level security (a hook
only), Superset alerts and reports, replacing the current Generative BI.

## Requirements

1. The LLM never writes SQL or raw Superset `form_data`. It emits a closed
   `ChartPlan`.
2. Nothing is written to Superset until the plan passes validation.
3. Everything is created **unpublished** under a service account. Publishing is
   a human act. Superset cannot stop an owner from publishing, so this is
   enforced and tested in ARP code.
4. Only reviewed facts are charted by default (see Data layer).
5. Needs Postgres (`ARP_PORTFOLIO_BACKEND=postgres` and the projection hooks
   on). The file-based default has no SQL surface for Superset.

## Architecture

```
brief/question
  -> planner (LLM, schema-forced)      arp/bi/planner.py
  -> validator (deterministic)         arp/bi/validator.py   (+1 repair round)
  -> compiler (pure functions)         arp/bi/compiler.py
  -> Superset REST (draft dashboard)   arp/bi/superset_client.py
  -> Superset runs SQL on bi.* views as bi_reader
```

### Data layer: the `bi` schema (views only)

Postgres stores dates as strings and fact values as JSONB, which Superset
cannot chart directly. The `bi` schema fixes that. The `bi_reader` role has
`SELECT` on this schema only.

| View | Source | Notes |
|---|---|---|
| `bi.holdings` | holdings + securities + companies + portfolios | `as_of_date` cast to `date`; EUR value, weight, sector, country, asset class |
| `bi.company_facts` | company_facts | current rows with status `approved`, `edited`, `auto_approved` only; `value_num`/`value_text` extracted from JSONB; `status`, `confidence`, `reviewer` |
| `bi.company_facts_pending` | company_facts | current rows with status `pending_review`; `rejected` is in no view |
| `bi.run_records` | company_records | one row per company per run; `needs_review`, `overall_confidence`; `payload` excluded |
| `bi.documents` | document_registry | company, doc type, first/last seen as dates; no file paths |

Views are created by the existing `arp db init-postgres` path and follow the
project's Postgres migration approach (DB review, F6).

### Semantic layer

A metric catalogue in `arp/bi/catalog.py`, provisioned into Superset as dataset
metrics with plain-language descriptions: `Exposure (EUR)`, `Holdings`,
`Avg confidence`, `% needing review`, and so on. The planner prompt is built
from these descriptions, so they also act as the business-alias layer
(GENBI_LANDSCAPE_REVIEW §5.4).

### ChartPlan (closed spec)

`{datasets, charts[{viz_type, dataset, metrics, groupby, filters, time_range}], layout}`

- `viz_type` is one of about 8: big number, bar, line, pie, table, pivot table,
  heatmap, treemap. The allowlist lives in `catalog.py`.
- Datasets must be `bi.*` views. Columns and metrics are checked against
  Superset's own dataset API before anything is created.

### Compile and publish

The compiler turns a plan into Superset chart `params` and dashboard
`position_json`. The client creates dataset (if missing), charts, then the
dashboard with `published=false`. If a later step fails, charts created so far
are deleted. Names and slugs are keyed by a plan hash, so a retry is idempotent.

### Ask the data

A question becomes a one-chart plan and lands on a "Scratch" dashboard.

## Components

| File | Job |
|---|---|
| `arp/bi/catalog.py` | views, metric catalogue, viz allowlist (single source of truth) |
| `arp/bi/planner.py` | brief to `ChartPlan` via the existing `LLMClient` |
| `arp/bi/validator.py` | checks and one bounded repair round, as in the portfolio planner |
| `arp/bi/compiler.py` | plan to Superset params and layout |
| `arp/bi/superset_client.py` | thin REST client: login, CSRF, create/read/delete |
| `arp/bi/service.py` | orchestration and cleanup |
| `arp/api/routers/bi.py` | `POST /api/bi/design`, `/api/bi/ask`, `/api/bi/embed-token` |
| `arp/cli/bi.py` | `arp bi bootstrap` (idempotent) |
| frontend | new **Superset** tab: brief box + embedded dashboard |

## Deployment

- `docker-compose.yml`: `superset` service on a pinned 5.x image, bound to
  `127.0.0.1:8088`, using a separate `superset` database in the existing
  Postgres container. No Redis in v1.
- Mounted `superset_config.py`: embedding on, guest tokens on, `frame-ancestors`
  limited to the ARP UI origin.
- `SUPERSET_SECRET_KEY` and the `bi_reader` password come from `backend/.env`,
  no defaults.
- `arp bi bootstrap` registers the `bi` database connection, creates datasets
  and metrics, and creates the `arp_designer` service account.

## Error handling

- Superset unreachable: clear API error, nothing written.
- Plan rejected by the validator: one repair round, then a refusal that names
  the reason. No partial objects.
- Partial create: compensating delete of what was created.

## Testing

1. Unit tests for validator and compiler with golden JSON.
2. A planner eval set under `arp golden-set` (briefs with known-correct chart
   shapes, plus briefs that must be refused), mirroring the portfolio planner's.
3. An integration test against a live Superset container: create a dashboard,
   read it back, delete it, and assert it was never published. Marked so it
   does not run by default.
4. A Postgres test that each `bi` view returns the expected rows from seeded
   demo data, and that `bi_reader` cannot read any base table.

## Risks

- Superset's chart `params` format changes between versions. Mitigation: pin
  the version; the integration test is the contract.
- Chart `params` shapes in the compiler are written from Superset's API and
  must be verified against the pinned version during implementation.
- The seeded demo data lives in files by default, so a Postgres seed step is
  needed before a demo works.

## Decisions taken

- Scope: portfolio plus company facts, run records, documents.
- Unreviewed facts are excluded from charts by default; a separate pending view
  exists for review-backlog questions.
- The LLM drives Superset (designs charts and dashboards), not just SQL.
