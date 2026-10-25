"""Fixture F of the Value Chain Explorer spec: a 2-region, 3-sector EXIOBASE archive in the real file layout."""

import json
import zipfile
from pathlib import Path

REGIONS = ("DE", "CN")
SECTORS = ("Cultivation of paddy rice", "Mining of copper ores and concentrates", "Other business activities (74)")
KEYS = [(r, s) for r in REGIONS for s in SECTORS]
LIVE = [KEYS[1], KEYS[2], KEYS[4], KEYS[5]]  # DE.2, DE.3, CN.2, CN.3; paddy rice (x = 0) has no flows
X = [100, 200, 100, 100]
Z = [[10, 20, 0, 10], [10, 20, 10, 0], [0, 0, 20, 10], [0, 20, 10, 10]]
SATELLITES = {
    "air_emissions": {"CO2 - combustion - air": [500000, 0, 100000, 0], "CH4 - agriculture - air": [0, 0, 0, 1000]},
    "energy": {"Energy use - Net": [10, 0, 0, 0], "Energy use - Gross": [0, 0, 0, 0]},
    "employment": {
        "Employment people: High-skilled male": [1, 2, 0, 0],
        "Employment people: Low-skilled female": [0, 0, 0, 1],
        "Employment hours: High-skilled male": [500, 500, 500, 500],
    },
    "factor_inputs": {
        "Compensation of employees; wages, salaries, & employers' social contributions: High-skilled": [30, 100, 50, 50],
        "Taxes less subsidies on products purchased: Total": [5, 5, 5, 5],
    },
}


def _line(cells) -> str:
    return "\t".join(str(c) for c in cells) + "\n"


def _spread(values) -> list:
    """The four live values placed on all six nodes."""
    by_key = dict(zip(LIVE, values, strict=True))
    return [by_key.get(k, 0) for k in KEYS]


def write_fixture_f(directory: Path) -> Path:
    path = Path(directory) / "IOT_2022_ixi.zip"
    z_rows = {k: dict(zip(LIVE, row, strict=True)) for k, row in zip(LIVE, Z, strict=True)}
    zt = _line(["region", "", *(r for r, _ in KEYS)]) + _line(["sector", "", *(s for _, s in KEYS)])
    zt += _line(["region", "sector", *[""] * len(KEYS)])
    zt += "".join(_line([*k, *(z_rows.get(k, {}).get(c, 0) for c in KEYS)]) for k in KEYS)
    x = dict(zip(LIVE, X, strict=True))
    xt = _line(["region", "sector", "indout"]) + "".join(_line([*k, x.get(k, 0)]) for k in KEYS)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Z.txt", zt)
        zf.writestr("x.txt", xt)
        zf.writestr("metadata.json", json.dumps({"name": "EXIO_IOT_2022_ixi", "system": "ixi", "version": "3.11.2"}))
        for folder, rows in SATELLITES.items():
            ft = _line(["region", *(r for r, _ in KEYS)]) + _line(["sector", *(s for _, s in KEYS)])
            ft += _line(["stressor", *[""] * len(KEYS)])
            ft += "".join(_line([name, *_spread(values)]) for name, values in rows.items())
            zf.writestr(f"{folder}/F.txt", ft)
    return path
