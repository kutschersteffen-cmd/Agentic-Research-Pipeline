# Taxonomy-generated extraction schemas

Status: draft, 2026-10-25 (revised after builder check and spec-critic).

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
- A theme run (API or CLI) starts only from a ratified version with a released schema, and records the schema's
  id and version in the run manifest.
- The exposure pipeline's extraction paths (revenue, CapEx, OpEx, R&D) extract only fields of that released
  schema, so every extracted value's citation carries `schema_version` `sch_<taxonomy_id>_v<n>:v<k>`.
- The Extraction screen can load a released taxonomy schema as a job and run it as a normal, non-trial run.

## Non-goals

- An innovation metric (patents and the like).
- Showing schema state on the dossier page (the dossier's step 2 stays as its spec defines it).
- The step 3 research note, or any narrative field in the schema.
- Changing path 1 (catalogue) or path 3 (qualitative debate) of the exposure cascade, the news-mention signal,
  which verifier each tier uses, or when the revenue and R&D tiers switch on.
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

| metric | `field_id` | `name` | label `L` in the text |
|---|---|---|---|
| revenue | `<taxonomy_id>_<activity_id>_revenue_pct` | `<activity name>: revenue share` | `revenue` |
| capex | `<taxonomy_id>_<activity_id>_capex_pct` | `<activity name>: CapEx share` | `capital expenditure (CapEx)` |
| opex | `<taxonomy_id>_<activity_id>_opex_pct` | `<activity name>: OpEx share` | `operating expenditure (OpEx)` |
| rd | `<taxonomy_id>_<activity_id>_rd_pct` | `<activity name>: R&D intensity` | (R&D text, below) |

  Every field: `data_type` `percentage`, `unit` `%`, `required` false, `version` = the taxonomy version `n`.

  **Text.** For revenue, CapEx and OpEx, `description` and `extraction_instructions` are today's
  `resolve_from_extraction` strings with `metric_label` set to `L`, and with every `{company.name}'s` replaced by
  `the company's`. OpEx is the CapEx text with only `L` changed. For R&D, both strings are today's
  `resolve_rd_intensity` strings, with the same `{company.name}'s` replacement. `seed_keywords` are what today's
  resolvers build: `[*activity.seed_keywords, "<metric>"]` for revenue, capex and opex, and
  `[*activity.seed_keywords, "research and development", "R&D"]` for rd.

  Those replacements are the only wording changes. A schema built once per version cannot name a company. Today's
  strings use `company.name` only in those two `{company.name}'s` places.

## Lifecycle

1. **Generate.** `POST /api/taxonomies/{id}/ratify` also saves `build_taxonomy_schema(ratified version)` to the
   `SchemaRegistry`, idempotently like the `POST` below. Its status codes and response body do not change
   (ratifying an already-ratified version returns 200 today and still does). If the save fails (for example, no
   Postgres), ratify still returns 200 and the schema stays `Not generated`.
   `POST /api/taxonomies/{id}/versions/{n}/schema` (analyst) does the same on demand. It is idempotent: when the
   built schema's content equals the latest registry version, it returns that version unchanged, released or not.
   It returns the registered `DataPointSchema`.
2. **Read.** `GET /api/taxonomies/{id}/versions/{n}/schema` (viewer) → the latest registry version of
   `sch_<id>_v<n>`.
3. **Errors, both endpoints:** an unknown taxonomy or version → 404 `Taxonomy not found: <id> v<n>`. A draft version
   → 409 `Taxonomy <id> v<n> is a draft; ratify it first.` GET on a ratified version with nothing registered → 404
   `No schema for <id> v<n>`.
4. **Release.** The existing `POST /api/extraction/schemas/{schema_id}/versions/{version}/release` (approver; the
   owner holds that role). Nothing new on the backend. "Released" in this spec always means: the **latest**
   registry version of `sch_<id>_v<n>` has `release_flag` true.

## Theme-run gate

One check, shared by `POST /api/themes/runs` and `arp theme run`:

- A request with `theme` (API) or `--theme` (CLI) → API 400 / CLI exit 1 with
  `Theme runs start from a taxonomy version: send taxonomy_id, not theme.`
- `taxonomy_id` unknown → as today (API 404 `Taxonomy not found: <id>`, CLI exit 1).
  `taxonomy_version` omitted → the latest version, as today.
- Version is a draft → API 409 / CLI exit 1:
  `Taxonomy <id> v<n> is a draft; ratify it and release its schema first.`
  This applies whatever `ARP_REQUIRE_RATIFIED_TAXONOMY` says.
- `sch_<id>_v<n>` is not released (nothing registered, or the latest registry version has `release_flag` false) →
  API 409 / CLI exit 1: `Schema sch_<id>_v<n> is not released; release it first.`
- Otherwise the run starts as today. The manifest params also get `extraction_schema_id` (`sch_<id>_v<n>`) and
  `extraction_schema_version` (the registry version), next to the existing `taxonomy_id` and `taxonomy_version`.
- **Resume.** A theme run created before this release has no `extraction_schema_id`. `check_resumable`
  (`arp/orchestration/jobs.py`) refuses it with `NotResumable("Started before taxonomy schemas; start a new run.")`,
  so `POST /api/runs/{id}/resume` returns 400 with that detail, like its other refusals.

Nothing in this feature starts a theme run automatically.

## Exposure pipeline

- The run's released schema (`extraction_schema_id`, `extraction_schema_version`, read from the registry) is passed
  to the revenue and R&D resolver contexts.
- **Revenue tier** (on when a catalogue is supplied, as today): per company × activity, path 1 runs for revenue
  and CapEx as today. Then one `_extract_company` call covers the fields still unresolved among that activity's
  revenue, CapEx and OpEx fields (the grouping is the builder's; only the field set is checked). That call's schema keeps the run schema's `schema_id`, `version` and
  `release_flag` but holds only those fields. It is skipped, as today, when the company is not sector-relevant.
- `RevenueExposureResult` gains `opex: MetricExposure`, defaulting to unresolved, set from the OpEx field.
  `GET /api/themes/runs/{id}/results` fills `opex` with `{"source": "unresolved", ...}` (the model default) on
  stored rows that lack it.
- **R&D tier** (on, and gated by lifecycle stage, as today): a separate `_extract_company` call per company ×
  activity with only that activity's `rd` field, with the same schema identity. It uses the same verifier as today.
- Every extracted percentage becomes a fraction the way today's code does it (`pct / 100 if pct > 1`), for all four
  metrics.
- No other schema is built anywhere in `revenue_exposure/` or `rd_exposure/`.

## Screens

- **Taxonomy Library**, a ratified version: a **Schema** line.
  - `Not generated`, with **Generate schema** (analyst and above).
  - `Not released`, with **Release schema** shown only to approvers. It asks for confirmation
    (`Release schema sch_<id>_v<n>?`), like ratify does.
  - `Released by <released_by> on <YYYY-MM-DD>`, where `released_by` is the value the release endpoint stores
    (the user id).

  A draft version shows `Schema: ratify this version first` and no schema button.
- **Thematic Universe**:
  - A version picker next to the taxonomy picker, listing that taxonomy's versions (`v<n> · draft` or
    `v<n> · ratified`), latest first, latest selected by default.
  - The page sends only `taxonomy_id` and `taxonomy_version` when starting a run, never `theme`.
  - The run button is disabled unless the selected version's schema is released. Next to the button the page
    shows the reason:
    - no taxonomy loaded → `Load a ratified taxonomy version first.`
    - draft → `Ratify this version and release its schema first.`
    - not released → `Release this version's schema in the Taxonomy Library first.`
    - loaded theme edited → `Save the edits as a new taxonomy version, ratify it and release its schema to run.`

    When the button is enabled, no reason is shown.
- **Extraction** (custom profile, schema tab): **From a taxonomy** lists the taxonomy versions whose schema is
  released, as `<taxonomy name> v<n>`. Picking one sets the job's schema to that registry version, in the same
  confirmed state a drafted schema reaches after its confirm button. The field list shows the 4 × activities field
  names. Because the schema is released, the start step shows no `Trial run: …` note.

## My calls (owner to confirm with the acceptance table)

1. **Field version = taxonomy version.** A changed activity in v3 can never clash with its released v2 field.
2. **Company name becomes "the company's"** in the moved text, the one wording change a shared schema forces.
   Field names change from `revenue_share_pct` style to `<activity>: revenue share`.
3. **R&D keeps its own extraction, with its current verifier setting**, so the R&D tier still works without a
   catalogue. Revenue, CapEx and OpEx go through one `_extract_company` call per company × activity. The rows
   check which fields reach the model, not how many calls are made.
4. **The gate covers the CLI too**, since your rule is about theme runs, not one screen.
   `--theme` is refused like the API's `theme`.
5. **Ratify never fails because of the schema.** A failed save leaves `Not generated`, and **Generate schema**
   recovers it.
6. **Old in-flight runs fail on resume** instead of extracting without a schema.
7. **The Thematic Universe gets a version picker.** Without it, nobody could run v1 once a v2 draft exists.
8. **`ARP_REQUIRE_RATIFIED_TAXONOMY` becomes dead config** for theme runs. Left in place and noted in the PR,
   not deleted.
9. **Existing tests that start a theme run from an inline `theme`** (for example the `themes` row of
   `tests/test_api_batch_runs.py`) change to start from a ratified taxonomy with a released schema. The owner's
   decision changes that behaviour on purpose. Each changed test is listed in the PR.

## Constraints

- Repo checks: `ruff`, `pytest`, `npm run lint`, `npx tsc -b`, `npm test`. The API contract is regenerated and
  committed (new endpoints, `opex` on `RevenueExposureResult`).
- The SchemaRegistry needs Postgres (`ARP_TEST_POSTGRES_DSN` in tests).
- No prompt wording changes beyond those in "The generated schema".

## Left to the builder

How the subset schema is passed to `_extract_company`, how the resolver contexts receive the run schema, where the
shared gate function and the moved text live, and the component layout of the new Taxonomy Library line, version
picker and Extraction picker.

## Acceptance

**Fixture.** Each row starts from this fixture, plus only the rows its Given names. Everything is seeded through the
backend's own stores:

- An empty taxonomy store and SchemaRegistry (Postgres).
- Taxonomy `tax_a` "Grid": v1 with activities `act_1` "HV cables" and `act_2` "Transformers", ratified by `ana`;
  v2 a draft with `act_1` only.
- A stand-in LLM replaces the model: an `LLMClient` (`arp/llm/base.py`) passed as both `llm` and `verifier_llm`
  wherever the run builds its clients. It answers 18.5 for every percentage field it is asked for and records the
  `prompt` of each `complete_structured` call. "A request names field F" means a recorded prompt contains the line
  `Field: <F's name>` (the extractor's `_field_spec` format). "c1's requests" are those whose prompt contains `c1`'s
  name.
- Users `ana` (analyst), `own` (approver), `vic` (viewer).
- Company `c1`, sector-relevant to both activities. A revenue catalogue and mapping where nothing matches, so
  path 2 runs. The R&D tier is off unless a row says otherwise.

"Run on v1" means `POST /api/themes/runs {"taxonomy_id": "tax_a", "taxonomy_version": 1, "companies": [c1], ...}`
with that catalogue. "Released v1" means AC-6b plus AC-10.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `tax_a` v1 | `build_taxonomy_schema` | `schema_id` `sch_tax_a_v1`; `name` `Grid v1`; `description` `Generated from taxonomy tax_a v1.`; 8 fields with ids `tax_a_act_1_revenue_pct`, `tax_a_act_1_capex_pct`, `tax_a_act_1_opex_pct`, `tax_a_act_1_rd_pct`, then the same four for `act_2`, in that order; every field `percentage`, `%`, `required` false, `version` 1 | holdout |
| AC-2 | `tax_a` v1 | build twice | the two results are equal after `model_dump(exclude={"created_at"})` | holdout |
| AC-3 | `tax_a` v2 (draft) | `build_taxonomy_schema` | raises `ValueError` `Taxonomy tax_a v2 is a draft; ratify it first.` | holdout |
| AC-4 | `tax_a` v2 draft | `POST /api/taxonomies/tax_a/ratify {"version": 2}` as `ana`, then `GET /api/taxonomies/tax_a/versions/2/schema` | GET 200: `schema_id` `sch_tax_a_v2`, 4 fields each `version` 2, `release_flag` false | holdout |
| AC-5 | AC-4 | ratify v2 again, then GET the schema | ratify 200; GET returns the same registry `version` as in AC-4 | holdout |
| AC-6a | fixture (no schema registered) | `GET /api/taxonomies/tax_a/versions/1/schema` | 404, `detail` `No schema for tax_a v1` | holdout |
| AC-6b | fixture | `POST /api/taxonomies/tax_a/versions/1/schema` as `ana` | 200; `schema_id` `sch_tax_a_v1`; `release_flag` false | holdout |
| AC-6c | AC-6b | `POST` again | 200; same `version` as AC-6b | holdout |
| AC-7 | `tax_a` v2 draft | `POST` and `GET /api/taxonomies/tax_a/versions/2/schema` | both 409, `detail` `Taxonomy tax_a v2 is a draft; ratify it first.` | holdout |
| AC-8 | fixture | `POST` and `GET /api/taxonomies/tax_a/versions/9/schema` | both 404, `detail` `Taxonomy not found: tax_a v9` | holdout |
| AC-9a | AC-6b | `GET .../versions/1/schema` as `vic` | 200 | holdout |
| AC-9b | fixture | `POST .../versions/1/schema` as `vic` | 403 | holdout |
| AC-10 | AC-6b | `POST /api/extraction/schemas/sch_tax_a_v1/versions/<AC-6b version>/release` as `own` | 200; `release_flag` true; `released_by` `own` | holdout |
| AC-11 | Released v1 | `POST .../versions/1/schema` as `ana`, then run on v1 | POST 200 with the same `version` and `release_flag` true; the run returns 200 | holdout |
| AC-12a | fixture | `POST /api/themes/runs` with `theme` and no `taxonomy_id` | 400, `detail` `Theme runs start from a taxonomy version: send taxonomy_id, not theme.` | holdout |
| AC-12b | Released v1 | `POST /api/themes/runs` with `theme` and `"taxonomy_id": "tax_a", "taxonomy_version": 1` | 400, same `detail` as AC-12a | holdout |
| AC-13 | fixture, `ARP_REQUIRE_RATIFIED_TAXONOMY` false | run on v2 | 409, `detail` `Taxonomy tax_a v2 is a draft; ratify it and release its schema first.` | holdout |
| AC-14 | fixture | `POST /api/themes/runs {"taxonomy_id": "tax_a", ...}` with no version (latest is v2) | 409, same `detail` as AC-13 | holdout |
| AC-15 | AC-6b (not released) | run on v1 | 409, `detail` `Schema sch_tax_a_v1 is not released; release it first.` | holdout |
| AC-16 | fixture (nothing registered) | run on v1 | 409, same `detail` as AC-15 | holdout |
| AC-17 | fixture | `POST /api/themes/runs {"taxonomy_id": "tax_zz", ...}` | 404, `detail` `Taxonomy not found: tax_zz` | holdout |
| AC-18 | Released v1 | run on v1 | 200; `GET /api/runs/{run_id}` manifest params have `taxonomy_id` `tax_a`, `taxonomy_version` 1, `extraction_schema_id` `sch_tax_a_v1`, `extraction_schema_version` equal to AC-6b's `version` | holdout |
| AC-19 | AC-18, run completed | `GET /api/themes/runs/{run_id}/results` | for `c1` × `act_1` and `c1` × `act_2`: `revenue_exposure.revenue`, `.capex` and `.opex` each `source` `extracted`, `value_pct` 0.185 | holdout |
| AC-20 | AC-19 | read the same results | every `MetricExposure` with `source` `extracted` has `citation.schema_version` `sch_tax_a_v1:v<AC-6b version>` | holdout |
| AC-21 | AC-19 | read the stand-in's recorded requests | the fields named are exactly the six `HV cables:` / `Transformers:` revenue share, CapEx share and OpEx share fields; none is an `R&D intensity` field | holdout |
| AC-22 | Released v1; the mapping resolves revenue and CapEx for `act_1` from the catalogue | run on v1, completed, read results | `c1` × `act_1`: `revenue.source` and `capex.source` `catalogue`, `opex.source` `extracted`; no recorded request names `HV cables: revenue share` or `HV cables: CapEx share` | holdout |
| AC-23 | Released v1; R&D tier on; `act_1` lifecycle `innovation`; no catalogue | run on v1, completed, read results | `c1` × `act_1`: `rd_exposure.rd_intensity.source` `extracted`, `value_pct` 0.185, `citation.schema_version` `sch_tax_a_v1:v<AC-6b version>`; a recorded request names `HV cables: R&D intensity` | holdout |
| AC-23b | AC-23 with `act_2` lifecycle `mature` | run on v1, completed | no recorded request names `Transformers: R&D intensity`; `c1` × `act_2` `rd_exposure` null, as before | holdout |
| AC-24 | Released v1; company `c2` with a resolved ISIC code outside `act_1`'s `core_isic_codes` | run on v1 for `c1` and `c2`, completed | `c2` × `act_1`: `revenue`, `capex` and `opex` `source` `unresolved`; no recorded request whose prompt contains `c2`'s name names `HV cables: OpEx share` | holdout |
| AC-25 | a stored theme run whose results row's `revenue_exposure` has no `opex` key | `GET /api/themes/runs/{id}/results` | 200; that row's `revenue_exposure.opex.source` `unresolved` | holdout |
| AC-26 | a theme run created through the run store with today's params (no `extraction_schema_id`), status `failed`, companies stored | `POST /api/runs/{run_id}/resume` as `ana` | 400, `detail` `Started before taxonomy schemas; start a new run.` | holdout |
| AC-27a | fixture | `arp theme run --theme t.json --universe u.csv` | exit 1; stderr contains `Theme runs start from a taxonomy version: send taxonomy_id, not theme.` | holdout |
| AC-27b | AC-6b (not released) | `arp theme run --taxonomy tax_a --taxonomy-version 1 --universe u.csv` | exit 1; stderr contains `Schema sch_tax_a_v1 is not released; release it first.` | holdout |
| AC-27c | fixture | `arp theme run --taxonomy tax_a --taxonomy-version 2 --universe u.csv` | exit 1; stderr contains `Taxonomy tax_a v2 is a draft; ratify it and release its schema first.` | holdout |
| AC-27d | Released v1 | `arp theme run --taxonomy tax_a --taxonomy-version 1 --universe u.csv` | exit 0; the new run's manifest params have `extraction_schema_id` `sch_tax_a_v1` | holdout |
| AC-1b | `tax_a` v1 | `build_taxonomy_schema`, read field `tax_a_act_1_opex_pct` and `tax_a_act_1_capex_pct` | names `HV cables: OpEx share` and `HV cables: CapEx share`; opex `description` and `extraction_instructions` equal capex's with `capital expenditure (CapEx)` replaced by `operating expenditure (OpEx)`; no field's text contains `{company` | holdout |
| AC-1c | `tax_a` v1 with `act_1.seed_keywords` `["hvdc"]` | `build_taxonomy_schema` | `seed_keywords`: revenue `["hvdc", "revenue"]`, opex `["hvdc", "opex"]`, rd `["hvdc", "research and development", "R&D"]` | holdout |
| AC-28 | Released v1, AC-4 done, nobody started a run | `GET /api/runs?run_type=theme` | `runs` is empty | holdout |
| AC-29 | Released v1 | `POST /api/extraction/start` custom profile, `datapoint_schema` = AC-10's schema, no `trial` | 200; the run's manifest params have `schema_id` `sch_tax_a_v1` and `trial` false | holdout |
| AC-30 | AC-4 (v2 generated, not released) | `POST /api/extraction/start` custom profile with that schema, no `trial` | 400, `detail` starts with `Schema sch_tax_a_v2 v` and contains `is not released` | holdout |
| AC-31a | the running app as `ana`; fixture | open the Taxonomy Library, `tax_a` v1 | Schema line reads `Not generated` with **Generate schema** | evaluator |
| AC-31b | AC-31a | click **Generate schema** | the line reads `Not released`; no **Release schema** button is shown to `ana` | evaluator |
| AC-32 | AC-6b, the running app as `own` | open v1; click **Release schema**; confirm | a dialog titled `Release schema sch_tax_a_v1?`; afterwards the line reads `Released by own on <today as YYYY-MM-DD>` | evaluator |
| AC-33 | the running app | open `tax_a` v2 in the Taxonomy Library | `Schema: ratify this version first`, no schema button | evaluator |
| AC-34a | Thematic Universe, nothing loaded | read the run button | disabled; reason `Load a ratified taxonomy version first.` | evaluator |
| AC-34b | Thematic Universe, `tax_a` loaded | read the version picker and the run button | picker shows `v2 · draft` (selected) then `v1 · ratified`; button disabled; reason `Ratify this version and release its schema first.` | evaluator |
| AC-34c | AC-6b; Thematic Universe, `tax_a` v1 selected | read the run button | disabled; reason `Release this version's schema in the Taxonomy Library first.` | evaluator |
| AC-34d | Released v1; Thematic Universe, `tax_a` v1 selected | read the run button | enabled; no reason shown | evaluator |
| AC-34e | AC-34d | rename an activity, read the run button | disabled; reason `Save the edits as a new taxonomy version, ratify it and release its schema to run.` | evaluator |
| AC-35 | Released v1; AC-4 (v2 not released) | Extraction screen, custom job, schema tab, open **From a taxonomy** | lists `Grid v1` only | evaluator |
| AC-36 | AC-35 | pick `Grid v1` | the job shows 8 fields, starting `HV cables: revenue share`, `HV cables: CapEx share`, `HV cables: OpEx share`, `HV cables: R&D intensity` | evaluator |
| AC-37 | AC-36 | go to the start step | no `Trial run: the custom schema is not released, so results are not final.` note | evaluator |

Must not change:
- AC-38a: `POST /api/taxonomies/{id}/ratify` returns 200 with a `Taxonomy` body (`status` `ratified`, `ratified_by`
  the caller) and 404 for an unknown id or version, as before. Checked by: holdout.
- AC-38b: with `SchemaRegistry.save` patched to raise, ratify `tax_a` v2 → 200; then
  `GET /api/taxonomies/tax_a/versions/2/schema` → 404 `No schema for tax_a v2`. Checked by: holdout.
- AC-39a: a custom-profile `POST /api/extraction/start` with a drafted, unreleased schema and no `trial` → 400,
  `detail` contains `is not released`. Checked by: holdout.
- AC-39b: the same request with `trial` true → 200, run manifest `trial` true. Checked by: holdout.
- AC-40: `GET /api/extraction/presets` lists exactly the preset ids `sch_green_lowcarbon`, `sch_eu_taxonomy`,
  `sch_esg_remuneration`, `transition_plan_indicators`, `sch_transition_capex`, `sch_transition_plan_actions`,
  `sch_transition_delivery_kpis`. Checked by: holdout.
- AC-41: Released v1, no catalogue, R&D tier off: the run completes, the stand-in recorded no request naming a field id of
  `sch_tax_a_v1`, and every `c1` result has `revenue_exposure` null, as before. Checked by: holdout.
