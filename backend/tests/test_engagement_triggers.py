from datetime import UTC, datetime, timedelta

from arp.engagement.triggers import ControversySignal, StaticControversySource, run_trigger_screen, scan_for_stalled_issues
from arp.schemas.common import CompanyRef
from arp.schemas.engagement import IssueSeverity, IssueStatus, TriggerSource
from arp.storage.engagement_store import EngagementStore


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
