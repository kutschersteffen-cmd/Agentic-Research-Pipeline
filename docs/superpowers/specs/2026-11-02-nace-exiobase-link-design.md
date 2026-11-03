# Link companies to EXIOBASE sectors through their own NACE codes

Status: approved by the owner, 2026-11-02. Owner decisions on 2026-11-02: sector codes per company come from the universe
files and the security master; one code per scheme per company for now, revenue shares later (supplied or
extracted); approach A (direct NACE → EXIOBASE at full 163-sector detail).
Background: [sector classifications research](../../SECTOR_CLASSIFICATIONS_RESEARCH.md), official tables in
`backend/arp/research/standards_mapping/reference/` (README there names every source).

## Intent

A company reaches EXIOBASE today only through one ISIC/ICIO code, usually guessed by the LLM, and that code
covers one of 50 ICIO groups (A01 = every crop). The owner has a NACE, ISIC and GICS code for every company.
This spec lets those given codes drive the link: a company's NACE class picks the EXIOBASE sectors it covers
(out of 163), in its own region, weighted by output. The value-chain links, the portfolio overlay and the
indirect-exposure tier then use that set instead of a guess.

## Goals

1. Companies carry `nace_code` (with its revision), `isic_code` and `gics_code`, from the universe file and
   from the security master; the security master wins where both give a value.
2. A shipped reference table maps every EXIOBASE 3 industry to NACE Rev. 2 and NACE Rev. 2.1 codes.
3. A company with a NACE code (or a 4-digit ISIC Rev. 4 class) resolves to EXIOBASE nodes without an LLM
   call, as a new link source `nace`.
4. The indirect-exposure tier uses the same node set for such a company.

## Non-goals

- Revenue shares across several codes per company. A later spec adds them (supplied or extracted); this one
  must not block it (see "How this connects").
- GICS → EXIOBASE. No official table exists; `gics_code` is stored and returned, not mapped.
- NAICS, SIC, ICB, TRBC, BICS inputs.
- Changing themes: `core_isic_codes`, activity links and the ICIO code list stay as they are.
- National 5-digit codes (German WZ and similar). A longer code is cut to its 4-digit NACE class.

## Anti-goals

- An LLM in the NACE path. A company with a valid NACE code never triggers `resolve_company_isic`.
- A silent wrong match. An unknown code is rejected at load; a code that matches no node in the current
  build is reported as unresolved, never replaced by a guess.
- Rewriting stored runs or stored link rules.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | NACE → EXIOBASE sectors directly through a shipped table, output-weighted, as link source `nace` | Full 163-sector detail; needs one new reference table | **Chosen** |
| B | Turn NACE into ISIC and fill `isic_code`, reuse the 50-group ICIO route | One day of work, but stays at ICIO detail, which is the problem | Rejected |
| C | Build revenue-segment extraction first, link each segment | Most precise, about two weeks, and no result until extraction works | Later spec |

## Definitions

- **NACE class**: a NACE code of the form `dd.dd`. A group `dd.d` and a division `dd` are also accepted.
- **Sector table**: `backend/arp/research/indirect_exposure/reference/exiobase_nace.csv`, columns
  `exiobase_sector,nace2_code,nace21_code`, one row per (sector, code) pair. `exiobase_sector` is the exact
  archive string, as in `exiobase_ixi_to_icio2025.csv` (including any ` (31)` suffix).
- **Match**: a company code `c` matches a table code `t` when `t == c`, or `c` starts with `t + "."` or
  `t + digit` (the table is coarser, e.g. `07.2` matches `07.29`), or `t` starts with `c` (the company code
  is coarser, e.g. `27` matches `27.11`). Comparison is on the column of the company's NACE revision.
- **NACE set** of a company: every `exiobase_sector` with a matching row.

## Scope

1. **Sector table.** Built once by the implementer from BONSAI's `exiobase2_to_NACE2008.csv` (BSD-3,
   https://github.com/BONSAMURAIS/correspondence_tables) for `nace2_code`, then the Eurostat NACE Rev. 2 →
   2.1 table in `standards_mapping/reference/` for `nace21_code`, with these rules and hand corrections:
   - every one of the 163 sector names in `exiobase_ixi_to_icio2025.csv` column `exiobase_sector` has at least
     one row; BONSAI misses 13 (`i24.a`–`i24.d`, the `.w` recycling rows renamed in v3, `i90.2.a`–`c`,
     `i90.5.c`) and has 15 with no NACE code (`i72`, the re-processing rows): the implementer fills them from
     the EXIOBASE and NACE titles;
   - a Rev. 2 code's 2.1 targets in a different NACE division are dropped unless they are its only target
     (Eurostat sends `27.11` to `27.11` and `29.10`; the table keeps `27.11` only);
   - NACE 2.1 splits electricity production: `35.11` (non-renewable) gets the coal, gas, nuclear, petroleum
     and other fossil rows; `35.12` (renewable) gets hydro, wind, solar PV, solar thermal, tide/wave,
     geothermal and biomass/waste rows;
   - a README section lists every hand-made or dropped row with its reason.
2. **Company fields.** `CompanyRef` gains `nace_code: str | None`, `nace_rev: Literal["2", "2.1"] = "2"`,
   `gics_code: str | None`. `isic_code` keeps its meaning and also accepts a 4-digit ISIC Rev. 4 class.
3. **Validation on load**, in exactly two places: universe file loading (`load_company_universe`, so
   `POST /api/universe/upload` and the CLI) and the security master upload. Not a model validator: stored
   companies are read back as they are. Checks, per company, in this order, the first failure rejecting the
   whole file and saving nothing (the uploaded file is not kept):
   - a NACE code longer than a class (`35.11.1`) is cut to the class;
   - a `nace_code` not in the Eurostat table for its revision: `unknown NACE Rev. <rev> code '<code>' for
     company '<id>'` (`<rev>` is `2` or `2.1`);
   - a `gics_code` that is not 2, 4, 6 or 8 digits: `bad GICS code '<code>' for company '<id>'`.
   The universe upload answers a rejection with 422 and `detail` the message.
4. **Security master.** Four optional columns appended to the template: `nace_code`, `nace_rev`,
   `isic_code`, `gics_code`. Rows of one issuer must agree on each, else a row error `issuer '<id>' has two
   different <column> values`. Values are kept per issuer next to the identifier map and replaced whole on
   each load, like the map. Errors in these columns are row errors of the existing 422 response.
5. **Override at read time.** `store.get_company` (and every list of companies the store returns) applies the
   current master: a company whose `company_id` equals a master `issuer_id` takes the master's non-empty
   sector values in place of its own. Every caller (links, overlay, theme runs, `classify_unlinked`) sees the
   same merged company. Nothing stored is rewritten.
6. **Resolution order** for a company link (`resolve_company`, `company_source`): stored rule (`nodes`,
   `split`) → `nace` → `code` (ICIO) → `llm` → `none`. `nace` applies when the company has a `nace_code`, or
   no `nace_code` and a 4-digit `isic_code` that the UN ISIC Rev. 4 → NACE Rev. 2 table maps (all its NACE
   targets, Rev. 2). The NACE set's nodes in the company's region (every region when the region is unknown or
   not in the build) are weighted by output, nodes with no output dropped, exactly as `code` weights an ICIO
   code's nodes today.
7. **Unresolved.** A `nace` company whose set has no node with output gets `nodes` `[]` and `unresolved`
   `[{"nace_code": "<code>", "nace_rev": "<rev>"}]`, or `[{"isic_code": "<code>"}]` when it came by the
   ISIC route.
8. **API and UI.** `ValueChainLinks.source` and the overlay's `link_source` gain the value `nace`. The
   universe upload's `sample` shows the three new fields. The value-chain link panel shows `Linked by NACE
   <code>` (or `Linked by ISIC <code>`) above the nodes for a `nace` company. OpenAPI and the generated
   frontend types are regenerated.
9. **Indirect exposure.** For a company that resolves as `nace`, `compute_indirect_exposure` takes the
   company's nodes from its NACE set. The result's `isic_code` holds the company's code as given (`27.11`,
   or `2710` by the ISIC route) and a new field `code_scheme` is `nace2`, `nace21`, `isic4` or `icio`.
   `isic_label` is the code's title from the Eurostat or UN table. `core_sector` is true when the NACE set
   shares an EXIOBASE sector with the theme's core codes' sectors; `critical_input` likewise with the sectors of the
   criticality registry's ISIC divisions, read as the same NACE divisions (`07` → every `07.x` row). So a NACE company keeps the core and critical-input status its
   sectors earn.

## My calls (owner to confirm with the acceptance table)

1. `nace_rev` defaults to `"2"`: most vendor data and BONSAI are Rev. 2.
2. The security master wins over the universe file, applied when a company is read, because the repo
   already treats the master as the golden source.
3. A company's NACE set is weighted by output, the same rule `code` uses, until revenue shares exist.
4. An ISIC class without a NACE code goes through the UN table rather than the ICIO route.
5. Cross-division Rev. 2.1 targets are dropped from the sector table (Scope 1).
6. Codes are validated only where files come in, never on read.

## Constraints

- No new dependency; the sector table is a committed CSV.
- No LLM call anywhere in the `nace` path.
- EXIOBASE licence unchanged; the sector table holds only names and codes.

## Left to the builder

- Where per-issuer sector values are stored next to the identifier map (file or Postgres), matching how the
  identifier map is stored.
- Code layout of the matcher and the table loader.
- The title-based choices for hand-filled rows, listed in the README.

## How this connects to revenue shares (later spec)

Revenue shares will arrive as several `(nace_code, share)` pairs per company. This spec's NACE set is the
building block: each pair becomes its output-weighted set times its share, the way a `split` rule combines
ICIO codes today. Nothing here assumes one code per company beyond the `CompanyRef` field.

## Acceptance

**Fixture V**, "V built", and sector names `<Copper>`, `<Nickel>`, `<Wind>`, `<Machinery>` as in the
value-chain links spec (2026-10-27). They are real EXIOBASE names, so tests use the shipped
`exiobase_nace.csv`, which AC-1 to AC-5 pin for these four: `<Copper>` and `<Nickel>` match NACE `07.29`,
`<Wind>` matches Rev. 2 `35.11` and Rev. 2.1 `35.12`, `<Machinery>` matches `27.11`. Outputs: DE
`[50, 0, 100, 200]`, CN `[100, 40, 80, 400]`, WA `[60, 20, 10, 50]`.

**Store N** (the JSON portfolio store), companies as `CompanyRef`:
- `nc`: country `CN`, `nace_code` `07.29`;
- `nw`: country `DE`, `nace_code` `35.11`;
- `nr`: country `DE`, `nace_code` `35.12`, `nace_rev` `2.1`;
- `nf`: country `DE`, `nace_code` `35.11`, `nace_rev` `2.1`;
- `ni`: country `CN`, `isic_code` `2710`;
- `nm`: country `CN`, `nace_code` `27.11`, `isic_code` `C27`;
- `nd`: country `CN`, `nace_code` `27`;
- `nu`: no country, `nace_code` `07.29`;
- `ng`: country `CN`, `gics_code` `20104010`, no other code;
- `nj`: country `CN`, `isic_code` `0710` (iron ores: no sector of V);
- `ns`: country `CN`, `nace_code` `27.11`, linked with `PUT …/links/company/ns`
  `{"kind":"split","parts":[{"icio_code":"B07","share":1}]}`.

`L(id)` is `GET /api/value-chain/links/company/<id>`. `U(file)` is `POST /api/universe/upload` with that
file. `M(file)` is `POST /api/security-master/upload` as an approver. `X(id, core, country)` is
`compute_indirect_exposure` for that company of N on V's model. Numbers rounded to 4 decimals. Requests as
an analyst.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | committed repo | read `exiobase_nace.csv` and `exiobase_ixi_to_icio2025.csv` | each of the 163 `exiobase_sector` values of the second file appears in `exiobase_sector` of the first | unit |
| AC-1b | committed repo | read `exiobase_nace.csv` | no row has an empty `nace2_code` or `nace21_code` | unit |
| AC-2 | committed repo | read the rows for `Production of electricity by wind` | `nace21_code` is `35.12` on every one of them | unit |
| AC-2b | committed repo | read the rows for `Production of electricity by coal` | `nace21_code` is `35.11` on every one of them | unit |
| AC-2c | committed repo | read the rows for `Production of electricity by solar photovoltaic` | `nace21_code` is `35.12` on every one of them | unit |
| AC-2d | committed repo | read every row with `nace2_code` `27.11` | none has a `nace21_code` starting `29` | unit |
| AC-3 | V built, N | `L(nc)` | 200; `source` `nace`; `region` `CN`; `nodes` in order: CN.1 0.7143, CN.2 0.2857 | holdout |
| AC-3b | as AC-3 | `L(nc)` | `unresolved` `[]`; `rule` null | holdout |
| AC-4 | V built, N | `L(nw)` | `source` `nace`; `nodes` exactly `[{DE.3, 1}]` | holdout |
| AC-5 | V built, N | `L(nr)` | `source` `nace`; `nodes` exactly `[{DE.3, 1}]` | holdout |
| AC-6 | V built, N | `L(nf)` | 200; `source` `nace`; `nodes` `[]`; `unresolved` `[{"nace_code":"35.11","nace_rev":"2.1"}]` | holdout |
| AC-7 | V built, N | `L(ni)` | `source` `nace`; `nodes` exactly `[{CN.4, 1}]` | holdout |
| AC-8 | V built, N | `L(nm)` | `source` `nace`; `nodes` exactly `[{CN.4, 1}]` | holdout |
| AC-8b | V built, N | `L(nd)` | `source` `nace`; `nodes` exactly `[{CN.4, 1}]` | holdout |
| AC-9 | V built, N | `L(nu)` | `source` `nace`; `region` null; `nodes` in order: CN.1 0.3704, WA.1 0.2222, DE.1 0.1852, CN.2 0.1481, WA.2 0.0741 | holdout |
| AC-10 | V built, N | `L(ns)` | `source` `split`; `rule.kind` `split` | holdout |
| AC-10c | V built, N | `L(nj)` | `source` `nace`; `nodes` `[]`; `unresolved` `[{"isic_code":"0710"}]` | holdout |
| AC-10b | V built, N | `L(ng)` | `source` `none`; `nodes` `[]` | holdout |
| AC-11 | V built, N, the LLM client replaced by a stub that counts calls | a theme run over `nc`, `nw`, `nr`, `nf`, `ni`, `nm`, `nd`, `nu` with the indirect tier on, then `classify_unlinked` over a portfolio holding them | the stub's call count is 0 | unit |
| AC-12 | V built, N | `X(nm, {"B07"}, "CN")` | `upstream_exposure` 0.1549, `downstream_exposure` 0.015 | unit |
| AC-12b | as AC-12 | `X(nm, {"B07"}, "CN")` | `code_scheme` `nace2`; `isic_code` `27.11` | unit |
| AC-12c | V built, N | `X(nr, {"B07"}, "DE")` | `code_scheme` `nace21`; `isic_code` `35.12` | unit |
| AC-12d | V built, N | `X(ni, {"B07"}, "CN")` | `code_scheme` `isic4`; `isic_code` `2710` | unit |
| AC-12f | as AC-12 | `X(nm, {"B07"}, "CN")` | `isic_label` is the `NACE_Rev_2_Heading` of `27.11` in `eurostat_nace2_nace21.csv` | unit |
| AC-12g | V built, N, the shipped criticality registry (its ISIC divisions are `07`, `20`, `24`) | `X(nc, {"C27"}, "CN")` | `critical_input` true | unit |
| AC-12h | as AC-12g | `X(nm, {"C27"}, "CN")` | `critical_input` false | unit |
| AC-12e | V built, N | `X(nm, {"C27"}, "CN")` | `core_sector` true | unit |
| AC-13 | a universe JSON with companies `ok1` (`nace_code` `07.29`) and `nb` (`nace_code` `99.99`) | `U(file)` | 422; `detail` `unknown NACE Rev. 2 code '99.99' for company 'nb'` | holdout |
| AC-13c | as AC-13 | list `<runs_dir>/_universes/` | no file from AC-13's upload is there | unit |
| AC-13b | a universe JSON with company `nb2`, `nace_code` `99.99`, `nace_rev` `2.1` | `U(file)` | 422; `detail` `unknown NACE Rev. 2.1 code '99.99' for company 'nb2'` | holdout |
| AC-14 | a universe JSON with company `nk`, `nace_code` `35.11.1` | `U(file)` | 200; `sample[0]` has `nace_code` `35.11` and `nace_rev` `2` | holdout |
| AC-15 | a universe JSON with company `nq`, `gics_code` `5510101` | `U(file)` | 422; `detail` `bad GICS code '5510101' for company 'nq'` | holdout |
| AC-16 | a universe JSON with one company `ny`: `nace_code` `07.29`, `isic_code` `0729`, `gics_code` `55101010` | `U(file)` | 200; `sample[0]` has `nace_code` `07.29`, `nace_rev` `2`, `isic_code` `0729`, `gics_code` `55101010` | holdout |
| AC-17 | a current master; a new master CSV with issuer `nx` on two rows, `nace_code` `07.29` and `35.11` | `M(file)` | 422; `errors` contains `issuer 'nx' has two different nace_code values` | holdout |
| AC-17b | after AC-17 | `GET /api/security-master` | `issuers` equals its value before AC-17 | holdout |
| AC-17c | a master CSV with issuer `nz`, `nace_code` `99.99` | `M(file)` | 422; `errors` contains `unknown NACE Rev. 2 code '99.99' for company 'nz'` | holdout |
| AC-18 | V built, N; then `M` with issuer `nw`, `nace_code` `07.29`, other sector cells empty | `L(nw)` | `source` `nace`; `nodes` exactly `[{DE.1, 1}]` | holdout |
| AC-18b | V built, N; then `M` with issuer `nr`, `nace_rev` `2`, other sector cells empty | `L(nr)` | `source` `nace`; `nodes` `[]`; `unresolved` `[{"nace_code":"35.12","nace_rev":"2"}]` (Rev. 2 `35.12` is transmission) | holdout |
| AC-18c | V built, N; then `M` with issuer `ng`, `isic_code` `2710`, other sector cells empty | `L(ng)` | `source` `nace`; `nodes` exactly `[{CN.4, 1}]` | holdout |
| AC-19 | as AC-18, then `M` with the same issuers and no sector columns | `L(nw)` | `nodes` exactly `[{DE.3, 1}]` | holdout |
| AC-20 | V built, N, portfolio `P` with securities of `nc` 600,000 and `nw` 400,000 EUR on `2026-09-30` | `GET /api/value-chain/portfolio/P` | `holdings[*].link_source` is `nace` for both | holdout |
| AC-21 | V built, N | open the value-chain link panel for `nc` | the text `Linked by NACE 07.29` shows | evaluator |
| AC-21b | as AC-21 | same panel | the nodes `CN · Mining of copper ores and concentrates 71.4%` and `CN · Mining of nickel ores and concentrates 28.6%` show | evaluator |
| AC-21c | V built, N | open the value-chain link panel for `ni` | the text `Linked by ISIC 2710` shows | evaluator |
| AC-24 | any | `GET /api/security-master/template` | body is the line `issuer_id,issuer_name,isin,cusip,sedol,figi,lei,cik,permid,valid_from,valid_to,nace_code,nace_rev,isic_code,gics_code` | holdout |

Must not change:

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-22 | V built, Store S of spec 2026-10-27 (no NACE codes) | that spec's AC-1 to AC-23 | all pass unchanged | holdout |
| AC-23 | V built | spec 2026-10-26 AC-9 to AC-17 (indirect exposure by ICIO code) | all pass unchanged, and each result has `code_scheme` `icio` | unit |
| AC-25 | a master CSV in today's 11-column layout | `M(file)` | 200; `identifiers` and `issuers` as today | holdout |
| AC-26 | a universe JSON in today's layout (no new fields) with 3 companies | `U(file)` | 200; `company_count` 3; every `sample` entry has `nace_code` null, `nace_rev` `2`, `gics_code` null | holdout |
| AC-27 | V built, Store S; a theme run stored before this change | open it in Run History | its indirect-exposure figures equal those in its stored result file | evaluator |
| AC-29 | V built, N; then `M` with issuer `ns`, `nace_code` `07.29` | `L(ns)` | `rule` is exactly `{"kind":"split","parts":[{"icio_code":"B07","share":1}]}` with the `set_by` and `set_at` it had before | holdout |
| AC-28 | V built, Store S | `GET /api/value-chain/links/activity/T/a1` | identical to spec 2026-10-27 AC-14 (themes and activity links unchanged) | holdout |
