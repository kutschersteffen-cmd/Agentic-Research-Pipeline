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


def test_superset_export_skipped(env):
    store, pf, client = env
    store.create("alpha", "A")
    store.save_dashboard("alpha", "arp-alpha--x", "X", "superset-export", b"zip")
    (d,) = open_project(store, pf, client, "alpha").dashboards
    assert (d.status, d.id) == ("skipped", None)


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
