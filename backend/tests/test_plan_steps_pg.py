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
