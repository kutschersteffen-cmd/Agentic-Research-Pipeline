# Authoritative data layer

Status: draft, awaiting owner approval. Delivered as several PRs (see Phases).

## Why

ARP keeps the same metric in places that never meet. Scope 1 emissions, for example, can exist as:

- a vendor value on a provider field (`prov:esg_<provider>:<code>`, loaded by `portfolio/climate/esg_intake.py`);
- an XBRL-tagged or LLM-extracted value on an extraction-schema field, reviewed and kept in `company_facts`;
- a reviewer's edit of that value (`company_facts.status = edited`);
- the climate-analytics field `climate_scope1_tco2e` in the portfolio store, which is what WACI and financed emissions
  actually read (`portfolio/datapoint_mapping.py`, with a hard-coded source order).

No part of ARP says that these are the same data point, and every consumer picks a source in its own way. The EDEN Nova
review made the gap visible: Nova's design rests on one canonical data contract that every source feeds and every
score reads.

The owner wants an **authoritative data layer that the user defines**. ARP ships no preset source order. Users write
the rules that pick and combine source values into one final value per data point. Each verdict states its value, the
inputs it used and the logic that produced it.

## Goals

1. Users define authoritative data points and their rules **in Decision Studio**, as a framework.
2. Rules can pick (fallback, preference, conditions on review state, age or source) and combine (sum, ratio, unit
   conversion) source values, per company and period.
3. Every authoritative value carries its derivation: which input columns it read, their values and sources, and the
   rule nodes that computed it (the ZEN trace).
4. An analyst drafts the rules, an approver ratifies them, and only a ratified version can publish authoritative values.
5. Published authoritative values are versioned and readable **as of a date**. Re-reading an earlier date returns
   exactly what was published then.
6. Consumers read the authoritative value instead of choosing a source: climate analytics, Decision Studio scoring
   frameworks and fact publishing.

## Non-goals

- No default or built-in precedence. A data point with no ratified authoritative framework behaves exactly as today.
- No LLM anywhere in the layer. It is deterministic code, like the rest of Decision Studio.
- No new rule language and no new rule editor: the framework's existing `rule_graph` (ZEN / GoRules JDM, edited in
  `RuleGraphEditor.tsx`) is the rule format.
- No reporting-year alignment convention (such as Nova's 17-month rule). Users can express one as a rule; ARP does not
  impose one.
- No change to extraction, grounding, review or the fact ledger rules (`decide`).

## Anti-goals (a failure even if it works)

- An authoritative value whose derivation cannot be shown, or that changes when nobody republished it.
- A consumer that silently falls back to its old source picking when a bound authoritative framework has no value.
  "No value" must reach the consumer as "no value" with a reason.
- Overwriting or editing any source value. The layer only reads sources.

## How it fits Decision Studio (decided with the owner)

| Decision Studio today | Authoritative framework |
|---|---|
| A `Dataset` from a source function in `decision/sources.py` | New source **"All source values"** (`from_source_values`), described below |
| `MechanismConfig.rule_graph` computes calculated columns per row (`decision/rules.py`) | The same graph computes the authoritative columns. Unchanged guarantees: it never overwrites a source column, and a row it cannot evaluate gets blank values |
| Criteria, gates, normalisation, tiers | Not used. The framework is **calculate-only** |
| Versioning, ratification (`DecisionStore.ratify`), audit log | Unchanged and required |
| `publish()` freezes a `PublishedDecision` (scores and tiers only) | Publishing writes the authoritative values and their derivations to Postgres (see Storage) |

### The "All source values" dataset

- **Rows.** One per (company, period_end, basis) that has at least one selected input value valid at the dataset's
  `as_of` date.
- **Inputs.** The user picks fields from the field registry (extracted and provider fields). For each picked field
  `f`, the row gets:
  - `<alias>`: the value of the fact current at `as_of` (the `company_facts` row with `valid_from <= as_of` and
    `valid_to` null or `> as_of`), as `canonical_value` in `canonical_unit` where one exists, else `value`;
  - `<alias>__status` (`auto_accepted`, `approved`, `edited`, `pending_review`, `held`), `<alias>__method`
    (`tagged`, `adjudicated`, …), `<alias>__source` (provider slug, `extraction` or `xbrl`), `<alias>__observed_at`,
    `<alias>__unit`, `<alias>__confidence`.

  The alias is a user-editable column name, defaulting to the field id with `:` replaced by `_`. ZEN identifiers cannot
  contain `:`.
- **Portfolio-store inputs.** The `climate_*` observations in the portfolio store also become selectable inputs
  (`portfolio_<source>_<field>`), so a framework can reproduce today's WACI behaviour before switching over.
- **`as_of`.** Set when the dataset is built, defaulting to today, and recorded on the dataset.

### Authoritative outputs

A calculate-only framework declares its **outputs**. These are the authoritative data points:
`{column, name, data_type, unit}`. The column is what the rule graph must output, for example `auth_scope1_tco2e`.

- Saving a framework whose rule graph cannot produce a declared output fails validation, with a message naming the
  output.
- An output can be blank for a row. The verdict is then "no value" with the reason: either "no rule produced a value"
  or the ZEN error text for that row.

### Derivation (per row and output)

- **`inputs`.** Every input column whose name appears in an expression that computed this output, with its value and
  companion columns (`__source`, `__status`, `__observed_at`, `__unit`) and the observation id of the underlying fact.
  Shortcut: matching names in the expression text over-reports an input that the expression mentions but did not use
  (for example the losing side of `a ?? b`). That is acceptable because the trace below shows the actual result.
- **`trace`.** The ZEN trace (`evaluate(..., {"trace": True})`, available in zen-engine 2.0.2) for the nodes on the
  path to this output: node name, expression or decision-table row, node input and output.
- **`framework_id`, `framework_version`, `dataset_as_of`, `snapshot_id`.**

The Decision Studio result screen shows the derivation when a user opens an authoritative cell.

## Storage (Postgres)

A new append-only table, `authoritative_values`. Nothing is ever edited; rows are only closed.

- Key: `(framework_id, output_column, company_id, period_end, basis)`.
- Columns: `value` (JSONB), `canonical_value`, `unit`, `status` (`value` | `no_value`), `reason`, `derivation`
  (JSONB), `framework_version`, `snapshot_id`, `published_by`, `valid_from`, `valid_to`, `superseded_by`.
- Publishing a snapshot works like `publish/facts.py`. Each key whose value or status changed gets a new version, and
  the previous version is closed. An unchanged value only gets `reconfirmed_at`.
- Read as of `b`: `valid_from <= b` and (`valid_to` null or `> b`).
- `DecisionStore` stays file-based for frameworks and datasets. Only the published authoritative values move to
  Postgres, because consumers need as-of queries across companies.

### Who may publish

Only the approver role, only a ratified framework version, and the publisher is recorded. This is the same rule as
`decision/publish.py` and `api/routers/publish.py`.

## Consumers (phases, one PR each, in this order)

1. **Core.** The source-values dataset, calculate-only frameworks with outputs, validation, derivation, the
   `authoritative_values` table, publish, and two read APIs: `GET /api/authoritative/values?framework_id=&as_of=&company_id=&output=`
   and `GET /api/authoritative/values/{id}/derivation`. Plus the result-screen derivation view.
2. **Climate analytics.** A setting binds each climate field (`climate_scope1_tco2e`, …) to a framework output. A
   bound field is read from `authoritative_values` as of the metric's `as_of`, and an unbound field works as today.
   With a binding, a company without an authoritative value counts as missing in coverage; it never falls back to
   `datapoint_mapping`.
3. **Decision Studio scoring.** A new source, `from_authoritative(framework_id, as_of, outputs)`, so a scoring
   framework can score authoritative values.
4. **Fact publishing.** Decided by the owner (see Open questions).

## Approaches considered

- **A: a ZEN rule graph per data point.** Most expressive. Heavy for simple fallbacks.
- **B: an ordered rule list in an ARP-specific language.** Easiest to read, but a second evaluator and editor to
  maintain.
- **C: an ordered rule list whose conditions are ZEN expressions.** Recommended by Claude.
- **Chosen by the owner:** rules come from Decision Studio. That means the framework's existing ZEN `rule_graph`
  (closest to A), with no new language or editor. This is the owner's call, and it reuses Decision Studio's versioning,
  ratification and audit trail.

## Left to the builder

- Which UI the field picker for the source-values dataset uses; the existing dataset-source screen is the default.
- Indexing of `authoritative_values`.
- How `derivation.trace` is trimmed to the nodes on an output's path.

## Open questions (for the owner)

- Phase 4: how does fact publishing (`published_facts`) relate to authoritative values? See the builder-check
  questions.

## Acceptance

(drafted after the builder check)
