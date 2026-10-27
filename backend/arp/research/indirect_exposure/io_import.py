from __future__ import annotations

import csv
import io
import zipfile
from functools import cache
from pathlib import Path

# Reference data shared by `arp io build-full` and the indirect-exposure tier: the ICIO code
# list, the EXIOBASE sector crosswalk, final-demand categories and region groups.

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
FD_GROUPS = ("households", "government", "investment", "inventories")

# The five electricity split codes, after the 50 ICIO codes (spec 2026-10-26 Scope 2).
SPLIT_INDUSTRIES = (
    ("D_GEN_FOS", "Electricity generation from fossil fuels", "35", "35.11"),
    ("D_GEN_NUC", "Electricity generation from nuclear", "35", "35.11"),
    ("D_GEN_REN", "Electricity generation from renewables", "35", "35.11"),
    ("D_TD", "Electricity transmission and distribution", "35", "35.12;35.13;35.14"),
    ("D_GAS", "Gas distribution and steam supply", "35", "35.21;35.22;35.23;35.30"),
)

# EXIOBASE final-demand category -> index into FD_GROUPS; None: not final demand of any region.
EXIOBASE_FD = {
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


def _lines(zf: zipfile.ZipFile, name: str):
    with zf.open(name) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8", newline=""):
            yield line.rstrip("\n").removesuffix("\r").split("\t")


@cache
def region_groups() -> dict[str, str]:
    """Table region or country code -> group, from reference/region_groups.csv."""
    return {r["code"]: r["group"] for r in _read_reference("region_groups.csv")}


@cache
def group_order() -> tuple[str, ...]:
    return tuple(dict.fromkeys(region_groups().values()))


@cache
def country_regions() -> dict[str, str]:
    """ISO alpha-2/alpha-3 country code (upper case) -> EXIOBASE region."""
    return {r["code"].upper(): r["region"] for r in _read_reference("country_exiobase_region.csv")}
