from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

# Turns the files OECD and EXIOBASE actually ship into the files icio_loader /
# exiobase_loader read, plus the optional side files (final demand, GHG,
# region-resolved model). See docs/superpowers/specs/2026-10-19-io-tables-import-design.md.

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
FD_GROUPS = ("households", "government", "investment", "inventories")
EXTRA_FILES = ("final_demand.csv", "ghg.csv", "regional_output.csv", "regional_flows.csv")
# Table regions, not countries: never matched against a company's country.
SPECIAL_REGIONS = frozenset({"CN1", "CN2", "MX1", "MX2", "ROW", "WA", "WE", "WF", "WL", "WM"})

# Appendix A2: replaces D at its place with --split-electricity.
SPLIT_INDUSTRIES = (
    ("D_GEN_FOS", "Electricity generation from fossil fuels", "35", "35.11"),
    ("D_GEN_NUC", "Electricity generation from nuclear", "35", "35.11"),
    ("D_GEN_REN", "Electricity generation from renewables", "35", "35.11"),
    ("D_TD", "Electricity transmission and distribution", "35", "35.12;35.13;35.14"),
    ("D_GAS", "Gas distribution and steam supply", "35", "35.21;35.22;35.23;35.30"),
)

_ICIO_FD = {"HFCE": 0, "NPISH": 0, "DPABR": 0, "GGFC": 1, "GFCF": 2, "INVNT": 3}
_EXIOBASE_FD = {
    "Final consumption expenditure by households": 0,
    "Final consumption expenditure by non-profit organisations serving households (NPISH)": 0,
    "Final consumption expenditure by government": 1,
    "Gross fixed capital formation": 2,
    "Changes in inventories": 3,
    "Changes in valuables": 3,
    "Exports: Total (fob)": None,
}


def _read_reference(name: str) -> list[dict[str, str]]:
    with (REFERENCE_DIR / name).open(newline="") as f:
        return list(csv.DictReader(f))


def industry_list(split: bool = False) -> list[tuple[str, str, str, str]]:
    """(code, label, isic_divisions, nace_classes) in Appendix A (or A2) order."""
    rows: list[tuple[str, str, str, str]] = []
    for r in _read_reference("icio2025_industries.csv"):
        if split and r["code"] == "D":
            rows.extend(SPLIT_INDUSTRIES)
        else:
            rows.append((r["code"], r["label"], r["isic_divisions"], ""))
    return rows


@cache
def region_groups() -> dict[str, str]:
    """Table region or country code -> group, from reference/region_groups.csv."""
    return {r["code"]: r["group"] for r in _read_reference("region_groups.csv")}


@cache
def group_order() -> tuple[str, ...]:
    return tuple(dict.fromkeys(region_groups().values()))


def _group_index(region: str) -> int:
    group = region_groups().get(region)
    if group is None:
        raise ValueError(f"region not in region groups: {region}")
    return group_order().index(group)


@dataclass
class _Tables:
    """Everything an import produces, in region-group x industry space
    (index = group * n + industry), before anything is written."""

    industries: list[tuple[str, str, str, str]]
    z: np.ndarray  # (G*n, G*n)
    x: np.ndarray  # (G*n,)
    groups_present: set[int]
    final_demand: np.ndarray | None  # (n, 4)
    ghg_kg: np.ndarray | None  # (n,)


def _fmt(v: float) -> str:
    return repr(float(v))


def _write(tables: _Tables, out: Path, *, exiobase: bool) -> None:
    inds = tables.industries
    codes = [c for c, *_ in inds]
    n, g_all = len(codes), len(group_order())
    z_blocks = tables.z.reshape(g_all, n, g_all, n)
    z = z_blocks.sum(axis=(0, 2))
    x = tables.x.reshape(g_all, n).sum(axis=0)
    groups = [g for g in range(g_all) if g in tables.groups_present]
    names = group_order()

    out.mkdir(parents=True, exist_ok=True)
    written: set[str] = set()

    def open_csv(name: str):
        written.add(name)
        return (out / name).open("w", newline="")

    with open_csv("industries.csv") as f:
        w = csv.writer(f)
        w.writerow(["isic_code", "label", "total_output", "isic_divisions", "nace_classes"])
        for (code, label, divs, nace), total in zip(inds, x, strict=True):
            w.writerow([code, label, _fmt(total), divs, nace])
    if exiobase:
        with open_csv("exiobase_flows.csv") as f:
            w = csv.writer(f)
            w.writerow(["supplier_isic_code", "user_isic_code", "value"])
            for i, j in zip(*np.nonzero(z), strict=True):
                w.writerow([codes[i], codes[j], _fmt(z[i, j])])
    else:
        with open_csv("icio_matrix.csv") as f:
            w = csv.writer(f)
            w.writerow(["isic_code", *codes])
            for i, code in enumerate(codes):
                w.writerow([code, *(_fmt(v) for v in z[i])])
    if tables.final_demand is not None:
        with open_csv("final_demand.csv") as f:
            w = csv.writer(f)
            w.writerow(["isic_code", *FD_GROUPS])
            for code, row in zip(codes, tables.final_demand, strict=True):
                w.writerow([code, *(_fmt(v) for v in row)])
    if tables.ghg_kg is not None:
        with open_csv("ghg.csv") as f:
            w = csv.writer(f)
            w.writerow(["isic_code", "kg_co2e"])
            for code, kg in zip(codes, tables.ghg_kg, strict=True):
                w.writerow([code, _fmt(kg)])
    with open_csv("regional_output.csv") as f:
        w = csv.writer(f)
        w.writerow(["region", "isic_code", "total_output"])
        for g in groups:
            for i, code in enumerate(codes):
                w.writerow([names[g], code, _fmt(tables.x[g * n + i])])
    with open_csv("regional_flows.csv") as f:
        w = csv.writer(f)
        w.writerow(["supplier_region", "supplier_isic_code", "user_region", "user_isic_code", "value"])
        for gs, i, gu, j in zip(*np.nonzero(z_blocks), strict=True):
            w.writerow([names[gs], codes[i], names[gu], codes[j], _fmt(z_blocks[gs, i, gu, j])])

    for name in EXTRA_FILES:
        if name not in written:
            (out / name).unlink(missing_ok=True)


def _env_lines(source: str, out: Path, matrix_file: str, matrix_var: str, label: str) -> list[str]:
    prefix = source.upper()
    return [
        f"ARP_IO_SOURCE={source}",
        f"ARP_{prefix}_{matrix_var}={out / matrix_file}",
        f"ARP_{prefix}_INDUSTRIES_PATH={out / 'industries.csv'}",
        f"ARP_{prefix}_EDITION_LABEL={label}",
    ]


# --- OECD ICIO -----------------------------------------------------------------


def import_icio(csv_path: Path, out: Path, label: str | None = None) -> list[str]:
    """Reads one ICIO 2025 year file (spec call 4) and writes the output
    directory. Returns the stdout lines. Raises ValueError with a one-line
    message; nothing is written on error."""
    inds = industry_list()
    code_index = {c: i for i, (c, *_) in enumerate(inds)}
    n, g_all = len(inds), len(group_order())
    z = np.zeros((g_all * n, g_all * n))
    x = np.zeros(g_all * n)
    fd = np.zeros((n, len(FD_GROUPS)))
    groups_present: set[int] = set()
    row_regions: set[str] = set()
    row_codes: set[str] = set()
    col_codes: set[str] = set()

    with csv_path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        ind_cols: list[int] = []
        ind_targets: list[int] = []
        fd_cols: list[int] = []
        fd_targets: list[int] = []
        out_col: int | None = None
        for c, col_label in enumerate(header[1:], start=1):
            region, _, rest = col_label.partition("_")
            if rest in code_index:
                g = _group_index(region)
                groups_present.add(g)
                col_codes.add(rest)
                ind_cols.append(c)
                ind_targets.append(g * n + code_index[rest])
            elif rest in _ICIO_FD:
                _group_index(region)
                fd_cols.append(c)
                fd_targets.append(_ICIO_FD[rest])
            elif col_label == "OUT":
                out_col = c
        if out_col is None:
            raise ValueError(f"{csv_path.name}: no OUT column")
        ind_targets_arr = np.array(ind_targets, dtype=np.intp)
        fd_targets_arr = np.array(fd_targets, dtype=np.intp)

        def numbers(row: list[str], cols: list[int]) -> np.ndarray:
            values = np.zeros(len(cols))
            for k, c in enumerate(cols):
                cell = row[c] if c < len(row) else ""
                if cell.strip():
                    try:
                        values[k] = float(cell)
                    except ValueError:
                        raise ValueError(f"row {row[0]}, column {header[c]}: not a number: {cell!r}") from None
            return values

        for row in reader:
            if not row:
                continue
            region, _, rest = row[0].partition("_")
            if rest not in code_index:
                continue
            g = _group_index(region)
            groups_present.add(g)
            row_regions.add(region)
            row_codes.add(rest)
            target = g * n + code_index[rest]
            z[target] += np.bincount(ind_targets_arr, weights=numbers(row, ind_cols), minlength=g_all * n)
            fd[code_index[rest]] += np.bincount(fd_targets_arr, weights=numbers(row, fd_cols), minlength=len(FD_GROUPS))
            x[target] += numbers(row, [out_col])[0]

    missing = [c for c, *_ in inds if c not in row_codes or c not in col_codes]
    if missing:
        raise ValueError(f"missing ICIO industries: {', '.join(missing)}")

    out = Path(out).resolve()
    _write(_Tables(inds, z, x, groups_present, fd, None), out, exiobase=False)
    return [
        f"{n} industries, {len(row_regions)} regions -> {out}",
        *_env_lines("icio", out, "icio_matrix.csv", "MATRIX_PATH", label or f"icio-{csv_path.stem}"),
    ]


# --- EXIOBASE 3 ixi ------------------------------------------------------------


def _lines(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8", newline=""):
            yield line.rstrip("\n").removesuffix("\r").split("\t")


def import_exiobase(zip_path: Path, out: Path, label: str | None = None, split: bool = False) -> list[str]:
    """Reads one EXIOBASE 3 ixi archive (spec call 6) and writes the output
    directory. Returns the stdout lines. Raises ValueError with a one-line
    message; nothing is written on error. Z.txt is streamed one line at a
    time so the real ~8000x8000 table fits in well under 1 GB."""
    inds = industry_list(split)
    code_index = {c: i for i, (c, *_) in enumerate(inds)}
    sector_code = {
        r["exiobase_sector"]: code_index[r["split_code" if split else "icio_code"]]
        for r in _read_reference("exiobase_ixi_to_icio2025.csv")
    }
    n, g_all = len(inds), len(group_order())

    def code_of(sector: str) -> int:
        if sector not in sector_code:
            raise ValueError(f"EXIOBASE sector not in crosswalk: {sector}")
        return sector_code[sector]

    def target(region: str, sector: str) -> int:
        return _group_index(region) * n + code_of(sector)

    def number_row(cells: list[str], where: str) -> np.ndarray:
        try:
            return np.array(cells, dtype=float)
        except ValueError:
            pass
        try:
            return np.array([float(c) if c.strip() else 0.0 for c in cells])
        except ValueError:
            raise ValueError(f"{where}: not a number") from None

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for required in ("Z.txt", "x.txt"):
            if required not in names:
                raise ValueError(f"no {required} at the archive root")

        z = np.zeros((g_all * n, g_all * n))
        lines = _lines(zf, "Z.txt")
        regions_line, sectors_line = next(lines), next(lines)
        next(lines)
        col_targets = np.array([target(r, s) for r, s in zip(regions_line[2:], sectors_line[2:], strict=True)], dtype=np.intp)
        groups_present = {int(t) // n for t in col_targets}
        row_regions: set[str] = set()
        row_sectors: set[str] = set()
        for cells in lines:
            if len(cells) < 2:
                continue
            region, sector = cells[0], cells[1]
            t = target(region, sector)
            groups_present.add(t // n)
            row_regions.add(region)
            row_sectors.add(sector)
            z[t] += np.bincount(col_targets, weights=number_row(cells[2:], f"Z.txt row {region}, {sector}"), minlength=g_all * n)

        x = np.zeros(g_all * n)
        lines = _lines(zf, "x.txt")
        header = next(lines)
        try:
            ri, si, vi = header.index("region"), header.index("sector"), header.index("indout")
        except ValueError:
            raise ValueError("x.txt: header needs region, sector and indout") from None
        for cells in lines:
            if len(cells) > vi:
                x[target(cells[ri], cells[si])] += number_row([cells[vi]], f"x.txt row {cells[ri]}, {cells[si]}")[0]

        fd = None
        if "Y.txt" in names:
            fd = np.zeros((n, len(FD_GROUPS)))
            lines = _lines(zf, "Y.txt")
            regions_line, categories = next(lines), next(lines)
            next(lines)
            for region in regions_line[2:]:
                _group_index(region)
            groups = []
            for category in categories[2:]:
                if category not in _EXIOBASE_FD:
                    raise ValueError(f"unknown final-demand category: {category}")
                groups.append(_EXIOBASE_FD[category])
            keep = np.array([g is not None for g in groups])
            fd_targets = np.array([g or 0 for g in groups], dtype=np.intp)
            for cells in lines:
                if len(cells) < 2:
                    continue
                values = number_row(cells[2:], f"Y.txt row {cells[0]}, {cells[1]}")
                fd[target(cells[0], cells[1]) % n] += np.bincount(fd_targets, weights=values * keep, minlength=len(FD_GROUPS))

        ghg = None
        if "air_emissions/F.txt" in names:
            factors = {r["stressor"]: float(r["factor"]) for r in _read_reference("ghg_gwp100.csv")}
            ghg = np.zeros(n)
            lines = _lines(zf, "air_emissions/F.txt")
            regions_line, sectors_line = next(lines), next(lines)
            f_targets = np.array([target(r, s) % n for r, s in zip(regions_line[1:], sectors_line[1:], strict=True)], dtype=np.intp)
            for cells in lines:
                if cells[0] in factors:
                    values = number_row(cells[1:], f"air_emissions/F.txt row {cells[0]}")
                    ghg += factors[cells[0]] * np.bincount(f_targets, weights=values, minlength=n)

    out = Path(out).resolve()
    _write(_Tables(inds, z, x, groups_present, fd, ghg), out, exiobase=True)
    return [
        f"{len(row_sectors)} sectors -> {n} industries, {len(row_regions)} regions -> {out}",
        *_env_lines("exiobase", out, "exiobase_flows.csv", "FLOWS_PATH", label or f"exiobase-{zip_path.stem}"),
    ]


def company_region_group(country: str | None) -> str | None:
    """Region group of a company's ISO alpha-2/alpha-3 country, case-insensitive;
    None for a missing or unknown code or a table-only region (WA, ROW, ...)."""
    code = (country or "").upper()
    if code in SPECIAL_REGIONS:
        return None
    return region_groups().get(code)
