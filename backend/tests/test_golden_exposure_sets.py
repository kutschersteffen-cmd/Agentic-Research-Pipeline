from __future__ import annotations

import re
from pathlib import Path

import pytest

from arp.golden_set.exposure import load_set, stats_lines, validate_set

ROOT = Path(__file__).parent / "golden" / "exposure"
READY = ["electrolyser_makers", "ai_datacentre_operators"]
PENDING = ["water_scarcity_exposed"]  # owner-checked labels still to come
SETS = [*READY, *(pytest.param(s, marks=pytest.mark.xfail(strict=True, reason="set not built yet")) for s in PENDING)]


@pytest.mark.parametrize("set_id", SETS)
def test_set_validates(set_id):  # AC-17
    assert validate_set(ROOT / set_id) == []


@pytest.mark.parametrize("set_id", SETS)
def test_set_size(set_id):  # AC-18
    counts = [int(n) for line in stats_lines(load_set(ROOT / set_id)) for n in re.findall(r"=(\d+)", line)]
    assert sum(counts) >= 55


@pytest.mark.parametrize("set_id", SETS)
def test_holdout_per_label(set_id):  # AC-19
    lines = stats_lines(load_set(ROOT / set_id))
    assert lines and all(int(re.search(r"holdout=(\d+)", line).group(1)) >= 8 for line in lines)


def test_readme_steps():  # AC-20
    text = (ROOT / "README.md").read_text()
    for step in ("1. A research pass proposes label", "2. A person checks every label", "3. Hard cases are kept on purpose"):
        assert step in text
