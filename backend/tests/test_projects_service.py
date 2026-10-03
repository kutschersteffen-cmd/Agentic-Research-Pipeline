import pytest

from arp.bi.plan import ChartSpec, DashboardTemplate
from arp.projects.dashboards import slugify_dashboard
from arp.projects.service import OpenError, open_project
from arp.projects.store import ProjectStore
from arp.storage.portfolio_store import PortfolioStore
from tests.test_bi_service import FakeClient
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


def test_junk_xlsx(env):
    store, _, _ = env
    store.create("alpha", "A")
    store.add_data_file("alpha", "Constituent_X.xlsx", b"junk", {"notional_eur": 1.0})
    _data_error(env, None)


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
import io  # noqa: E402
import zipfile  # noqa: E402

from arp.bi.service import NotAnARPDashboard  # noqa: E402
from arp.bi.superset_client import SupersetError  # noqa: E402
from arp.config import Settings  # noqa: E402
from arp.projects import service as svc  # noqa: E402
from arp.projects.service import export_dashboard_to_project  # noqa: E402

PW = "s3cret-reader-pw"


def _bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dashboard_export_1/metadata.yaml", "x")
        z.writestr("dashboard_export_1/databases/x.yaml", "x")
    return buf.getvalue()


class ExportClient(FakeClient):
    fail_import = False

    def export_dashboard(self, dashboard_id):
        self.calls.append(("export_dashboard", dashboard_id))
        return _bundle()

    def import_dashboard(self, bundle, db_passwords):
        self.calls.append(("import_dashboard", db_passwords))
        if self.fail_import:
            raise SupersetError(500, f"body with {PW}")
        self.dashboards["arp-hand"] = {"id": 900, "published": False, "charts": [], "position": {}, "meta": None}


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
    assert store.file_path("alpha", "dashboards", "arp-hand.zip").read_bytes() == _bundle()
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
