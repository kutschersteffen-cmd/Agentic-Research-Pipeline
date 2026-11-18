# ruff: noqa: B023, F811  (threads are joined inside each loop iteration; `client` is the imported fixture)
"""Spec decision-store-latest-lock: "latest" is the highest version on disk, and writers wait for each other."""

from __future__ import annotations

import json
import multiprocessing
import threading
from pathlib import Path

import pytest

from arp.api.deps import get_decision_store
from arp.decision import overrides
from arp.schemas.decision import LevelOverride, MechanismConfig, PublishedDecision
from arp.storage.decision_store import DecisionStore
from tests.test_decision_api import client  # noqa: F401 - the API fixture


def _cfg(**kw) -> MechanismConfig:
    return MechanismConfig(framework_id="fw1", name="n", dimensions=[], criteria=[]).model_copy(update=kw)


def _two_versions(tmp_path: Path) -> DecisionStore:
    store = DecisionStore(tmp_path)
    store.save(_cfg())
    store.new_version(_cfg(name="v2"))
    return store


def _latest(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "fw1" / "latest.json").read_text())


def _race(*fns):
    barrier = threading.Barrier(len(fns))
    out: list = [None] * len(fns)

    def run(i, fn):
        barrier.wait()
        try:
            out[i] = fn()
        except Exception as e:  # noqa: BLE001
            out[i] = e

    threads = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def _ov(entity="x", crit="y") -> LevelOverride:
    return LevelOverride(entity_key=entity, criterion_id=crit, level=3, reason="because", reviewer="Ana")


def test_ac1_ratify_older_keeps_latest(tmp_path):
    store = _two_versions(tmp_path)
    store.ratify("fw1", 1)
    assert store.get("fw1").version == 2
    assert store.get("fw1", 1).ratified is True
    assert store.get("fw1", 2).ratified is False
    assert _latest(tmp_path) == {"latest_version": 2}


def test_ac2_ratify_newest(tmp_path):
    store = _two_versions(tmp_path)
    store.ratify("fw1", 2)
    assert store.get("fw1").version == 2 and store.get("fw1").ratified is True
    assert store.latest_ratified("fw1").version == 2


def test_ac3_save_edited_v1_keeps_latest(tmp_path):
    store = _two_versions(tmp_path)
    store.save(_cfg(version=1, name="edited"))
    assert store.get("fw1").version == 2
    assert store.get("fw1", 1).name == "edited"


def test_ac4_missing_pointer_gets_none(tmp_path):
    store = _two_versions(tmp_path)
    (tmp_path / "fw1" / "latest.json").unlink()
    assert store.get("fw1") is None


def test_ac5_stale_pointer_repaired_by_ratify(tmp_path):
    store = _two_versions(tmp_path)
    (tmp_path / "fw1" / "latest.json").write_text('{"latest_version": 1}')
    store.ratify("fw1", 2)
    assert _latest(tmp_path) == {"latest_version": 2}
    assert store.get("fw1").version == 2


def test_ac6_corrupt_pointer_repaired_by_ratify(tmp_path):
    store = _two_versions(tmp_path)
    (tmp_path / "fw1" / "latest.json").write_text("not json")
    store.ratify("fw1", 2)
    assert _latest(tmp_path) == {"latest_version": 2}
    assert store.get("fw1").version == 2


def test_ac7_concurrent_new_version(tmp_path):
    for i in range(50):
        store = DecisionStore(tmp_path / str(i))
        store.save(_cfg())
        res = _race(lambda: store.new_version(_cfg()), lambda: store.new_version(_cfg()))
        assert store.list_versions("fw1") == [1, 2, 3]
        assert {r.version for r in res} == {2, 3}
        assert store.get("fw1").version == 3


def test_ac8_save_published_once(tmp_path):
    for i in range(50):
        store = DecisionStore(tmp_path / str(i))

        def pub(tag):
            return lambda: store.save_published(_published().model_copy(update={"framework_id": tag}))

        res = _race(pub("a"), pub("b"))
        errs = [r for r in res if isinstance(r, Exception)]
        oks = [r for r in res if not isinstance(r, Exception)]
        assert len(oks) == 1 and len(errs) == 1
        assert isinstance(errs[0], ValueError) and str(errs[0]) == "snap1 is already published and cannot be overwritten."
        assert store.get_published("snap1").framework_id == oks[0].framework_id


def _published() -> PublishedDecision:
    return PublishedDecision(
        snapshot_id="snap1", framework_id="fw1", framework_version=1, framework_name="n",
        dataset_id="ds", dataset_name="ds", id_column="Name", published_by="Ana",
    )


def test_ac9_concurrent_set_override(tmp_path):
    for i in range(50):
        path = tmp_path / f"{i}" / "o.json"
        _race(lambda: overrides.set_override(path, _ov("e1")), lambda: overrides.set_override(path, _ov("e2")))
        assert {o.entity_key for o in overrides.load(path)} == {"e1", "e2"}
        assert [h["action"] for h in overrides.history(path)] == ["set", "set"]


def test_ac10_remove_and_set_race(tmp_path):
    for i in range(50):
        path = tmp_path / f"{i}.json"
        overrides.set_override(path, _ov("e1", "c1"))
        _race(
            lambda: overrides.remove_override(path, "e1", "c1", "rev", "why"),
            lambda: overrides.set_override(path, _ov("e2", "c1")),
        )
        assert [(o.entity_key, o.criterion_id) for o in overrides.load(path)] == [("e2", "c1")]
        hist = overrides.history(path)
        assert len(hist) == 3 and hist[0]["action"] == "set" and hist[0]["entity_key"] == "e1"
        assert sorted((h["action"], h["entity_key"]) for h in hist[1:]) == [("removed", "e1"), ("set", "e2")]


def test_ac11_overrides_read_as_utf8(tmp_path, monkeypatch):
    path = tmp_path / "o.json"
    overrides.set_override(path, _ov().model_copy(update={"reason": "Münchener Rück"}))
    # set_override escapes non-ASCII, so rewrite the raw UTF-8 bytes a hand-edited or older file would hold.
    path.write_text(json.dumps(json.loads(path.read_text()), ensure_ascii=False), encoding="utf-8")
    real = Path.read_text

    def latin1(self, encoding=None, errors=None):
        return real(self, encoding=encoding or "latin-1", errors=errors)

    monkeypatch.setattr(Path, "read_text", latin1)
    assert overrides.load(path)[0].reason == "Münchener Rück"


def test_ac12_corrupt_pointer_get_raises(tmp_path):
    store = _two_versions(tmp_path)
    (tmp_path / "fw1" / "latest.json").write_text("not json")
    with pytest.raises(json.JSONDecodeError):
        store.get("fw1")


def test_ac13_save_into_empty_store(tmp_path):
    store = DecisionStore(tmp_path)
    store.save(_cfg())
    assert store.get("fw1").version == 1 and store.get("fw1").ratified is False


def test_ac14_ratify_without_version(tmp_path):
    store = DecisionStore(tmp_path)
    store.save(_cfg())
    c = store.ratify("fw1", ratified_by="A. Novak")
    assert (c.version, c.ratified, c.ratified_by) == (1, True, "A. Novak")
    assert store.get("fw1").version == 1


def test_ac15_new_version_after_ratify(tmp_path):
    store = DecisionStore(tmp_path)
    store.save(_cfg())
    store.ratify("fw1")
    store.new_version(_cfg())
    assert store.get("fw1").version == 2 and store.get("fw1").ratified is False
    assert store.get("fw1", 1).ratified is True


def test_ac16_ratified_not_overwritable(tmp_path):
    store = DecisionStore(tmp_path)
    store.save(_cfg())
    store.ratify("fw1")
    with pytest.raises(ValueError) as e:
        store.save(_cfg(version=1))
    assert str(e.value) == "fw1 v1 is ratified and cannot be overwritten -- create a new version instead."


def test_ac17_unknown_version(tmp_path):
    store = DecisionStore(tmp_path)
    store.save(_cfg())
    with pytest.raises(ValueError) as e:
        store.ratify("fw1", 9)
    assert str(e.value) == "Unknown framework: fw1 v9"


def test_ac18_ratify_none_uses_pointer(tmp_path):
    store = _two_versions(tmp_path)
    (tmp_path / "fw1" / "latest.json").write_text('{"latest_version": 1}')
    c = store.ratify("fw1")
    assert c.version == 1 and c.ratified is True
    assert store.get("fw1", 2).ratified is False
    assert _latest(tmp_path) == {"latest_version": 2}


def test_ac19_single_override(tmp_path):
    out = overrides.set_override(tmp_path / "o.json", _ov())
    assert len(out) == 1 and (out[0].entity_key, out[0].criterion_id) == ("x", "y")


def test_ac20_remove_missing_override(tmp_path):
    path = tmp_path / "o.json"
    overrides.set_override(path, _ov())
    before, hist = path.read_bytes(), overrides.history(path)
    with pytest.raises(KeyError) as e:
        overrides.remove_override(path, "nope", "y", "r", "why")
    assert e.value.args[0] == "No override for nope · y."
    assert path.read_bytes() == before and overrides.history(path) == hist


def test_ac21_folder_has_only_json_and_one_lock(tmp_path):
    store = _two_versions(tmp_path)
    store.ratify("fw1", 2)
    assert store.list_versions("fw1") == [1, 2]
    assert [n.name for n in (tmp_path / "fw1").iterdir() if n.name.endswith(".lock")] == [".lock"]


def _proc(args):
    path, barrier = args
    barrier.wait()
    DecisionStore(Path(path)).new_version(_cfg())


def test_ac22_two_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    for i in range(20):
        root = tmp_path / str(i)
        DecisionStore(root).save(_cfg())
        with ctx.Manager() as m:
            barrier = m.Barrier(2)
            with ctx.Pool(2) as pool:
                pool.map(_proc, [(str(root), barrier)] * 2)
        assert DecisionStore(root).list_versions("fw1") == [1, 2, 3]


def test_ac23_api_ratify_older_keeps_latest(client):
    store = client.app.dependency_overrides[get_decision_store]()
    store.save(_cfg())
    store.new_version(_cfg(name="v2"))
    r = client.post("/api/decision/mechanisms/fw1/ratify", params={"version": 1})
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["ratified"] is True
    assert client.get("/api/decision/mechanisms/fw1").json()["config"]["version"] == 2


def test_ac24_single_published(tmp_path):
    store = DecisionStore(tmp_path)
    store.save_published(_published())
    assert [s.snapshot_id for s in store.list_published()] == ["snap1"]


def test_ac25_overrides_folder_listing(tmp_path):
    store = DecisionStore(tmp_path)
    overrides.set_override(tmp_path / "_overrides" / "ds1.json", _ov())
    assert sorted(p.name for p in (tmp_path / "_overrides").glob("*.json")) == ["ds1.json"]
    assert store.list_datasets() == []


def test_ac26_ratify_vs_save(tmp_path):
    for i in range(50):
        store = DecisionStore(tmp_path / str(i))
        store.save(_cfg())
        res = _race(lambda: store.ratify("fw1", 1), lambda: store.save(_cfg(version=1, name="new")))
        assert store.get("fw1", 1).ratified is True
        if isinstance(res[1], Exception):
            assert isinstance(res[1], ValueError) and "ratified and cannot be overwritten" in str(res[1])
        else:
            assert store.get("fw1", 1).name == "new"


def test_ac27_new_version_with_stale_pointer(tmp_path):
    store = _two_versions(tmp_path)
    (tmp_path / "fw1" / "latest.json").write_text('{"latest_version": 1}')
    assert store.new_version(_cfg()).version == 3
    assert store.list_versions("fw1") == [1, 2, 3]
    assert _latest(tmp_path) == {"latest_version": 3}
