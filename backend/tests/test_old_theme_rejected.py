"""Old-format themes (core_isic_codes) are rejected with M8 on every load path (AC-14..17, AC-62)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from arp.api import deps
from arp.api.main import app
from arp.cli import theme as cli_theme
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.pipeline import create_theme_run
from arp.schemas.common import CompanyRef
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import OLD_FORMAT_MESSAGE as M8
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.taxonomy_schema_helpers import registered_schema

OLD_ACTIVITY = {"name": "n", "in_scope_description": "i", "out_of_scope_description": "o", "core_isic_codes": ["B07"]}
OLD_THEME = {"name": "T", "description": "", "activities": [OLD_ACTIVITY]}


def _oldify(path) -> None:
    """Rewrites a stored theme/taxonomy JSON so its activity carries core_isic_codes instead of core_sectors."""
    path.write_text(path.read_text().replace('"core_sectors": []', '"core_isic_codes": ["B07"]'))
    assert "core_isic_codes" in path.read_text()


def test_model_rejects():
    with pytest.raises(ValidationError) as exc:
        ActivityDefinition.model_validate(OLD_ACTIVITY)
    assert M8 in str(exc.value)


@pytest.fixture
def api(tmp_path):
    """The real app (its ValueError handler decides the status), with the taxonomy store on tmp_path."""
    store = TaxonomyStore(tmp_path / "taxonomies")
    overrides = {
        deps.get_taxonomy_store: lambda: store,
        deps.settings_dep: lambda: Settings(anthropic_api_key="unused", cache_dir=tmp_path / "cache"),
        deps.get_registry: lambda: None, deps.get_llm_client: lambda: None,
    }
    app.dependency_overrides.update(overrides)
    yield TestClient(app), store
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


def test_post_taxonomies_422(api):  # AC-14, AC-15
    client, store = api
    res = client.post("/api/taxonomies", json={"name": "t", "derivation_method": "manual", "theme": OLD_THEME})
    assert res.status_code == 422 and M8 in res.text
    tid = store.create("t", ThemeDefinition(name="T", description=""), DerivationMethod.MANUAL).taxonomy_id
    res = client.post(f"/api/taxonomies/{tid}/versions", json={"theme": OLD_THEME})
    assert res.status_code == 422 and M8 in res.text


def test_get_unmigrated_422(api, tmp_path):  # AC-17
    client, store = api
    theme = ThemeDefinition(name="T", description="", activities=[ActivityDefinition(name="n", in_scope_description="i", out_of_scope_description="o")])
    tid = store.create("t", theme, DerivationMethod.MANUAL).taxonomy_id
    _oldify(tmp_path / "taxonomies" / tid / "v1.json")
    res = client.get(f"/api/taxonomies/{tid}")
    assert res.status_code == 422 and M8 in res.text
    for path in ("/api/taxonomies", f"/api/taxonomies/{tid}/versions"):  # the list reads too
        res = client.get(path)
        assert res.status_code == 422 and M8 in res.text, path


def test_cli_taxonomy_new_version_rejects(tmp_path, monkeypatch):
    from arp.cli import taxonomy as cli_taxonomy

    store = TaxonomyStore(tmp_path / "taxonomies")
    tid = store.create("t", ThemeDefinition(name="T", description=""), DerivationMethod.MANUAL).taxonomy_id
    monkeypatch.setattr(cli_taxonomy, "_taxonomy_store", lambda: store)
    theme_file = tmp_path / "old.json"
    theme_file.write_text(json.dumps(OLD_THEME))
    res = CliRunner().invoke(cli_taxonomy.taxonomy_app, ["new-version", tid, "--theme", str(theme_file)])
    assert res.exit_code == 1
    assert M8 in res.stderr
    assert [t.version for t in store.list_versions(tid)] == [1]


def test_cli_classify_sectors_rejects(tmp_path):  # AC-16
    theme_file = tmp_path / "old.json"
    theme_file.write_text(json.dumps(OLD_THEME))
    res = CliRunner().invoke(cli_theme.theme_app, ["classify-sectors", "--theme", str(theme_file), "--out", str(tmp_path / "x.json"), "--use-sample-io"])
    assert res.exit_code == 1
    assert M8 in res.stderr
    assert not (tmp_path / "x.json").exists()


def test_resume_rejects(tmp_path, pg, monkeypatch):  # AC-62
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    store = RunStore(pg, settings.runs_dir)
    activity = ActivityDefinition(name="EV", in_scope_description="EVs.", out_of_scope_description="ICE.")
    run_id = create_theme_run(
        ThemeDefinition(name="E", description="", activities=[activity]), [CompanyRef(company_id="c1", name="Co 1")],
        settings, store, extraction_schema=registered_schema(activity),
    )
    _oldify(store.run_dir(run_id) / "theme.json")
    monkeypatch.setattr(cli_theme, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_theme, "_run_store", lambda: store)
    monkeypatch.setattr(cli_theme, "_registry", lambda: DocumentSourceRegistry([]))
    res = CliRunner().invoke(cli_theme.theme_app, ["resume", run_id])
    assert res.exit_code == 1
    assert M8 in res.stderr
