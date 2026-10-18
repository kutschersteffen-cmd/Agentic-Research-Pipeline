from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from arp.config import get_settings
from arp.transition_barrier import dataset
from arp.transition_barrier.dataset import load_criteria, load_scores

FIXTURE_SRC = Path(__file__).parent / "fixtures" / "transition_barrier"


@pytest.fixture
def fixture_dir(tmp_path, monkeypatch):
    """Fixture data directory F, copied to tmp_path and wired in through the setting."""
    target = tmp_path / "transition_barrier"
    shutil.copytree(FIXTURE_SRC, target)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(target))
    get_settings.cache_clear()
    dataset.reset_caches()
    yield target
    get_settings.cache_clear()
    dataset.reset_caches()


def test_data_dir_setting_switches_files(fixture_dir):
    assert dataset.data_dir() == fixture_dir
    assert len(load_criteria()) == 1
    assert [s.region.value for s in load_scores()] == ["European Union", "United States", "China"]


def test_bundled_default_unchanged(monkeypatch):
    monkeypatch.delenv("ARP_TRANSITION_BARRIER_DATA_DIR", raising=False)
    get_settings.cache_clear()
    dataset.reset_caches()
    try:
        assert len(load_criteria()) == 35
        assert len(load_scores()) == 105
    finally:
        get_settings.cache_clear()
        dataset.reset_caches()
