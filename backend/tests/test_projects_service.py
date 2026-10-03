import pytest

from arp.bi.plan import ChartSpec, DashboardTemplate
from arp.bi.service import NotAnARPDashboard
from arp.config import Settings
from arp.projects import service as svc
from arp.projects.dashboards import slugify_dashboard
from arp.projects.service import OpenError, export_dashboard_to_project, open_project
from arp.projects.store import ForeignProjectDashboard, ProjectStore
from arp.storage.portfolio_store import PortfolioStore
from tests.export_helpers import PW, ExportClient, make_bundle
from tests.test_bi_service import FakeClient, _spec
from tests.test_constituent_import import ROWS, _xlsx


def _tpl(pid, title):
    chart = ChartSpec(title=title, viz_type="pie", dataset="holdings", metrics=["Exposure (EUR)"], groupby=["sector"])
    return DashboardTemplate(slug=slugify_dashboard(pid, title), title=title, charts=[chart])


@pytest.fixture
def env(tmp_path):
    return ProjectStore(tmp_path / "projects"), PortfolioStore(tmp_path / "pf"), FakeClient()


def _project(store, tmp_path, pid, titles=("One", "Two")):
    store.create(pid, pid)
    store.add_data_file(pid, "Constituent_IE00TESTFUND.xlsx", _xlsx(tmp_path, ROWS).read_bytes(), {"notional_eur": 100.0})
    for t in titles:
        tpl = _tpl(pid, t)
        store.save_dashboard(pid, tpl.slug, t, "template", tpl.model_dump_json().encode())


def test_empty_project(env):
    store, pf, client = env
    store.create("empty", "Empty")
    r = open_project(store, pf, client, "empty")
    assert r.data == [] and r.dashboards == []


def test_idempotent_open(env, tmp_path):
    store, pf, client = env
    _project(store, tmp_path, "alpha")
    first = open_project(store, pf, client, "alpha")
    assert [d.status for d in first.dashboards] == ["created", "created"]
    second = open_project(store, pf, client, "alpha")
    assert [d.status for d in second.dashboards] == ["unchanged", "unchanged"]
    assert all(d.id is not None and d.published is False for d in second.dashboards)
    assert [p.portfolio_id for p in pf.list_portfolios()] == ["alpha-dws-ie00testfund"]


def test_two_projects_separate(env, tmp_path):
    store, pf, client = env
    _project(store, tmp_path, "alpha", ("One",))
    _project(store, tmp_path, "beta", ("One",))
    open_project(store, pf, client, "alpha")
    open_project(store, pf, client, "beta")
    assert {p.portfolio_id for p in pf.list_portfolios()} == {"alpha-dws-ie00testfund", "beta-dws-ie00testfund"}
    assert len(client.dashboards) == 2


def test_failure_keeps_earlier_work_and_retry_completes(env, tmp_path):
    store, pf, client = env
    _project(store, tmp_path, "alpha")
    client.fail_on_chart = 2
    with pytest.raises(OpenError) as ei:
        open_project(store, pf, client, "alpha")
    assert ei.value.step == f"dashboard:{slugify_dashboard('alpha', 'Two')}"
    assert "bad params" not in str(ei.value)
    assert list(client.dashboards) == [slugify_dashboard("alpha", "One")]
    client.fail_on_chart = None
    r = open_project(store, pf, client, "alpha")
    assert [d.status for d in r.dashboards] == ["unchanged", "created"]


def test_missing_notional_is_data_error(env, tmp_path):
    store, pf, client = env
    store.create("alpha", "A")
    store.add_data_file("alpha", "Constituent_X.xlsx", _xlsx(tmp_path, ROWS).read_bytes(), {})
    with pytest.raises(OpenError) as ei:
        open_project(store, pf, client, "alpha")
    assert ei.value.step == "data"


def _data_error(env, tmp_path, name="alpha"):
    store, pf, client = env
    with pytest.raises(OpenError) as ei:
        open_project(store, pf, client, name)
    assert ei.value.step == "data"
    return str(ei.value)


def test_junk_xlsx(env):
    store, _, _ = env
    store.create("alpha", "A")
    store.add_data_file("alpha", "Constituent_X.xlsx", b"junk", {"notional_eur": 1.0})
    msg = _data_error(env, None)
    assert msg.startswith("dws-constituents: ")


def test_unexpected_import_exception_is_not_echoed(env, tmp_path, monkeypatch):
    store, _, _ = env
    _project(store, tmp_path, "alpha", ())

    def boom(*a, **k):
        raise RuntimeError("secret /etc/passwd detail")

    monkeypatch.setattr(svc, "import_constituent_files", boom)
    msg = _data_error(env, None)
    assert msg == "dws-constituents: import failed (RuntimeError)" and "secret" not in msg


def test_missing_data_file(env, tmp_path):
    store, _, _ = env
    _project(store, tmp_path, "alpha", ())
    store.file_path("alpha", "data", "Constituent_IE00TESTFUND.xlsx").unlink()
    _data_error(env, tmp_path)


def test_non_numeric_notional(env, tmp_path):
    store, _, _ = env
    store.create("alpha", "A")
    store.add_data_file("alpha", "Constituent_X.xlsx", _xlsx(tmp_path, ROWS).read_bytes(), {"notional_eur": "abc"})
    _data_error(env, tmp_path)


def test_traversal_filename_in_manifest(env, tmp_path):
    store, _, _ = env
    _project(store, tmp_path, "alpha", ())
    m = store.root / "alpha" / "project.json"
    m.write_text(m.read_text().replace("Constituent_IE00TESTFUND.xlsx", "../../x.xlsx"))
    _data_error(env, tmp_path)


def test_published_is_read_not_changed(env, tmp_path):
    store, pf, client = env
    _project(store, tmp_path, "alpha", ("One",))
    open_project(store, pf, client, "alpha")
    client.dashboards[slugify_dashboard("alpha", "One")]["published"] = True
    (d,) = open_project(store, pf, client, "alpha").dashboards
    assert d.published is True and d.status == "unchanged"
    assert client.dashboards[slugify_dashboard("alpha", "One")]["published"] is True


def test_malformed_template_file(env, tmp_path):
    store, pf, client = env
    _project(store, tmp_path, "alpha", ("One",))
    slug = slugify_dashboard("alpha", "One")
    store.file_path("alpha", "dashboards", f"{slug}.json").write_text("{not json")
    with pytest.raises(OpenError) as ei:
        open_project(store, pf, client, "alpha")
    assert ei.value.step == f"dashboard:{slug}"


# --- hand-built dashboards as export bundles ---


@pytest.fixture
def xenv(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "get_settings", lambda: Settings(bi_reader_password=PW))
    store = ProjectStore(tmp_path / "projects")
    store.create("alpha", "A")
    client = ExportClient()
    client.dashboards["arp-hand"] = {"id": 900, "published": False, "charts": [], "position": {}, "meta": None}
    return store, PortfolioStore(tmp_path / "pf"), client


def _imports(client):
    return [c for c in client.calls if c[0] == "import_dashboard"]


def test_export_stores_zip_and_manifest(xenv):
    store, _, client = xenv
    d = export_dashboard_to_project(store, client, "alpha", 900)
    assert (d.slug, d.source, d.file) == ("arp-hand", "superset-export", "arp-hand.zip")
    assert store.file_path("alpha", "dashboards", "arp-hand.zip").read_bytes() == client.bundle
    assert store.get("alpha").dashboards == [d]


def test_export_rejects_non_arp(xenv):
    store, _, client = xenv
    client.dashboards["other"] = {"id": 5, "published": False, "charts": [], "position": {}, "meta": None}
    with pytest.raises(NotAnARPDashboard):
        export_dashboard_to_project(store, client, "alpha", 5)
    assert store.get("alpha").dashboards == []


def test_open_never_imports_over_existing(xenv):
    store, pf, client = xenv
    export_dashboard_to_project(store, client, "alpha", 900)
    r = open_project(store, pf, client, "alpha")
    assert [d.status for d in r.dashboards] == ["unchanged"] and r.dashboards[0].id == 900
    assert _imports(client) == []


def test_open_imports_when_absent_with_key_from_bundle(xenv):
    store, pf, client = xenv
    export_dashboard_to_project(store, client, "alpha", 900)
    del client.dashboards["arp-hand"]
    r = open_project(store, pf, client, "alpha")
    assert [d.status for d in r.dashboards] == ["created"] and r.dashboards[0].id == 900
    assert _imports(client) == [("import_dashboard", {"databases/x.yaml": PW})]


def test_open_import_failure_hides_password(xenv):
    store, pf, client = xenv
    export_dashboard_to_project(store, client, "alpha", 900)
    del client.dashboards["arp-hand"]
    client.fail_import = True
    with pytest.raises(OpenError) as ei:
        open_project(store, pf, client, "alpha")
    assert ei.value.step == "dashboard:arp-hand" and PW not in str(ei.value)


def test_open_without_reader_password(xenv, monkeypatch):
    store, pf, client = xenv
    export_dashboard_to_project(store, client, "alpha", 900)
    del client.dashboards["arp-hand"]
    monkeypatch.setattr(svc, "get_settings", lambda: Settings(bi_reader_password=None))
    with pytest.raises(OpenError, match="ARP_BI_READER_PASSWORD") as ei:
        open_project(store, pf, client, "alpha")
    assert ei.value.step == "dashboard:arp-hand" and _imports(client) == []


def _absent(xenv):
    store, pf, client = xenv
    export_dashboard_to_project(store, client, "alpha", 900)
    del client.dashboards["arp-hand"]
    return store, pf, client


def test_open_unpublishes_published_import(xenv):
    store, pf, client = _absent(xenv)
    client.import_published = True
    (d,) = open_project(store, pf, client, "alpha").dashboards
    assert (d.status, d.published) == ("created", False)


def test_open_unpublish_failure_is_open_error(xenv):
    store, pf, client = _absent(xenv)
    client.import_published = True
    client.fail_unpublish = True
    with pytest.raises(OpenError) as ei:
        open_project(store, pf, client, "alpha")
    assert ei.value.step == "dashboard:arp-hand"


def test_open_never_touches_published_existing(xenv):
    store, pf, client = xenv
    export_dashboard_to_project(store, client, "alpha", 900)
    client.dashboards["arp-hand"]["published"] = True
    (d,) = open_project(store, pf, client, "alpha").dashboards
    assert (d.status, d.published) == ("unchanged", True)
    assert not [c for c in client.calls if c[0] == "unpublish_dashboard"]


@pytest.mark.parametrize("pw", [None, "", "change-me-dev-only"])
def test_open_rejects_unset_or_placeholder_password(xenv, monkeypatch, pw):
    store, pf, client = _absent(xenv)
    monkeypatch.setattr(svc, "get_settings", lambda: Settings(bi_reader_password=pw))
    with pytest.raises(OpenError) as ei:
        open_project(store, pf, client, "alpha")
    assert ei.value.step == "dashboard:arp-hand" and "change-me" not in str(ei.value) and _imports(client) == []


@pytest.mark.parametrize("names", [("metadata.yaml",), ("databases/a.yaml", "databases/b.yaml"), ("databases/sub/a.yaml",)])
def test_open_rejects_bundle_without_exactly_one_database(xenv, names):
    store, pf, client = xenv
    client.bundle = make_bundle(*names)
    export_dashboard_to_project(store, client, "alpha", 900)
    del client.dashboards["arp-hand"]
    with pytest.raises(OpenError, match="exactly one"):
        open_project(store, pf, client, "alpha")
    assert _imports(client) == []


def test_open_rejects_non_zip_bundle(xenv):
    store, pf, client = xenv
    client.bundle = b"not a zip"
    export_dashboard_to_project(store, client, "alpha", 900)
    del client.dashboards["arp-hand"]
    with pytest.raises(OpenError, match="not a valid zip"):
        open_project(store, pf, client, "alpha")


def test_open_rejects_oversize_bundle(xenv, monkeypatch):
    store, pf, client = _absent(xenv)
    monkeypatch.setattr(svc, "MAX_UPLOAD_BYTES", 5)
    with pytest.raises(OpenError, match="too large"):
        open_project(store, pf, client, "alpha")


def test_export_rejects_foreign_scoped_dashboard_but_allows_hand_built(xenv):
    store, _, client = xenv
    client.dashboards["arp-beta--exposure"] = {"id": 11, "published": False, "charts": [], "position": {}, "meta": None}
    with pytest.raises(ForeignProjectDashboard):
        export_dashboard_to_project(store, client, "alpha", 11)
    client.dashboards["arp-risk-exposure"] = {"id": 13, "published": False, "charts": [], "position": {}, "meta": None}
    assert export_dashboard_to_project(store, client, "alpha", 13).slug == "arp-risk-exposure"
    assert [d.slug for d in store.get("alpha").dashboards] == ["arp-risk-exposure"]


def _save(store, client, title, plan):
    from arp.projects.dashboards import plan_to_template

    return svc.save_template_dashboard(store, client, "alpha", plan_to_template("alpha", title, plan), title)


def test_save_rebuilds_existing_dashboard_and_open_does_not(env, tmp_path):
    from arp.bi.plan import ChartPlan

    store, pf, client = env
    store.create("alpha", "A")
    a = ChartPlan(title="T", charts=[_spec("A1", groupby=["country"])])
    b = ChartPlan(title="T", charts=[_spec("B1", groupby=["country"]), _spec("B2", groupby=["sector"])])
    assert _save(store, client, "T", a).status == "created"
    r = _save(store, client, "T", b)
    assert r.status == "rebuilt" and not r.published
    slug = r.slug
    assert [c[0] for c in client.calls].count("delete_dashboard") == 1
    assert len(client.dashboards[slug]["charts"]) == 2
    assert open_project(store, pf, client, "alpha").dashboards[0].status == "unchanged"
