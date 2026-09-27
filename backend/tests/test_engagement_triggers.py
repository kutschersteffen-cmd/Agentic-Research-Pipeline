from datetime import UTC, datetime, timedelta

from arp.engagement.triggers import (
    ControversySignal,
    StaticControversySource,
    TransitionPlanSource,
    run_trigger_screen,
    scan_for_stalled_issues,
)
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.schemas.engagement import IssueSeverity, IssueStatus, TriggerSource
from arp.schemas.transition_plan import TransitionPlanAssessmentRecord
from arp.storage.engagement_store import EngagementStore
from arp.storage.run_store import RunStore
from arp.transition_plan.clti import load_assessments


async def test_run_trigger_screen_opens_issue_for_new_signal(tmp_path):
    store = EngagementStore(tmp_path)
    companies = [CompanyRef(company_id="C1", name="Acme Corp")]
    source = StaticControversySource([ControversySignal(company_id="C1", theme="climate", severity=IssueSeverity.HIGH, detail="Spill reported.")])

    events = await run_trigger_screen(companies, source, store)

    assert len(events) == 1
    assert events[0].source == TriggerSource.CONTROVERSY_SCREEN
    record = store.get("C1")
    assert len(record.issues) == 1
    assert record.issues[0].theme == "climate"


async def test_run_trigger_screen_dedupes_against_open_issue(tmp_path):
    store = EngagementStore(tmp_path)
    companies = [CompanyRef(company_id="C1", name="Acme Corp")]
    store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    source = StaticControversySource([ControversySignal(company_id="C1", theme="climate")])

    events = await run_trigger_screen(companies, source, store)

    assert events == []
    assert len(store.get("C1").issues) == 1


async def test_run_trigger_screen_reopens_after_resolution(tmp_path):
    store = EngagementStore(tmp_path)
    companies = [CompanyRef(company_id="C1", name="Acme Corp")]
    _record, issue = store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    store.set_issue_status("C1", issue.issue_id, IssueStatus.RESOLVED)
    source = StaticControversySource([ControversySignal(company_id="C1", theme="climate")])

    events = await run_trigger_screen(companies, source, store)

    assert len(events) == 1
    assert len(store.get("C1").issues) == 2


async def test_run_trigger_screen_ignores_signals_for_unlisted_companies(tmp_path):
    store = EngagementStore(tmp_path)
    companies = [CompanyRef(company_id="C1", name="Acme Corp")]
    source = StaticControversySource([ControversySignal(company_id="C2", theme="climate")])

    events = await run_trigger_screen(companies, source, store)

    assert events == []
    assert store.get("C2") is None


def test_scan_for_stalled_issues_flags_and_marks_status(tmp_path):
    store = EngagementStore(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    # Backdate opened_at by rewriting the record directly (simplest way to simulate age in a test).
    record = store.get("C1")
    issue = record.issues[0]
    stale = record.model_copy(update={"issues": [issue.model_copy(update={"opened_at": old})]})
    store._save(stale)

    events = scan_for_stalled_issues(store, sla_days=45)

    assert len(events) == 1
    assert events[0].source == TriggerSource.SLA_STALL
    assert store.get("C1").issues[0].status == IssueStatus.STALLED


def test_scan_for_stalled_issues_no_events_when_fresh(tmp_path):
    store = EngagementStore(tmp_path)
    store.open_issue("C1", "Acme Corp", theme="climate", source=TriggerSource.MANUAL)
    assert scan_for_stalled_issues(store, sla_days=45) == []


def _assessment(company_id: str, disclosed: int, generated_at: str) -> TransitionPlanAssessmentRecord:
    return TransitionPlanAssessmentRecord(company_id=company_id, name=company_id, run_id="r", disclosed_count=disclosed, generated_at=generated_at)


async def test_transition_plan_source_flags_low_and_falling_clti(tmp_path):
    run_store = RunStore(tmp_path / "runs")
    for rows in [
        [_assessment("LOW", 10, "2025-01-01"), _assessment("FALL", 50, "2025-01-01"), _assessment("OK", 48, "2025-01-01")],
        [_assessment("LOW", 12, "2026-01-01"), _assessment("FALL", 40, "2026-01-01"), _assessment("OK", 48, "2026-01-01")],
    ]:
        run_id = JobManager(run_store).create_run("transition_plan", {}, len(rows)).run_id
        for row in rows:
            run_store.append_jsonl(run_store.results_path(run_id), row.model_dump(mode="json"))

    store = EngagementStore(tmp_path / "eng")
    companies = [CompanyRef(company_id=c, name=c) for c in ("LOW", "FALL", "OK", "NONE")]
    source = TransitionPlanSource(load_assessments(run_store), threshold=0.5)

    events = await run_trigger_screen(companies, source, store)

    assert {e.company_id for e in events} == {"LOW", "FALL"}  # FALL: 0.78 -> 0.62, above threshold but dropped
    assert all(e.source == TriggerSource.TRANSITION_PLAN and e.theme == "climate_transition" for e in events)
    assert "CLTI 0.19" in store.get("LOW").issues[0].source_detail
