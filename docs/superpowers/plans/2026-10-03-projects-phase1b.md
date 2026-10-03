# Projects (Phase 1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user defines a dashboard, stores it in a project together with the data it was built on, and selecting the project reloads the data and recreates the dashboards in Superset automatically.

**Architecture:** A project is a git-ignored folder of replayable data sources (copies of uploaded xlsx plus params) and stored dashboard definitions. `open` replays the importer into Postgres with project-namespaced portfolios tagged `project:<id>`, provisions each stored dashboard as an unpublished draft with a `project_id == <id>` chart filter, and returns what to show. Scoping is a `project_id` column on the `bi.holdings*` views.

**Tech Stack:** FastAPI + Typer (backend), SQLAlchemy/Postgres views, `SupersetClient` REST, React/Vite (frontend), pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-10-03-projects-phase1b-design.md` (builds on `2026-10-03-superset-foundation-phase1-design.md`).

## Global Constraints

- Source files are user data: only under `ARP_PROJECTS_DIR` (default `projects/`, git-ignored), never in the repo.
- Open is idempotent: second open changes nothing (importer overwrites the same snapshot, dashboards report `unchanged`).
- Every dashboard stays `published=false`; open never publishes and never deletes charts (Phase 1 provisioning rules, `arp/bi/templates.py`).
- Project id regex `^[a-z0-9][a-z0-9-]{0,62}$`; filenames pass `safe_filename`; uploads `.xlsx` only, max 50 MB, stored under a sanitized name.
- Needs `portfolio_backend="postgres"` and a configured Superset, else open returns 503 with no partial work.
- Project dashboard slugs are `arp-<project>-<name>` (only `arp-` slugs are embeddable/listed).
- No Superset response bodies in API errors (reuse `_bad_gateway` in `arp/api/routers/bi.py`).
- Standard dashboard `arp-risk-exposure` stays unfiltered.
- Out of scope: other data kinds, project delete/versioning/sharing/auth, whole-project zip export.

## Review Focus

- Two projects importing the same fund ISIN: portfolio ids must not collide (`<project>-dws-<isin>`), numbers must not mix.
- Project id with uppercase, `..`, `/`, or 64+ chars: rejected with 422, nothing written to disk.
- Upload named `../x.xlsx`, `evil.xlsm`, or over 50 MB: rejected, no partial file left.
- Open when Superset is down mid-way: data import stays done, response names the failing step, a retry succeeds.
- A project with zero data sources or zero dashboards: open returns empty lists, not an error.
- Dashboard saved with a title that slugifies to empty or collides with an existing stored slug: clear 422 / replaces the same slug deterministically.

---

### Task 1: Spike: Superset dashboard export/import round trip

**Files:**
- Create: `backend/tests/test_bi_live_export.py` (marker `live_superset`, skipped without `ARP_TEST_SUPERSET_URL`; mirror `test_bi_live_superset.py` setup)
- Create: `docs/superpowers/specs/2026-10-03-projects-phase1b-spike.md` (result)
- Modify: `backend/arp/bi/superset_client.py` (only if the spike passes)

**Interfaces:**
- Produces (if it passes): `SupersetClient.export_dashboard(dashboard_id: int) -> bytes` and `SupersetClient.import_dashboard(bundle: bytes, db_passwords: dict[str, str]) -> None`.

- [ ] **Step 1: Write `test_export_then_import_roundtrip`**: provision `arp-risk-exposure`, export it, delete the dashboard (not charts or datasets), import the bundle with `overwrite=true` and the `arp_bi` password map, assert `find_dashboard("arp-risk-exposure")` returns an id and `dashboard_charts` returns 8 charts, and the dashboard is `published=false`.
- [ ] **Step 2: Run live** (stack env in `/tmp/claude-0/p1-stack/`): `ARP_TEST_SUPERSET_URL=... pytest -m live_superset tests/test_bi_live_export.py -v`. Try `GET /api/v1/dashboard/export/?q=!(<id>)` and `POST /api/v1/dashboard/import/` (multipart `formData`, `overwrite`, `passwords` JSON `{"databases/arp_bi.yaml": "<bi_reader pw>"}`).
- [ ] **Step 3: Second scenario**: import onto a fresh metadata DB (new `superset_live2` DB) after `arp bi bootstrap`; datasets must match by UUID.
- [ ] **Step 4: Write the result doc**: pass or fail for each scenario, exact endpoints/params that worked, and the decision for Task 8 ("auto-import" or "export only").
- [ ] **Step 5: Commit** the test, the result doc, and (on pass) the two client methods with unit tests against a fake `httpx` transport.

### Task 2: Project store and config

**Files:**
- Create: `backend/arp/projects/__init__.py`, `backend/arp/projects/store.py`
- Modify: `backend/arp/config.py` (add `projects_dir: Path = Field(default=REPO_ROOT / "projects")`), `.gitignore` (`projects/*`, `!projects/.gitkeep`)
- Test: `backend/tests/test_projects_store.py`

**Interfaces:**
- Produces:
  - `class Project(BaseModel)`: `id, name, description="", created_at, data: list[DataSource], dashboards: list[StoredDashboard]`
  - `DataSource`: `kind: Literal["dws-constituents"], files: list[str], params: dict`
  - `StoredDashboard`: `slug: str, title: str, source: Literal["template","superset-export"], file: str`
  - `class ProjectStore(root: Path)` with `create(id, name, description="") -> Project`, `get(id) -> Project` (raises `ProjectNotFound`), `list() -> list[Project]`, `add_data_file(id, filename: str, content: bytes, params: dict) -> Project` (enforces ext/size, appends to the `dws-constituents` source, merges params), `file_path(id, kind_dir: Literal["data","dashboards"], name) -> Path`, `save_dashboard(id, slug, title, source, payload: bytes) -> Project`, `lock(id)` context manager.
  - `ProjectError(ValueError)`, `ProjectNotFound(ProjectError)`; constants `MAX_UPLOAD_BYTES = 50 * 1024 * 1024`, `ID_RE`.

- [ ] **Step 1: Write failing tests**: create/get/list round trip; duplicate id raises `ProjectError`; ids `Foo`, `a/b`, `..`, `-x`, 64-char id rejected; `add_data_file` rejects `../x.xlsx`, `a.xlsm`, `MAX_UPLOAD_BYTES + 1`, leaves no file behind; second `add_data_file` appends to the same source; `save_dashboard` with an existing slug replaces its entry.
- [ ] **Step 2: Run to verify fail**: `pytest backend/tests/test_projects_store.py -v` → ImportError.
- [ ] **Step 3: Implement** `store.py` using `atomic_write_text` / `read_text_utf8` (`arp/storage/atomic_io.py`), `safe_filename` (`arp/storage/safe_path.py`), and `KeyedLock` (`arp/storage/locks.py`, same pattern as other file stores) for `lock(id)`.
- [ ] **Step 4: Run tests** → pass; `ruff check backend`.
- [ ] **Step 5: Commit** `feat(projects): file-based project store`.

### Task 3: `project_id` in the bi views and catalog

**Files:**
- Modify: `backend/arp/bi/views.py` (`_HOLDINGS_SELECT`), `backend/arp/bi/catalog.py` (holdings columns; `holdings_history` copies them)
- Test: `backend/tests/test_bi_views.py` (Postgres, opt-in), `backend/tests/test_bi_catalog.py`

**Interfaces:**
- Produces: trailing view column `project_id TEXT` on `bi.holdings` and `bi.holdings_history`, = the suffix of the portfolio tag `project:<id>`, NULL if none; catalog column `project_id` (string, filterable, not groupable by default is fine, `description` says "Project the portfolio belongs to; NULL for portfolios outside any project").

- [ ] **Step 1: Write failing tests**: with portfolios `p-a` tagged `project:alpha`, `p-b` tagged `project:beta`, `p-c` untagged, `SELECT portfolio_id, project_id FROM bi.holdings` gives `alpha`, `beta`, NULL; same for history; the catalog test asserting view columns equal catalog columns (already exists) passes.
- [ ] **Step 2: Run** (`ARP_TEST_POSTGRES_DSN=...`) → fail.
- [ ] **Step 3: Implement** the derived column in `_HOLDINGS_SELECT` with `(SELECT substr(t, 9) FROM unnest(p.tags) t WHERE t LIKE 'project:%' LIMIT 1) AS project_id`, appended last (CREATE OR REPLACE VIEW only allows appended columns); add the catalog column.
- [ ] **Step 4: Run** the views, catalog and `test_postgres_schema.py` tests → pass.
- [ ] **Step 5: Commit** `feat(bi): project_id column on holdings views`.

### Task 4: Importer project namespacing

**Files:**
- Modify: `backend/arp/portfolio/constituent_import.py` (`import_constituent_file`, `import_constituent_files`), `backend/arp/cli/portfolio.py` (optional `--project`)
- Test: `backend/tests/test_constituent_import.py`

**Interfaces:**
- Consumes: `Portfolio.tags`.
- Produces: `import_constituent_files(store, paths, notional_eur, project_id: str | None = None) -> dict`; with a project id, portfolio ids are `<project_id>-dws-<fund isin lower>` and tags gain `project:<project_id>`; without, unchanged (`dws_<isin>`).

- [ ] **Step 1: Write failing tests**: two projects importing the same file yield two portfolios with disjoint ids and each tagged `project:<id>`; no project keeps the old id and has no `project:` tag; re-import of the same project overwrites (one portfolio, one snapshot).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** by threading `project_id` through the two functions and the id/tag construction; validate the id with `safe_id`.
- [ ] **Step 4: Run** `test_constituent_import.py` → pass.
- [ ] **Step 5: Commit** `feat(portfolio): namespace constituent imports by project`.

### Task 5: Project dashboards: filter compile and provisioning

**Files:**
- Create: `backend/arp/projects/dashboards.py`
- Test: `backend/tests/test_projects_dashboards.py`

**Interfaces:**
- Consumes: `DashboardTemplate` (`arp/bi/plan.py`), `provision` (`arp/bi/templates.py`), `ChartPlan`, `validate_plan`.
- Produces:
  - `slugify_dashboard(project_id: str, title: str) -> str` → `arp-<project_id>-<slugified title>`; raises `ProjectError` if the title slugifies to empty.
  - `scope_to_project(template: DashboardTemplate, project_id: str) -> DashboardTemplate`: adds `filters["project_id"] = project_id` to every chart whose dataset is `holdings` or `holdings_history`; other datasets unchanged; pure, never mutates input.
  - `plan_to_template(project_id: str, title: str, plan: ChartPlan) -> DashboardTemplate` (adds Fund/Sector/Country native filters only if the plan has holdings charts, copied from `arp-risk-exposure`).
  - `provision_project_dashboard(client, template: DashboardTemplate) -> str` = `provision(client, template)` (status `created|rebuilt|unchanged`).

- [ ] **Step 1: Write failing tests**: `scope_to_project` golden (holdings and history charts get the filter, a `company_facts` chart does not, input untouched); `slugify_dashboard("alpha", "My Exposure!")` → `arp-alpha-my-exposure`; empty title raises; `plan_to_template` result validates against fake metas; `provision_project_dashboard` against the existing `FakeClient` (`tests/test_bi_service.py`) is `created` then `unchanged`.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(projects): project-scoped dashboard templates`.

### Task 6: Open service

**Files:**
- Create: `backend/arp/projects/service.py`
- Test: `backend/tests/test_projects_service.py`

**Interfaces:**
- Consumes: `ProjectStore`, `import_constituent_files`, `provision_project_dashboard`, `PortfolioStore`, `SupersetClient`.
- Produces: `open_project(store: ProjectStore, portfolio_store, client: SupersetClient, project_id: str) -> OpenResult`; `OpenResult(data: list[dict], dashboards: list[OpenedDashboard])`; `OpenedDashboard(id: int | None, slug: str, title: str, published: bool, status: str)`; `class OpenError(Exception)` with `.step` (`"data"` or `"dashboard:<slug>"`).
- Behavior: under `store.lock(id)`; data first, then dashboards in stored order; `superset-export` entries follow Task 8's decision; failure raises `OpenError` naming the step; earlier work stays.

- [ ] **Step 1: Write failing tests** with fakes: open twice → second call has every dashboard `unchanged` and one portfolio per fund; two projects stay separate; Superset failing on dashboard 2 raises `OpenError(step="dashboard:<slug2>")` and a retry completes; empty project returns empty lists; `published` always False.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** (`dws-constituents` kind → `import_constituent_files(portfolio_store, paths, params["notional_eur"], project_id=id)`; `template` dashboards → `DashboardTemplate.model_validate_json` of the stored file → `provision_project_dashboard`).
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(projects): idempotent open`.

### Task 7: API (`/api/projects`)

**Files:**
- Create: `backend/arp/api/routers/projects.py`
- Modify: `backend/arp/api/deps.py` (`get_project_store`), `backend/arp/api/main.py` (include router)
- Test: `backend/tests/test_api_projects.py` (pattern: `tests/test_api_bi.py`)

**Interfaces:**
- Produces endpoints: `GET /api/projects` → `list[ProjectSummary]`; `POST /api/projects` `{id?, name, description}` (id defaults to slugified name) → 201; `POST /api/projects/{id}/data` (multipart `file`, form `notional_eur: float`) → `Project`; `POST /api/projects/{id}/open` → `OpenResult`; `POST /api/projects/{id}/dashboards` `{title, plan: ChartPlan}` → `OpenedDashboard`; `POST /api/projects/{id}/dashboards/export` `{dashboard_id: int}` (Task 8). Errors: `ProjectError` → 422, `ProjectNotFound` → 404, `OpenError`/Superset → 502 via `_bad_gateway`, non-Postgres backend or no Superset config → 503.

- [ ] **Step 1: Write failing tests**: create/list/get; bad ids 422; upload ok, `.xlsm` 422, oversize 422, `../x.xlsx` 422; open returns the dashboards and a second open all `unchanged`; open with `portfolio_backend="file"` is 503 and writes nothing; save dashboard validates the plan (rejected plan → 422 with the validator problems) and stores a template; Superset error body never appears in a 502.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** thin handlers using `asyncio.to_thread` for open (same as `embed_token`); stream upload with a size cap while reading.
- [ ] **Step 4: Run** → pass; `ruff check backend`.
- [ ] **Step 5: Commit** `feat(projects): API`.

### Task 8: Hand-built dashboards as export bundles

**Depends on Task 1's decision.** Skip the auto-import half if the spike failed (export-only: store and offer download).

**Files:**
- Modify: `backend/arp/projects/service.py`, `backend/arp/api/routers/projects.py`
- Test: `backend/tests/test_projects_service.py`, `backend/tests/test_api_projects.py`

**Interfaces:**
- Consumes: `SupersetClient.export_dashboard`, `import_dashboard` (Task 1).
- Produces: `export_dashboard_to_project(store, client, project_id, dashboard_id: int) -> StoredDashboard` (only slugs starting `arp-`, else `NotAnARPDashboard`); open imports `superset-export` entries when `find_dashboard(slug)` is absent, leaves existing ones alone (`unchanged`), never overwrites.

- [ ] **Step 1: Write failing tests** with the fake client: non-`arp-` dashboard rejected 403; export stores a `.zip` under `dashboards/`; open imports it when absent and reports `unchanged` when present; import is never called with overwrite on an existing dashboard.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(projects): store hand-built dashboards as export bundles`.

### Task 9: CLI

**Files:**
- Create: `backend/arp/cli/project.py`; modify `backend/arp/cli/__init__.py` (`app.add_typer(project_app, name="project")`)
- Test: `backend/tests/test_projects_cli.py`

**Interfaces:**
- Produces: `arp project create <id> --name ... [--description ...]`, `add-data <id> <file.xlsx>... --notional-eur N`, `list`, `open <id>` (prints `OpenResult` JSON; non-zero exit and one-line error on `OpenError`).

- [ ] **Step 1: Write failing tests** (Typer `CliRunner`, tmp `ARP_PROJECTS_DIR`): create → list shows it; add-data copies the file; bad id exits non-zero; open with a fake wiring prints JSON.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** reusing store/service (client built as in `cli/bi.py`).
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(projects): CLI`.

### Task 10: UI

**Files:**
- Modify: `frontend/src/api/client.ts` (`listProjects`, `createProject`, `uploadProjectData`, `openProject`, `saveProjectDashboard`), `frontend/src/pages/portfolio-monitoring/SupersetBI.tsx`
- Create: `frontend/src/pages/portfolio-monitoring/ProjectBar.tsx`
- Test: `frontend/src/pages/portfolio-monitoring/ProjectBar.test.tsx`

**Interfaces:**
- Consumes: Task 7 endpoints.
- Produces: `ProjectBar` props `{onOpened(dashboards: OpenedDashboard[]): void}`: selector (first option "Standard dashboards"), "New project" (name, notional default 100000000, file input), "Open" button with a summary panel; selecting a project calls open automatically, then `SupersetBI` selects the first returned dashboard. "Save to project" button on a designer result and on picked `arp-` dashboards.

- [ ] **Step 1: Write failing tests** (vitest, mocked `api`): selecting a project calls `openProject` once and `onOpened` with its dashboards; a failing open shows the error and not a Superset body; "Standard dashboards" calls no open.
- [ ] **Step 2: Run** `npm test -- ProjectBar` → fail.
- [ ] **Step 3: Implement** following the existing component styling in `SupersetBI.tsx`; no new libraries.
- [ ] **Step 4: Run** `npm test`, `npm run lint`, `npm run build` → pass, no new lint warnings.
- [ ] **Step 5: Commit** `feat(projects): selector, new project, save-to-project UI`.

### Task 11: Live test, docs, whole-branch check

**Files:**
- Create: `backend/tests/test_projects_live.py` (marker `live_superset`)
- Modify: `README` / docs section where `arp bi bootstrap` is documented (one paragraph + CLI examples)

- [ ] **Step 1: Write the live test**: create a project with a synthetic xlsx (reuse the generator in `test_constituent_import.py`), open twice (second `unchanged`), dashboard charts return rows only for that project, a second project's numbers are separate; if Task 1 passed, a hand-built dashboard round-trips via export bundle.
- [ ] **Step 2: Run live** against the stack in `/tmp/claude-0/p1-stack/` → pass.
- [ ] **Step 3: Docs**: usage, `ARP_PROJECTS_DIR`, upgrade note (re-run `arp bi bootstrap` so views gain `project_id`).
- [ ] **Step 4: Full verification**: `ruff check backend`, `pytest backend` (only the 5 known baseline failures), frontend tests/lint/build.
- [ ] **Step 5: Commit** `test+docs(projects): live test and usage`.
