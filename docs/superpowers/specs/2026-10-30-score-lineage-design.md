# Score lineage

Status: approved by the owner on 2026-10-30. Replaces phase 3 of
`2026-10-28-authoritative-data-layer-design.md`, whose AC-37 this spec takes over as AC-1.

## Why

PR #276 made one authoritative value per company and data point, with its derivation. Decision Studio still scores
from an anonymous table: a published tier cannot say which values produced it, and a company with missing data is
quietly scored on whatever is left. The EDEN Nova lineage (provider observation → canonical contract → eligibility →
score → "published result and provenance", with a "null result with reason code" branch) is the model.

The owner wants every published score, rank and tier traceable to the authoritative values it used, and through them
to source facts and documents. Where a value the framework requires is missing, the result must be "no score" with a
reason, not a quiet fill-in.

## Goals

1. Decision Studio can score authoritative values: a new dataset source, `from_authoritative`.
2. A framework can mark criteria **required**. A company missing any required value gets **no score** with a reason
   code naming each missing criterion and the authoritative value's own reason. Optional criteria keep today's
   missing-data policy.
3. Every criterion contribution records the authoritative value id it used, and whether it was imputed and why.
4. A published decision freezes that per row. Its lineage resolves score → criteria → authoritative values →
   derivation inputs → source facts → published fact and document. It stays the same however the values change later.
5. The chain is visible in four places, as the owner chose:
   - a Decision Studio drill-down;
   - a published-decision lineage API;
   - an exportable audit file (CSV and JSON);
   - a "Why this tier" link in the Steward coverage screen and in Index Builder.

## Non-goals

- A reverse lookup ("which published tiers used this value?"). Approach B, deferred.
- Copying the chain into published decisions (approach C). Only ids are stored.
- Any change to scoring maths, normalisation, weighting or tiers for frameworks that mark no criterion required.
- Alerts when an authoritative value behind a published tier is restated.
- Lineage for datasets that do not come from `from_authoritative`. Their criteria show the link `dataset_cell` and stop
  there.

## Anti-goals

- A chain that silently stops. Every link that cannot be resolved is shown as such, never omitted.
- A changed score, rank or tier for any existing framework that marks nothing required.
- Lineage that reads today's values instead of the values the decision was scored with.

## Principle (owner)

**The user determines every decision.** Whenever this feature has a choice that changes a result, the choice is a
framework setting the user picks in Decision Studio. It is stored on the framework version and recorded in the audit
log. ARP ships no hidden default policy. Where a setting needs an initial value so that existing frameworks keep
behaving as today, that value reproduces today's behaviour, and the setting is shown in the UI.

## Decided with the owner

| Question | Decision |
|---|---|
| Missing values | **Required criteria.** A required criterion with no usable value means no score. Optional criteria are filled as today. |
| Where the chain is visible | All four places: Decision Studio drill-down, the lineage API, the export file, and the Steward and Index Builder links |
| Normalisation of `no_score` companies | **The user chooses**, per framework: `no_score_rows: "exclude" \| "include"` (see §2). |
| Levels mode | **Relative mode only.** `required` is not offered in levels mode; levels frameworks are unchanged. |
| Steward link | **One link per framework.** For each company, one "Why" link per latest published framework that has a row for it, labelled with the framework name and tier. |
| Storage | **Approach A.** Value ids go into the published decision (the JSON file in `DecisionStore`). The rest of the chain is resolved when read. This is safe because `authoritative_values` is append-only and `published_facts` is versioned. |

## Design

### 1. Dataset source `from_authoritative`

`from_authoritative(framework_id, as_of, outputs)` in `decision/sources.py`. It is offered as source
`authoritative`, with `framework_id`, `as_of` (default now) and `outputs` (default all) on `FromSourceRequest`.

- **Rows.** One per company with any row for the framework in `authoritative_values` visible at `as_of`, including
  `no_value` rows.
- **Columns:**
  - `company_id`, `Company`;
  - per output: `<output>` (the value, `""` when `no_value`), `<output>__reason` (`""` when there is a value) and
    `<output>__value_id` (the `authoritative_values.id`).
- **`source_ref`** = `framework_id`, and `as_of` is recorded on the dataset.
- **Profiling.** `__value_id` and `__reason` columns are never proposed as criteria. They are marked as identifier and
  text columns in profiling.

### 2. Required criteria

- `Criterion.required: bool = False`. A config without the key loads as `False`.
- `required` is offered only in relative mode (`mode = "relative"`). Saving a levels-mode framework with a required
  criterion returns 422.
- `required` applies to a criterion whether or not its weight is 0. A required criterion that is disabled counts as
  not required. A required criterion whose column is absent from the table makes every row `no_score`, and publishing
  is already refused through `missing_columns`.
- A row is **missing** a required criterion when the engine's typed value for it is `None`: a blank cell, or a cell
  that does not parse in a numeric column. This is the same test coverage uses.
- Such a row gets the new `EntityStatus` **`no_score`**. Its `score`, `rank`, `rank_min`, `rank_max`, `tier`,
  `tier_name` and `leverage` are all `None`. The engine computes a raw score today even for rows it does not rank, so
  `no_score` must clear it explicitly. The other rows are ranked and tiered without it.
- **User setting `no_score_rows`** on the framework:
  - `"include"`, the initial value for every framework (today's behaviour): `no_score` rows still count in
    normalisation, means, cohort sizes and entropy weights, so the other companies' scores are exactly what they would
    be without the required flag;
  - `"exclude"`: `no_score` rows are removed before normalisation, so the other companies are normalised only against
    each other.

  The Mechanism tab shows the setting next to the missing-data policy. Changing it is audited like any other rule
  change.
- `EntityDecision.reasons: list[str]` holds one entry per missing required criterion, in criterion order:
  - `required_missing: <column> (<reason>)`;
  - `<reason>` is the row's `<column>__reason` cell when the dataset has one, else `blank`.
- Levels mode never produces `no_score`.

### 3. Contributions carry their source

`CriterionContribution` gains:
- `value_id: int | None`: the row's `<column>__value_id` when the dataset has it;
- `missing_reason: str | None`: set whenever the typed value is `None`, whether or not the missing-data policy
  imputed it. It holds the row's `__reason` cell when the dataset has one, else `blank`.

`imputed` already exists. For a `no_score` row, contributions are still listed with `contribution = 0` and the
reason, so the drill-down can show what was there.

### 4. Published rows keep the ids

- `PublishedRow` gains `reasons: list[str]` and
  `criteria: list[{column, contribution, imputed, value_id, missing_reason}]`.
- `PublishedDecision` gains `source: str` (the dataset's source) and `source_ref`.
- A published decision written before this change has neither. Its lineage returns `criteria: [{"link": "not_recorded"}]`, exactly one entry.

### 5. Resolving the chain (one function, used by all four places)

`arp/decision/lineage.py`: `row_lineage(snapshot, entity_id) -> dict`. For each criterion:

1. **Contribution:** `{column, contribution, imputed, missing_reason}`.
2. **Link to the value:**
   - `value_id` set: the `authoritative_values` row by id, with value, status, reason, framework version and
     derivation (`AuthoritativeStore.get`). These fields never change. The row's `valid_to` and `superseded_by` are
     today's, so the lineage labels them "current validity", and adds `superseded: true` when the value has since
     been replaced.
   - No `value_id`, from a non-authoritative source: `link: "dataset_cell"`.
   - An id that no longer resolves: `link: "missing", value_id: <id>`.
3. **Per derivation input:**
   - the input as it was when the value was evaluated, read from the stored derivation (value, status, source,
     provider, period end, unit, observation id);
   - the `field_observations` row, when the id resolves (field id, value as recorded);
   - the `published_fact_id` stored in the derivation, when present;
   - the citations of that observation (`value_citations`: doc id, page, quote, grounded).

   An input without an observation id is shown with `link: "no_observation"`.

The result also carries the row's score, rank, tier, status and reasons, and the snapshot's framework id, version,
`as_of`, `published_by` and `published_at`. Its shape, with every key; values are JSON numbers, strings, booleans or
null:

```json
{
  "snapshot_id": "pub_…", "framework_id": "fw_s", "framework_version": 1, "as_of": "…",
  "published_by": "Bob", "published_at": "…",
  "entity_id": "A", "name": "Company A", "status": "scored", "reasons": [],
  "score": 61.2, "rank": 2, "tier": 1, "tier_name": "Tier 1",
  "criteria": [
    {
      "column": "auth_scope1", "contribution": 30.6, "imputed": false, "missing_reason": null,
      "link": "authoritative", "value_id": 17,
      "value": {"value": 90, "unit": "tCO2e", "status": "value", "reason": null, "period_end": "2025-12-31",
                "framework_id": "fw_f", "framework_version": 1, "superseded": false,
                "current_valid_to": null},
      "inputs": [
        {"name": "scope1_tco2e", "value": 90, "status": "approved", "source": "extraction", "provider": null,
         "period_end": "2025-12-31", "unit": "tCO2e", "observation_id": 42, "published_fact_id": null,
         "link": "observation",
         "citations": [{"doc_id": "d1", "page": 4, "quote": "Scope 1: 90 tCO2e", "grounded": true}]}
      ]
    }
  ]
}
```

`criteria[].link` is one of `authoritative`, `dataset_cell` (with `value` and `inputs` null), `missing` (with `value_id`
set and `value` and `inputs` null) or `not_recorded`. For a published row written before this change, `criteria` is
exactly `[{"link": "not_recorded"}]`. `inputs[].link` is `observation` or `no_observation` (with `observation_id` null
and `citations` empty).

### 6. Where it is shown

- **API (`api/routers/decision.py`):**
  - `GET /api/decision/published/{snapshot_id}/rows/{entity_id}/lineage` returns `row_lineage`, or 404 for an unknown
    snapshot or entity;
  - `GET /api/decision/published/{snapshot_id}/lineage.json` returns all rows;
  - `GET /api/decision/published/{snapshot_id}/lineage.csv` returns one line per entity × criterion × input ×
    citation. An input with no citation gives one line with blank citation columns, and `reasons` are joined with
    `; `. Header:
    `entity_id,name,status,score,tier,rank,reasons,criterion,contribution,imputed,missing_reason,value_id,value,value_status,value_reason,input,input_value,observation_id,source,provider,period_end,published_fact_id,doc_id,page,quote`.
    A criterion with no inputs gets one line with blank input columns. A `no_score` row with no criteria data gets one
    line.
- **Decision Studio:**
  - Results drill-down: clicking a company's score, or a `no_score` badge, opens a lineage panel. It reuses PR 1's
    derivation panel styles and shows each criterion → its value → its inputs → its citations.
  - Before publishing, the panel uses the live result. After publishing, it uses `row_lineage`.
  - The published-decisions list gets "Download lineage (CSV)" and "(JSON)".
- **Steward coverage screen (`pages/steward/decisions.tsx`) and Index Builder:** for each company, one link per
  latest published framework that has a row for it, labelled `Why: <framework name> <tier name or "no score">`. It opens
  the same lineage panel for that snapshot and entity. The coverage rule engine is not changed.

### 7. Consumers

- `as_fields` adds `decision.<framework_id>.status` (`scored`, `excluded`, `insufficient` or `no_score`) and
  `decision.<framework_id>.reasons` (the reasons joined with `; `). All existing fields are unchanged.
- A `no_score` row emits none of today's keys `.score`, `.tier`, `.tier_name`, `.rank` or `.rank_max`; it has only `.status` and `.reasons`. Coverage rules and index screens treat those as
  missing, under their own missing-value policy, which the user sets there. A rule can also read `.status` directly.
  The company appears in Index Builder's "matched" count because `.status` is present.

## Approaches considered

- **A: value ids in the published decision, resolved on read.** Chosen by the owner. Smallest change, and ids are
  stable.
- **B: a Postgres lineage table.** Adds reverse lookup, at the cost of a new table and two stores for one publication.
- **C: a full copied snapshot.** Self-contained, but large, and it drifts from corrected sources.

## Left to the builder

- Layout of the lineage panel within the existing design system.
- How many inputs and citations the panel shows before folding the rest behind "show all".
- CSV quoting, which follows the `csv` module's defaults.

## Acceptance

Rows marked `holdout` stay `unit` until the `HOLDOUT_TOKEN` secret is set, and the PR then lists them as owed.
"After AC-n" means the fixture plus the steps of AC-n and of the rows AC-n itself names, and nothing else.

**Fixture.** Authoritative framework **F** (as built in PR #276) has two outputs:
- `auth_scope1`, with rule `auth_scope1 = scope1_tco2e`;
- `auth_capex`, with rule `auth_capex = capex_eur`.

F is published for companies A, B, C and D:

| Company | `auth_scope1` | `auth_capex` |
|---|---|---|
| A | 90 | 10 |
| B | 50 | `no_value`, reason `no_rule_value` |
| C | `no_value`, reason `not_in_dataset` | 5 |
| D | 70 | 20 |

A's `scope1_tco2e` observation has one `value_citations` row: doc `d1`, page 4, quote `Scope 1: 90 tCO2e`, grounded `true`.

Scoring framework **S**:
- relative mode;
- criterion `auth_scope1`: direction `lower`, `required = true`;
- criterion `auth_capex`: direction `higher`, not required;
- `missing = "renormalise"`, `no_score_rows = "include"`.

Dataset **DA** = `from_authoritative(F, as_of=now)`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The fixture | Build DA | 4 rows. C: `auth_scope1` = `""`, `auth_scope1__reason` = `not_in_dataset`, `auth_scope1__value_id` = C's `auth_scope1` row id in `authoritative_values`, as a string. A: `auth_scope1` = `"90"` (dataset cells are strings), `auth_scope1__value_id` = the id as a string | holdout |
| AC-2 | DA | `POST /api/decision/mechanisms/derive` on DA | No proposed criterion has a column ending in `__reason` or `__value_id` | holdout |
| AC-3 | DA, S | Score | C: `status` = `no_score`, `reasons` = `["required_missing: auth_scope1 (not_in_dataset)"]` | holdout |
| AC-4 | DA, S | Score | C: `score`, `rank`, `rank_min`, `rank_max`, `tier`, `tier_name` and `leverage` are all `null` | holdout |
| AC-5 | DA, S | Score | The ranks of A, B and D are exactly {1, 2, 3} | holdout |
| AC-6 | DA, S | Score | B's `auth_capex` contribution: `missing_reason` = `no_rule_value`, `value_id` = B's `auth_capex` row id, `imputed` = `false` | holdout |
| AC-7 | DA, S | Score | A's contributions: `value_id` = A's `auth_scope1` and `auth_capex` row ids; `missing_reason` = `null` on both | holdout |
| AC-8 | DA, S (`no_score_rows = "include"`) and S' = S with `required = false` | Score both | A, B and D have equal scores (difference < 1e-9), equal ranks and equal tiers under S and S' | holdout |
| AC-9 | DA, S with `no_score_rows = "exclude"`, and DA' = DA without C's row | Score S on DA and on DA' | A, B and D have equal scores in both (difference < 1e-9) | holdout |
| AC-10 | The existing Decision Studio tests (`backend/tests/test_decision_*.py`) | Run on the PR build | All pass with no test changed | unit |
| AC-11 | A levels-mode framework with a criterion `required = true` | `POST /api/decision/mechanisms` | HTTP 422; the message contains `required` | holdout |
| AC-12 | An uploaded CSV with a blank cell in column `x` for row R, and a relative-mode framework where `x` is required | Score | R: `status` = `no_score`, `reasons` = `["required_missing: x (blank)"]` | holdout |
| AC-13 | DA, S ratified | Publish | The published row for C has `status` = `no_score` and the same `reasons` as AC-3. The published row for A has `criteria` with A's two `value_id`s. The snapshot's `source` = `authoritative` | holdout |
| AC-14 | After AC-13 | `GET /api/decision/published/{snapshot}/rows/A/lineage` | In `criteria` the entry with `column` = `auth_scope1` has `link` = `authoritative`, `value_id` = A's row id and `value.value` == 90 (a JSON number). Its `inputs` holds exactly one entry, with `name` = `scope1_tco2e`, the observation's id as `observation_id`, and `citations` = `[{"doc_id": "d1", "page": 4, "quote": "Scope 1: 90 tCO2e", "grounded": true}]` | holdout |
| AC-15 | After AC-13, F republished so that A's `auth_scope1` = 95 (a new version) | The same request as AC-14 | The `auth_scope1` entry still has `value.value` == 90 and the same `value_id`, and `value.superseded` = `true` | holdout |
| AC-16 | A published decision of a framework scored on an uploaded CSV | Lineage of any row | Every criterion has `link` = `dataset_cell` | holdout |
| AC-17 | A published decision file written before this change (rows have no `criteria` key) | Lineage of a row | Response 200. The row's status and score are present, and `criteria` = `[{"link": "not_recorded"}]` | holdout |
| AC-18 | After AC-13 | Lineage for an unknown snapshot id; for an unknown entity id | HTTP 404 for each | holdout |
| AC-19 | After AC-13 | `GET …/lineage.csv` | The first line equals the header in §6 exactly; there are exactly 8 data lines: A, B, C and D × 2 criteria × 1 line. Each input has at most one citation, and C's `auth_scope1` has no input, so it gives one line with blank input columns | holdout |
| AC-20 | After AC-13 | `GET …/lineage.json` | A list of 4 objects, each equal to that row's `…/rows/{id}/lineage` response | holdout |
| AC-21 | After AC-13 | `as_fields(snapshot)` | C has `decision.<S>.status` = `no_score` and `decision.<S>.reasons` = `required_missing: auth_scope1 (not_in_dataset)`, and none of the keys `.score`, `.tier`, `.tier_name`, `.rank` or `.rank_max`. A has exactly the keys `decision.<S>.score`, `.tier`, `.tier_name`, `.rank`, `.rank_max`, `.status` and `.reasons`, with `.status` = `scored` and `.reasons` = `""` | holdout |
| AC-22 | S saved with `no_score_rows = "include"` | Save a new version with `"exclude"` | The audit log for the new version has one entry naming `no_score_rows`, with `origin` = `human` | unit |
| AC-23 | After AC-13, in the running app | In Decision Studio Results, click C's `no_score` badge; then click A's score | C's panel shows `required_missing: auth_scope1 (not_in_dataset)`. A's panel shows `auth_scope1` = 90 → `scope1_tco2e` → `d1` page 4 `Scope 1: 90 tCO2e` | evaluator |
| AC-24 | After AC-13, with the coverage screen showing company A | Open the Steward coverage screen | A shows a link `Why: S <A's tier name>`; clicking it shows the same chain as AC-23 | evaluator |
| AC-25 | After AC-13, with S's snapshot joined in Index Builder | Open Index Builder | A shows `Why: S <A's tier name>` and C shows `Why: S no score`; clicking A's link shows the chain of AC-23 | evaluator |
| AC-26 | S open on the Mechanism tab | Look at the missing-data settings | A control for `no_score_rows` with the choices "include" and "exclude", showing the saved value | evaluator |
| AC-27 | After AC-13, A's `auth_scope1` row deleted from `authoritative_values` directly in the test database | The lineage of A | The `auth_scope1` entry has `link` = `missing`, `value_id` = the deleted id, and `value` = `null` | holdout |
| AC-28 | After AC-13, the `observation_id` removed from A's `scope1_tco2e` input in the stored derivation (test setup) | The lineage of A | That input has `link` = `no_observation`, `observation_id` = `null` and `citations` = `[]` | holdout |
| AC-29 | An uploaded CSV whose numeric column `x` holds `n/a` for row R, and a relative framework where `x` is required | Score | R: `status` = `no_score`, `reasons` = `["required_missing: x (blank)"]` | holdout |
| AC-30 | DA, S with `auth_scope1` required but disabled | Score | C has `status` = `scored`, a non-null `rank`, and `reasons` = `[]` | holdout |
| AC-31 | DA, S with `missing` = `"mean"` (the existing mean-imputation policy value) | Score | B's `auth_capex` contribution: `imputed` = `true`, `missing_reason` = `no_rule_value` | holdout |
| AC-32 | DA, S, not yet published, in the running app | In Results, click C's `no_score` badge | The panel shows `required_missing: auth_scope1 (not_in_dataset)` | evaluator |
| AC-33 | After AC-13, in the running app | The published-decisions list | S's snapshot shows "Download lineage (CSV)" and "Download lineage (JSON)", and each downloads the file of AC-19 / AC-20 | evaluator |
| AC-34 | After AC-13, S published a second time, and a framework T published with a row for A | Open the Steward coverage screen | A shows exactly two links, `Why: S …` (opening the second S snapshot) and `Why: T …` | evaluator |

Must not change: scoring of frameworks with no required criterion (AC-8, AC-10); existing `as_fields` keys (AC-21);
published decisions written before this change still load and resolve (AC-17).
