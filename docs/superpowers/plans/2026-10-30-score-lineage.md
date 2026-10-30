# Score Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every published Decision Studio score, rank and tier can be traced to the authoritative values it used, and
through them to source facts and document citations. Required criteria turn a missing value into "no score" with a
reason.

**Architecture:**
- A new source, `from_authoritative`, carries `__value_id` and `__reason` per output.
- The engine marks `no_score` rows through the existing eligibility mask, or removes them before normalisation when
  the framework's setting says `exclude`.
- Contributions and published rows keep value ids.
- One resolver, `arp/decision/lineage.py::row_lineage`, feeds the API, the CSV/JSON exports, and a shared frontend
  `LineagePanel` used in Decision Studio, Steward and Index Builder.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy/Postgres, React + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-30-score-lineage-design.md` (approved; AC-1 to AC-34).

## Global Constraints

- Owner principle: every choice that changes a result is a framework setting, stored on the version and audited.
- `no_score_rows` takes `"include"` or `"exclude"`; a config without the key loads as `"include"`.
- `Criterion.required` defaults to `False`. Saving a framework that has a required criterion with `mode = "levels"`
  gives 422, and the message contains `required`.
- Reason format, exactly: `required_missing: <column> (<reason>)`, where the reason is the `<column>__reason` cell or
  `blank`.
- For `no_score` rows, `score`, `rank`, `rank_min`, `rank_max`, `tier`, `tier_name` and `leverage` are all `None`.
- The lineage JSON shape and the CSV header are exactly as in spec §5 and §6.
- `as_fields`:
  - adds `.status` and `.reasons` (reasons joined with `; `);
  - a `no_score` row has none of `.score`, `.tier`, `.tier_name`, `.rank` or `.rank_max`.
- Never change scores, ranks or tiers for frameworks with no required criterion (AC-8, AC-10).
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`, and
  `cd frontend && npm run lint && npx tsc -b && npm test`. After changing a model, regenerate the API contract
  (`scripts/export_openapi.py`, then `npm run gen:api`).

## Review Focus

1. **A published row whose `entity_id` matches no company in Steward or Index Builder.** Expect no `Why` link and no
   error. Test in Task 7.
2. **A lineage request on a snapshot whose framework was deleted or archived.** Expect the lineage to resolve from the
   snapshot alone, because the framework is not read. Test in Task 5.
3. **CSV export of quotes containing commas, quotes or newlines.** Expect valid CSV that round-trips through
   `csv.reader`. Test in Task 5.
4. **`from_authoritative` for a framework that was never published.** Expect HTTP 422 with the message
   `No authoritative values published for <framework_id>`. Test in Task 2.
5. **`no_score_rows = "exclude"` with every row `no_score`.** Expect every row `no_score` and no crash in normalisation
   or cuts. Test in Task 3.

---

### Task 1: Schema fields and the audit entry

**Files:**
- Modify: `backend/arp/schemas/decision.py`, `backend/arp/decision/diffing.py` (`_SETTING_LABELS`),
  `frontend/src/types.ts` (`MechanismConfig`)
- Test: `backend/tests/test_score_lineage_schema.py`

**Interfaces — Produces:**
- `Criterion.required: bool = False`
- `MechanismConfig.no_score_rows: Literal["include", "exclude"] = "include"`
- `MechanismConfig` validator: raises `ValueError` containing `required` when `mode == "levels"` and any criterion is
  required.
- `EntityStatus` gains `"no_score"`.
- `EntityDecision.reasons: list[str] = []`
- `CriterionContribution.value_id: int | None = None` and `CriterionContribution.missing_reason: str | None = None`
- `class PublishedCriterion(BaseModel): column: str; contribution: float; imputed: bool; value_id: int | None; missing_reason: str | None`
- `PublishedRow.reasons: list[str] = []` and `PublishedRow.criteria: list[PublishedCriterion] | None = None`. `None`
  means the row was written before this change.
- `PublishedDecision.source: str | None = None` and `PublishedDecision.source_ref: str | None = None`
- `_SETTING_LABELS["no_score_rows"] = "Rows with no score"`

- [ ] **Step 1: Write the failing tests.**
  - An old config dict without the new keys loads with `no_score_rows == "include"`, and every `required` is `False`.
  - AC-11: `MechanismConfig(mode="levels", criteria=[Criterion(column="x", dimension_id="d", required=True)])` raises,
    and `"required" in str(exc)`.
  - AC-22: `describe_changes(v1, v2)` with `no_score_rows` going from `include` to `exclude` gives exactly one entry
    whose `item` is `"Rows with no score"` and whose `origin` is `"human"`.
  - `PublishedRow.model_validate({...without criteria...}).criteria is None`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_score_lineage_schema.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the fields, the validator and the label.** Add `required?: boolean` and
  `no_score_rows?: "include" | "exclude"` to the frontend `MechanismConfig`.
- [ ] **Step 4: Run** the new tests and `tests/test_decision_*.py`. Expected: PASS, with no existing test changed.
- [ ] **Step 5: Commit** `feat(decision): schema for required criteria, no_score and lineage ids`

### Task 2: The `from_authoritative` source

**Files:**
- Modify: `backend/arp/decision/sources.py`, adding `from_authoritative` and the `"authoritative"` case in
  `from_source`; `backend/arp/api/routers/decision.py`, adding `framework_id` and `outputs` to `FromSourceRequest`
  (`as_of` exists); `backend/arp/decision/profiling.py`, so that columns ending `__value_id` are `identifier` and
  columns ending `__reason` are `text`.
- Test: `backend/tests/test_from_authoritative_pg.py`

**Interfaces:**
- Consumes: `AuthoritativeStore.values(framework_id=, as_of=)` (PR #276).
- Produces: `from_authoritative(store: AuthoritativeStore, framework_id: str, as_of: str | None, outputs: list[str] | None) -> Dataset`
  - `source="authoritative"`, `source_ref=framework_id`;
  - columns: `company_id`, `Company`, then for each output (sorted) `<o>`, `<o>__reason`, `<o>__value_id`;
  - cells are strings, with `""` for no value or no reason;
  - `Company` is the company name from the registry.

- [ ] **Step 1: Write the failing tests.** Seed the spec fixture: F with `auth_scope1` and `auth_capex` published for
  A to D, using `tests/authoritative_fixtures.py` plus the PR #276 store.
  - AC-1: 4 rows; C's `auth_scope1 == ""`, its `__reason == "not_in_dataset"` and its `__value_id == str(<row id>)`;
    A's `auth_scope1 == "90"`.
  - AC-2: `derive_mechanism(DA)` proposes no criterion whose column ends in `__reason` or `__value_id`.
  - Review Focus 4: an unpublished framework raises `ValueError("No authoritative values published for fw_x")`, and the
    route returns 422.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** The route maps `ValueError` to 422 for `source == "authoritative"`, as it does for
  `source_values`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(decision): from_authoritative dataset source`

### Task 3: Required criteria and `no_score` in the engine

**Files:**
- Modify: `backend/arp/decision/mechanism.py` (`_apply_config` around the eligibility mask, lines ~340-440)
- Test: `backend/tests/test_score_lineage_engine.py` (no database; builds `Dataset` objects shaped like DA)

**Interfaces — Produces:**
- `required_missing(dataset, config, profiles) -> list[list[str]]`, in `mechanism.py`. Returns the reasons per row:
  - only enabled, required criteria count;
  - a criterion counts as missing when its normalised value is `None`;
  - the reason text is `<col>__reason`, or `blank` when that cell is empty or the column is absent.
- In `_apply_config`, when `no_score_rows == "include"`, a row with reasons:
  - is masked like an `insufficient` row, so it is kept in normalisation and left out of ranks and cuts;
  - gets `status = "no_score"`;
  - has every rank, score and tier field set to `None`.
- When `"exclude"`:
  - run `_apply_config` on a copy of the dataset without those rows;
  - then insert their `no_score` entities back at their original row positions, because publish needs row alignment;
  - with every row `no_score`, return every entity as `no_score`, no cuts and an empty histogram.
- Every contribution:
  - `value_id = int(row[f"{col}__value_id"])` when that cell is non-empty;
  - `missing_reason` set whenever the typed value is `None`, using the same reason text as above.

- [ ] **Step 1: Write the failing tests** on DA with S, `renormalise` and `include`:
  - AC-3: C's status and reasons;
  - AC-4: C's null fields;
  - AC-5: the ranks of A, B and D are `{1, 2, 3}`;
  - AC-6: B's `auth_capex` contribution;
  - AC-7: A's contributions carry the `value_id`s;
  - AC-8: S against S′ (`required=False`); scores differ by less than 1e-9, and ranks and tiers are equal;
  - AC-9: `exclude` on DA against S on DA′ (DA without C);
  - AC-12 and AC-29: an uploaded-style dataset with `""` or `"n/a"` in numeric `x` gives `required_missing: x (blank)`;
  - AC-30: required but disabled leaves C `scored`;
  - AC-31: `missing="mean"` gives `imputed=True` and `missing_reason="no_rule_value"`;
  - Review Focus 5: all rows `no_score` under `exclude`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_score_lineage_engine.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** as in the Interfaces block. The `include` path reuses the existing
  `insufficient` mask.
- [ ] **Step 4: Run** the new tests and all of `tests/test_decision_*.py` (AC-10). Expected: PASS, with no existing
  test changed.
- [ ] **Step 5: Commit** `feat(decision): required criteria give no_score with reasons; contributions carry value ids`

### Task 4: Published rows and `as_fields`

**Files:**
- Modify: `backend/arp/decision/publish.py` (`publish`, `as_fields`)
- Test: `backend/tests/test_score_lineage_publish.py`

**Interfaces — Produces:**
- `publish()` fills:
  - `PublishedRow.reasons`;
  - `PublishedRow.criteria` from the entity's contributions;
  - `PublishedDecision.source` and `source_ref` from the dataset.
- `as_fields`:
  - for a scored or other non-`no_score` row: today's five keys, plus `.status`, plus `.reasons`
    (`"; ".join(reasons)`);
  - for a `no_score` row: `.status` and `.reasons` only.

- [ ] **Step 1: Write the failing tests.**
  - AC-13: published C has `no_score` and its reasons; A has `criteria` with both `value_id`s; the snapshot's
    `source == "authoritative"`.
  - AC-21: the exact key sets for A and C.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run** the new tests, plus
  `tests/test_decision_publish.py` and the stewardship and index tests that read `as_fields`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(decision): published rows keep criteria ids, reasons and status`

### Task 5: The resolver, the API and the exports

**Files:**
- Create: `backend/arp/decision/lineage.py`
- Modify: `backend/arp/api/routers/decision.py`, adding three routes
- Test: `backend/tests/test_score_lineage_api_pg.py`

**Interfaces:**
- Consumes: `AuthoritativeStore.get(id)`, `DecisionStore.get_published(snapshot_id)`, and the `field_observations` and
  `value_citations` models.
- Produces:
  - `row_lineage(snapshot: PublishedDecision, entity_id: str, *, values: AuthoritativeStore, session_factory) -> dict`,
    in the spec §5 shape. `superseded` is `valid_to is not None`, and `current_valid_to` is its ISO string. Raises
    `KeyError` for an unknown entity.
  - `lineage_csv(snapshot, rows: list[dict]) -> str`, with the §6 header and one line per entity × criterion × input ×
    citation, written with `csv.writer`.
  - Routes, which map `KeyError` and a missing snapshot to 404:
    - `GET /api/decision/published/{snapshot_id}/rows/{entity_id}/lineage`
    - `GET /api/decision/published/{snapshot_id}/lineage.json`
    - `GET /api/decision/published/{snapshot_id}/lineage.csv` (`text/csv`)
  - Add the new response types to `frontend/src/api/contract.ts`, or type them in `types.ts` as
    `Served<S[...]>`.

- [ ] **Step 1: Write the failing tests.** Publish S on DA through the API, then check:
  - AC-14 to AC-20;
  - AC-27: delete A's `auth_scope1` row in the test database, then expect `link` to be `missing`;
  - AC-28: strip the `observation_id` from the stored derivation, then expect `link` to be `no_observation`;
  - Review Focus 2: delete the framework's files from `DecisionStore`; the lineage still returns 200;
  - Review Focus 3: a quote containing `,`, `"` and `\n` round-trips through `csv.reader`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS. Then regenerate the
  OpenAPI file and the frontend types, and run `npx tsc -b`, expecting 0 errors.
- [ ] **Step 5: Commit** `feat(decision): score lineage resolver, API and CSV/JSON export`

### Task 6: The lineage panel in Decision Studio

**Files:**
- Create: `frontend/src/lib/lineage.ts` (pure formatting), `frontend/src/components/LineagePanel.tsx`,
  `frontend/tests/lineage.test.ts`
- Modify: `frontend/src/components/DecisionResultsTable.tsx` (score cell, plus the `no_score` badge in `StatusCell`),
  `frontend/src/pages/DecisionStudio.tsx` (the Mechanism-tab controls `required` and `no_score_rows`, and the lineage
  download links in the published list), `frontend/src/api/client.ts` (`getRowLineage`, plus lineage URLs for CSV and
  JSON)

**Interfaces — Produces:**
- `lineageLines(l: RowLineage): { header: string; reasons: string[]; criteria: { title: string; value: string; inputs: string[]; citations: string[] }[] }`
- `<LineagePanel lineage={RowLineage} onClose />`
- Before publish, the panel builds a `RowLineage`-shaped object from the live `EntityDecision`: the contributions with
  `value_id`, and values fetched with `getAuthoritativeValue(id)`.

- [ ] **Step 1: Write the failing test** `lineage.test.ts`. For the AC-14 JSON, the output contains:
  - `auth_scope1 = 90`
  - `scope1_tco2e = 90 · approved · extraction · 2025-12-31`
  - `d1 p.4 · "Scope 1: 90 tCO2e"`

  For C, `reasons` contains `required_missing: auth_scope1 (not_in_dataset)`.
- [ ] **Step 2: Run** `npm test`. Expected: FAIL. **Step 3: Implement** the panel and controls with existing
  components only. **Step 4: Run** `npm run lint && npx tsc -b && npm test`. Expected: PASS.
- [ ] **Step 5: Check in the app.** Seed the fixture on the e2e stack. Click C's badge and A's score, before and after
  publish (AC-23, AC-32). Check the Mechanism controls (AC-26) and the downloads (AC-33). Screenshot at 1400 px and
  400 px, then run `/impeccable:impeccable audit`.
- [ ] **Step 6: Commit** `feat(frontend): lineage panel, required and no-score settings, lineage downloads`

### Task 7: "Why" links in Steward and Index Builder

**Files:**
- Create: `frontend/src/lib/whyLinks.ts`, `frontend/tests/whyLinks.test.ts`
- Modify: `frontend/src/pages/steward/decisions.tsx`, `frontend/src/pages/IndexBuilder.tsx`

**Interfaces — Produces:**
- `whyLinks(issuerId: string, published: PublishedDecision[]): { label: string; snapshotId: string; entityId: string }[]`
  - one link per framework, using its latest snapshot by `published_at`, and only where a row's `entity_id` equals
    `issuerId`;
  - label: `Why: <framework_name> <tier_name>`, or `Why: <framework_name> no score` for `no_score`.

- [ ] **Step 1: Write the failing tests.**
  - AC-34 data: S published twice plus T gives exactly two links, and the S link points at the newer snapshot.
  - Review Focus 1: an unmatched issuer gives `[]`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement** the links. Each opens `LineagePanel` with
  `getRowLineage(snapshotId, entityId)`. **Step 4: Run** lint, tsc and tests. Expected: PASS.
- [ ] **Step 5: Check in the app** AC-24, AC-25 and AC-34. Screenshot, then run the audit.
- [ ] **Step 6: Commit** `feat(frontend): Why links from Steward and Index Builder to score lineage`

---

## After the last task

- Run a whole-branch review: `/code-review` and `/ponytail:ponytail-review` in a fresh agent.
- Open a PR against `main` with:
  - `Spec: score-lineage-design`;
  - label `risk:high`, because it changes how published scores, ranks and tiers are computed.
- List the holdout rows as owed while `HOLDOUT_TOKEN` is missing.
- `openwiki/` needs a page after merge. Do not edit it by hand.
