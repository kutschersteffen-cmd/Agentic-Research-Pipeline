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


@pytest.mark.parametrize("bad", ["Foo", "a/b", "..", "-x", "a" * 64, "", "a.b", "a\n"])
def test_bad_ids(store, bad):
    with pytest.raises(ProjectError):
        store.create(bad, "x")


def test_id_max_length_ok(store):
    store.create("a" * 63, "x")


@pytest.mark.parametrize("name", ["../x.xlsx", "a.xlsm", "a/b.xlsx", "", "a\0.xlsx"])
def test_bad_upload_names(store, tmp_path, name):
    store.create("p", "P")
    with pytest.raises(ProjectError):
        store.add_data_file("p", name, b"x", {})
    assert not any((tmp_path / "p").rglob("*.xlsx"))
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
    store.save_dashboard("p", "arp-d1", "One", "template", b"{}")
    p = store.save_dashboard("p", "arp-d1", "Uno", "superset-export", b"[]")
    assert len(p.dashboards) == 1
    assert p.dashboards[0].title == "Uno" and p.dashboards[0].source == "superset-export"
    assert store.file_path("p", "dashboards", p.dashboards[0].file).read_bytes() == b"[]"


def test_file_path_rejects_traversal(store):
    store.create("p", "P")
    with pytest.raises(ProjectError):
        store.file_path("p", "data", "../project.json")
    with pytest.raises(ProjectError):
        store.file_path("p", "other", "a")


def test_lock_mutual_exclusion(store):
    import threading
    import time

    store.create("p", "P")
    inside, bad = [], []

    def worker():
        with store.lock("p"):
            inside.append(1)
            if len(inside) > 1:
                bad.append(1)
            time.sleep(0.02)
            inside.pop()

    ts = [threading.Thread(target=worker) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not bad


def test_parallel_uploads(store):
    from concurrent.futures import ThreadPoolExecutor

    store.create("p", "P")
    n = 12
    with ThreadPoolExecutor(n) as ex:
        list(ex.map(lambda i: store.add_data_file("p", f"f{i}.xlsx", b"x", {f"k{i}": i}), range(n)))
    p = store.get("p")
    assert sorted(p.data[0].files) == sorted(f"f{i}.xlsx" for i in range(n))
    assert len(p.data[0].params) == n
    assert all(store.file_path("p", "data", f).exists() for f in p.data[0].files)


def test_zip_dashboard_no_stale_json(store):
    store.create("p", "P")
    store.save_dashboard("p", "arp-d", "D", "template", b"{}")
    p = store.save_dashboard("p", "arp-d", "D", "superset-export", b"PK")
    assert p.dashboards[0].file == "arp-d.zip"
    assert store.file_path("p", "dashboards", "arp-d.zip").read_bytes() == b"PK"
    assert not store.file_path("p", "dashboards", "arp-d.json").exists()


def test_missing_project_leaves_no_dir(store, tmp_path):
    with pytest.raises(ProjectNotFound):
        store.add_data_file("ghost", "a.xlsx", b"x", {})
    with pytest.raises(ProjectNotFound):
        store.save_dashboard("ghost", "arp-d", "D", "template", b"{}")
    with pytest.raises(ProjectNotFound), store.lock("ghost"):
        pass
    assert not (tmp_path / "ghost").exists()


def test_dashboard_slug_rules(store):
    store.create("p", "P")
    store.save_dashboard("p", "arp-" + "a" * 119, "D", "template", b"{}")
    for bad in ("d", "arp-", "arp-" + "a" * 120, "arp-../x", "arp-A", "arp-a/b"):
        with pytest.raises(ProjectError):
            store.save_dashboard("p", bad, "D", "template", b"{}")
    with pytest.raises(ProjectError):
        store.file_path("p", "dashboards", "x.json")
