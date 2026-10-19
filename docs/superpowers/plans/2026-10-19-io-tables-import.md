# IO tables import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `arp io import-icio` / `import-exiobase` / `status`, `ARP_IO_SOURCE`, ISIC-division lookup and five new optional exposure fields.

**Architecture:** One importer module turns publisher files into the existing pair (`industries.csv` + matrix/flows) plus four optional side files. The factory picks the source, builds the summed model as today and attaches the side files to `LeontiefModel`; `compute_indirect_exposure` reads them.

**Tech Stack:** Python, numpy, typer, pydantic.

**Spec:** `docs/superpowers/specs/2026-10-19-io-tables-import-design.md`

## Global Constraints

- Industry codes are ICIO 2025 codes, Appendix A order (A2 with `--split-electricity`).
- Import errors: exit 1, exactly one stderr line, no output file written.
- `upstream_exposure`/`downstream_exposure` unchanged on the bundled samples (0.11052858 / 0.01855963 for `27`, core `20`).
- Hand-prepared `industries.csv` without `isic_divisions`/`nace_classes` keeps loading.

## Review Focus

1. Re-importing into the same edition label with different numbers must not serve a stale cached Leontief inverse → cache keyed on a hash of the inputs (Task 3 test).
2. Real EXIOBASE `Z.txt` (~8k × 8k) read line by line; peak memory stays well under 1 GB (evaluator AC-32).
3. A stale `ghg.csv` from a previous EXIOBASE import into the same dir is deleted by an ICIO import (AC-121).
4. Columns identified by header, never position (reversed-column fixtures).
5. `\r\n` line endings in every EXIOBASE file.

---

### Task 1: Reference files

**Files:** Create `backend/arp/research/indirect_exposure/reference/{icio2025_industries,exiobase_ixi_to_icio2025,region_groups,ghg_gwp100}.csv`, generated once from the spec's appendices.
- [ ] Test: `tests/test_io_import.py::test_reference_files` checks row counts 50/163/23 and AC-16 codes.

### Task 2: Importers (`arp/research/indirect_exposure/io_import.py`)

**Interfaces — Produces:**
- `import_icio(csv_path: Path, out: Path, label: str | None) -> list[str]` (stdout lines)
- `import_exiobase(zip_path: Path, out: Path, label: str | None, split: bool) -> list[str]`
- both raise `ValueError(<one-line message>)`; nothing written on error.
- Region folding to Appendix C groups; final demand folded to 4 groups; GHG via Appendix D.
- [ ] Tests build fixture I and fixture E in `tmp_path` and assert AC-1..AC-3, AC-12, AC-57, AC-62, AC-69, AC-75, AC-92 and the error messages of AC-6/7/8/14/15/81/101.

### Task 3: Settings, factory, extras

- `Settings.io_source: Literal["auto", "icio", "exiobase"] = "auto"`.
- `factory.active_io_source(settings) -> tuple[str, Path, Path, str] | None` raises `ValueError("io source <s> is not configured: set ARP_… and ARP_…")`.
- `LeontiefModel` gains `isic_divisions`, `nace_classes`, `total_output`, `final_demand (n×4)`, `ghg_kg`, `regional: RegionalModel | None`, attached from files next to the industries file.
- Cache file stores a hash of (codes, matrix, total_output); mismatch rebuilds.
- [ ] Tests: AC-17..AC-21, AC-28, AC-29 via `arp io status` / factory.

### Task 4: Exposure + lookup + CLI

- `compute_indirect_exposure(..., country: str | None = None)` fills `end_market`, `theme_demand_share`, `ghg_*`, `regional` (spec calls 13, 14, 16, 17).
- `resolve_company_isic` resolves a unique `isic_divisions`/`nace_classes` hit before the LLM.
- `match_graph` passes `company.country`.
- `arp io` typer app registered in `arp/cli/__init__.py`.
- API contract regenerated (`export_openapi.py`, `gen:api`).
- [ ] Tests: AC-24..AC-27, AC-59, AC-60, AC-63, AC-64, AC-76, AC-79, AC-86, AC-110.
