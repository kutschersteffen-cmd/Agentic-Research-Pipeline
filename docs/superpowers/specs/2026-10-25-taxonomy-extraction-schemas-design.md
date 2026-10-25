# Taxonomy-generated extraction schemas

Status: draft, 2026-10-25.

Step 2 (**Define**) of the five-step theme process tied together by the theme dossier
(`docs/superpowers/specs/2026-10-25-theme-dossier-design.md`, PR #226). This spec does not change the dossier.

## Intent

Numbers extracted about a theme should be traceable to the taxonomy that defines the theme. Today they are not.
`resolve_from_extraction` (`backend/arp/research/revenue_exposure/resolver.py`) and `resolve_rd_intensity`
(`backend/arp/research/rd_exposure/resolver.py`) build a one-field `DataPointSchema` on the fly for each
company × activity × metric and call `_extract_company` directly. Those schemas are never registered or
versioned, and nobody releases them. They cover revenue, CapEx and R&D only.

After this change, every ratified taxonomy version has one generated extraction schema. It is derived
deterministically from that version's activities, registered in the `SchemaRegistry`, and released by the owner.
The Thematic Universe and the Extraction screen both use that schema for the theme and nothing else.

Narrative beyond the numbers comes from the theme's research note (step 3, its own spec), not from this schema.

## Owner decisions (2026-10-25)

1. The schema is generated from a **ratified** taxonomy version. Draft versions have no usable schema.
2. **Ratifying a version does not release its schema.** The owner releases it as a separate step, one person,
   no second approver.
3. Fields per activity: **revenue share %, CapEx share %, OpEx share %, R&D intensity %**. No innovation field.
4. A Thematic Universe run starts only when someone starts it, and only against a taxonomy version whose generated
   schema is released. Inline themes and draft versions can no longer start a run.
5. Approach A: **one schema per taxonomy version** (see Approaches).

## Goals

- Ratifying a taxonomy version registers its generated schema, unreleased.
- The owner can see and release that schema from the Taxonomy Library.
- `POST /api/themes/runs` starts only from a ratified version with a released schema, and records the schema's
  id and version in the run manifest.
- The exposure pipeline's extraction paths (revenue, CapEx, OpEx, R&D) extract only fields of that released
  schema, so every extracted value carries `schema_version` `sch_<taxonomy_id>_v<n>:v<k>`.
- The Extraction screen can load a released taxonomy schema as a job and run it as a normal, non-trial run.

## Non-goals

- An innovation metric (patents and the like).
- Showing schema state on the dossier page (the dossier's step 2 stays as its spec defines it).
- The step 3 research note, or any narrative field in the schema.
- Changing path 1 (catalogue) or path 3 (qualitative debate) of the exposure cascade, the news-mention signal,
  or when the revenue and R&D tiers switch on.
- A catalogue mapping for OpEx. OpEx is resolved by extraction only.
- Backfilling schemas for versions ratified before release. An analyst generates one on demand (`POST`, below).

## Anti-goals

- Two generated schemas for the same taxonomy version, or a schema whose fields differ from its version's
  activities.
- Any extraction in a theme run whose field is not in the run's released schema.
- A run or Extraction job that treats an unreleased generated schema as released.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **One schema per taxonomy version**, id `sch_<taxonomy_id>_v<n>`, generated like `presets/green.py`. | The id names the version, so schema and taxonomy cannot drift. Each new version needs one release, even if its activities did not change. | **Chosen by the owner** |
| B | One schema per taxonomy, registry versions following taxonomy versions. | Fewer schemas; unchanged fields stay released. Registry version ≠ taxonomy version, so a lookup table is needed and can drift. | Rejected |
| C | Schema stored inside the taxonomy file. | Smallest change; invisible to the Extraction screen and the release gate. | Rejected |

## The generated schema

`build_taxonomy_schema(taxonomy: Taxonomy) -> DataPointSchema`, a pure function in
`backend/arp/research/taxonomy_schema.py`. Same input, same output. It refuses a draft version with
`ValueError("Taxonomy <taxonomy_id> v<n> is a draft; ratify it first.")`.

- `schema_id`: `sch_<taxonomy_id>_v<n>` (for example `sch_tax_1a2b3c_v2`).
- `name`: `<taxonomy name> v<n>`.
- `description`: `Generated from taxonomy <taxonomy_id> v<n>.`
- `fields`: for each activity in `taxonomy.theme.activities` order, four fields in this order:

| metric | `field_id` | `name` | instructions |
|---|---|---|---|
| revenue | `<taxonomy_id>_<activity_id>_revenue_pct` | `<activity name>: revenue share` | today's `resolve_from_extraction` text for `revenue` |
| capex | `<taxonomy_id>_<activity_id>_capex_pct` | `<activity name>: CapEx share` | today's text for `capex` |
| opex | `<taxonomy_id>_<activity_id>_opex_pct` | `<activity name>: OpEx share` | today's `capex` text with the label `operating expenditure (OpEx)` |
| rd | `<taxonomy_id>_<activity_id>_rd_pct` | `<activity name>: R&D intensity` | today's `resolve_rd_intensity` text |

  Every field: `data_type` `percentage`, `unit` `%`, `required` false, `version` = the taxonomy version `n`.
  `description` and `seed_keywords` are what today's resolvers build for that metric (`opex` gets
  `[*activity.seed_keywords, "opex"]`). The instructions are moved, not reworded, so extraction behaviour stays
  the same for revenue, CapEx and R&D.

## Lifecycle

1. **Generate.** `POST /api/taxonomies/{id}/ratify` also saves `build_taxonomy_schema(ratified version)` to the
   `SchemaRegistry` (a no-op if already saved). Its response body does not change.
   `POST /api/taxonomies/{id}/versions/{n}/schema` (analyst) does the same on demand for a version ratified before
   this release. It is idempotent and returns the registered `DataPointSchema`. A draft version returns 409 with the
   generator's message; an unknown taxonomy or version returns 404 `Taxonomy not found: <id> v<n>`.
2. **Read.** `GET /api/taxonomies/{id}/versions/{n}/schema` (viewer) → the latest registry version of
   `sch_<id>_v<n>`; 404 `No schema for <id> v<n>` when none is registered; 409 for a draft version.
3. **Release.** The existing `POST /api/extraction/schemas/{schema_id}/versions/{version}/release` (approver; the
   owner holds that role). Nothing new on the backend.

## Thematic Universe gate

`POST /api/themes/runs`:

- A request with `theme` → 400 `Theme runs start from a taxonomy version: send taxonomy_id, not theme.`
  (this replaces today's inline-theme path).
- `taxonomy_id` unknown → 404 as today. `taxonomy_version` omitted → the latest version, as today.
- Version is a draft → 409 `Taxonomy <id> v<n> is a draft; ratify it and release its schema first.`
  This applies whatever `ARP_REQUIRE_RATIFIED_TAXONOMY` says.
- No released `sch_<id>_v<n>` (none registered, or the latest registry version has `release_flag` false) → 409
  `Schema sch_<id>_v<n> is not released; release it first.`
- Otherwise the run starts as today. The manifest params also get `extraction_schema_id` (`sch_<id>_v<n>`) and
  `extraction_schema_version` (the registry version), next to the existing `taxonomy_id` and `taxonomy_version`.

Only the API gets this gate. Nothing in this feature starts a theme run automatically.

## Exposure pipeline

- The run's released schema is passed to the revenue and R&D resolver contexts.
- **Revenue tier** (on when a catalogue is supplied, as today): per company × activity, path 1 runs for revenue
  and CapEx as today. Then **one** `_extract_company` call covers that activity's fields still unresolved
  among revenue, CapEx and OpEx. The call uses a `DataPointSchema` with the run schema's `schema_id`, `version`
  and `release_flag` and only those fields, so extracted values carry `schema_version`
  `sch_<id>_v<n>:v<k>`. It is skipped, as today, when the company is not sector-relevant.
- `RevenueExposureResult` gains `opex: MetricExposure`, defaulting to unresolved. It is set from the OpEx field.
  Values are converted to fractions the same way revenue and CapEx are today.
- **R&D tier** (on and gated by lifecycle stage as today): `rd_intensity` comes from the activity's `rd` field
  of the run schema, through the same subset call.
- No other schema is built anywhere in `revenue_exposure/` or `rd_exposure/`.

## Screens

- **Taxonomy Library**, a ratified version: a **Schema** line reading `Not generated` with **Generate schema**,
  `Not released` with **Release schema**, or `Released by <name> on <YYYY-MM-DD>`. **Release schema** asks for
  confirmation (`Release schema sch_<id>_v<n>?`), like ratify does. A draft version shows
  `Schema: ratify this version first`.
- **Thematic Universe**: the run button is disabled unless the loaded taxonomy version has a released schema.
  Next to it the page shows the gate's message: draft → `Ratify this version and release its schema first.`,
  unreleased → `Release this version's schema in the Taxonomy Library first.`, no taxonomy loaded →
  `Load a ratified taxonomy version first.` Editing the loaded theme's activities still works for drafting
  but disables the run with `Save the edits as a new taxonomy version, ratify it and release its schema to run.`
- **Extraction** (custom profile, schema tab): **From a taxonomy** lists the taxonomy versions whose schema is
  released, as `<taxonomy name> v<n>`. Picking one fills the job with that schema, confirmed, and the run is not a
  trial.

## My calls (owner to confirm with the acceptance table)

1. **Field version = taxonomy version.** A changed activity in v3 can never clash with its released v2 field.
2. **One extraction call per company × activity**, over the fields still needed. The cost is about the same as
   today's one call per metric, or lower.
3. **The `theme` request field is refused, not ignored**, so an old client finds out instead of running something else.
4. **`ARP_REQUIRE_RATIFIED_TAXONOMY` becomes dead config** for theme runs. Left in place and noted in the PR,
   not deleted.
5. **Existing tests that start a theme run from an inline `theme`** (for example the `themes` row of
   `tests/test_api_batch_runs.py`) change to start from a ratified taxonomy with a released schema. The owner's
   decision changes that behaviour on purpose. Each changed test is listed in the PR.

## Constraints

- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`. The API contract is regenerated and
  committed (new endpoints, `opex` on `RevenueExposureResult`).
- The SchemaRegistry needs Postgres (`ARP_TEST_POSTGRES_DSN` in tests).
- No new LLM prompt wording: instructions move verbatim. The OpEx text is the CapEx text with the label changed.

## Left to the builder

How the subset schema is passed to `_extract_company`, how the resolver contexts receive the run schema, the
component layout of the new Taxonomy Library line and the Extraction picker, and where the shared instruction
text lives once it is moved.

## Acceptance

Fixture, seeded through the backend's own stores: an empty taxonomy store and SchemaRegistry (Postgres). Taxonomy
`tax_a` "Grid", v1 with activities `act_1` "HV cables" and `act_2` "Transformers", ratified by `ana`; v2 a draft
with `act_1` only. A stand-in LLM replaces the model in unit and holdout tests. Users `ana` (analyst), `own`
(approver), `vic` (viewer). A company universe of one company, `c1`, sector-relevant to both activities, with a
revenue catalogue where nothing matches, so path 2 runs.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `tax_a` v1 | `build_taxonomy_schema` | `schema_id` `sch_tax_a_v1`; `name` `Grid v1`; 8 fields with ids `tax_a_act_1_revenue_pct`, `tax_a_act_1_capex_pct`, `tax_a_act_1_opex_pct`, `tax_a_act_1_rd_pct`, then the same four for `act_2`, in that order; every field `percentage`, `%`, `required` false, `version` 1 | holdout |
| AC-2 | `tax_a` v1 | build twice | the two results are equal after `model_dump(exclude={"created_at"})` | holdout |
| AC-3 | `tax_a` v2 (draft) | `build_taxonomy_schema` | raises `ValueError` `Taxonomy tax_a v2 is a draft; ratify it first.` | holdout |
| AC-4 | `tax_a` v2 draft, no schema | `POST /api/taxonomies/tax_a/ratify {"version": 2}` as `ana` | 200, body keys as before; `GET /api/taxonomies/tax_a/versions/2/schema` → 200, `schema_id` `sch_tax_a_v2`, 4 fields, `release_flag` false | holdout |
| AC-5 | AC-4 | ratify v2 again | `GET .../versions/2/schema` → the same registry `version` as in AC-4 | holdout |
| AC-6 | `tax_a` v1 ratified before release, no schema | `GET .../versions/1/schema`; then `POST .../versions/1/schema` as `ana`; then `POST` again | 404 `No schema for tax_a v1`; 200 with `schema_id` `sch_tax_a_v1`; 200 with the same `version` | holdout |
| AC-7 | `tax_a` v2 draft | `POST` and `GET .../versions/2/schema` | both 409, `detail` `Taxonomy tax_a v2 is a draft; ratify it first.` | holdout |
| AC-8 | unknown version | `POST .../versions/9/schema` | 404 `Taxonomy not found: tax_a v9` | holdout |
| AC-9 | caller `vic` | `GET .../versions/1/schema` after AC-6; `POST .../versions/1/schema` | 200; 403 | holdout |
| AC-10 | AC-6's schema | `POST /api/extraction/schemas/sch_tax_a_v1/versions/<v>/release` as `own` | 200; `release_flag` true; `released_by` `own` | holdout |
| AC-11 | any taxonomy | `POST /api/themes/runs` with `theme` (with or without `taxonomy_id`) | 400 `Theme runs start from a taxonomy version: send taxonomy_id, not theme.` | holdout |
| AC-12 | `tax_a` v2 draft; `ARP_REQUIRE_RATIFIED_TAXONOMY` false | `POST /api/themes/runs {"taxonomy_id": "tax_a", "taxonomy_version": 2, ...}` | 409 `Taxonomy tax_a v2 is a draft; ratify it and release its schema first.` | holdout |
| AC-13 | `tax_a` v1 ratified, schema generated, not released | start a run on v1 | 409 `Schema sch_tax_a_v1 is not released; release it first.` | holdout |
| AC-14 | `tax_a` v1 ratified, no schema registered | start a run on v1 | 409 `Schema sch_tax_a_v1 is not released; release it first.` | holdout |
| AC-15 | AC-10 (released) | start a run on v1 | 200; run manifest params have `taxonomy_id` `tax_a`, `taxonomy_version` 1, `extraction_schema_id` `sch_tax_a_v1`, `extraction_schema_version` the released registry version | holdout |
| AC-16 | AC-15's run, stand-in LLM returning 18.5 for every field | run completes | for `c1` × `act_1`, `revenue_exposure.revenue.value_pct` 0.185, `capex.value_pct` 0.185, `opex.value_pct` 0.185, each `source` `extracted` | holdout |
| AC-17 | AC-16 | read the extraction calls the stand-in received | one call per company × activity (2 for `c1`), each asking only for that activity's revenue, CapEx and OpEx field ids of `sch_tax_a_v1` | holdout |
| AC-18 | AC-16 | read the extracted citations/records for the run | every extracted value's `schema_version` is `sch_tax_a_v1:v<released version>` | holdout |
| AC-19 | AC-15 with a catalogue mapping that resolves revenue and CapEx for `act_1` | run completes | `c1` × `act_1`: `revenue.source` and `capex.source` `catalogue`; the stand-in's call for `act_1` asks only for `tax_a_act_1_opex_pct` | holdout |
| AC-20 | AC-15 with the R&D tier on and `act_1` at lifecycle `innovation` | run completes | `rd_exposure.rd_intensity` for `c1` × `act_1` is `extracted`, value 0.185, from field `tax_a_act_1_rd_pct` | holdout |
| AC-21 | a stored `RevenueExposureResult` JSON without `opex` (an older run) | `GET /api/themes/runs/{id}/results` | 200; `opex.source` `unresolved` | holdout |
| AC-22 | the running app, `tax_a` v1 ratified, schema not generated | open the Taxonomy Library, v1 | Schema line reads `Not generated` with **Generate schema**; after clicking it reads `Not released` with **Release schema** | evaluator |
| AC-23 | AC-22, as `own` | click **Release schema**, confirm | a dialog `Release schema sch_tax_a_v1?`; afterwards the line reads `Released by own on <today>` | evaluator |
| AC-24 | the running app, `tax_a` v2 draft | open v2 in the Taxonomy Library | `Schema: ratify this version first`, no schema button | evaluator |
| AC-25 | the running app, Thematic Universe | load `tax_a` v1 with the schema unreleased; then release it and reload | run button disabled with `Release this version's schema in the Taxonomy Library first.`; then enabled | evaluator |
| AC-26 | Thematic Universe, nothing loaded; then `tax_a` v2 loaded | read the run button | disabled with `Load a ratified taxonomy version first.`; then with `Ratify this version and release its schema first.` | evaluator |
| AC-27 | Thematic Universe, released `tax_a` v1 loaded | edit an activity's name | run button disabled with `Save the edits as a new taxonomy version, ratify it and release its schema to run.` | evaluator |
| AC-28 | Extraction screen, custom job, schema tab; `sch_tax_a_v1` released, `tax_a` v2 schema unreleased | open **From a taxonomy** | lists `Grid v1` only; picking it fills 8 fields; the started run shows no trial note | evaluator |

Must not change:
- AC-29: `POST /api/taxonomies/{id}/ratify` returns the same status codes and body keys as before. Checked by: holdout.
- AC-30: a custom-profile `POST /api/extraction/start` with a drafted, unreleased schema still refuses without
  `trial` and starts with it, as before. Checked by: holdout.
- AC-31: `GET /api/extraction/presets` lists the same presets as before, and none with an id starting `sch_tax_`.
  Checked by: holdout.
- AC-32: a run without a revenue catalogue and with the R&D tier off makes no extraction call (the stand-in sees
  none) and completes with the qualitative debate, as before. Checked by: holdout.
