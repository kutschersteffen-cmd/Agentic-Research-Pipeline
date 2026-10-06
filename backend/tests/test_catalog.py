from __future__ import annotations

import json
from types import SimpleNamespace

from arp import catalog
from arp.api.routers.universe import save_universe
from arp.config import Settings
from arp.decision.dataset import Dataset
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.schemas.decision import PublishedDecision
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore


class _NoIndex:
    def list_indices(self):
        return ["IDX"]

    def list_review_dates(self, index_id):
        return ["2026-09-30"]

    def get_review(self, index_id, day):
        return SimpleNamespace(decision_snapshot_ids=["pub_1"], calibration_id=None)

    def list_calibrations(self):
        return []


class _Reports:
    def list_reports(self):
        return [SimpleNamespace(report_id="rpt_1", title="Q3 pack")]

    def load_request(self, report_id):
        return SimpleNamespace(run_refs=[SimpleNamespace(kind="decision", ref_id="pub_1")])


def test_catalog_lists_every_kind_with_what_uses_it(tmp_path):
    settings = Settings(runs_dir=tmp_path / "runs")
    settings.runs_dir.mkdir()
    rs, decisions, taxonomy = RunStore(settings.runs_dir), DecisionStore(tmp_path / "fw"), TaxonomyStore(tmp_path / "tax")

    universe = save_universe(settings, [CompanyRef(company_id="c1", name="Acme")], "climate leaders")["path"]
    tax = taxonomy.create("Grid", ThemeDefinition(name="Grid", description="grid"), DerivationMethod.LLM_DRAFT)
    theme_run = JobManager(rs).create_run("theme", {"universe_path": universe, "taxonomy_id": tax.taxonomy_id, "taxonomy_version": 1}, 1).run_id
    extraction = JobManager(rs).create_run("extraction", {}, 1).run_id
    (rs.run_dir(extraction) / "inputs.json").write_text(json.dumps({"universe_path": universe}))
    decisions.save_dataset(Dataset(name="scores", columns=["a"], rows=[], source="extraction_run", source_ref=extraction))
    decisions.save_published(PublishedDecision(snapshot_id="pub_1", framework_id="fw", framework_version=2, framework_name="Green",
                                               dataset_id="ds", dataset_name="scores", id_column="Company_Id", published_by="IC"))

    out = catalog.catalog(runs_dir=settings.runs_dir, run_store=rs, decisions=decisions, taxonomy=taxonomy, index=_NoIndex(),
                          reports=_Reports())
    by = {(o["kind"], o["id"]): o for o in out}

    u = by[("universe", universe)]
    assert (u["name"], u["status"], u["count"]) == ("climate leaders (1 companies)", "saved", 1)
    assert sorted(c["id"] for c in u["used_by"]) == sorted([theme_run, extraction])
    assert [c["id"] for c in by[("taxonomy", tax.taxonomy_id)]["used_by"]] == [theme_run]
    assert by[("taxonomy", tax.taxonomy_id)]["status"] == "draft"
    assert [c["kind"] for c in by[("run", extraction)]["used_by"]] == ["dataset"]
    pub = by[("publication", "pub_1")]
    assert pub["name"] == "Green v2 · scores" and pub["by"] == "IC"
    assert sorted(c["kind"] for c in pub["used_by"]) == ["index_review", "report"]

    only = catalog.catalog(runs_dir=settings.runs_dir, run_store=rs, decisions=decisions, taxonomy=taxonomy, index=_NoIndex(),
                           reports=_Reports(), kind="universe")
    assert {o["kind"] for o in only} == {"universe"}


def test_a_theme_run_records_the_taxonomy_version_it_ran_on(tmp_path):
    from arp.research.pipeline import create_theme_run

    rs = RunStore(tmp_path / "runs")
    theme = ThemeDefinition(name="Grid", description="grid")
    run_id = create_theme_run(theme, [CompanyRef(company_id="c1", name="Acme")], Settings(), rs, taxonomy_id="tax_1", taxonomy_version=3)
    params = rs.load_manifest(run_id).params
    assert (params["taxonomy_id"], params["taxonomy_version"]) == ("tax_1", 3)
