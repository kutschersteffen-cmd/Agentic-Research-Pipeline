import pytest

from arp.models import cache
from arp.models.registry import RegistryEntry

entry_nli = RegistryEntry(key="nli", capability="classify", hf_id="x/y", revision="r1")


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    class S:
        cache_dir = tmp_path
    monkeypatch.setattr(cache, "get_settings", lambda: S)


def test_second_call_hits_cache(tmp_settings):  # spec AC-12, AC-13
    calls = []

    def f(ts):
        calls.append(list(ts))
        return [len(t) for t in ts]

    a = cache.cached(entry_nli, ["x", "yy"], ("l",), f)
    b = cache.cached(entry_nli, ["x", "yy"], ("l",), f)
    assert calls == [["x", "yy"]] and a == b == [1, 2]


def test_duplicates_keep_positions(tmp_settings):  # Review Focus 2
    assert cache.cached(entry_nli, ["x", "x", "z"], None, lambda ts: [t.upper() for t in ts]) == ["X", "X", "Z"]


def test_labels_are_part_of_key(tmp_settings):
    n = []

    def f(ts):
        n.append(1)
        return [0] * len(ts)

    cache.cached(entry_nli, ["x"], ("a",), f)
    cache.cached(entry_nli, ["x"], ("b",), f)
    assert len(n) == 2
