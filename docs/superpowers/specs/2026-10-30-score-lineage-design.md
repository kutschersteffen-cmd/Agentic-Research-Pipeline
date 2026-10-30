# Score lineage

Status: draft, awaiting owner approval. Replaces phase 3 of
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
- Any change to scoring maths, normalisation, weighting or tiers for criteria that are not required.
- Alerts when an authoritative value behind a published tier is restated.
- Lineage for datasets that do not come from `from_authoritative`. Their criteria show the link `dataset_cell` and stop
  there.

## Anti-goals

- A chain that silently stops. Every link that cannot be resolved is shown as such, never omitted.
- A changed score, rank or tier for any existing framework that marks nothing required.
- Lineage that reads today's values instead of the values the decision was scored with.

## Decided with the owner

| Question | Decision |
|---|---|
| Missing values | **Required criteria.** A required criterion with no usable value means no score. Optional criteria are filled as today. |
| Where the chain is visible | All four places: Decision Studio drill-down, the lineage API, the export file, and the Steward and Index Builder links |
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
- A row is **missing** a required criterion when its cell is blank after typing (the same test the engine uses for
  coverage).
- Such a row gets the new `EntityStatus` **`no_score`**, applied before gates, sufficiency and scoring. It gets no
  score, rank, rank range or tier, and the rest of the table is ranked without it.
- `EntityDecision.reasons: list[str]` holds one entry per missing required criterion, in criterion order:
  - `required_missing: <column> (<reason>)`;
  - `<reason>` is the row's `<column>__reason` cell when the dataset has one, else `blank`.
- Levels mode follows the same rule.

### 3. Contributions carry their source

`CriterionContribution` gains:
- `value_id: int | None`: the row's `<column>__value_id` when the dataset has it;
- `missing_reason: str | None`: the `__reason` cell when the value was imputed.

`imputed` already exists. For a `no_score` row, contributions are still listed with `contribution = 0` and the
reason, so the drill-down can show what was there.

### 4. Published rows keep the ids

- `PublishedRow` gains `reasons: list[str]` and
  `criteria: list[{column, contribution, imputed, value_id, missing_reason}]`.
- `PublishedDecision` gains `source: str` (the dataset's source) and `source_ref`.
- A published decision written before this change has neither. Its lineage reports `link: "not_recorded"` per
  criterion.

### 5. Resolving the chain (one function, used by all four places)

`arp/decision/lineage.py`: `row_lineage(snapshot, entity_id) -> dict`. For each criterion:

1. **Contribution:** `{column, contribution, imputed, missing_reason}`.
2. **Link to the value:**
   - `value_id` set: the `authoritative_values` row by id, with value, status, reason, framework version and
     derivation (`AuthoritativeStore.get`).
   - No `value_id`, from a non-authoritative source: `link: "dataset_cell"`.
   - An id that no longer resolves: `link: "missing", value_id: <id>`.
3. **Per derivation input:**
   - the `field_observations` row (field, value, source kind, provider, period end);
   - the `published_fact_id` stored in the derivation, when present;
   - the citations of that observation (`value_citations`: doc id, page, quote, grounded).

   An input without an observation id is shown with `link: "no_observation"`.

The result also carries the row's score, rank, tier, status and reasons, and the snapshot's framework id, version,
`as_of`, `published_by` and `published_at`.

### 6. Where it is shown

- **API (`api/routers/decision.py`):**
  - `GET /api/decision/published/{snapshot_id}/rows/{entity_id}/lineage` returns `row_lineage`, or 404 for an unknown
    snapshot or entity;
  - `GET /api/decision/published/{snapshot_id}/lineage.json` returns all rows;
  - `GET /api/decision/published/{snapshot_id}/lineage.csv` returns one line per entity × criterion × input. Header:
    `entity_id,name,status,score,tier,rank,reasons,criterion,contribution,imputed,missing_reason,value_id,value,value_status,value_reason,input,input_value,observation_id,source,provider,period_end,published_fact_id,doc_id,page,quote`.
    A criterion with no inputs gets one line with blank input columns. A `no_score` row with no criteria data gets one
    line.
- **Decision Studio:**
  - Results drill-down: clicking a company's score, or a `no_score` badge, opens a lineage panel. It reuses PR 1's
    derivation panel styles and shows each criterion → its value → its inputs → its citations.
  - Before publishing, the panel uses the live result. After publishing, it uses `row_lineage`.
  - The published-decisions list gets "Download lineage (CSV)" and "(JSON)".
- **Steward coverage screen (`pages/steward/decisions.tsx`) and Index Builder:** every company that has a published
  decision field gets a "Why this tier" link, which opens the same lineage panel for that snapshot and entity.

### 7. Consumers

- `as_fields` adds `decision.<framework_id>.status` (`scored`, `excluded`, `insufficient` or `no_score`). All existing
  fields are unchanged.
- A `no_score` company has no `.score`, `.tier` or `.rank`, so coverage rules and index screens see it exactly as they
  see a company with no published decision. Their missing-value policy applies.

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

(drafted after the builder check)
