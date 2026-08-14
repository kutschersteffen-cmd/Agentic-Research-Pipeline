from arp.llm.cache import DiskLLMCache


def test_cache_roundtrip(tmp_path):
    cache = DiskLLMCache(tmp_path, enabled=True)
    key = cache.make_key(model="m", system="s", prompt="p", schema_name="S", schema_json={"a": 1})
    assert cache.get(key) is None
    cache.set(key, {"result": {"x": 1}, "usage": {"input_tokens": 5, "output_tokens": 5}})
    assert cache.get(key) == {"result": {"x": 1}, "usage": {"input_tokens": 5, "output_tokens": 5}}


def test_cache_key_changes_with_any_input(tmp_path):
    cache = DiskLLMCache(tmp_path)
    k1 = cache.make_key(model="m", system="s", prompt="p", schema_name="S", schema_json={"a": 1})
    k2 = cache.make_key(model="m", system="s", prompt="different", schema_name="S", schema_json={"a": 1})
    assert k1 != k2


def test_cache_key_changes_with_temperature(tmp_path):
    cache = DiskLLMCache(tmp_path)
    k1 = cache.make_key(model="m", system="s", prompt="p", schema_name="S", schema_json={"a": 1}, temperature=0.0)
    k2 = cache.make_key(model="m", system="s", prompt="p", schema_name="S", schema_json={"a": 1}, temperature=0.5)
    assert k1 != k2


def test_disabled_cache_never_persists(tmp_path):
    cache = DiskLLMCache(tmp_path, enabled=False)
    key = cache.make_key(model="m", system="s", prompt="p", schema_name="S", schema_json={})
    cache.set(key, {"result": {}, "usage": {}})
    assert cache.get(key) is None
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []
