"""Fixture V of spec 2026-10-26-io-full-resolution-tier-design: a 3-region, 4-sector EXIOBASE archive with Y.txt."""

import json
import zipfile
from pathlib import Path

REGIONS = ("DE", "CN", "WA")
SECTORS = (
    "Mining of copper ores and concentrates",
    "Mining of nickel ores and concentrates",
    "Production of electricity by wind",
    "Manufacture of electrical machinery and apparatus n.e.c. (31)",
)
KEYS = [(r, s) for r in REGIONS for s in SECTORS]
NODES = [f"{r}.{i}" for r in REGIONS for i in range(1, 5)]
X = [50, 0, 100, 200, 100, 40, 80, 400, 60, 20, 10, 50]
Z = {
    ("CN.1", "CN.4"): 40, ("CN.2", "CN.4"): 20, ("WA.1", "CN.4"): 20, ("DE.1", "DE.4"): 10, ("CN.1", "DE.4"): 10,
    ("CN.3", "CN.4"): 20, ("DE.3", "DE.4"): 20, ("DE.4", "DE.3"): 30, ("CN.4", "CN.3"): 16, ("CN.4", "DE.3"): 10,
    ("CN.3", "CN.1"): 10, ("WA.4", "WA.1"): 6, ("WA.1", "WA.4"): 5, ("DE.4", "CN.4"): 20,
}
CATEGORIES = (
    "Final consumption expenditure by households",
    "Final consumption expenditure by non-profit organisations serving households (NPISH)",
    "Final consumption expenditure by government",
    "Gross fixed capital formation",
    "Changes in inventories",
    "Changes in valuables",
    "Exports: Total (fob)",
)
HH, GOV, GFCF, INV, EXP = CATEGORIES[0], CATEGORIES[2], CATEGORIES[3], CATEGORIES[4], CATEGORIES[6]
Y = {  # (demand region, category, node): value
    ("DE", GFCF, "DE.4"): 100, ("DE", HH, "DE.4"): 20, ("CN", GFCF, "CN.4"): 200, ("CN", HH, "CN.4"): 100,
    ("DE", HH, "CN.4"): 30, ("DE", HH, "DE.3"): 50, ("CN", HH, "CN.3"): 30, ("CN", GOV, "CN.3"): 4,
    ("CN", INV, "CN.1"): 10, ("WA", HH, "WA.4"): 39, ("CN", EXP, "CN.4"): 999,
}
AIR = {"CO2 - combustion - air": {"CN.1": 100000, "CN.4": 2000000, "DE.4": 400000}, "CH4 - agriculture - air": {"WA.1": 1000}}
ZERO_SATELLITES = {"energy": "Energy use - Net", "employment": "Employment people: High-skilled male",
                   "factor_inputs": "Taxes less subsidies on products purchased: Total"}


def _line(cells) -> str:
    return "\t".join(str(c) for c in cells) + "\n"


def write_fixture_v(directory: Path, *, with_y: bool = True, y_categories: dict[tuple[str, str], str] | None = None) -> Path:
    """`y_categories` renames Y.txt line-2 cells: {(region, category): new name}."""
    path = Path(directory) / "IOT_2022_ixi.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    zt = _line(["region", "", *(r for r, _ in KEYS)]) + _line(["sector", "", *(s for _, s in KEYS)])
    zt += _line(["region", "sector", *[""] * len(KEYS)])
    zt += "".join(_line([*k, *(Z.get((a, b), 0) for b in NODES)]) for k, a in zip(KEYS, NODES, strict=True))
    xt = _line(["region", "sector", "indout"]) + "".join(_line([*k, v]) for k, v in zip(KEYS, X, strict=True))
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Z.txt", zt)
        zf.writestr("x.txt", xt)
        zf.writestr("metadata.json", json.dumps({"name": "EXIO_IOT_2022_ixi", "system": "ixi", "version": "3.11.2"}))
        if with_y:
            cols = [(r, c) for r in REGIONS for c in CATEGORIES]
            names = [(y_categories or {}).get(col, col[1]) for col in cols]
            yt = _line(["region", "", *(r for r, _ in cols)]) + _line(["category", "", *names])
            yt += _line(["region", "sector", *[""] * len(cols)])
            yt += "".join(_line([*k, *(Y.get((r, c, n), 0) for r, c in cols)]) for k, n in zip(KEYS, NODES, strict=True))
            zf.writestr("Y.txt", yt)
        head = _line(["region", *(r for r, _ in KEYS)]) + _line(["sector", *(s for _, s in KEYS)])
        head += _line(["stressor", *[""] * len(KEYS)])
        zf.writestr("air_emissions/F.txt", head + "".join(_line([s, *(v.get(n, 0) for n in NODES)]) for s, v in AIR.items()))
        for folder, row in ZERO_SATELLITES.items():
            zf.writestr(f"{folder}/F.txt", head + _line([row, *[0] * len(KEYS)]))
    return path
