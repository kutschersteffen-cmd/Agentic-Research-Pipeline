import pytest

from arp.projects.store import MAX_UPLOAD_BYTES, ProjectError, ProjectNotFound, ProjectStore


@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path)


def test_create_get_list_round_trip(store):
    p = store.create("alpha", "Alpha", "desc")
    assert store.get("alpha") == p
    assert p.description == "desc" and p.data == [] and p.dashboards == []
    store.create("beta", "Beta")
    assert sorted(x.id for x in store.list()) == ["alpha", "beta"]


def test_get_missing(store):
    with pytest.raises(ProjectNotFound):
        store.get("nope")
    with pytest.raises(ProjectNotFound):
        store.get("../x")


def test_duplicate_id(store):
    store.create("alpha", "A")
    with pytest.raises(ProjectError):
        store.create("alpha", "A2")


@pytest.mark.parametrize("bad", ["Foo", "a/b", "..", "-x", "a" * 64, "", "a.b"])
def test_bad_ids(store, bad):
    with pytest.raises(ProjectError):
        store.create(bad, "x")


def test_id_max_length_ok(store):
    store.create("a" * 63, "x")


@pytest.mark.parametrize("name", ["../x.xlsx", "a.xlsm", "a/b.xlsx", ""])
def test_bad_upload_names(store, tmp_path, name):
    store.create("p", "P")
    with pytest.raises(ProjectError):
        store.add_data_file("p", name, b"x", {})
    assert not list((tmp_path / "p" / "data").glob("*")) if (tmp_path / "p" / "data").exists() else True
    assert store.get("p").data == []


def test_oversize_leaves_no_file(store, tmp_path):
    store.create("p", "P")
    with pytest.raises(ProjectError):
        store.add_data_file("p", "a.xlsx", b"0" * (MAX_UPLOAD_BYTES + 1), {})
    assert not any((tmp_path / "p").rglob("*.xlsx"))
    assert store.get("p").data == []


def test_add_data_file_appends_and_merges(store):
    store.create("p", "P")
    store.add_data_file("p", "A.XLSX", b"1", {"a": 1})
    p = store.add_data_file("p", "b.xlsx", b"2", {"b": 2})
    assert len(p.data) == 1
    assert p.data[0].kind == "dws-constituents"
    assert p.data[0].files == ["A.XLSX", "b.xlsx"]
    assert p.data[0].params == {"a": 1, "b": 2}
    assert store.file_path("p", "data", "b.xlsx").read_bytes() == b"2"


def test_save_dashboard_replaces_slug(store):
    store.create("p", "P")
    store.save_dashboard("p", "d1", "One", "template", b"{}")
    p = store.save_dashboard("p", "d1", "Uno", "superset-export", b"[]")
    assert len(p.dashboards) == 1
    assert p.dashboards[0].title == "Uno" and p.dashboards[0].source == "superset-export"
    assert store.file_path("p", "dashboards", p.dashboards[0].file).read_bytes() == b"[]"


def test_file_path_rejects_traversal(store):
    store.create("p", "P")
    with pytest.raises(ProjectError):
        store.file_path("p", "data", "../project.json")
    with pytest.raises(ProjectError):
        store.file_path("p", "other", "a")


def test_lock_context(store):
    store.create("p", "P")
    with store.lock("p"):
        pass
