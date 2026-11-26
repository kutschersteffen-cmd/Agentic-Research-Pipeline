# EXIOBASE sectors replace the ICIO code layer

## Why

The indirect-exposure model and the Value Chain Explorer already run on EXIOBASE's 163 sectors.
On top of that sits a coarse code layer: 50 OECD ICIO codes plus 5 electricity split codes
(`factory.py::code_list()`, `icio2025_industries.csv`, `exiobase_ixi_to_icio2025.csv`,
`io_import.py::SPLIT_INDUSTRIES`). Every activity, link rule and LLM prompt is expressed in those codes,
which are then expanded back to EXIOBASE sectors. The owner decided to drop the layer and name EXIOBASE
sectors directly everywhere. NACE → EXIOBASE (`indirect_exposure/nace.py`) stays the only code lookup
path, because the industry-anchored taxonomy method will later anchor to NACE 4-digit classes and derive
sectors from them (another session).

## Decisions (owner)

1. **Identifier.** A sector is named by its full EXIOBASE name as `sector_name()` returns it (archive
   name without a trailing ` (31)`), e.g. `Mining of copper ores and concentrates`. No short codes.
2. **Split link rules.** A `split` or `llm` part becomes `{sectors: [name, ...], share}`. A part's share
   is spread over its sectors' live nodes by output in the current build, exactly as an ICIO code part
   is today. `nodes` rules (`{region, sector, share}`) are unchanged.
3. **Activity field.** `ActivityDefinition.core_isic_codes` is renamed `core_sectors` and holds sector
   names.
4. **LLM prompts.** The core-sector classifier (`core_sectors.py`), the company classifier
   (`company_mapper.py`) and the industry-anchored taxonomy draft (`activity_generator.py`) pick from the
   163 sector names, a closed list as today. Answers not in the list are dropped. The anchored method's
   logic is otherwise untouched.
5. **Standards mapping.** `core_sectors` → NACE Rev.2 codes (reverse of `exiobase_nace.csv`, new
   function in `nace.py`) → ISIC Rev.4 (`un_nace2_isic4.csv`, every matching row, partial or not) → the
   existing ISIC-keyed NACE/NAICS/SIC crosswalk tables, unchanged. `unmapped_isic_codes` becomes
   `unmapped_sectors`: sectors none of the loaded tables matched.
6. **Relevance check.** `is_sector_relevant` (revenue and R&D exposure) is true when the company's
   sectors overlap the activity's `core_sectors`. No company sectors, or no `core_sectors`, gives `True`.
7. **Migration.** A one-off command `arp io migrate-exiobase` rewrites stored data. It is the only reader
   of `exiobase_ixi_to_icio2025.csv` after this change; all other ICIO reference data and code is deleted.
8. **Old format rejected everywhere.** Loading any theme, activity or taxonomy JSON that still has a
   `core_isic_codes` key fails, in every load path (API, CLI, taxonomy store, run resume), with the
   message M8 (exact, `<theme.json>` literal):
   `core_isic_codes (ICIO) is no longer supported; run arp io migrate-exiobase --file <theme.json> to convert it`.
   The check lives in `ActivityDefinition` (a "before" validator), so nothing loads with silently empty
   sectors. API: HTTP 422 with M8 in the body. CLI: exit 1 with M8 on stderr.
9. **Taxonomy versions.** The command rewrites every `v*.json` of every taxonomy in place: same version
   number, same ratification, same `based_on_version`.

## Approaches considered

- **Convert on read** (pydantic "before" validators converting old shapes): no per-deployment step,
  but ICIO conversion stays in the load path forever. Not chosen.
- **One-off migration command** (chosen): the load path is ICIO-free; the command runs once per
  deployment and on any old file on request. Within it, appending a new taxonomy version instead of
  rewriting in place was rejected: older versions would need re-ratification.

## What changes

**Model and code list** (`research/indirect_exposure/`)
- `factory.py`: `CodeList` / `code_list()` deleted. A new `sectors()` returns the 163 names in order of
  first appearance in `exiobase_nace.csv`. `LeontiefModel.codes` = those names, `code_nodes` keyed by
  name; `labels`, `isic_divisions`, `nace_classes`, `prompt_codes` deleted.
  `industry_reference_list()` returns the 163 names; `industry_prompt_list()` renders one name per line.
- `io_import.py`: `SPLIT_INDUSTRIES` deleted. `value_chain/build.py` checks archive sectors against
  `sectors()`; an unknown one fails with `EXIOBASE sector not in exiobase_nace.csv: <name>`.
- `icio2025_industries.csv` deleted. `exiobase_ixi_to_icio2025.csv` moves to
  `research/indirect_exposure/migrate/` next to the migration module, its only reader.
- `company_mapper.py`: `lookup_isic` deleted; `resolve_company_isic` → `resolve_company_sector`. It
  returns `None` with no LLM call when `company_nace()` resolves, else asks the LLM for one sector name
  and returns it if it is in the list, else `None`.
- `value_chain/links.py::company_nace` also accepts a 2-digit ISIC Rev.4 code, as NACE Rev.2 division
  (`nace_sectors` matches by prefix). The `code` resolution source is gone: sources are
  `nodes | split | nace | llm | none`.
- `exposure.py::compute_indirect_exposure`: the non-NACE path takes a sector name with
  `code_scheme="exiobase"`. Core = nodes of `core_sectors`. `critical_input` and
  `criticality.py::apply_criticality_overlay` compare sectors: the registry's ISIC divisions →
  `division_sectors()`.
- `research/pipeline.py`: the company's sectors (NACE/ISIC through `nace.py`, else the LLM-picked
  sector) feed both the indirect tier and `is_sector_relevant(company_sectors, core_sectors)`.

**Schemas and storage**
- `IndirectExposureResult`: `code_scheme` literal gains `"exiobase"` (new default); `"icio"` stays
  accepted so past run results load. `icio_edition` is renamed `io_edition`, with the old key accepted
  as a validation alias. `isic_code` / `isic_label` keep their names; for `"exiobase"` both hold the
  sector name.
- `ActivityStandardsMapping.unmapped_isic_codes` → `unmapped_sectors`.
- `LinkRule` / `LinkRuleIn`: a `split` part is `{sectors, share}`. Validation errors (HTTP 422,
  `detail` exact): `each part needs sectors and a numeric share` (missing or non-list `sectors`,
  missing share), `sectors must not be empty`, `unknown sector '<name>'`, `duplicate sector '<name>'`
  (inside a part or across parts). Existing messages (`1 to 20 parts`, `share must be > 0`,
  `shares must sum to 1`, …) are unchanged.
- `IcioCode` → `Sector {name}`; `GET /api/value-chain/codes` returns the 163 names (path unchanged).
- `postgres_models.py` docstring only; the JSONB column is unchanged.
- `arp io links-import`: header `company_id,sector,share`, each row one one-sector part; any other
  header fails with `header must be company_id,sector,share`, exit 1.

**Frontend**
- `PortfolioView.tsx` split editor: one row per part, each with a multi-select of the 163 names and a
  share. Migrated multi-sector parts load and save unchanged.
- `valueChain.ts::unresolvedText` shows the part's sectors joined by `, `; `ThemeBuilder.tsx` shows
  `io_edition`. `types.ts`, `schema.gen.ts`, `openapi.json` regenerated.
- `StrategyReplication.tsx` and `replication/sanity_check.py` match "icio" only inside "suspicious": no
  change.

## The migration command

`arp io migrate-exiobase [--file PATH] [--dry-run]` (`cli/io_tables.py`, logic in
`research/indirect_exposure/migrate/`). It reads raw JSON, never through the models, since those reject
the old format.

- Without `--file`: converts (a) every `v*.json` under the configured taxonomies dir, (b) every link rule
  in the configured portfolio store (Postgres or file).
- With `--file`: converts one theme, taxonomy or run `theme.json` file in place, nothing else.
- `S(x)` for an ICIO code `x`: the sorted, de-duplicated `sector_name()` of every row of
  `exiobase_ixi_to_icio2025.csv` whose `icio_code` or `split_code` is `x`.
- Activity: `core_isic_codes: [x, …]` → `core_sectors: sorted union of S(x)`; key order otherwise kept.
  `standards_mapping.unmapped_isic_codes: [x, …]` → `unmapped_sectors: sorted union of S(x)`.
- Link rule `split`/`llm` part `{icio_code: x, share}` → `{sectors: S(x), share}`. `nodes` untouched.
- Output, stdout: one line per changed item, `taxonomy <taxonomy_id> v<n>`, `link <subject>` or
  `file <path>`, then a last line `<n> changed`. Exit 0.
- Already-new data is left byte-identical and not counted.
- An ICIO code with empty `S(x)` aborts before any write: stderr
  `unknown ICIO code '<x>' in <taxonomy <id> v<n> | link <subject> | file <path>>`, exit 1.
- `--dry-run`: same stdout, writes nothing.

Amended 2026-11-05 (owner decision after final review):

- Five ICIO codes were in `icio2025_industries.csv` but match no crosswalk row: `B09`, `C21`, `C301`,
  `H53`, `J58T60`. Old results never used them, so `S(x)` is `[]` for these. A code that never existed
  (e.g. `ZZZ`) still aborts (AC-9).
- A digit-only code (an old hand-supplied ISIC Rev.4 division or class, e.g. `07`, `24`, `2420`) converts
  through the NACE table: `S(x) = sorted(nace.code_set_sectors("isic4", x, "2"))`, the path
  `company_nace_sectors` uses. An empty result aborts like an unknown ICIO code.
- An activity that carries both `core_isic_codes` and `core_sectors` gets `core_sectors` = the sorted union
  of both, so no data is dropped.
- A `--file` JSON document that is not an object is left alone: `0 changed`, exit 0.

## Non-goals

- Improving taxonomy derivation methods, NACE 4-digit anchoring (other session).
- Rewriting past run outputs (results); only a run's `theme.json` is converted, on request via `--file`.
- Short sector codes; editions other than the configured EXIOBASE build.

## Acceptance

**Baseline B** (recorded on `main` before any code change, committed as
`backend/tests/fixtures/icio_baseline.json` in the branch's first commit, before any code change, so the
diff shows it was not edited later): on the sample build (`research/indirect_exposure/sample_data`),
(a) the node weights `resolve_company` gives company `c1` with Fixture M's ICIO rule, and
(b) `upstream_exposure` and `downstream_exposure` from `compute_indirect_exposure` for company `c9`
(`nace_code "24.44"`, `nace_rev "2"`, country `DE`) with core codes `["B07"]`.

**Fixture M**: taxonomy `t1` with `v1.json` (ratified) and `v2.json` (`based_on_version: 1`), each with
activity `a1` (`core_isic_codes ["B07"]`, `standards_mapping.unmapped_isic_codes ["B07"]`) and activity `a2` (`core_isic_codes []`); a file portfolio store
with rule `company:c1` = `split [{icio_code: "B07", share: 0.4}, {icio_code: "D_GEN_REN", share: 0.6}]` and
rule `company:c2` = `nodes [{region: "DE", sector: "Copper production", share: 1}]`.
`S(B07)` = the 8 metal-ore mining sectors; `S(D_GEN_REN)` = the 7 renewable electricity sectors.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture M | `arp io migrate-exiobase` | In `v1.json` and `v2.json`, `a1.core_sectors` = `S(B07)` and `a2.core_sectors` = `[]` | holdout |
| AC-2 | Fixture M | migrate | Neither `v1.json` nor `v2.json` has a `core_isic_codes` key | holdout |
| AC-3 | Fixture M | migrate | `v1.json`'s ratification fields (`status`, `ratified_by`, `ratified_at`) are equal before and after | holdout |
| AC-55 | Fixture M | migrate | `v2.json` has `version` 2 and `based_on_version` 1 | holdout |
| AC-56 | Fixture M | migrate | No `v3.json` exists | holdout |
| AC-57 | Fixture M | migrate | `a1.standards_mapping.unmapped_sectors` = `S(B07)`; no `unmapped_isic_codes` key | holdout |
| AC-4 | Fixture M | migrate | `company:c1` parts = `[{sectors: S(B07), share: 0.4}, {sectors: S(D_GEN_REN), share: 0.6}]` | holdout |
| AC-58 | Fixture M with the store in Postgres (`ARP_TEST_POSTGRES_DSN`) | migrate | `company:c1` parts as in AC-4 | unit |
| AC-5 | Fixture M | migrate | `company:c2` is equal before and after (must not change) | holdout |
| AC-6 | Fixture M | migrate | stdout is exactly the 4 lines `taxonomy t1 v1`, `taxonomy t1 v2`, `link company:c1`, `3 changed`, in this order; exit 0 | holdout |
| AC-7 | Fixture M, migrated | migrate again | stdout is exactly `0 changed`; exit 0 | holdout |
| AC-59 | Fixture M, migrated | migrate again | All files and rules byte-identical to before this run | holdout |
| AC-8 | Fixture M | migrate `--dry-run` | stdout identical to AC-6; all files and rules byte-identical | holdout |
| AC-9 | Fixture M with c1's second part `icio_code "ZZZ"` | migrate | exit 1; stderr exactly `unknown ICIO code 'ZZZ' in link company:c1` | holdout |
| AC-10 | as AC-9 | migrate | All Fixture M files and rules byte-identical | holdout |
| AC-11 | A theme JSON file with one activity `core_isic_codes ["B07"]` | `migrate-exiobase --file <it>` | The file's activity has `core_sectors` `S(B07)` | holdout |
| AC-60 | Same | same | The file has no `core_isic_codes` key | holdout |
| AC-61 | Same | same | stdout is exactly `file <path as passed to --file>`, `1 changed`; exit 0 | holdout |
| AC-12 | Fixture M plus that theme file | `--file <theme>` | Taxonomies dir and store byte-identical | holdout |
| AC-13 | A copy of Fixture M's unmigrated `v1.json` | `--file <copy>` | Byte-identical to the `v1.json` AC-1 produces | holdout |
| AC-14 | Body: a theme with an activity carrying `core_isic_codes` | `POST /api/taxonomies` | HTTP 422; body contains M8 | holdout |
| AC-15 | Same body | `POST /api/taxonomies/t1/versions` | HTTP 422; body contains M8 | holdout |
| AC-16 | A theme file with `core_isic_codes` | `arp theme classify-sectors --theme <it> --out x.json --use-sample-io` | exit 1; stderr contains M8 | holdout |
| AC-62 | A run dir whose `theme.json` has `core_isic_codes` | `arp theme resume <run_id>` | exit 1; stderr contains M8 | holdout |
| AC-17 | Fixture M's unmigrated taxonomies dir | `GET /api/taxonomies/t1` | HTTP 422; body contains M8 | holdout |
| AC-18 | Fixture M migrated, sample build | `links.resolve_company` for c1 | Node weights equal Baseline B (a) to 1e-12 (must not change) | unit |
| AC-19 | Sample build, activity `core_sectors` = `S(B07)` | `compute_indirect_exposure` for c9 | `upstream_exposure`, `downstream_exposure` equal Baseline B (b) to 1e-12 (must not change) | unit |
| AC-20 | Same | same | `code_scheme` `"nace2"`, `isic_code` `"24.44"` | unit |
| AC-21 | Sample build, sector `Copper production` | `compute_indirect_exposure(company_id, "Copper production", model, …)` (non-NACE path) | `code_scheme` `"exiobase"`; `isic_code` and `isic_label` both `Copper production` | unit |
| AC-22 | Sample build | `GET /api/value-chain/codes` | 163 items, each `{name}`; item 0 is `Cultivation of paddy rice` | holdout |
| AC-23 | Split rule body with part `{sectors: ["Not a sector"], share: 1}` | `PUT /api/value-chain/links/company/c1` | HTTP 422, `detail` `unknown sector 'Not a sector'` | holdout |
| AC-24 | Part `{sectors: [], share: 1}` | same PUT | HTTP 422, `detail` `sectors must not be empty` | holdout |
| AC-25 | Parts `[{sectors: ["Copper production"], share: 0.5}, {sectors: ["Copper production"], share: 0.5}]` | same PUT | HTTP 422, `detail` `duplicate sector 'Copper production'` | holdout |
| AC-63 | Part `{sectors: ["Copper production", "Copper production"], share: 1}` | same PUT | HTTP 422, `detail` `duplicate sector 'Copper production'` | holdout |
| AC-26 | Part `{icio_code: "B07", share: 1}` | same PUT | HTTP 422, `detail` `each part needs sectors and a numeric share` | holdout |
| AC-64 | 21 parts, each one distinct sector, shares summing to 1 | same PUT | HTTP 422, `detail` `1 to 20 parts` (must not change) | holdout |
| AC-65 | Part `{sectors: ["Copper production"], share: 0}` plus a second part with share 1 | same PUT | HTTP 422, `detail` `share must be > 0` (must not change) | holdout |
| AC-66 | One part `{sectors: ["Copper production"], share: 0.5}` | same PUT | HTTP 422, `detail` `shares must sum to 1` (must not change) | holdout |
| AC-27 | Valid part `{sectors: S(B07), share: 1}` | same PUT, then `GET /api/value-chain/links` | HTTP 200; the stored rule's part equals the body's | holdout |
| AC-28 | Company sectors from `nace_code 24.44`; activity `core_sectors ["Copper production"]` | `is_sector_relevant` | `True` | unit |
| AC-29 | Same company; `core_sectors ["Cultivation of wheat"]` | `is_sector_relevant` | `False` | unit |
| AC-30 | Company with no NACE/ISIC and no LLM sector; `core_sectors ["Copper production"]` | `is_sector_relevant` | `True` | unit |
| AC-31 | Company sectors from `nace_code 24.44`; `core_sectors []` | `is_sector_relevant` | `True` | unit |
| AC-32 | Company with `isic_code "07"`, no NACE, no rule | `value_chain.links.company_source(company, None)` | `"nace"` | unit |
| AC-33 | Company with `isic_code "C26"` (an old ICIO code), no NACE, no rule | `value_chain.links.company_source(company, None)` | `"none"` | unit |
| AC-34 | Company with `nace_code 24.44`, fake LLM | `resolve_company_sector` | `None`; fake LLM called 0 times | unit |
| AC-35 | Company with no codes, fake LLM answering `Made-up sector` | `resolve_company_sector` | `None` | unit |
| AC-36 | Fake LLM answering `["Copper production", "Made-up sector"]` | `classify_theme_core_sectors` on a theme whose activity has no `core_sectors` | The returned theme's activity has `core_sectors` = `["Copper production"]` | unit |
| AC-37 | Fake LLM drafting one activity with `core_sectors ["Copper production", "Made-up sector"]` | `generate_activities_industry_anchored` | The returned activity's `core_sectors` = `["Copper production"]` | unit |
| AC-38 | Sample build | `industry_prompt_list()` | 163 lines; line 1 `Cultivation of paddy rice` | unit |
| AC-39 | Activity `core_sectors ["Copper production"]` (NACE 24.44 → ISIC 2420, a partial-only match in `un_nace2_isic4.csv`), the bundled sample NACE/NAICS/SIC tables, empty GICS reference | `standards_mapping.mapper.map_activity_standards` | codes of `nace_codes` = `["24"]`, `naics_codes` = `["331"]`, `sic_codes` = `["33"]` | unit |
| AC-40 | Same | same | `unmapped_sectors` = `[]` | unit |
| AC-41 | Activity `core_sectors ["Cultivation of wheat"]`, same tables | same | `unmapped_sectors` = `["Cultivation of wheat"]` | unit |
| AC-42 | Theme with activity `core_sectors ["Copper production"]` | `apply_criticality_overlay` | `criticality_flag` `True` | unit |
| AC-43 | Activity `core_sectors ["Cultivation of wheat"]` | `apply_criticality_overlay` | `criticality_flag` `False` | unit |
| AC-44 | Sample build, c9, core `S(B07)` | `compute_indirect_exposure` | `critical_input` `True` | unit |
| AC-45 | CSV `company_id,sector,share` / `c3,Copper production,1` | `arp io links-import` | exit 0; rule `company:c3` = `split [{sectors: ["Copper production"], share: 1}]` | holdout |
| AC-67 | CSV rows `c3,Copper production,0.5` and `c3,Cultivation of wheat,0.5` | `arp io links-import` | exit 0; rule `company:c3` = `split [{sectors: ["Copper production"], share: 0.5}, {sectors: ["Cultivation of wheat"], share: 0.5}]` | holdout |
| AC-46 | CSV with header `company_id,icio_code,share` | `arp io links-import` | exit 1; stderr `header must be company_id,sector,share` | holdout |
| AC-47 | Archive fixture whose `x.txt` has sector `Foo` | `arp io build-full` | exit 1; stderr contains `EXIOBASE sector not in exiobase_nace.csv: Foo` | unit |
| AC-48 | A stored run result with `code_scheme "icio"` and `icio_edition "X"` | `GET /api/themes/runs/<run_id>/results` | HTTP 200 | holdout |
| AC-49 | Same | same | `io_edition` `"X"`, `code_scheme` `"icio"` | holdout |
| AC-50 | Repo after the change | `grep -rli icio backend/arp frontend/src \| grep -v -e sanity_check.py -e StrategyReplication.tsx` | Output, as a set, equals exactly: `backend/arp/research/indirect_exposure/migrate/__init__.py`, `backend/arp/research/indirect_exposure/migrate/exiobase_ixi_to_icio2025.csv`, `backend/arp/cli/io_tables.py`, `backend/arp/schemas/exposure.py`, `backend/arp/schemas/thematic.py`, `backend/arp/research/pipeline.py`, `frontend/src/api/schema.gen.ts`, `frontend/src/api/openapi.json` | unit |
| AC-68 | Repo after the change | `find backend/arp frontend/src -iname '*icio*'` | Exactly `backend/arp/research/indirect_exposure/migrate/exiobase_ixi_to_icio2025.csv` | unit |
| AC-51 | Split editor loads migrated `company:c1` | Save without edits | The PUT body deep-equals the loaded rule | unit |
| AC-52 | Value Chain portfolio, split editor open on a company | look at a part row | A multi-select listing the 163 sector names, and a share field | evaluator |
| AC-53 | A split part `{sectors: ["A", "B"], share: 0.4}` with no node in the build | look at the link | Text exactly `Not in this edition: A, B 40.0%` | evaluator |
| AC-54 | ThemeBuilder showing an indirect-exposure result | look at the IO line | `Computed from <io_edition value>` | evaluator |

Note on AC-50 (controller ruling): the regenerated `schema.gen.ts` and `openapi.json` contain no "icio", so
they are not in the found set.

Must not change: link weights and exposure numbers for migrated data (AC-18, AC-19); `nodes` link rules
(AC-5); past run results still load (AC-48, AC-49); NACE-path exposure (AC-19, AC-20).

## Builder calls (not decided by the owner; flagged for review)

- Past run results keep loading: `"icio"` stays a valid `code_scheme`, and `io_edition` accepts the
  old key `icio_edition`. Run results are not rewritten.
- `isic_code` / `isic_label` on `IndirectExposureResult` keep their names (renaming breaks run history).
- The relevance check uses the LLM-picked sector when a company has no NACE/ISIC code (as today's
  check uses the LLM-picked ICIO code).
- Stored `standards_mapping.unmapped_isic_codes` is converted with `S(x)`; stored `nace_codes`,
  `naics_codes`, `sic_codes` are kept as they are (re-run `map-standards` to refresh).
- `CompanyRef.isic_code` values that are ICIO codes (from external universes) are not converted; such
  companies fall to `llm` / `none` (AC-33).
- Split editor uses a multi-select per row rather than one row per sector.
- `holdout` rows run as `unit` until `HOLDOUT_TOKEN` is set; the PR lists them as owed. Rows that call
  Python functions directly or need a fake LLM are `unit`, since the running app cannot be driven that way.
- New AC IDs (55–68) were added when splitting rows; IDs are never renumbered.
