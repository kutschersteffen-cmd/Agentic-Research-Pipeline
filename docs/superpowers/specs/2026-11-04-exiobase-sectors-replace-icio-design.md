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
   163 sector names, a closed list as today. Answers not in the list are dropped as today. The anchored
   method's logic is otherwise untouched.
5. **Standards mapping.** `core_sectors` → NACE Rev.2 codes (reverse of `exiobase_nace.csv`, new
   function in `nace.py`) → ISIC Rev.4 (`un_nace2_isic4.csv`) → the existing ISIC-keyed NACE/NAICS/SIC
   crosswalk tables, unchanged. `ActivityStandardsMapping.unmapped_isic_codes` becomes
   `unmapped_sectors`: sectors none of the loaded tables matched.
6. **Relevance check.** `is_sector_relevant` (revenue and R&D exposure) is true when the company's
   sectors (its NACE / ISIC code through `nace.py`) overlap the activity's `core_sectors`. No company
   code, or no `core_sectors`, stays `True`.
7. **Migration.** A one-off command `arp io migrate-exiobase` rewrites stored data. It is the only reader
   of `exiobase_ixi_to_icio2025.csv` after this change; all other ICIO reference data and code is deleted.
8. **Old uploads.** A theme or taxonomy JSON still carrying `core_isic_codes` is rejected with HTTP 422
   (CLI: exit 1) and the message
   `core_isic_codes (ICIO) is no longer supported; run arp io migrate-exiobase --file <theme.json> to convert it`.
9. **Taxonomy versions.** The command rewrites every `v*.json` of every taxonomy in place: same version
   number, same ratification, same `based_on_version`; only `core_isic_codes` → `core_sectors`.

## Approaches considered

- **Convert on read** (pydantic "before" validators on `ActivityDefinition` and `LinkRule`): no
  per-deployment step, old uploads keep working, but ICIO conversion stays in the load path forever.
- **One-off migration command** (chosen): the load path is ICIO-free; the command runs once per
  deployment and on old files on request. Rejected alternative within it: appending a new taxonomy version
  instead of rewriting in place, which leaves older versions loading with empty sectors and needs
  re-ratification.

## What changes

**Model and code list** (`indirect_exposure/`)
- `factory.py`: `CodeList` / `code_list()` deleted. A new `sectors()` returns the 163 names in
  `exiobase_nace.csv` order of first appearance. `LeontiefModel.codes` = those names,
  `code_nodes` keyed by name; `labels`, `isic_divisions`, `nace_classes`, `prompt_codes` deleted.
  `industry_reference_list()` / `industry_prompt_list()` list the 163 names, one per line.
- `io_import.py`: `SPLIT_INDUSTRIES` deleted. `build.py` validates archive sectors against `sectors()`
  instead of the ICIO crosswalk.
- `icio2025_industries.csv` deleted. `exiobase_ixi_to_icio2025.csv` moves next to the migration command
  and is read only there.
- `company_mapper.py`: `lookup_isic` deleted. `resolve_company_isic` → `resolve_company_sector`: returns
  `None` with no LLM call when `company_nace()` resolves; otherwise one LLM call picking one sector name.
- `links.py::company_nace` also accepts a 2-digit ISIC Rev.4 division (as NACE Rev.2 division, which
  `nace_sectors` matches by prefix). The `code` resolution source disappears: sources are
  `nodes | split | nace | llm | none`.
- `exposure.py::compute_indirect_exposure`: the non-NACE path takes a sector name
  (`code_scheme="exiobase"`). Core = nodes of `core_sectors`. `critical_input` and
  `criticality.py::apply_criticality_flags` compare sectors: the registry's ISIC divisions → `division_sectors()`.

**Schemas and storage**
- `IndirectExposureResult`: `code_scheme` literal gains `"exiobase"` (default), `"icio"` stays accepted so
  past run results load; `icio_edition` renamed `io_edition` (see "Builder calls").
- `LinkRule` / `LinkRuleIn` docs and validation: `split` parts need `sectors` (non-empty list of known
  names, no duplicates inside a part or across parts) and `share`. `IcioCode` → `Sector {name}`;
  `GET /api/value-chain/codes` returns the 163 names (path unchanged).
- `postgres_models.py` docstring only; the JSONB column is unchanged.
- `arp io links-import` CSV header becomes `company_id,sector,share`; each row is a one-sector part.

**Frontend**
- `PortfolioView.tsx` split editor: each row is one part with a sector multi-select (the 163 names) and a
  share. Migrated multi-sector parts load and save unchanged.
- `valueChain.ts::unresolvedText` shows `sectors.join(", ")`; `ThemeBuilder.tsx` shows `io_edition`;
  `types.ts`, `schema.gen.ts`, `openapi.json` regenerated.
- `StrategyReplication.tsx` and `replication/sanity_check.py` match "icio" only inside "suspicious": no
  change.

## The migration command

`arp io migrate-exiobase [--file PATH] [--dry-run]`

- Without `--file`: rewrites (a) every taxonomy version file under the configured taxonomies dir, (b) every
  link rule in the configured portfolio store (Postgres or file).
- With `--file`: converts one theme or taxonomy JSON in place and touches nothing else.
- ICIO code → sectors: every `exiobase_sector` row whose `icio_code` or `split_code` equals the code,
  through `sector_name()`, sorted. Same mapping `code_list().covers` uses today.
- A `split`/`llm` part `{icio_code, share}` → `{sectors, share}`. `nodes` rules untouched.
- Idempotent: data already in the new shape is left byte-identical. An unknown ICIO code aborts the whole
  run before any write, naming the subject or file.
- Prints one line per changed item and a total; `--dry-run` prints the same and writes nothing.

## Non-goals

- Improving taxonomy derivation methods, NACE 4-digit anchoring (other session).
- Rewriting past run outputs.
- Short sector codes, editions other than the configured EXIOBASE build.

## Acceptance

Fixture M: taxonomy `t1` with `v1.json` (ratified) and `v2.json`, each with one activity whose
`core_isic_codes` is `["B07"]` plus one with `[]`; a file portfolio store with rule
`company:c1` = `split [{icio_code: "C26", share: 0.4}, {icio_code: "D35T", share: 0.6}]`
(`D35T` = an electricity split code) and rule `company:c2` = `nodes [{region: DE, sector: Copper production, share: 1}]`.
`S(x)` = the sorted sector names `exiobase_ixi_to_icio2025.csv` maps code `x` to.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | Fixture M | `arp io migrate-exiobase` | `v1.json` and `v2.json` have `core_sectors` `S(B07)` and `[]`, no `core_isic_codes`; `v1` still ratified, same version numbers | unit |
| AC-2 | Fixture M | migrate | `company:c1` parts are `[{sectors: S(C26), share: 0.4}, {sectors: S(D35T), share: 0.6}]`; `company:c2` unchanged | unit |
| AC-3 | Fixture M, migrated | migrate again | No file or rule changes (byte-identical); total line says 0 changed | unit |
| AC-4 | Fixture M | migrate `--dry-run` | Same output lines as AC-1/AC-2's run; no file or rule changes | unit |
| AC-5 | Fixture M with a rule part `icio_code: "ZZZ"` | migrate | Exit 1, message names `ZZZ` and the subject; nothing written | unit |
| AC-6 | A theme JSON with `core_isic_codes: ["C26"]` | `migrate-exiobase --file it` | The file has `core_sectors` `S(C26)`; taxonomies dir and store untouched | unit |
| AC-7 | A theme JSON with `core_isic_codes` | upload via the taxonomy API | HTTP 422 with the decision-8 message | unit |
| AC-8 | Sample build, company c1 migrated as AC-2 | `resolve_company` | Same node weights (to 1e-12) as the pre-change resolution of the ICIO rule | unit |
| AC-9 | Sample build, activity with `core_sectors` = `S(B07)` | `compute_indirect_exposure` for a company | Same upstream/downstream exposure (to 1e-12) as before with `core_isic_codes ["B07"]` | unit |
| AC-10 | Sample build | `GET /api/value-chain/codes` | 163 items, each `{name}`, first one is the first sector of `exiobase_nace.csv` | unit |
| AC-11 | A split rule with a part `sectors: ["Not a sector"]` | `PUT` the rule | HTTP 422 `unknown sector 'Not a sector'` | unit |
| AC-12 | Company with `nace_code 24.44` and activity `core_sectors` = `["Copper production"]` | `is_sector_relevant` | `True`; with `core_sectors` `["Cultivation of wheat"]`: `False` | unit |
| AC-13 | Company with `isic_code "07"` (no NACE) | `company_source` | `nace` | unit |
| AC-14 | Activity with `core_sectors` `["Copper production"]`, sample crosswalks | standards mapping | NACE codes include the `exiobase_nace.csv` codes for Copper production; `unmapped_sectors` `[]` | unit |
| AC-15 | Fake LLM answering `Copper production` and `Made-up sector` | `classify_core_sectors` | `core_sectors` = `["Copper production"]` | unit |
| AC-16 | Repo after the change | `grep -ri icio backend/arp frontend/src` | Hits only in the migration command, its CSV, the `"icio"` literal kept for past results, and the words "suspicious"/"suspiciously" | unit |
| AC-17 | Split editor loads `company:c1` migrated | Save without edits | The stored rule is unchanged | unit |
| AC-18 | A stored run result with `code_scheme "icio"` and `icio_edition "X"` | load the run | It loads; `io_edition` is `"X"` | unit |

Must not change: exposure numbers and link weights for migrated data (AC-8, AC-9); `nodes` link rules
(AC-2); past run results still load (AC-18).

## Builder calls (not decided by the owner; flagged for review)

- **Past run results** keep loading: `"icio"` stays a valid `code_scheme`, and `io_edition` accepts the old
  key `icio_edition` via a pydantic validation alias. Run outputs are not rewritten.
- `isic_code` / `isic_label` on `IndirectExposureResult` keep their names (renaming breaks run history);
  for `code_scheme="exiobase"` they hold the sector name twice.
- Split editor uses a multi-select per row rather than one row per sector.
- `CompanyRef.isic_code` values that are ICIO codes (from external universes) are not converted; such
  companies fall to `llm` / `none`.
