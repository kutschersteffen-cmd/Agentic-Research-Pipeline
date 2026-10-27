#!/usr/bin/env python3
"""Write the illustrative EXIOBASE-format archive behind arp/research/indirect_exposure/sample_data.

Usage (from backend/):  python scripts/make_io_sample.py <archive.zip>
Then `arp io build-full <archive.zip> --out arp/research/indirect_exposure/sample_data --label sample`
and restore the README (see that README).
"""

import json
import sys
import zipfile
from pathlib import Path

REGIONS = ("DE", "CN", "US", "WA")
SECTORS = (
    "Mining of copper ores and concentrates",
    "Copper production",
    "Production of electricity by wind",
    "Production of electricity by coal",
    "Manufacture of electrical machinery and apparatus n.e.c. (31)",
    "Manufacture of motor vehicles, trailers and semi-trailers (34)",
    "Construction (45)",
    "Retail trade, except of motor vehicles and motorcycles; repair of personal and household goods (52)",
)
MINE, CU, WIND, COAL, MACH, CAR, CONS, RETAIL = range(8)
# output per sector, M EUR, and a scale per region
BASE = [40, 120, 60, 90, 300, 500, 800, 700]
SCALE = {"DE": 1.0, "CN": 2.5, "US": 1.8, "WA": 0.6}
# input coefficients a[supplier][user]: share of the user's output bought from that supplier sector
A = {
    (MINE, CU): 0.30, (CU, MACH): 0.08, (CU, CAR): 0.02, (CU, CONS): 0.01,
    (WIND, CU): 0.03, (COAL, CU): 0.06, (WIND, MACH): 0.01, (COAL, MACH): 0.02, (WIND, CAR): 0.005, (COAL, CAR): 0.01,
    (WIND, RETAIL): 0.01, (COAL, RETAIL): 0.015, (COAL, MINE): 0.05, (WIND, MINE): 0.02,
    (MACH, MINE): 0.04, (MACH, WIND): 0.15, (MACH, COAL): 0.05, (MACH, CAR): 0.06, (MACH, CONS): 0.03,
    (CAR, RETAIL): 0.05, (CONS, WIND): 0.10, (CONS, COAL): 0.03, (RETAIL, CONS): 0.02, (RETAIL, CAR): 0.01,
}
# share of each supplier sector's input that a user region buys from CN / WA instead of at home
IMPORT = {MINE: {"WA": 0.5, "CN": 0.1}, CU: {"CN": 0.3}, MACH: {"CN": 0.2}}
CATEGORIES = (
    "Final consumption expenditure by households",
    "Final consumption expenditure by non-profit organisations serving households (NPISH)",
    "Final consumption expenditure by government",
    "Gross fixed capital formation",
    "Changes in inventories",
    "Changes in valuables",
    "Exports: Total (fob)",
)
# final demand at home as a share of output: (category index, sector, share)
DEMAND = [(0, RETAIL, 0.9), (0, CAR, 0.5), (0, WIND, 0.3), (0, COAL, 0.3), (1, RETAIL, 0.02), (2, CONS, 0.15),
          (3, CONS, 0.7), (3, MACH, 0.4), (3, CAR, 0.2), (4, CU, 0.05), (4, MINE, 0.05), (5, CU, 0.01), (6, CAR, 0.1)]
CO2_KG_PER_MEUR = {MINE: 300_000, CU: 900_000, WIND: 10_000, COAL: 6_000_000, MACH: 150_000, CAR: 120_000, CONS: 200_000, RETAIL: 50_000}

keys = [(r, s) for r in REGIONS for s in range(len(SECTORS))]
x = {k: BASE[k[1]] * SCALE[k[0]] for k in keys}
z = {}
for ur, us in keys:
    for (si, uj), a in A.items():
        if uj != us:
            continue
        need = a * x[(ur, us)]
        shares = IMPORT.get(si, {})
        home = 1 - sum(v for r, v in shares.items() if r != ur)
        for r, v in [(ur, home), *((r, v) for r, v in shares.items() if r != ur)]:
            z[((r, si), (ur, us))] = z.get(((r, si), (ur, us)), 0) + need * v



def line(cells) -> str:
    return "\t".join(str(c) for c in cells) + "\n"


names = [(r, SECTORS[s]) for r, s in keys]
out = Path(sys.argv[1])
with zipfile.ZipFile(out, "w") as zf:
    zt = line(["region", "", *(r for r, _ in names)]) + line(["sector", "", *(s for _, s in names)]) + line(["region", "sector", *[""] * len(keys)])
    zt += "".join(line([*n, *(round(z.get((k, c), 0), 6) for c in keys)]) for n, k in zip(names, keys, strict=True))
    zf.writestr("Z.txt", zt)
    zf.writestr("x.txt", line(["region", "sector", "indout"]) + "".join(line([*n, x[k]]) for n, k in zip(names, keys, strict=True)))
    cols = [(r, c) for r in REGIONS for c in CATEGORIES]
    yt = line(["region", "", *(r for r, _ in cols)]) + line(["category", "", *(c for _, c in cols)]) + line(["region", "sector", *[""] * len(cols)])

    def y(k, col):
        return sum(round(share * x[k], 6) for ci, s, share in DEMAND if s == k[1] and col == (k[0], CATEGORIES[ci]))
    yt += "".join(line([*n, *(y(k, col) for col in cols)]) for n, k in zip(names, keys, strict=True))
    zf.writestr("Y.txt", yt)
    zf.writestr("metadata.json", json.dumps({"name": "EXIO_IOT_2022_ixi", "system": "ixi", "version": "sample"}))
    head = line(["region", *(r for r, _ in names)]) + line(["sector", *(s for _, s in names)]) + line(["stressor", *[""] * len(keys)])
    zf.writestr("air_emissions/F.txt", head + line(["CO2 - combustion - air", *(CO2_KG_PER_MEUR[k[1]] * x[k] for k in keys)]))
    zf.writestr("energy/F.txt", head + line(["Energy use - Net", *(round(0.002 * x[k], 6) for k in keys)]))
    zf.writestr("employment/F.txt", head + line(["Employment people: Medium-skilled male", *(round(0.01 * x[k], 6) for k in keys)]))
    zf.writestr("factor_inputs/F.txt", head + line(["Operating surplus: Consumption of fixed capital", *(round(0.4 * x[k], 6) for k in keys)]))
