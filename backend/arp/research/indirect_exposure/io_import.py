from __future__ import annotations

import csv
import io
import zipfile
from functools import cache
from pathlib import Path

# Reference data shared by `arp io build-full` and the indirect-exposure tier: the EXIOBASE
# sector table, final-demand categories and region groups.

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
FD_GROUPS = ("households", "government", "investment", "inventories")

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
