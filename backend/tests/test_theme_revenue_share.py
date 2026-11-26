"""theme-revenue-share run wiring: resume (AC-37, AC-45) and `arp theme run` (AC-38, AC-44)."""

import json

import pytest
from typer.testing import CliRunner

import arp.cli.theme as cli_theme
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import resume_run
from arp.research.pipeline import create_theme_run
from arp.schemas.common import CompanyRef
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.models import SegmentRow
from arp.xbrl_pipeline.store import XbrlStore
from tests.conftest import FakeLLMClient
from tests.taxonomy_schema_helpers import registered_schema, released_schema
from tests.test_research_pipeline import _settings

A = ActivityDefinition(
    name="Electrolysers", in_scope_description="Makes water electrolysers.", out_of_scope_description="Industrial gas distribution.",
    seed_keywords=["electrolyser", "hydrogen"], exclusion_keywords=["hydrogen peroxide"],
)
THEME = ThemeDefinition(name="Hydrogen", description="", activities=[A])
C1 = CompanyRef(company_id="c1", name="Acme Gas")


def _fixture_r(settings) -> None:
    store = XbrlStore(settings.xbrl_dir)
    rows = [
        SegmentRow(
            company_id="c1", market="sec", fiscal_year=2025, metric="revenue", concept="us-gaap:Revenues",
            axis="us-gaap:StatementBusinessSegmentsAxis", member=f"x:{name.replace(' ', '')}Member", segment=name, value=value,
            unit="USD", period_start="2025-01-01", period_end="2025-12-31", accession="0000000001-25-000001",
            sum_matches_total=True, reconciling=0,
        )
        for name, value in (("Hydrogen Systems", 300), ("Industrial Gases", 500), ("Services", 200))
    ]
    store.write_segments("0000000001", rows)
    (store.company_dir("0000000001") / "meta.json").write_text(json.dumps({"company_ids": ["c1"]}))


def _revenue(store, run_id):
    row = next(r for r in store.read_results(run_id) if r["_key"] == "c1")
    return row["company_matches"][0]["revenue_exposure"]


async def _resume_interrupted(tmp_path, pg, monkeypatch, *, created_on: bool, resumed_on: bool, drop_param: bool = False):
    if created_on:
        monkeypatch.setenv("ARP_THEME_REVENUE_SHARE_ENABLED", "true")
    settings = _settings(tmp_path).model_copy(update={"xbrl_dir": tmp_path / "xbrl", "max_concurrent_llm_calls": 1})
    store = RunStore(pg, settings.runs_dir)
    run_id = create_theme_run(THEME, [C1], settings, store, extraction_schema=registered_schema(A))
    manifest = store.load_manifest(run_id)
    assert manifest.params["theme_revenue_share"] is created_on
    if drop_param:
        del manifest.params["theme_revenue_share"]
        store.save_manifest(manifest)
    JobManager(store).request_cancel(run_id)  # interrupted before c1
    _fixture_r(settings)
    settings = settings.model_copy(update={"theme_revenue_share_enabled": resumed_on})
    llm = FakeLLMClient({})
    await resume_run(run_id, llm=llm, verifier_llm=llm, registry=DocumentSourceRegistry([]), settings=settings, run_store=store)
    return store, run_id


async def test_resume_keeps_setting_on_from_creation(tmp_path, pg, monkeypatch):
    """AC-37."""
    store, run_id = await _resume_interrupted(tmp_path, pg, monkeypatch, created_on=True, resumed_on=False)
    assert _revenue(store, run_id)["revenue"]["source"] == "reported"


@pytest.mark.parametrize("drop_param", [False, True])
async def test_resume_keeps_setting_off_from_creation(tmp_path, pg, monkeypatch, drop_param):
    """AC-45, including a run stored without the param."""
    store, run_id = await _resume_interrupted(tmp_path, pg, monkeypatch, created_on=False, resumed_on=True, drop_param=drop_param)
    assert _revenue(store, run_id) is None


def _cli_run(tmp_path, pg, monkeypatch, *extra):
    settings = _settings(tmp_path).model_copy(
        update={"xbrl_dir": tmp_path / "xbrl", "max_concurrent_llm_calls": 1, "theme_revenue_share_enabled": True}
    )
    store = RunStore(pg, settings.runs_dir)
    _fixture_r(settings)
    taxonomy = Taxonomy(taxonomy_id="tax_t", name="T", theme=THEME, derivation_method=DerivationMethod.MANUAL, status=TaxonomyStatus.RATIFIED)
    llm = FakeLLMClient({})
    monkeypatch.setattr(cli_theme, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_theme, "_run_store", lambda: store)
    monkeypatch.setattr(cli_theme, "_registry", lambda: DocumentSourceRegistry([]))
    monkeypatch.setattr(cli_theme, "_taxonomy_store", lambda: None)
    monkeypatch.setattr(cli_theme, "released_run_schema", lambda *_a: (taxonomy, released_schema(A)))
    monkeypatch.setattr(cli_theme, "build_llm_client", lambda s: llm)
    monkeypatch.setattr(cli_theme, "build_verifier_llm_client", lambda s: llm)
    universe = tmp_path / "universe.csv"
    universe.write_text("company_id,name\nc1,Acme Gas\n")
    res = CliRunner().invoke(cli_theme.theme_app, ["run", "--taxonomy", "tax_t", "--universe", str(universe), *extra])
    assert res.exit_code == 0, res.output
    (run_id,) = [m.run_id for m in store.list_runs()]
    return store, run_id


def test_cli_theme_run_without_catalogue(tmp_path, pg, monkeypatch):
    """AC-38."""
    store, run_id = _cli_run(tmp_path, pg, monkeypatch)
    assert _revenue(store, run_id)["revenue"]["source"] == "reported"


def test_cli_theme_run_with_catalogue_that_misses(tmp_path, pg, monkeypatch):
    """AC-44."""
    catalogue = tmp_path / "catalogue.csv"
    catalogue.write_text("data_point_id,company_id,metric,label,as_pct_of_total\nd1,c1,revenue,EV Sales,0.4\n")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps([{"activity_id": "other", "metric": "revenue", "matched_labels": ["EV Sales"]}]))
    store, run_id = _cli_run(tmp_path, pg, monkeypatch, "--revenue-catalogue", str(catalogue), "--catalogue-mapping", str(mapping))
    assert _revenue(store, run_id)["revenue"]["source"] == "reported"
