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
# Spec 2026-10-27-product-recipes-design.md, Acceptance (project 1): material/F.txt rows of fixture F, kt.
MATERIAL = {
    "Domestic Extraction Used - Metal Ores - Other non-ferrous metal ores (incl. PGM)": [0, 0, 0, 0],
    "Unused Domestic Extraction - Metal Ores - Copper ores": [999, 999, 999, 999],
    "Domestic Extraction Used - Metal Ores - Nickel ores": [0, 0, 0, 0],
    "Domestic Extraction Used - Metal Ores - Copper ores": [40, 0, 100, 0],
    "Domestic Extraction Used - Non-Metallic Minerals - Sand and gravel": [5, 5, 5, 5],
}
MATERIALS = [
    {"key": "metal_ores_other_non_ferrous_metal_ores_incl_pgm", "label": "Other non-ferrous metal ores (incl. PGM)", "group": "Metal Ores"},
    {"key": "metal_ores_nickel_ores", "label": "Nickel ores", "group": "Metal Ores"},
    {"key": "metal_ores_copper_ores", "label": "Copper ores", "group": "Metal Ores"},
    {"key": "non_metallic_minerals_sand_and_gravel", "label": "Sand and gravel", "group": "Non-Metallic Minerals"},
]


def _line(cells) -> str:
    return "\t".join(str(c) for c in cells) + "\n"


def _spread(values) -> list:
    """The four live values placed on all six nodes."""
    by_key = dict(zip(LIVE, values, strict=True))
    return [by_key.get(k, 0) for k in KEYS]


def write_fixture_f(directory: Path, material: dict[str, list] | None = None, z: list[list[int]] = Z) -> Path:
    """`material` adds a material/F.txt (values for the four live nodes); the explorer's F has none.
    `z` replaces the Z rows of the four live nodes (fixture F2 of the shocks spec)."""
    path = Path(directory) / "IOT_2022_ixi.zip"
    z_rows = {k: dict(zip(LIVE, row, strict=True)) for k, row in zip(LIVE, z, strict=True)}
    zt = _line(["region", "", *(r for r, _ in KEYS)]) + _line(["sector", "", *(s for _, s in KEYS)])
    zt += _line(["region", "sector", *[""] * len(KEYS)])
    zt += "".join(_line([*k, *(z_rows.get(k, {}).get(c, 0) for c in KEYS)]) for k in KEYS)
    x = dict(zip(LIVE, X, strict=True))
    xt = _line(["region", "sector", "indout"]) + "".join(_line([*k, x.get(k, 0)]) for k in KEYS)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Z.txt", zt)
        zf.writestr("x.txt", xt)
        zf.writestr("metadata.json", json.dumps({"name": "EXIO_IOT_2022_ixi", "system": "ixi", "version": "3.11.2"}))
        for folder, rows in {**SATELLITES, **({"material": material} if material else {})}.items():
            ft = _line(["region", *(r for r, _ in KEYS)]) + _line(["sector", *(s for _, s in KEYS)])
            ft += _line(["stressor", *[""] * len(KEYS)])
            ft += "".join(_line([name, *_spread(values)]) for name, values in rows.items())
            zf.writestr(f"{folder}/F.txt", ft)
    return path
