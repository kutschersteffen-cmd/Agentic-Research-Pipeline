"""Research Orchestrator adapters: company hand-off between steps and the review gate (plan task 7)."""
from __future__ import annotations

import pytest

from arp.config import get_settings
from arp.orchestration.job_manager import JobManager
from arp.orchestration.plan_steps import StepNotWired, _companies, _result, build_reviewed, build_steps
from arp.orchestration.review_queue import queue_for_review, record_review_decision
from arp.schemas.common import CompanyRef

ACME = CompanyRef(company_id="acme", name="Acme")
BETA = CompanyRef(company_id="beta", name="Beta")


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Adapters build LLM clients; the patched run types never use them, and CI has no API key."""
    import arp.llm.factory as factory

    monkeypatch.setattr(factory, "build_llm_client", lambda *a, **k: None)
    monkeypatch.setattr(factory, "build_verifier_llm_client", lambda *a, **k: None)


@pytest.fixture
def universe_run(run_store):
    return JobManager(run_store).create_run("theme", {}, 2, companies=[ACME, BETA]).run_id


def test_companies_come_from_the_universe_run(run_store, universe_run):
    assert [c.company_id for c in _companies(run_store, universe_run, None)] == ["acme", "beta"]
    assert [c.company_id for c in _companies(run_store, universe_run, ["beta"])] == ["beta"]


def test_gate_until_every_item_is_decided(run_store, universe_run):
    queue_for_review(run_store, universe_run, "k1", {"why": "low confidence"})
    assert _result(universe_run, run_store)["gate"] is True
    reviewed = build_reviewed(run_store)
    assert reviewed({"run_id": universe_run}) is False
    record_review_decision(run_store, universe_run, "k1", "approve", "alice", None)
    assert reviewed({"run_id": universe_run}) is True


def test_all_eight_kinds_present_and_unwired_ones_fail_clearly(run_store):
    steps = build_steps(get_settings(), run_store)
    assert len(steps) == 8
    with pytest.raises(StepNotWired, match="index_construct is not wired"):
        steps["index_construct"](decision_id="d")


def test_report_gate_until_storyline_approved(run_store, monkeypatch):
    from types import SimpleNamespace as NS

    import arp.api.deps as deps
    from arp.schemas.reporting import ReportStatus

    status = {"s": ReportStatus.STORYLINE_READY}
    monkeypatch.setattr(deps, "get_reporting_store", lambda: NS(load_manifest=lambda _id: NS(status=status["s"])))
    reviewed = build_reviewed(run_store)
    assert reviewed({"result_ref": "report:rep_1"}) is False
    status["s"] = ReportStatus.COMPLETED
    assert reviewed({"result_ref": "report:rep_1"}) is True


class _Recorder:
    """Stands in for a run type's create/execute pair; records which companies each got."""

    def __init__(self, run_store, kind):
        self.run_store, self.kind, self.companies = run_store, kind, None

    def create(self, *args, **kwargs):
        refs = next(a for a in args if isinstance(a, list))
        self.companies = [c.company_id for c in refs]
        return JobManager(self.run_store).create_run(self.kind, {}, len(refs), companies=refs).run_id

    async def execute(self, run_id, *args, **kwargs):
        return run_id


@pytest.mark.parametrize(("kind", "module", "create", "execute", "params"), [
    ("document_discovery", "arp.discovery.pipeline", "create_discovery_run", "execute_discovery_run", {}),
    ("financials_extraction", "arp.extraction.financials_pipeline", "create_financials_extraction_run",
     "execute_financials_extraction_run", {}),
    ("xbrl_facts", "arp.xbrl_pipeline.fetch", "create_xbrl_run", "execute_xbrl_run", {}),
])
def test_background_adapters_pass_filtered_companies(run_store, universe_run, monkeypatch, kind, module, create,
                                                     execute, params):
    import importlib

    mod = importlib.import_module(module)
    rec = _Recorder(run_store, kind)
    monkeypatch.setattr(mod, create, rec.create)
    monkeypatch.setattr(mod, execute, rec.execute)
    monkeypatch.setattr("arp.api.deps.get_registry", lambda: None)
    out = build_steps(get_settings(), run_store)[kind](universe_run_id=universe_run, companies=["beta"], **params)
    assert rec.companies == ["beta"]
    assert out["run_id"] and out["gate"] is False


def test_extraction_adapter_loads_schema(run_store, universe_run, monkeypatch):
    import arp.db.fields as fields
    import arp.extraction.pipeline as pipeline

    rec = _Recorder(run_store, "extraction")
    monkeypatch.setattr(fields.SchemaRegistry, "get", lambda self, sid: f"schema:{sid}")
    monkeypatch.setattr(pipeline, "create_extraction_run", lambda schema, refs, *a, **k: rec.create(refs))
    monkeypatch.setattr(pipeline, "execute_extraction_run", rec.execute)
    monkeypatch.setattr("arp.api.deps.get_registry", lambda: None)
    out = build_steps(get_settings(), run_store)["extraction"](universe_run_id=universe_run, schema_id="s")
    assert rec.companies == ["acme", "beta"] and out["run_id"]


def test_universe_adapter_takes_best_exposure(run_store, monkeypatch, tmp_path):
    from types import SimpleNamespace as NS

    import arp.research.pipeline as research
    import arp.research.taxonomy_schema as ts
    import arp.universe as universe

    def match(cid, exposure, verdict):
        return NS(company_id=cid, name=cid, exposure_estimate=NS(value=exposure), verdict=NS(value=verdict))

    async def fake_run(theme, companies, **kw):
        return JobManager(run_store).create_run("theme", {}, len(companies), companies=companies).run_id

    monkeypatch.setattr(ts, "released_run_schema", lambda *a: (NS(theme="t", taxonomy_id="tax", version=1), None))
    monkeypatch.setattr(universe, "load_company_universe", lambda src: [ACME, BETA])
    monkeypatch.setattr(research, "run_thematic_universe", fake_run)
    monkeypatch.setattr(research, "load_theme_run_matches", lambda rs, rid: [
        match("acme", "minor", "exclude"), match("acme", "significant", "include")])
    monkeypatch.setattr("arp.research.indirect_exposure.factory.resolve_indirect_exposure_model", lambda *a, **k: None)
    monkeypatch.setattr("arp.api.deps.get_registry", lambda: None)
    out = build_steps(get_settings(), run_store)["universe_build"](taxonomy_id="tax", source="u.csv")
    by_id = {c["id"]: c for c in out["companies"]}
    assert by_id["acme"] == {"id": "acme", "name": "Acme", "exposure": "significant", "included": True}
    assert by_id["beta"]["exposure"] == "none" and by_id["beta"]["included"] is False


def test_decision_adapter_needs_a_framework(run_store, universe_run):
    with pytest.raises(ValueError, match="no decision framework attached"):
        build_steps(get_settings(), run_store)["decision_score"](source_run_id=universe_run)
