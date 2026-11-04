import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api import deps
from arp.api.auth import Principal, current_user
from arp.api.routers import taxonomies
from arp.cli import taxonomy as cli
from arp.storage.taxonomy_store import TaxonomyStore

FIXTURES = Path(__file__).parent / "fixtures" / "taxonomy"
METHODS = ("empirical", "etf_index_holdings")


def _msg(m: str) -> str:
    return f"--method {m} is replaced by 'arp taxonomy infer start --stocks <file>'."


@pytest.mark.parametrize("m", METHODS)
def test_cli_refuses_retired_method(m):  # AC-47
    res = CliRunner().invoke(cli.taxonomy_app, ["create", "X", "--method", m])
    assert res.exit_code == 1 and res.stderr.strip() == _msg(m)


@pytest.mark.parametrize("m", METHODS)
def test_api_refuses_retired_method(m):  # AC-48
    app = FastAPI()
    app.include_router(taxonomies.router)
    app.dependency_overrides.update({deps.get_taxonomy_store: lambda: None, deps.settings_dep: lambda: None,
                                     deps.get_registry: lambda: None, current_user: lambda: Principal(user_id="u", name="u", role="analyst")})
    res = TestClient(app).post("/api/taxonomies", json={"name": "X", "derivation_method": m})
    assert (res.status_code, res.json()["detail"]) == (422, _msg(m))


@pytest.mark.parametrize("m", METHODS)
def test_saved_taxonomy_shows_as_on_main(m, tmp_path, monkeypatch):  # AC-50
    shutil.copytree(FIXTURES / "store", tmp_path / "store")
    store = TaxonomyStore(tmp_path / "store")
    tid = next(t.taxonomy_id for t in store.list_all() if t.derivation_method.value == m)
    monkeypatch.setattr(cli, "_taxonomy_store", lambda: store)
    res = CliRunner().invoke(cli.taxonomy_app, ["show", tid])
    assert res.exit_code == 0
    new = {"kpis", "contextual_keywords", "exclusion_keywords", "contextual_window_words", "contrast_statements"}  # last one: fixtures predate it

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in new}
        return [strip(i) for i in x] if isinstance(x, list) else x

    assert strip(json.loads(res.stdout)) == json.loads((FIXTURES / f"show_main_{m}.json").read_text())
