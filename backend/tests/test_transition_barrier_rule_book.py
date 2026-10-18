from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from arp.config import get_settings
from arp.transition_barrier import dataset
from arp.transition_barrier.dataset import load_criteria, load_scores
from arp.transition_barrier.rule_book import (
    RuleBookNotFound,
    compute_fingerprint,
    load_rule_book,
    sign_rule_book,
)

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


def _raw(data_dir):
    return json.loads((data_dir / "rule_book.json").read_text(encoding="utf-8"))


def test_ac91_sign(fixture_dir):
    assert sign_rule_book(fixture_dir, "owner", date(2026, 10, 18)) == 8
    raw = _raw(fixture_dir)
    assert raw["version"] == 8
    assert raw["fingerprint"] == compute_fingerprint(raw)
    assert raw["history"][-1] == {
        "version": 8,
        "fingerprint": raw["fingerprint"],
        "approved_by": "owner",
        "approved_at": "2026-10-18",
    }


def test_fixture_rule_book_is_signed_and_loads(fixture_dir):
    rule_book, raw = load_rule_book(fixture_dir)
    assert rule_book.version == 7
    assert raw["fingerprint"] == compute_fingerprint(raw)
    assert raw["history"][-1]["version"] == 7
    assert [f.id for f in rule_book.criteria["STL-R1"].facts] == ["price", "applies", "levy"]


def test_fingerprint_ignores_formatting(fixture_dir):
    raw = _raw(fixture_dir)
    raw["criteria"]["STL-R1"]["rationale"] += " Cost gap × volume."
    (fixture_dir / "rule_book.json").write_text(json.dumps(raw), encoding="utf-8")
    sign_rule_book(fixture_dir, "owner", date(2026, 10, 18))
    signed = _raw(fixture_dir)
    reordered = {k: signed[k] for k in reversed(list(signed))}
    text = json.dumps(reordered, indent=4, ensure_ascii=True)
    assert compute_fingerprint(json.loads(text)) == signed["fingerprint"]


def test_missing_rule_book(tmp_path):
    with pytest.raises(RuleBookNotFound, match=r"^Rule book not found: "):
        load_rule_book(tmp_path)
