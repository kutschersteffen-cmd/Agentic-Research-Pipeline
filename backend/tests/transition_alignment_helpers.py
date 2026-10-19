"""Fixture barrier directory F-TA and benchmarks fixture BM, wired in through their settings."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from arp.config import get_settings
from arp.transition_alignment import benchmarks
from arp.transition_barrier import dataset

FIXTURES = Path(__file__).parent / "fixtures" / "transition_alignment"


def _reset() -> None:
    get_settings.cache_clear()
    dataset.reset_caches()
    benchmarks.reset_cache()


@pytest.fixture
def ta_dirs(tmp_path, monkeypatch):
    """F-TA and BM copied to tmp_path; yields (f_ta, bm)."""
    f_ta, bm = tmp_path / "f_ta", tmp_path / "bm"
    shutil.copytree(FIXTURES / "f_ta", f_ta)
    shutil.copytree(FIXTURES / "bm", bm)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(f_ta))
    monkeypatch.setenv("ARP_TRANSITION_ALIGNMENT_DATA_DIR", str(bm))
    _reset()
    yield f_ta, bm
    _reset()


def edit_bm(bm: Path, fn: Callable[[dict], object]) -> None:
    """Apply `fn` to the raw benchmarks file and write it back, without re-signing."""
    path = bm / benchmarks.BENCHMARKS_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    fn(raw)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
