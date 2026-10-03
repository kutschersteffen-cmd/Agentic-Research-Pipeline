# Projects: stored dashboards and data that open automatically (Phase 1b)

Status: draft for review. Date: 2026-10-03. Builds on the Phase 1 spec
(`2026-10-03-superset-foundation-phase1-design.md`, PR #91).

## Goal

A user can define a dashboard, store it, and open it again easily. A **project**
bundles the dashboard definitions and the source data they were built on.
Selecting a project loads the data and (re)creates its dashboards in Superset
automatically, then shows them.

## Scope

1. A file-based project store with an API and CLI.
2. Opening a project: replay its data imports into Postgres, provision its
   dashboards in Superset, return what to show.
3. Saving a dashboard into a project: AI-designed (stored as a template),
   standard templates, and hand-built (stored as a Superset export bundle,
   gated on a live spike).
4. Project scoping so projects never mix in shared Postgres/Superset.
5. UI: project selector, new project with file upload, save-to-project, open.

Out of scope: arbitrary-table data kinds (only kinds that have an importer:
DWS constituent xlsx now), project delete/versioning/sharing, per-project
access control (the API has no auth today), whole-project zip export (cheap
follow-up).

## Requirements

- Source data files are user data. They live only under the git-ignored
  projects directory (`ARP_PROJECTS_DIR`, default `projects/`), never in the repo.
- Open is idempotent: opening twice changes nothing the second time (same
  imports, dashboards `unchanged`).
- Every dashboard stays an **unpublished draft**; opening never publishes and
  never deletes charts (same provisioning rules as Phase 1).
- A project id and every filename are validated with `safe_id`-style rules; no
  path traversal; uploads are bounded (50 MB per file, extension allowlist
  `.xlsx`) and stored under a sanitized name.
- Needs the Postgres backend and a configured Superset; otherwise open returns a
  clear 503 (no partial work).
- Two projects never mix: portfolios and dashboards are namespaced by project.

## Design

### Project store

`projects/<id>/project.json`:
`{id, name, description, created_at, data: [{kind, files: [name], params}],
dashboards: [{slug, title, source: "template" | "superset-export", file}]}`,
plus `data/<files>` and `dashboards/<slug>.json|zip`. `ProjectStore` (new,
`arp/projects/store.py`) reads/writes with the repo's atomic JSON helpers and a
per-project lock (`KeyedLock`). Ids are `^[a-z0-9][a-z0-9-]{0,62}$`.

### Scoping

The `bi.holdings` and `bi.holdings_history` views gain a trailing column
`project_id`, derived from the portfolio tag `project:<id>` (NULL for portfolios
outside any project, e.g. the demo seed). The importer namespaces portfolio ids
(`<project>-dws-<fund isin>`) and tags them `project:<id>`. Every chart of a
project dashboard gets the SIMPLE filter `project_id == <id>` at compile time;
the standard `arp-risk-exposure` dashboard stays unfiltered (all data).

### Open (`POST /api/projects/{id}/open`)

Under the project lock: (1) for each data source, run its importer with the
stored files and params (kind `dws-constituents` ->
`constituent_import.import_constituents(..., project_id=<id>)`); (2) for each
stored dashboard, provision it (`template`: compile with the project filter and
`provision()` from Phase 1, slug `arp-<project>-<name>`; `superset-export`:
import the bundle, see Spike); (3) return `{data: [...summaries],
dashboards: [{id, slug, title, published, status}]}`. Failures name the step and
leave earlier steps in place (they are idempotent).

### Save a dashboard

`POST /api/projects/{id}/dashboards` with `{title, plan}` where `plan` is the
`ChartPlan` the designer returned: validate it (same validator), store it as a
template (`DashboardTemplate`, slug `arp-<project>-<slugified title>`), and
provision it. Hand-built: `POST .../dashboards/export` with a Superset
dashboard id (must be an `arp-` dashboard): download its export zip via the
Superset API and store it.

### Spike (first task of the plan)

Verify live on Superset 5.0.0: `GET /api/v1/dashboard/export/` and
`POST /api/v1/dashboard/import/` (multipart, `overwrite=true`, database
password map for the masked connection) round-trip a hand-built dashboard onto
a fresh metadata DB, with datasets matched by UUID. If it does not work
reliably, hand-built dashboards ship as "export only" (download the zip, store
it, document the manual import) and `superset-export` entries are listed but
not auto-imported.

### Data upload

`POST /api/projects/{id}/data` (multipart): validates extension and size, stores
the file, appends it to the matching data source (`dws-constituents` for DWS
xlsx; `notional_eur` param required, default shown in the UI). Parse errors are
reported at open time with row context, not at upload.

### UI

On the Dashboards tab: a project selector (list from `GET /api/projects`;
"Standard dashboards" is the no-project choice), "New project" (name, notional,
file upload), "Open" (runs open with a progress/summary panel), "Save to
project" on a designer result and on the picker for `arp-` dashboards.
Selecting a project calls open automatically, then selects its first dashboard.

### CLI

`arp project create|add-data|list|open` for scripting and for loading projects
without the UI.

## Trade-offs

- Replaying importers (not DB dumps) keeps projects small, auditable and
  portable, but only supports data kinds that have an importer.
- Template storage re-creates a dashboard from the plan; manual edits made in
  Superset to an AI dashboard are not captured unless it is also saved as an
  export bundle.
- A project's data lives in the shared Postgres after open; nothing is removed
  when another project is selected.

## Testing

Unit: store (create/list/validate ids/paths/upload limits), API (TestClient,
fake Superset client and importer), project filter compile (golden), importer
namespacing/tags, open idempotency (fake client: absent/present/fewer/extended).
Postgres: `project_id` in both views from the tag, NULL without it, two projects
do not mix. Live (`live_superset`): create a project with a synthetic xlsx,
open it twice (second `unchanged`), dashboards return rows only for that
project, a second project's numbers are separate; if the spike passes, a
hand-built dashboard round-trips through export bundle and import.

## Decisions taken

- Projects are folders of replayable sources and dashboard definitions.
- Selecting a project opens it automatically.
- Namespacing by portfolio tag + view column + chart filter.
