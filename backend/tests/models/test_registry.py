import json

import pytest

from arp.models import registry


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    reg, allowed = tmp_path / "registry.json", tmp_path / "allowed.txt"
    allowed.write_text("")
    monkeypatch.setattr(registry, "REGISTRY_PATH", reg)
    monkeypatch.setattr(registry, "ALLOWED_PATH", allowed)

    class W:
        def write(self, *rows):
            reg.write_text(json.dumps(list(rows)))

    return W()


def test_unknown_key_raises_keyerror():  # AC-7
    with pytest.raises(KeyError, match="not_in_registry"):
        registry.entry("not_in_registry")


def test_hf_id_not_allowed_raises(tmp_registry):  # AC-8
    tmp_registry.write({"key": "nli", "capability": "classify", "hf_id": "evil/model", "revision": "abc"})
    with pytest.raises(ValueError, match="evil/model"):
        registry.entry("nli")


def test_provenance_shape():
    e = registry.entry("nli")
    assert registry.provenance(e, "local") == {"model": "nli", "revision": e.revision, "where": "local"}
    assert registry.model_header(e) == f"{e.hf_id}@{e.revision}"


def test_all_registry_entries_allowed():
    for d in json.loads(registry.REGISTRY_PATH.read_text()):
        registry.entry(d["key"])
