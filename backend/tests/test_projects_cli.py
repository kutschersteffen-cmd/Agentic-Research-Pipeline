"""`arp project ...`, offline: tmp projects dir, fakes in place of Postgres and Superset."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.cli import project as cli
from arp.config import get_settings
from arp.projects.service import OpenedDashboard, OpenError, OpenResult

runner = CliRunner()


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _xlsx(tmp_path, name="Constituent_X.xlsx"):
    f = tmp_path / name
    f.write_bytes(b"PK-fake")
    return f


def _create(id="demo"):
    return runner.invoke(app, ["project", "create", id, "--name", "Demo"])


def test_create_then_list(projects_dir):
    r = _create()
    assert r.exit_code == 0 and json.loads(r.output)["id"] == "demo"
    assert runner.invoke(app, ["project", "list"]).output == "demo\tDemo\t0\t0\n"


def test_add_data_copies_file_and_updates_counts(projects_dir):
    _create()
    f = _xlsx(projects_dir)
    r = runner.invoke(app, ["project", "add-data", "demo", str(f), "--notional-eur", "1000"])
    assert r.exit_code == 0 and json.loads(r.output)["data_files"] == 1
    assert (projects_dir / "projects" / "demo" / "data" / f.name).read_bytes() == b"PK-fake"
    assert runner.invoke(app, ["project", "list"]).output == "demo\tDemo\t1\t0\n"


def test_bad_id_exits_without_traceback(projects_dir):
    r = _create("Bad Id!")
    assert r.exit_code == 1 and "Traceback" not in r.output and isinstance(r.exception, SystemExit)


@pytest.mark.parametrize("notional", ["0", "-5", "nan", "inf"])
def test_non_positive_notional_rejected(projects_dir, notional):
    _create()
    r = runner.invoke(app, ["project", "add-data", "demo", str(_xlsx(projects_dir)), "--notional-eur", notional])
    assert r.exit_code == 1 and "notional-eur" in r.output


def test_non_xlsx_rejected(projects_dir):
    _create()
    f = projects_dir / "a.csv"
    f.write_text("x")
    r = runner.invoke(app, ["project", "add-data", "demo", str(f), "--notional-eur", "10"])
    assert r.exit_code == 1 and "xlsx" in r.output


def _configure(monkeypatch):
    monkeypatch.setenv("ARP_PORTFOLIO_BACKEND", "postgres")
    monkeypatch.setenv("ARP_POSTGRES_DSN", "postgresql+psycopg://u:p@localhost:5432/arp")
    monkeypatch.setenv("ARP_SUPERSET_PASSWORD", "x" * 20)
    get_settings.cache_clear()


def test_open_prints_json(projects_dir, monkeypatch):
    _create()
    _configure(monkeypatch)
    dash = OpenedDashboard(id=7, slug="s", title="T", published=True, status="created")
    seen = {}

    def fake_open(store, pstore, client, pid):
        seen["pid"] = pid
        return OpenResult(data=[], dashboards=[dash])

    monkeypatch.setattr(cli, "_portfolio_store", lambda: "pstore")
    monkeypatch.setattr(cli, "_superset_client", lambda: "client")
    monkeypatch.setattr("arp.projects.service.open_project", fake_open)
    r = runner.invoke(app, ["project", "open", "demo"])
    assert r.exit_code == 0 and seen["pid"] == "demo"
    assert json.loads(r.output)["dashboards"][0]["id"] == 7


def test_open_error_is_one_line(projects_dir, monkeypatch):
    _create()
    _configure(monkeypatch)

    def boom(*a):
        raise OpenError("import", "bad file")

    monkeypatch.setattr(cli, "_portfolio_store", lambda: None)
    monkeypatch.setattr(cli, "_superset_client", lambda: None)
    monkeypatch.setattr("arp.projects.service.open_project", boom)
    r = runner.invoke(app, ["project", "open", "demo"])
    assert r.exit_code == 1 and "Opening the project failed at import: bad file" in r.output


def test_open_with_file_backend_exits_2_before_any_work(projects_dir, monkeypatch):
    monkeypatch.setenv("ARP_PORTFOLIO_BACKEND", "file")
    get_settings.cache_clear()

    def forbidden(*a):
        raise AssertionError("called")

    monkeypatch.setattr(cli, "_portfolio_store", forbidden)
    monkeypatch.setattr(cli, "_superset_client", forbidden)
    monkeypatch.setattr("arp.projects.service.open_project", forbidden)
    r = runner.invoke(app, ["project", "open", "demo"])
    assert r.exit_code == 2 and "Postgres" in r.output
