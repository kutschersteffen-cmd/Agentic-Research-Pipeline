from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from arp.research.indirect_exposure.io_import import _lines, _read_reference

# Full-resolution EXIOBASE build for the Value Chain Explorer: every region x sector
# is one node. See docs/superpowers/specs/2026-10-24-value-chain-explorer-design.md.

NODE_COLUMNS = (
    "node_id", "region", "sector", "sector_no", "output_meur", "goods",
    "ghg_t_per_meur", "energy_tj_per_meur", "jobs_per_meur", "va_share",
)
TAXES_ROW = "Taxes less subsidies on products purchased: Total"


def _floats(cells: list[str], where: str) -> np.ndarray:
    try:
        return np.array(cells, dtype=float)
    except ValueError:
        pass
    try:
        return np.array([float(c) if c.strip() else 0.0 for c in cells])
    except ValueError:
        raise ValueError(f"{where}: not a number") from None


def _need(zf: zipfile.ZipFile, name: str) -> str:
    if name not in zf.namelist():
        raise ValueError(f"no {name} in the archive")
    return name


def _read_nodes(zf: zipfile.ZipFile, crosswalk: dict[str, str]) -> tuple[list[tuple[str, str]], np.ndarray]:
    lines = _lines(zf, _need(zf, "x.txt"))
    header = next(lines)
    try:
        ri, si, vi = header.index("region"), header.index("sector"), header.index("indout")
    except ValueError:
        raise ValueError("x.txt: header needs region, sector and indout") from None
    keys: list[tuple[str, str]] = []
    values: list[str] = []
    for cells in lines:
        if len(cells) <= max(ri, si, vi):
            continue
        sector = cells[si]
        if sector not in crosswalk:
            raise ValueError(f"EXIOBASE sector not in crosswalk: {sector}")
        keys.append((cells[ri], sector))
        values.append(cells[vi])
    if len(set(keys)) != len(keys):
        raise ValueError("x.txt: a region and sector appear twice")
    return keys, _floats(values, "x.txt")


def _read_z(zf: zipfile.ZipFile, index: dict[tuple[str, str], int]) -> np.ndarray:
    n = len(index)

    def where(region: str, sector: str) -> int:
        if (region, sector) not in index:
            raise ValueError(f"Z.txt: {region}, {sector} is not in x.txt")
        return index[(region, sector)]

    lines = _lines(zf, _need(zf, "Z.txt"))
    regions, sectors = next(lines), next(lines)
    next(lines)
    cols = [where(r, s) for r, s in zip(regions[2:], sectors[2:], strict=True)]
    if len(set(cols)) != n:
        raise ValueError("Z.txt: columns do not match the nodes of x.txt")
    z = np.zeros((n, n))
    seen: set[int] = set()
    for cells in lines:
        if len(cells) < 2:
            continue
        row = where(cells[0], cells[1])
        seen.add(row)
        z[row, cols] = _floats(cells[2:], f"Z.txt row {cells[0]}, {cells[1]}")
    if len(seen) != n:
        raise ValueError("Z.txt: rows do not match the nodes of x.txt")
    return z


def _satellite(zf: zipfile.ZipFile, name: str, index: dict[tuple[str, str], int], weight) -> np.ndarray:
    """Sum over the rows of one satellite F.txt of weight(row name) x row, per node."""
    lines = _lines(zf, _need(zf, name))
    regions, sectors = next(lines), next(lines)
    next(lines)
    cols = [index.get(k, -1) for k in zip(regions[1:], sectors[1:], strict=True)]
    if min(cols, default=0) < 0:
        raise ValueError(f"{name}: a column is not in x.txt")
    total = np.zeros(len(index))
    for cells in lines:
        w = weight(cells[0]) if cells else 0
        if w:
            total[cols] += w * _floats(cells[1:], f"{name} row {cells[0]}")
    return total


def _per_output(total: np.ndarray, x: np.ndarray) -> list[str]:
    return [repr(float(t / v)) if v else "" for t, v in zip(total, x, strict=True)]


def _write(tmp: Path, **arrays: np.ndarray) -> None:
    tmp.mkdir(parents=True)
    for name, array in arrays.items():
        np.save(tmp / f"{name}.npy", array)


def build_full(zip_path: Path, out: Path, label: str | None = None) -> list[str]:
    """Reads one EXIOBASE 3 ixi archive and writes manifest.json, nodes.csv and the
    A, L, G matrices to `out`. Returns the stdout lines. Raises ValueError with a
    one-line message; `out` must be missing, empty or an earlier build-full output, and
    is replaced only once the build succeeded."""
    out = Path(out)
    here = Path.cwd().resolve()
    if out.resolve() in (here, *here.parents):
        raise ValueError(f"{out} is the current directory or a parent of it")
    if out.exists() and not (out.is_dir() and (not any(out.iterdir()) or (out / "manifest.json").is_file())):
        raise ValueError(f"{out} is not empty and is not a build-full output")
    crosswalk = {r["exiobase_sector"]: r["icio_code"] for r in _read_reference("exiobase_ixi_to_icio2025.csv")}
    gwp = {r["stressor"]: float(r["factor"]) for r in _read_reference("ghg_gwp100.csv")}
    with zipfile.ZipFile(zip_path) as zf:
        try:
            meta = json.loads(zf.read(_need(zf, "metadata.json")))
            year = int(re.search(r"IOT_(\d{4})", meta["name"]).group(1))
            version = str(meta["version"])
        except (ValueError, KeyError, AttributeError, TypeError):
            raise ValueError("metadata.json: needs name EXIO_IOT_<year>_ixi and version") from None
        keys, x = _read_nodes(zf, crosswalk)
        index = {k: i for i, k in enumerate(keys)}
        z = _read_z(zf, index)
        intensities = [
            _per_output(_satellite(zf, "air_emissions/F.txt", index, lambda r: gwp.get(r, 0)) / 1000, x),
            _per_output(_satellite(zf, "energy/F.txt", index, lambda r: r == "Energy use - Net"), x),
            _per_output(_satellite(zf, "employment/F.txt", index, lambda r: 1000 * r.startswith("Employment people")), x),
            _per_output(_satellite(zf, "factor_inputs/F.txt", index, lambda r: r != TAXES_ROW), x),
        ]

    n = len(keys)
    tmp = out.parent / f".{out.name}.building"
    shutil.rmtree(tmp, ignore_errors=True)
    live = x > 0
    eye = np.arange(n)
    try:
        b = np.divide(z, x[:, None], out=np.zeros_like(z), where=live[:, None])
        z[:, ~live] = 0.0
        np.divide(z, x, out=z, where=live)  # z is now A
        _write(tmp, A=z)
        z *= -1
        z[eye, eye] += 1
        try:
            np.save(tmp / "L.npy", np.linalg.inv(z))
            del z
            b *= -1
            b[eye, eye] += 1
            np.save(tmp / "G.npy", np.linalg.inv(b))
        except np.linalg.LinAlgError:
            raise ValueError("I - A or I - B is singular: the flows cannot be inverted") from None
        del b

        sector_no: dict[str, int] = {}
        with (tmp / "nodes.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(NODE_COLUMNS)
            for i, (region, sector) in enumerate(keys):
                sector_no[region] = no = sector_no.get(region, 0) + 1
                w.writerow([
                    f"{region}.{no}", region, sector, no, repr(float(x[i])), str(crosswalk[sector][0] in "ABCDE").lower(),
                    *(col[i] for col in intensities),
                ])
        sha = hashlib.sha256()
        with Path(zip_path).open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha.update(chunk)
        n_regions, n_sectors = len(sector_no), len({s for _, s in keys})
        manifest = {
            "edition": label or f"exiobase-{Path(zip_path).stem}", "exiobase_version": version, "year": year,
            "source_sha256": sha.hexdigest(), "n_regions": n_regions, "n_sectors": n_sectors, "n_nodes": n,
            "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        old = out.parent / f".{out.name}.old"
        shutil.rmtree(old, ignore_errors=True)
        if out.exists():
            out.rename(old)
        try:
            tmp.rename(out)
        except OSError:
            if old.exists():
                old.rename(out)
            raise
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return [f"{n} nodes ({n_sectors} sectors × {n_regions} regions) -> {out}", f"ARP_VALUE_CHAIN_DIR={out}"]
