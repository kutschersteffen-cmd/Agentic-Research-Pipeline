# Authoritative Data Layer: Core (PR 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add calculate-only Decision Studio frameworks. Their ZEN rule graph turns one row of all source values per
company into authoritative values, stored with their derivation in a versioned, as-of Postgres table.

**Architecture:** This adds a new package, `backend/arp/authoritative/`, with four modules:

- `source_values.py` builds the dataset;
- `evaluate.py` runs the rules and builds each verdict and its derivation;
- `store.py` handles publish and as-of reads;
- `models.py` holds the two tables.

`MechanismConfig` gains `purpose`, `outputs` and `dataset_id`. The existing ratify route gets an approver check and an
output check for authoritative frameworks. A new router, `api/routers/authoritative.py`, serves publish and reads.
`DecisionResultsTable.tsx` shows the derivation.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 on Postgres, zen-engine 2.0.2, React + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-28-authoritative-data-layer-design.md`. This plan covers phase 1 and its
acceptance rows: AC-1 to AC-30, including the b-rows. AC-31 to AC-37 belong to phases 2 and 3, which get their own
plans.

## Global Constraints

- No LLM call anywhere in `arp/authoritative/`.
- Never write to `company_facts`, `field_observations` or `published_facts` (AC-29).
- `purpose` is `"score"` or `"authoritative"`. A config without `purpose` loads as `"score"`.
- Scoring frameworks keep today's ratify and publish behaviour, open to any analyst (AC-10).
- Reason strings are exact: `no_rule_value`, `rule_error: <ZEN error source text>`, `not_in_dataset`.
- Status strings are exact: `value`, `no_value`.
- A Decision Studio dataset cell with no value is `""`. The rule context and every stored value or derivation use JSON
  `null` (see the question in the handoff).
- Default alias: the field id with every character outside `[a-z0-9_]` replaced by `_`. Portfolio inputs use
  `portfolio_<source>_<field_id>`.
- Checks:
  - `cd backend && ruff check . && python3 -m pytest tests/<file>`;
  - Postgres tests need `ARP_TEST_POSTGRES_DSN` (`bash .claude/hooks/ensure-deps.sh postgres`);
  - frontend: `cd frontend && npm run lint && npx tsc -b && npm test`;
  - API contract: `python scripts/export_openapi.py`, then `npm run gen:api`.

## Review Focus

1. **A company in `company_ids` that the registry does not know.** Expect: no row is produced, and the dataset's
   `source_ref` notes how many ids were skipped. Test in Task 2.
2. **A picked field id that does not exist.** Expect: HTTP 422 naming the id, not an empty column. Test in Task 2.
3. **A text value, or a JSONB value that is not a number** (for example a boolean field). Expect: it is passed
   through as text and never cast to a number. Test in Task 2.
4. **Publishing the same dataset twice at once.** Expect: the advisory lock serialises the two publishes, and the
   second one only reconfirms. Test in Task 4.
5. **Ratifying an authoritative framework with no `dataset_id`.** Expect: HTTP 422 `"An authoritative framework needs
   a dataset_id"`. Test in Task 5.

---

### Task 1: Framework purpose, outputs and loading old files

**Files:**
- Modify: `backend/arp/schemas/decision.py`, in `MechanismConfig` (line ~191)
- Test: `backend/tests/test_authoritative_config.py`

**Interfaces:**
- Produces:
  - `class AuthoritativeOutput(BaseModel): column: str; name: str; data_type: Literal["number", "text", "boolean"] = "number"; unit: str | None = None`
  - `MechanismConfig.purpose: Literal["score", "authoritative"] = "score"`
  - `MechanismConfig.outputs: list[AuthoritativeOutput] = []`
  - `MechanismConfig.dataset_id: str | None = None`

- [ ] **Step 1: Write the failing tests**
  - `test_ac_11_old_file_loads_as_score`: `MechanismConfig.model_validate(json.loads(<a v1.json written by today's
    code, with no purpose key>))` gives `.purpose == "score"`, `.outputs == []`.
  - `test_outputs_roundtrip`: a config with `purpose="authoritative"` and
    `outputs=[AuthoritativeOutput(column="auth_scope1", name="Scope 1", unit="tCO2e")]` survives `DecisionStore.save`
    and `get` unchanged.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_authoritative_config.py -v`. Expected: FAIL, because
  `AuthoritativeOutput` is not defined.
- [ ] **Step 3: Add the three fields and the model.** Use `Field(description=...)` like the neighbouring fields.
- [ ] **Step 4: Run** the new tests, then `python3 -m pytest tests/test_decision_*.py` (AC-11b). Expected: all PASS
  with no existing test changed.
- [ ] **Step 5: Commit** `feat(decision): authoritative purpose and outputs on frameworks`

### Task 2: The "All source values" dataset

**Files:**
- Create: `backend/arp/authoritative/__init__.py`, `backend/arp/authoritative/source_values.py`
- Modify: `backend/arp/decision/sources.py`, adding `"source_values"` to `from_source` and a `session_factory`
  keyword; `backend/arp/api/routers/decision.py`, extending `FromSourceRequest` (line ~162)
- Test: `backend/tests/test_authoritative_source_values_pg.py` (Postgres)

**Interfaces:**
- Produces:
  - `class SourcePick(BaseModel): field_id: str; alias: str | None = None; portfolio_source: str | None = None`.
    When `portfolio_source` is set, `field_id` is a portfolio-store field such as `climate_scope1_tco2e`.
  - `def from_source_values(session: Session, *, company_ids: list[str], picks: list[SourcePick], as_of: str, portfolio_store=None) -> Dataset`
    returns `source="source_values"`, `as_of` as given, and columns `company_id`, `Company`, then per pick the columns
    in the spec's input table, plus a hidden `<alias>__observation_id` per pick (the `field_observations.id`, or `""` for
    portfolio inputs), which Task 3 reads into the derivation.
  - `def default_alias(field_id: str, portfolio_source: str | None = None) -> str`
  - `FromSourceRequest` gains `company_ids: list[str] | None`, `picks: list[SourcePick] | None` and `as_of` (already
    present; it defaults to now when `source == "source_values"`).

- [ ] **Step 1: Write the failing tests.** Seed the spec's fixture through `arp.db.providers` (source `esg_demo`) and
  `arp.db.observations`, then assert:
  - AC-1 and AC-2: exact cells, with `""` where the spec says `null`;
  - AC-3: the latest period wins;
  - AC-4: the empty basis wins a tie;
  - AC-5: `as_of` 2026-09-01 hides the provider values;
  - AC-6: two picks with the same alias raise `ValueError`, whose message names both field ids;
  - AC-7 and AC-7b: portfolio inputs, using `PortfolioStore` on `tmp_path`;
  - Review Focus 1 to 3: an unknown company is skipped, an unknown field raises `ValueError` naming it, and a text
    value passes through.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_authoritative_source_values_pg.py -v`. Expected: FAIL with an
  import error.
- [ ] **Step 3: Implement `from_source_values`.**
  - One query per pick: `company_facts` joined to `field_observations` on `observation_id`, and outer-joined to
    `data_sources` on `source_id`.
  - Filters: `valid_from <= as_of`, and `valid_to` null or `> as_of`.
  - Order by `period_end DESC, (basis = '') DESC`, and take the first row per company in Python.
  - `__observed_at` = `field_observations.created_at`, as an ISO string.
  - Portfolio picks: `store.load_observations(company_id, field_id)`, filtered to `source == portfolio_source` and
    `observed_at[:10] <= as_of`, taking the last one. Company ids are mapped with
    `lookup(session, IdScheme.UNIVERSE, id)`.
- [ ] **Step 4: Wire `"source_values"` into `from_source` and the route.** The route maps `ValueError` to HTTP 422,
  as it already does.
- [ ] **Step 5: Run** the tests. Expected: PASS. Then run `ruff check .`.
- [ ] **Step 6: Commit** `feat(authoritative): all-source-values dataset`

### Task 3: Evaluation, verdicts and derivation

**Files:**
- Create: `backend/arp/authoritative/evaluate.py`
- Test: `backend/tests/test_authoritative_evaluate.py` (no database; builds `Dataset` objects directly)

**Interfaces:**
- Consumes: `arp.decision.rules.rule_inputs(dataset)`; `zen.ZenEngine` as used in `rules.evaluate_rows`.
- Produces:
  - `class Verdict(BaseModel): company_id: str; output: str; status: Literal["value", "no_value"]; value: Any = None; unit: str | None = None; period_end: str | None = None; reason: str | None = None; derivation: dict`
  - `def check_outputs(dataset: Dataset, config: MechanismConfig) -> None` raises `ValueError`:
    - when an output column equals a dataset column (message contains the column, AC-29b);
    - when an output is absent from every row's result (message contains the output, AC-12).
  - `def evaluate(dataset: Dataset, config: MechanismConfig, *, snapshot_id: str) -> list[Verdict]` returns one
    verdict per (row, output).
  - `derivation` = `{"inputs": {alias: {"value", "status", "source", "provider", "period_end", "unit", "observation_id"}}, "trace": [...], "framework_id", "framework_version", "dataset_id", "dataset_as_of", "snapshot_id"}`

- [ ] **Step 1: Write the failing tests**, each with a one-node expression graph helper `_graph(**expressions)`:
  - AC-17: `x = 100 / scope1_tco2e` with B's `scope1_tco2e` = `""` gives B `status == "no_value"` and
    `reason.startswith("rule_error:")`;
  - AC-18: A's value is within 1e-9 of 100/90;
  - AC-19: `y = scope1_tco2e` gives B `reason == "no_rule_value"`;
  - AC-20: A's total is 190, and `set(derivation["inputs"]) >= {"scope1_tco2e", "prov_esg_demo_scope1"}`;
  - AC-21: the `date(...) >` rule gives 100;
  - AC-13 values: F gives A = 90 with `period_end == "2025-12-31"`, and B = 50;
  - AC-15 trace: some trace entry has `output["auth_scope1"] == 90`;
  - AC-12 and AC-29b: `check_outputs` messages.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_authoritative_evaluate.py -v`. Expected: FAIL with an import
  error.
- [ ] **Step 3: Implement.**
  - Evaluate with `engine.evaluate_batch(requests, {"trace": True})`.
  - A failed response gives `rule_error: <error.source>`.
  - A null or absent output gives `no_rule_value`.
  - The output's period comes from `<column>__period_end` in the result.
  - The input set is every dataset alias that occurs as a whole word (`\b<alias>\b`) in a trace node's expression or
    decision-table text. The `shortcut:` comment from the spec goes on this code.
  - `observation_id` is carried in the dataset as a hidden column, `<alias>__observation_id`. Add it in Task 2's
    builder.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(authoritative): evaluate rule graph into verdicts with derivation`

### Task 4: Tables, publish and as-of reads

**Files:**
- Create: `backend/arp/authoritative/models.py`, `backend/arp/authoritative/store.py`
- Modify: `backend/arp/db/models.py` or `tests/postgres_helpers.py`, only as needed so that `ensure_schema` and
  `reset_postgres_tables` see the new tables. The simplest route is to import `arp.authoritative.models` from
  `arp/db/models.py`.
- Test: `backend/tests/test_authoritative_store_pg.py`

**Interfaces:**
- Consumes: `Verdict` and `evaluate` from Task 3.
- Produces:
  - Table `authoritative_values` with the spec's Storage columns. Partial unique index on
    `(framework_id, output_column, company_id)` `WHERE valid_to IS NULL`.
  - Table `authoritative_publishes` with the spec's publish-record columns.
  - `class AuthoritativeStore: __init__(self, dsn: str)`
  - `AuthoritativeStore.publish(dataset: Dataset, config: MechanismConfig, *, published_by: str) -> str` returns the
    `snapshot_id`. It raises `StalePublish` for an older `as_of` (AC-23), which the router maps to 409.
  - `AuthoritativeStore.values(*, framework_id: str, output: str | None, company_id: str | None, as_of: str | None) -> list[dict]`
  - `AuthoritativeStore.get(value_id: int) -> dict | None`

- [ ] **Step 1: Write the failing tests**:
  - AC-13: exactly 2 current rows with their exact values;
  - AC-22: the same ids, `reconfirmed_at` equal to the new publish's `published_at`, the same `snapshot_id`, and 2
    publish rows;
  - AC-23: `StalePublish` is raised and no row changes;
  - AC-24: a source edit with no republish still reads 90;
  - AC-25 and AC-25b: v1 is closed, `superseded_by` is v2's id, and B's new row has `framework_version == 2`;
  - AC-26 and AC-27: as-of reads return 1 item (90) and 0 items;
  - AC-28: `not_in_dataset`, with the closed 50 row kept;
  - AC-29: row counts and a sha256 of `company_facts`, `field_observations` and `published_facts` are equal before
    and after;
  - AC-16: with a `published_facts` row for A's 90, the input's `published_fact_id` equals its `fact_id`;
  - Review Focus 4: two publishes in threads leave 2 current rows.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_authoritative_store_pg.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `publish`.**
  - Run in one transaction under `pg_advisory_xact_lock(hashtext('authoritative:' || framework_id))`.
  - Compare against the current rows. Reconfirm when the value, unit, period, status and `framework_version` are all
    the same. Otherwise insert the new row and close the old one.
  - Write a `not_in_dataset` row for each current company that is missing from the dataset.
  - Insert the publish record.
  - Fill `published_fact_id` from the current `published_facts` row with the same `company_id`, `field_id`,
    `period_end` and `basis`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(authoritative): versioned authoritative_values with as-of reads`

### Task 5: Routes and the approver rule

**Files:**
- Create: `backend/arp/api/routers/authoritative.py`, prefix `/api/authoritative`, mounted in `api/main.py` with
  `dependencies=[Depends(authorize)]` like its neighbours.
- Modify: `backend/arp/api/routers/decision.py`, in `ratify_mechanism` (line ~396)
- Modify: `frontend/src/api/contract.ts`, then regenerate the OpenAPI types
- Test: `backend/tests/test_authoritative_api_pg.py`

**Interfaces:**
- Consumes: `AuthoritativeStore` (Task 4), `check_outputs` (Task 3), `require_role` / `ROLE_RANK` from `arp.api.auth`.
- Produces:
  - `POST /api/authoritative/publish` with body `{framework_id, version?, dataset_id}`. Approver only (403 otherwise).
    Ratified version only (422 otherwise). Returns 409 on `StalePublish` and `{snapshot_id}` on success.
  - `GET /api/authoritative/values?framework_id=&output=&company_id=&as_of=` returns `list[AuthoritativeValue]`.
  - `GET /api/authoritative/values/{id}` returns `AuthoritativeValue` including `derivation`; 404 if missing.
  - `ratify_mechanism` for `purpose == "authoritative"`:
    - an analyst gets 403 (AC-8);
    - no `dataset_id` on the config gives 422 (Review Focus 5);
    - otherwise it calls `check_outputs` on that dataset, and a failure gives 422.

    Scoring frameworks are unchanged.
- [ ] **Step 1: Write the failing tests** through `TestClient`, with `ARP_AUTH_MODE=local` users for analyst and
  approver, as `test_publish_api.py` does: AC-8, AC-9 (403 and 0 rows), AC-10, AC-12 (422 contains `auth_scope2`),
  AC-14, AC-15, AC-23 (409), AC-24, AC-26, AC-27, AC-29b, and Review Focus 5.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_authoritative_api_pg.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the router and the ratify branch.**
- [ ] **Step 4: Run** the tests, then the existing `tests/test_decision_api.py`. Expected: PASS.
- [ ] **Step 5: Regenerate the contract.** Run `python scripts/export_openapi.py` and `cd ../frontend && npm run
  gen:api`, and add a line to `contract.ts` for each of the two GET responses. Then run `npx tsc -b`. Expected:
  0 errors.
- [ ] **Step 6: Commit** `feat(api): authoritative publish and read routes; approver-only ratify for authoritative frameworks`

### Task 6: The derivation panel in Decision Studio

**Files:**
- Create: `frontend/src/lib/derivation.ts` (pure formatting), `frontend/tests/derivation.test.ts`
- Modify: `frontend/src/components/DecisionResultsTable.tsx`, and `frontend/src/pages/DecisionStudio.tsx` only where
  the table gets its props.

**Interfaces:**
- Consumes: `GET /api/authoritative/values/{id}` (Task 5).
- Produces:
  - `export function derivationLines(v: AuthoritativeValue): { value: string; inputs: string[]; expressions: string[] }`.
    Each input line reads `<alias> = <value> · <status> · <source> · <period_end>`.
  - Clicking an output cell of an authoritative framework opens a panel that renders those lines (AC-30, checked by
    the evaluator).

- [ ] **Step 1: Write the failing test** in `frontend/tests/derivation.test.ts` (node `--test`, like its neighbours).
  For A's verdict, `derivationLines` gives `value == "90"`, and `inputs` contains
  `scope1_tco2e = 90 · approved · extraction · 2025-12-31`. `expressions` contains
  `scope1_tco2e__status == 'approved' ? scope1_tco2e : prov_esg_demo_scope1`.
- [ ] **Step 2: Run** `cd frontend && npm test`. Expected: FAIL with the module not found.
- [ ] **Step 3: Implement** `derivationLines` and the panel. The panel uses the components the table already uses for
  row details; add no new dependency.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test`. Expected: PASS.
- [ ] **Step 5: Screenshot and audit.** Start the browser stack (`bash .claude/hooks/ensure-deps.sh postgres && bash
  backend/scripts/e2e_stack.sh up`), screenshot Decision Studio with the panel open using Playwright, and run
  `/impeccable:impeccable audit`. Fix any blocking finding. Run `e2e_stack.sh down` when done.
- [ ] **Step 6: Commit** `feat(frontend): derivation panel for authoritative values`

---

## After the last task

- Open a PR against `main` with:
  - title `Authoritative data layer: core (phase 1)`;
  - body line `Spec: 2026-10-28-authoritative-data-layer-design`;
  - label `risk:high`, because it adds a new storage table, a permission rule and a published layer.
- List every holdout row as owed while `HOLDOUT_TOKEN` is missing.
- State in the PR that `openwiki/` needs a new page for the authoritative layer after merge. Do not edit it by hand.
