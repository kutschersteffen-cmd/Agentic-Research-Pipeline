# Authoritative data layer

Status: approved by the owner on 2026-10-28. Delivered as three PRs (see Phases).

## Why

ARP keeps the same metric in places that never meet. Scope 1 emissions, for example, can exist as:

- a vendor value on a provider field (`prov:esg_<provider>:<code>`, loaded by `portfolio/climate/esg_intake.py`);
- an XBRL-tagged or LLM-extracted value on an extraction-schema field, reviewed and kept in `company_facts`;
- a reviewer's edit of that value (`company_facts.status = edited`);
- the climate-analytics field `climate_scope1_tco2e` in the portfolio store. That is what WACI and financed emissions
  read, through `portfolio/datapoint_mapping.py` with a hard-coded source order.

Nothing in ARP says these are the same data point, and every consumer picks a source its own way. The EDEN Nova review
made the gap visible: Nova rests on one canonical data contract that every source feeds and every score reads.

The owner wants an **authoritative data layer that the user defines**. ARP ships no preset source order. Users write
the rules that pick and combine source values into one final value per data point. Each verdict states its value, the
inputs it used and the logic that produced it.

## Goals

1. Users define authoritative data points and their rules **in Decision Studio**, as a framework.
2. Rules can pick and combine source values per company. Picking covers fallback, preference, and conditions on review
   state, period, age or source. Combining covers sums, ratios and unit conversion.
3. Every authoritative value carries its derivation: the input columns it read, their values, sources and periods, and
   the rule nodes that computed it (the ZEN trace).
4. An analyst drafts the rules, an approver ratifies them, and only an approver can publish a ratified version.
5. Published authoritative values are versioned and readable **as of a date**. Reading an earlier date returns exactly
   what was published then.
6. Consumers read the authoritative value instead of choosing a source: climate analytics and Decision Studio scoring
   frameworks.

## Non-goals

- No default or built-in precedence. A consumer field with no binding to an authoritative framework behaves exactly as
  today. A bound field never falls back (see Phases).
- No LLM anywhere in the layer. It is deterministic code, like the rest of Decision Studio.
- No new rule language and no new rule editor. The framework's existing `rule_graph` (ZEN / GoRules JDM, edited in
  `RuleGraphEditor.tsx`) is the rule format.
- No reporting-year or period-alignment convention, such as Nova's 17-month rule. Each input carries its own period
  and the user's rules decide. ARP imposes nothing.
- No history of past periods in this version. The layer holds one current authoritative value per company and data
  point, plus its period. A time series (FY2023, FY2024, …) is a later extension.
- No change to extraction, grounding, review, the fact ledger rules (`decide`) or `published_facts`.
- No change to how scoring frameworks are ratified or published.

## Anti-goals (a failure even if it works)

- An authoritative value whose derivation cannot be shown, or that changes when nobody republished it.
- A consumer that silently falls back to its old source picking when a bound framework has no value. "No value" must
  reach the consumer as "no value" with a reason.
- Overwriting or editing any source value. The layer only reads sources.

## How it fits Decision Studio (decided with the owner)

| Decision Studio today | Authoritative framework |
|---|---|
| A `Dataset` from a source function in `decision/sources.py` | New source **"All source values"** (`from_source_values`), described below |
| `MechanismConfig.rule_graph` computes calculated columns per row (`decision/rules.py`) | The same graph computes the authoritative columns. The existing guarantees still hold: it never overwrites a source column, and a row it cannot evaluate gets blank values |
| Criteria, gates, normalisation, tiers | Not used. The framework is **calculate-only** (new `MechanismConfig.purpose = "authoritative"`; a framework saved without `purpose`, including every existing file, loads as `"score"`) |
| Versioning, audit log | Unchanged |
| Ratify and publish: any analyst today (`api/routers/decision.py` uses `current_user`) | For `purpose = "authoritative"` only: ratify and publish require the **approver** role (`require_role("approver")`). Scoring frameworks are unchanged |
| `publish()` freezes a `PublishedDecision` (scores and tiers only) | Publishing writes the authoritative values and their derivations to Postgres (see Storage) |

### The "All source values" dataset

- **Scope.** The user picks a universe or portfolio, as other sources do. One row per company in it that the identity
  registry resolves. *(Claude's call.)*
- **One row per company.** Each input is the company's **latest** value valid at the dataset's `as_of`, whatever its
  period. That is the `company_facts` row with `valid_from <= as_of` and `valid_to` null or `> as_of` and the greatest
  `period_end`; ties go to the empty `basis`. This is the owner's choice: sources dated differently (vendor files by
  load month, filings by fiscal year end) still meet in one row, and the rules decide which period counts.
- **Inputs.** The user picks fields from the field registry, both extracted and provider fields. For each picked field,
  the row gets these columns:

  | Column | From |
  |---|---|
  | `<alias>` | `company_facts.canonical_value` where set, else `value` |
  | `<alias>__unit` | `company_facts.canonical_unit`, else `field_observations.unit` |
  | `<alias>__period_end` | `company_facts.period_end` |
  | `<alias>__status` | `company_facts.status`: `auto_accepted`, `approved`, `edited`, `pending_review`, `held` |
  | `<alias>__source` | the observation's `source_kind`: `extraction`, `provider`, `xbrl` or `manual` |
  | `<alias>__provider` | for provider rows, the `data_sources.slug` (e.g. `esg_demo`); otherwise null |
  | `<alias>__method` | `field_observations.method` |
  | `<alias>__confidence` | `field_observations.confidence` |
  | `<alias>__observed_at` | `field_observations.created_at`, when ARP recorded the value *(Claude's call)* |

  The alias is a user-editable column name. It defaults to the field id with every character outside `[a-z0-9_]`
  replaced by `_`, because ZEN identifiers cannot contain `:`. A cell with no value is JSON `null`. Two picked fields
  whose aliases collide are refused with HTTP 422 naming both.
- **Portfolio-store inputs.** The portfolio store's `climate_*` observations (`DataPointObservation`) can also be
  picked, so a framework can reproduce today's WACI behaviour before switching over. They are joined by mapping the
  observation's `company_id` through the identity registry. The latest observation with `observed_at <= as_of` is
  used. The user picks a portfolio field **and one source**; only that source's observations are used. The default
  alias is `portfolio_<source>_<field_id>`, e.g. `portfolio_internal_api_climate_scope1_tco2e`.
  Columns are `<alias>`, `<alias>__unit`, `<alias>__period` (the free-text period, for example `FY2025`),
  `<alias>__source` (`internal_api`, `extracted`, `catalogue`, `estimated_proxy`) and `<alias>__observed_at`.
  *(Claude's call.)*
- **`as_of`.** Set when the dataset is built, defaulting to now, and recorded on the dataset.

### Authoritative outputs

A calculate-only framework declares its **outputs**, which are the authoritative data points:
`{column, name, data_type, unit}`, for example `auth_scope1_tco2e`. The rule graph must output `<column>`, and may
output `<column>__period_end` (ISO date) to state which period the value is for.

- Ratifying fails with HTTP 422 if a declared output's column equals an input column of its dataset; the message names
  the column. This keeps Decision Studio's rule that a rule never overwrites a source column.
- Ratifying a framework fails with HTTP 422 if, evaluated on its current dataset, any declared output is absent from
  every row's result. The message names the output.
- An output can be blank for a row. The verdict is then `no_value`, with reason `no_rule_value` when the graph ran but
  produced nothing (null or absent), or `rule_error: <ZEN error source text>` when the row failed to evaluate (ZEN raises
  a `NodeError`, for example on `10 / x` with `x` null).

### Derivation (per company and output)

- **`inputs`.** Every input column whose name appears in an expression or decision-table cell that computed this
  output, with its value and companion columns and the `field_observations.id` (or portfolio observation) behind it.
  Shortcut: matching names in the expression text over-reports an input that the expression mentions but did not use
  (the losing side of `a ?? b`). That is acceptable because the trace shows the actual result.
- **`trace`.** The ZEN trace (`evaluate(..., {"trace": True})`, confirmed on zen-engine 2.0.2) for the nodes on the
  path to this output: node name, expression or matched table row, node input and output. `evaluate_batch` accepts
  `{"trace": True}` (confirmed on 2.0.2).
- **`framework_id`, `framework_version`, `dataset_id`, `dataset_as_of`, `snapshot_id`.**

The Decision Studio result screen shows this derivation when the user opens an authoritative cell.

## Storage (Postgres)

New table `authoritative_values`. Like `published_facts`, it is append-only: rows are never deleted, and the only
in-place updates are closing a row (`valid_to`, `superseded_by`) and stamping `reconfirmed_at`.

- Key: `(framework_id, output_column, company_id)`. One current row per key (`valid_to IS NULL`).
- Columns: `id`, the key, `value` (JSONB), `canonical_value` (Numeric), `unit`, `period_end`, `status` (`value` or
  `no_value`), `reason`, `derivation` (JSONB), `framework_version`, `dataset_as_of`, `snapshot_id`, `published_by`,
  `valid_from`, `valid_to`, `superseded_by`, `reconfirmed_at`.
- **Publishing a snapshot.** For each key in the dataset:
  - same value, unit, period, status **and `framework_version`** as the current row → set `reconfirmed_at`. A new
    framework version always inserts a new row, so every current derivation names the version that produced it;
  - anything else → insert a new version and close the previous one.

  A current key whose company is not in the new dataset gets a new `no_value` version with reason `not_in_dataset`.
  *(Claude's call: a value never outlives its framework version unnoticed.)*
- **Publish record.** Every publish, including one that only reconfirms, inserts one row into
  `authoritative_publishes`: `snapshot_id`, `framework_id`, `framework_version`, `dataset_id`, `dataset_as_of`,
  `published_by`, `published_at`. A newly inserted value row carries that publish's `snapshot_id`. A reconfirmed row
  keeps its original `snapshot_id`; only `reconfirmed_at` is set to the reconfirming publish's `published_at`.
- **Time.** `valid_from` is the publish time. Reading as of `b` returns rows with `valid_from <= b` and (`valid_to`
  null or `> b`), so it shows what was published at `b`. Publishing a dataset whose `as_of` is earlier than the greatest
  `dataset_as_of` in that framework's `authoritative_publishes` is refused with HTTP 409. *(Claude's call: the timeline
  never runs backwards.)*
- `DecisionStore` stays file-based for frameworks and datasets. Only the published authoritative values live in
  Postgres, because consumers query them across companies and as of dates.

## Relation to fact publishing (decided by the owner)

The two layers stay separate. `published_facts` keeps holding reviewed extraction values with document lineage.
`authoritative_values` is itself the published, versioned, as-of layer for downstream readers. Where the winning input
is an extracted field with a published fact, the derivation links to it: `published_fact_id` is set on that input.
There is no merge and no change to the publish gate.

## Phases (one PR each, in this order)

1. **Core.**
   - the source-values dataset;
   - `purpose = "authoritative"` with outputs and validation;
   - approver-only ratify and publish for those frameworks;
   - derivation, the `authoritative_values` table and publish;
   - read APIs: `GET /api/authoritative/values?framework_id=&output=&company_id=&as_of=` and
     `GET /api/authoritative/values/{id}` (value plus derivation);
   - the derivation view on the Decision Studio result screen.
2. **Climate analytics.** A setting binds each climate field (`climate_scope1_tco2e`, …) to a framework output
   (`climate_authoritative_bindings`, `{field_id: {framework_id, output}}`).
   - A bound field is read from `authoritative_values` as of the metric's `as_of` (by publish time).
   - A company whose current row is `no_value`, or that has no row, counts as missing and never falls back to
     `datapoint_mapping`. `coverage_report` adds `missing: {company_id: reason}` for a bound field; the reason is the
     row's `reason`, `no_authoritative_row` when the company has no row, or `not_published` when the framework has
     never been published.
   - An unbound field works exactly as today.
3. **Decision Studio scoring.** A new source, `from_authoritative(framework_id, as_of, outputs)`: one row per company,
   with columns `<output>` (null for `no_value`) and `<output>__reason` (null for a value). A scoring framework can then
   score authoritative values, and its missing-data policy handles the nulls.

## Approaches considered

- **A: a ZEN rule graph per data point.** Most expressive. Heavy for simple fallbacks.
- **B: an ordered rule list in an ARP-specific language.** Easiest to read, but a second evaluator and editor to
  maintain.
- **C: an ordered rule list whose conditions are ZEN expressions.** Recommended by Claude.
- **Chosen by the owner:** rules come from Decision Studio. That means the framework's existing ZEN `rule_graph`
  (closest to A), with no new language or editor. It reuses Decision Studio's versioning, ratification, audit trail and
  editor.

## Left to the builder

- The UI of the field picker for the source-values dataset; the existing dataset-source screen is the default.
- Indexes on `authoritative_values`.
- How `derivation.trace` is trimmed to the nodes on an output's path.
- The UI for editing an input's alias.

## Acceptance

Rows marked `holdout` stay `unit` until the `HOLDOUT_TOKEN` secret is set; the PR then lists them as owed.

"After AC-n" means: the fixture, plus the steps of AC-n and of the rows AC-n itself names, nothing else.

**Fixture.** A universe with companies **A** and **B**, both resolved in the identity registry. Times are UTC.

- A: provider field `prov:esg_demo:scope1` (source slug `esg_demo`) = 100 tCO2e, period_end 2026-09-30, fact valid from
  2026-10-01. Extracted field `scope1_tco2e` = 90 tCO2e, period_end 2025-12-31, status `approved`, fact valid from
  2026-03-01.
- B: only `prov:esg_demo:scope1` = 50 tCO2e, period_end 2026-09-30, fact valid from 2026-10-01.
- Framework **F**: `purpose = "authoritative"`, output `auth_scope1` (number, tCO2e), one expression node with two
  expressions: `auth_scope1 = scope1_tco2e__status == 'approved' ? scope1_tco2e : prov_esg_demo_scope1` and
  `auth_scope1__period_end = scope1_tco2e__status == 'approved' ? scope1_tco2e__period_end : prov_esg_demo_scope1__period_end`.
- "Dataset D1": an "All source values" dataset for the universe, fields `prov:esg_demo:scope1` and `scope1_tco2e`,
  `as_of` 2026-10-15.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The fixture | Build D1 | 2 rows. A: `prov_esg_demo_scope1` = 100, `prov_esg_demo_scope1__period_end` = `2026-09-30`, `prov_esg_demo_scope1__source` = `provider`, `prov_esg_demo_scope1__provider` = `esg_demo`, `scope1_tco2e` = 90, `scope1_tco2e__status` = `approved`, `scope1_tco2e__source` = `extraction`, `scope1_tco2e__provider` = `null` | holdout |
| AC-2 | The fixture | Build D1 | B: `scope1_tco2e` = `null` and `scope1_tco2e__status` = `null` | holdout |
| AC-3 | A also has extracted `scope1_tco2e` = 80 for period_end 2024-12-31 | Build D1 | A: `scope1_tco2e` = 90, `scope1_tco2e__period_end` = `2025-12-31` | holdout |
| AC-4 | A also has extracted `scope1_tco2e` = 85 for period_end 2025-12-31 with basis `restated` | Build D1 | A: `scope1_tco2e` = 90 (the empty basis wins the tie) | unit |
| AC-5 | The fixture | Build the dataset with `as_of` 2026-09-01 | A and B: `prov_esg_demo_scope1` = `null`. A: `scope1_tco2e` = 90 | holdout |
| AC-6 | Two picked fields whose default aliases are equal | Build the dataset | HTTP 422; the message names both field ids | unit |
| AC-7 | The portfolio store holds `climate_scope1_tco2e` = 200 for A (source `internal_api`, period `FY2025`, observed 2026-05-01) | Build D1 with that field picked | A: `portfolio_internal_api_climate_scope1_tco2e` = 200, `…__period` = `FY2025`, `…__source` = `internal_api` | unit |
| AC-7b | As AC-7, and B has only a `catalogue` observation of `climate_scope1_tco2e` | Build D1 with field `climate_scope1_tco2e`, source `internal_api` picked | B: `portfolio_internal_api_climate_scope1_tco2e` = `null` | unit |
| AC-8 | F unratified; signed in as an analyst | `POST` ratify for F | HTTP 403 | holdout |
| AC-9 | F ratified by an approver; signed in as an analyst | `POST` publish for F on D1 | HTTP 403, and `authoritative_values` has 0 rows | holdout |
| AC-10 | A scoring framework (`purpose` = `score`); signed in as an analyst | Ratify, then publish | Both return HTTP 200, as today | holdout |
| AC-11 | A framework file written before this change (no `purpose` key) | Load it | `purpose` = `score` | holdout |
| AC-11b | The existing Decision Studio test files (`backend/tests/test_decision*.py`) | Run them on the PR build | All pass with no test changed | unit |
| AC-12 | F also declares output `auth_scope2`, which the graph never outputs | Ratify as an approver | HTTP 422; the message contains `auth_scope2` | holdout |
| AC-13 | F ratified; approver signed in | Publish F on D1 | `authoritative_values` has exactly 2 current rows for `auth_scope1`: A: `value` 90, `status` `value`, `period_end` 2025-12-31. B: `value` 50, `status` `value`, `period_end` 2026-09-30 | holdout |
| AC-14 | After AC-13 | `GET /api/authoritative/values/{A's id}` | `derivation.inputs` has an entry `scope1_tco2e` with `value` 90, `status` `approved`, `source` `extraction`, `period_end` `2025-12-31` and `observation_id` = the `field_observations.id` of the 90 | holdout |
| AC-15 | After AC-13 | Same request as AC-14 | `derivation.trace` contains a node whose output has `auth_scope1` = 90. `framework_version` = F's ratified version, `dataset_as_of` = D1's `as_of`, `snapshot_id` = B's row's `snapshot_id` | holdout |
| AC-16 | After AC-13, and A's 90 is published in `published_facts` as fact P | Same request as AC-14 | The `scope1_tco2e` input has `published_fact_id` = P's `fact_id` | unit |
| AC-17 | Framework F2 (purpose authoritative), output `x`, expression `x = 100 / scope1_tco2e`, ratified | Publish F2 on D1 | B: `status` `no_value`, `reason` starts with `rule_error:` | holdout |
| AC-18 | As AC-17 | Publish F2 on D1 | A: `status` `value`, `value` within 1e-9 of 100/90 | unit |
| AC-19 | Framework F3, output `y`, expression `y = scope1_tco2e`, ratified | Publish F3 on D1 | B: `status` `no_value`, `reason` = `no_rule_value` | holdout |
| AC-20 | Framework F4, output `total`, expression `total = scope1_tco2e + prov_esg_demo_scope1`, ratified | Publish F4 on D1, read A | A: `value` 190; `derivation.inputs` lists both `scope1_tco2e` and `prov_esg_demo_scope1` | holdout |
| AC-21 | Framework F5, output `latest`, expression `latest = date(prov_esg_demo_scope1__period_end) > date(scope1_tco2e__period_end) ? prov_esg_demo_scope1 : scope1_tco2e` (plain `>` on two date strings raises a `NodeError` in ZEN 2.0.2, checked), ratified | Publish F5 on D1, read A | A: `value` 100 | unit |
| AC-22 | After AC-13, no change; dataset D2 = D1 with `as_of` 2026-10-20 | Publish F on D2 | Still exactly 2 current rows, with the same `id`s as after AC-13; both have `reconfirmed_at` = this publish's `published_at` and keep AC-13's `snapshot_id`; `authoritative_publishes` has 2 rows for F | holdout |
| AC-23 | After AC-22 | Publish F on a dataset with `as_of` 2026-10-17 | HTTP 409, and no row in `authoritative_values` or `authoritative_publishes` changes | holdout |
| AC-24 | After AC-13, A's `scope1_tco2e` fact is edited to 95 (status `edited`); nothing republished | `GET /api/authoritative/values?framework_id=F&output=auth_scope1&company_id=A` | Exactly 1 item, `value` 90 | holdout |
| AC-25 | After AC-24, F v2 ratified with `scope1_tco2e__status in ['approved','edited']` in both expressions; dataset D3 with `as_of` 2026-10-25 | Publish F v2 on D3 | A has 2 rows: v1 `value` 90 with `valid_to` = v2's `valid_from` and `superseded_by` = v2's `id`; v2 `value` 95 with `valid_to` null | holdout |
| AC-25b | After AC-25 | Read B's current `auth_scope1` row | `value` 50, `framework_version` = 2 (a new row); B's v1 row has `valid_to` set | holdout |
| AC-26 | After AC-25 | `GET …&company_id=A&as_of=<a time between the two publishes>` | Exactly 1 item, `value` 90 | holdout |
| AC-27 | After AC-25 | `GET …&company_id=A&as_of=<a time before AC-13's publish>` | 0 items | holdout |
| AC-28 | After AC-13, B removed from the universe; dataset D4 with `as_of` 2026-10-26 | Publish F on D4 | B's current row: `status` `no_value`, `reason` `not_in_dataset`; B's row with `value` 50 still exists with `valid_to` set | holdout |
| AC-29 | Before and after AC-13's publish | Count and hash all rows of `company_facts`, `field_observations` and `published_facts` | Identical | holdout |
| AC-29b | Framework F6 declares output `scope1_tco2e`, which is also an input column of D1 | Ratify as an approver | HTTP 422; the message contains `scope1_tco2e` | holdout |
| AC-30 | After AC-13, in the running app | Open F's result in Decision Studio and click A's `auth_scope1` cell | A panel shows value 90; the input `scope1_tco2e` = 90 with `approved`, `extraction`, `2025-12-31`; and the expression text `scope1_tco2e__status == 'approved' ? scope1_tco2e : prov_esg_demo_scope1` | evaluator |
| AC-31 | Phase 2. Portfolio store: A and B have `climate_scope1_tco2e` 200 and 300, `climate_scope2_tco2e` 0 and 0, `climate_evic_eur_m` 10 and 10. One holding each, `market_value_eur` 1,000,000. `climate_scope1_tco2e` bound to F/`auth_scope1`; state after AC-13 | `compute_financed_emissions` with `as_of` now | `financed_emissions_tco2e` = 14.0 (0.1 × 90 + 0.1 × 50) | holdout |
| AC-32 | As AC-31 but no binding | Same call | `financed_emissions_tco2e` = 50.0 (0.1 × 200 + 0.1 × 300), as on `main` | holdout |
| AC-33 | As AC-31, state after AC-28 (B `no_value`) | Same call | `financed_emissions_tco2e` = 9.0, `uncovered_holding_count` = 1 | holdout |
| AC-34 | As AC-33 | `coverage_report` for `climate_scope1_tco2e` | `missing` = `{B: "not_in_dataset"}` | holdout |
| AC-35 | As AC-31, but F never published | `coverage_report` for `climate_scope1_tco2e` | `missing` = `{A: "not_published", B: "not_published"}` | holdout |
| AC-35b | As AC-31 after AC-13, plus a holding in company C, resolved but not in F's universe, with portfolio-store values | `coverage_report` for `climate_scope1_tco2e` | `missing` includes `C: "no_authoritative_row"` | holdout |
| AC-36 | As AC-31, state after AC-25 | `compute_financed_emissions` with `as_of` between AC-13's and AC-25's publish | `financed_emissions_tco2e` = 14.0 (A still 90) | unit |
| AC-37 | Phase 3, state after AC-28 | `from_authoritative(F, as_of=now, ["auth_scope1"])` | 2 rows. A: `auth_scope1` = 90, `auth_scope1__reason` = `null`. B: `auth_scope1` = `null`, `auth_scope1__reason` = `not_in_dataset` | holdout |

Must not change: extraction, review and `published_facts` (AC-29); ratification, publishing and scoring of scoring
frameworks (AC-10, AC-11); climate analytics without a binding (AC-32).
