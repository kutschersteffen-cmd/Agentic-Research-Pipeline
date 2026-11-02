# NACE → EXIOBASE Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Companies with their own NACE (or 4-digit ISIC) code link to EXIOBASE nodes without an LLM, at 163-sector detail.

**Architecture:** One new module `arp/research/indirect_exposure/nace.py` owns the shipped sector table and the
match rule (code → set of EXIOBASE sector names). Company fields come in through the universe loader and the
security master; the portfolio stores merge the master's per-issuer values on read. `links.py` adds the `nace`
source before `code`; `compute_indirect_exposure` takes its node set from the same function.

**Tech Stack:** Python 3.13, Pydantic, FastAPI, SQLAlchemy (additive columns are reconciled automatically by
`arp/storage/postgres_schema.py`), React/TypeScript for the panel text.

**Spec:** `docs/superpowers/specs/2026-11-02-nace-exiobase-link-design.md` (approved 2026-11-02). Every AC-n below
refers to its Acceptance table; copy values from there, not from memory.

## Global Constraints

- No new dependency. No LLM call anywhere in the `nace` path.
- Validation runs only in `load_company_universe` and the security master upload, never in a model validator.
- Messages, verbatim: `unknown NACE Rev. <rev> code '<code>' for company '<id>'`,
  `bad GICS code '<code>' for company '<id>'`, `issuer '<id>' has two different <column> values`,
  panel text `Linked by NACE <code>` / `Linked by ISIC <code>`.
- `nace_rev` is `"2"` or `"2.1"`, default `"2"`.
- Resolution order: stored rule → `nace` → `code` → `llm` → `none`.
- After changing response models: `cd backend && python scripts/export_openapi.py`, then
  `cd frontend && npm run gen:api`, commit both generated files.
- Checks: `cd backend && ruff check . && python3 -m pytest tests/<file>`; frontend `npm run lint && npx tsc -b && npm test`.

## Review Focus

1. A NACE code written without its dot or with spaces (`0729`, ` 07.29 `) in a universe file: expect it
   normalised to `07.29` before validation, not rejected. Test in Task 2.
2. A NACE code that JSON turned into a number (`7.29`, `35.1`): expect rejection with the unknown-code message
   (`7.29` is not a NACE code), never a silent match. Test in Task 2.
3. A master issuer with sector values but no company of that id: expect nothing to break and no company
   created. Test in Task 3.
4. A master row with `nace_code` but empty `nace_rev`: expect revision `2`, validated as Rev. 2. Test in Task 3.
5. A build where none of a NACE set's sectors has output in any region (`nu`-style, no country): expect
   `nodes` `[]` plus `unresolved`, never a division by zero. Test in Task 4.

---

### Task 1: Sector table and NACE matcher

**Files:**
- Create: `backend/arp/research/indirect_exposure/reference/exiobase_nace.csv`
- Modify: `backend/arp/research/standards_mapping/reference/README.md` (new section listing every hand-made or dropped row)
- Create: `backend/arp/research/indirect_exposure/nace.py`
- Test: `backend/tests/test_nace_table.py`

**Interfaces:**
- Produces:
  - `normalise_nace(code: str) -> str` — strips spaces, inserts the dot after 2 digits, cuts past a class.
  - `nace_known(code: str, rev: str) -> bool` — code exists in `eurostat_nace2_nace21.csv` (`NACE_Rev_2_Code`
    for `"2"`, `NACE_Rev_21_Code` for `"2.1"`).
  - `nace_title(code: str, rev: str) -> str | None`.
  - `isic_to_nace2(isic4: str) -> list[str]` — every NACE target of a 4-digit class in `un_isic4_nace2.csv`.
  - `nace_sectors(code: str, rev: str) -> set[str]` — EXIOBASE sector names whose table code matches under the
    spec's Definitions match rule, on column `nace2_code` or `nace21_code`.
  - `division_sectors(division: str) -> set[str]` — `nace_sectors(division, "2")`, for the criticality registry.

- [ ] **Step 1: Build `exiobase_nace.csv`** from BONSAI's `exiobase2_to_NACE2008.csv`
  (`git clone --depth 1 https://github.com/BONSAMURAIS/correspondence_tables`, file under
  `correspondence_tables/data/raw/`) and the Eurostat table, following spec Scope 1 (fill the 13 missing and 15
  empty rows, drop cross-division 2.1 targets, hand-split electricity into `35.11`/`35.12`). Write a one-off
  script in the scratchpad, not the repo; commit only the CSV and the README section.
- [ ] **Step 2: Write the failing tests** in `test_nace_table.py`:

```python
def test_ac1_every_exiobase_sector_present(): ...      # 163 names of exiobase_ixi_to_icio2025.csv ⊆ exiobase_nace.csv
def test_ac1b_no_empty_codes(): ...
def test_ac2_wind_is_renewable(): ...                  # every wind row: nace21_code == "35.12"
def test_ac2b_coal_is_non_renewable(): ...             # every coal row: nace21_code == "35.11"
def test_ac2c_solar_pv_is_renewable(): ...
def test_ac2d_no_cross_division_for_2711(): ...        # rows with nace2 27.11: no nace21 starting "29"
def test_match_rule():
    assert {"Mining of copper ores and concentrates", "Mining of nickel ores and concentrates"} <= nace_sectors("07.29", "2")
    assert "Manufacture of electrical machinery and apparatus n.e.c. (31)" in nace_sectors("27", "2")
    assert "Production of electricity by wind" in nace_sectors("35.12", "2.1")
    assert "Production of electricity by wind" not in nace_sectors("35.11", "2.1")
    assert nace_sectors("35.12", "2") & {"Production of electricity by wind"} == set()
def test_normalise():
    assert normalise_nace(" 0729 ") == "07.29" and normalise_nace("35.11.1") == "35.11"
def test_isic_route():
    assert isic_to_nace2("2710") == ["27.11", "27.12"]
```

- [ ] **Step 3: Run** `cd backend && python3 -m pytest tests/test_nace_table.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement `nace.py`.** Load each CSV once (`functools.cache`). Match rule exactly as the spec's
  Definitions: `t == c`, or `c` starts with `t` followed by `.` or a digit, or `t` starts with `c`.
- [ ] **Step 5: Run** the same command. Expected: PASS.
- [ ] **Step 6: Commit** `feat: EXIOBASE↔NACE sector table and matcher`.

### Task 2: Company fields and universe validation

**Files:**
- Modify: `backend/arp/schemas/common.py:44-63` (`CompanyRef`)
- Modify: `backend/arp/universe.py:10` (`load_company_universe`)
- Modify: `backend/arp/api/routers/universe.py:19-37` (`upload_universe`)
- Modify: `backend/arp/storage/postgres_models.py:60` (`CompanyModel`), `backend/arp/storage/postgres_portfolio_store.py:215-235,554-558`
- Test: `backend/tests/test_universe_nace.py`

**Interfaces:**
- Consumes: `normalise_nace`, `nace_known` (Task 1).
- Produces: `CompanyRef.nace_code: str | None`, `CompanyRef.nace_rev: Literal["2", "2.1"] = "2"`,
  `CompanyRef.gics_code: str | None`; `class UniverseRejected(ValueError)` raised by `load_company_universe`
  with the spec's message as `str(e)`; helper `check_sector_codes(company: CompanyRef) -> CompanyRef` (normalises,
  raises `UniverseRejected`) that Task 3 reuses.

- [ ] **Step 1: Write the failing tests** — one per AC-13, AC-13b, AC-13c, AC-14, AC-15, AC-16, AC-26 through
  `TestClient` `POST /api/universe/upload`, plus Review Focus 1 (`" 0729 "` → `07.29`) and 2 (`7.29` as a JSON
  number → 422 `unknown NACE Rev. 2 code '7.29' for company '<id>'`), plus a Postgres round-trip that
  `save_company` / `get_company` keep all three fields (skips without `ARP_TEST_POSTGRES_DSN`, like the existing tests).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_universe_nace.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Fields on `CompanyRef`; `load_company_universe` calls `check_sector_codes` on each
  company; `upload_universe` parses before writing (write to the final path only after the parse succeeds, so
  AC-13c holds) and maps `UniverseRejected` to `HTTPException(422, str(e))`. Add the three nullable columns to
  `CompanyModel` and both directions of the Postgres mapping.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: NACE/GICS fields on companies, validated on universe load`.

### Task 3: Security master sector columns and read-time override

**Files:**
- Modify: `backend/arp/holdings/security_master.py` (`COLUMNS`, `parse`, `load`)
- Create: `backend/arp/storage/issuer_sectors.py`
- Modify: `backend/arp/storage/portfolio_store.py:154-159`, `backend/arp/storage/postgres_portfolio_store.py:227-240`,
  `backend/arp/storage/portfolio_store_factory.py:12`
- Test: `backend/tests/test_security_master_sectors.py`

**Interfaces:**
- Consumes: `check_sector_codes` (Task 2).
- Produces:
  - `IssuerSectorStore(path: Path)` with `replace(rows: dict[str, dict[str, str]]) -> None` and
    `get(issuer_id: str) -> dict[str, str]` (non-empty values only). File:
    `settings.identifier_map_path.with_name("issuer_sectors.json")`.
  - `apply_master(company: CompanyRef, sectors: IssuerSectorStore) -> CompanyRef` — returns a copy with the
    master's non-empty values; used by both stores' `get_company` and `list_companies`.

- [ ] **Step 1: Write the failing tests** — AC-17, AC-17b, AC-17c, AC-24, AC-25 via `TestClient` on
  `/api/security-master/upload` and `/template`; store-level tests that after a master upload `get_company("nw")`
  returns `nace_code` `07.29` and after a master without sector columns returns `35.11` again (the store half of
  AC-18/AC-19); Review Focus 3 (issuer `ghost` with sector values, no company: `get_company("ghost")` is None,
  `list_companies()` unchanged) and 4 (empty `nace_rev` → stored as `2`).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_security_master_sectors.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Append `nace_code, nace_rev, isic_code, gics_code` to `COLUMNS` (template order per
  AC-24); in `parse`, collect per issuer, emit the disagreement row error, run `check_sector_codes` on a
  `CompanyRef(company_id=issuer_id, name=issuer_name, ...)` and turn its error into a row error. In `load`, call
  `IssuerSectorStore.replace` only after the identifier map is written. Both portfolio stores take an
  `IssuerSectorStore` (built in `build_portfolio_store`) and apply it on read.
- [ ] **Step 4: Run** the tests, plus `tests/test_security_master.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: sector codes in the security master, applied when companies are read`.

### Task 4: `nace` link source

**Files:**
- Modify: `backend/arp/research/value_chain/links.py:116-135` (`company_source`, `resolve_company`), `:193-230`
  (overlay `link_source`)
- Modify: `backend/arp/schemas/value_chain.py:209` (`source` Literal), the overlay holding's `link_source` Literal
- Test: `backend/tests/test_value_chain_links_nace.py`

**Interfaces:**
- Consumes: `nace_sectors`, `isic_to_nace2`, `normalise_nace` (Task 1); merged `CompanyRef` (Task 3).
- Produces: `company_nace(company: CompanyRef) -> tuple[str, str, str] | None` returning
  `(scheme, code, rev)` with scheme `"nace2"`, `"nace21"` or `"isic4"`; `nace_weights(vc, company, region) -> dict[int, float]`.
  Task 5 uses `company_nace`.

- [ ] **Step 1: Write the failing tests** — AC-3, AC-3b, AC-4 … AC-10c, AC-18, AC-18b, AC-18c, AC-19, AC-20,
  AC-29 against Fixture V and Store N, built with the helpers `tests/test_value_chain_links.py` already uses;
  plus Review Focus 5. Keep AC-22 green: run `tests/test_value_chain_links.py` unchanged.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_value_chain_links_nace.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `company_source` returns `"nace"` when `company_nace` is not None and no stored rule
  applies. Weights: nodes of `nace_sectors(...)` in the region (all regions if None), through the existing
  `_by_output` after dropping nodes with no output. Empty → `unresolved` per spec Scope 7.
- [ ] **Step 4: Run** both test files. Expected: PASS.
- [ ] **Step 5: Regenerate the API types** (Global Constraints) and run `cd frontend && npx tsc -b`. Expected: no errors.
- [ ] **Step 6: Commit** `feat: link companies to EXIOBASE nodes through their NACE code`.

### Task 5: Indirect exposure on the NACE set

**Files:**
- Modify: `backend/arp/schemas/exposure.py:19-40` (`IndirectExposureResult`: add
  `code_scheme: Literal["nace2", "nace21", "isic4", "icio"] = "icio"`)
- Modify: `backend/arp/research/indirect_exposure/exposure.py:49` (`compute_indirect_exposure`),
  `backend/arp/research/indirect_exposure/company_mapper.py:41` (`resolve_company_isic` returns before any LLM
  call when `company_nace` is set), `backend/arp/research/pipeline.py:83`
- Test: `backend/tests/test_indirect_exposure_nace.py`

**Interfaces:**
- Consumes: `company_nace` (Task 4), `nace_sectors`, `nace_title`, `division_sectors` (Task 1).
- Produces: `compute_indirect_exposure(..., nace: tuple[str, str, str] | None = None)`; when given, the
  company's node set is its NACE set and `code_scheme`/`isic_code`/`isic_label` follow spec Scope 9.

- [ ] **Step 1: Write the failing tests** — AC-11 (stub counting LLM calls over a theme run and
  `classify_unlinked`), AC-12, AC-12b … AC-12h, AC-23 (re-run spec 2026-10-26's AC-9 to AC-17 cases and assert
  `code_scheme == "icio"`).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_indirect_exposure_nace.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `core_sector`: NACE set ∩ sectors covered by the theme's core codes ≠ ∅.
  `critical_input`: NACE set ∩ ⋃ `division_sectors(d)` for the registry's divisions ≠ ∅.
- [ ] **Step 4: Run** the new file plus `tests/test_indirect_exposure*.py` and `tests/test_value_chain*.py`. Expected: PASS.
- [ ] **Step 5: Regenerate the API types**, commit `feat: indirect exposure from the NACE set`.

### Task 6: Link panel text

**Files:**
- Modify: `frontend/src/pages/value-chain/PortfolioView.tsx:152`
- Test: the existing PortfolioView test file under `frontend/tests/` (add cases)

**Interfaces:**
- Consumes: `ValueChainLinks.source == "nace"` (Task 4); the company's `nace_code` / `isic_code`. If the links
  response lacks the code, add `code: str | None` to `ValueChainLinks` in Task 4's schema (the code the `nace`
  source used) and regenerate types.

- [ ] **Step 1: Write the failing test** — rendering a `nace` link shows `Linked by NACE 07.29` (AC-21) and,
  for an ISIC-route link, `Linked by ISIC 2710` (AC-21c); percentages `71.4%` / `28.6%` (AC-21b).
- [ ] **Step 2: Run** `cd frontend && npm test -- PortfolioView`. Expected: FAIL.
- [ ] **Step 3: Implement** the line above the nodes for `source === "nace"`.
- [ ] **Step 4: Run** `npm run lint && npx tsc -b && npm test`. Expected: PASS.
- [ ] **Step 5: Screenshot** the panel with Playwright (e2e stack per `.claude/CLAUDE.md` Checks) and run
  `/impeccable:impeccable audit`; fix what it flags in this text only.
- [ ] **Step 6: Commit** `feat: show the NACE code a link came from`.
