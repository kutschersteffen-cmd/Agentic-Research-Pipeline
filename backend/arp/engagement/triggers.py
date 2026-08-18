from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from arp.engagement.orchestrator import is_stalled
from arp.schemas.common import CompanyRef
from arp.schemas.engagement import IssueSeverity, IssueStatus, TriggerEvent, TriggerSource
from arp.storage.engagement_store import EngagementStore


class ControversySignal(BaseModel):
    company_id: str
    theme: str
    severity: IssueSeverity = IssueSeverity.MEDIUM
    detail: str = ""


class ControversySource(ABC):
    """Screens a company universe for ESG/controversy signals that should
    open a new engagement issue. A real implementation wraps a paid data
    provider API (MSCI, Sustainalytics, RepRisk, ...); the specific provider
    is a house integration decision, not an architectural one (see
    docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #8)."""

    name: str = "base"

    @abstractmethod
    async def screen(self, companies: list[CompanyRef]) -> list[ControversySignal]:
        raise NotImplementedError


class StaticControversySource(ControversySource):
    """Returns a fixed, caller-supplied list of signals. Stands in for a
    real provider in tests, demos, and for callers (like the API) that
    already have signals from elsewhere and just want them raised into the
    engagement queue through the same trigger path as everything else."""

    name = "static"

    def __init__(self, signals: list[ControversySignal]) -> None:
        self._signals = signals

    async def screen(self, companies: list[CompanyRef]) -> list[ControversySignal]:
        wanted = {c.company_id for c in companies}
        return [s for s in self._signals if s.company_id in wanted]


async def run_trigger_screen(
    companies: list[CompanyRef], source: ControversySource, store: EngagementStore
) -> list[TriggerEvent]:
    """Screens `companies` via `source` and opens a new engagement issue for
    every signal that doesn't already have a matching open issue for that
    company/theme -- the dedupe is what keeps a recurring controversy feed
    from spawning duplicate issues on every scan."""
    names_by_id = {c.company_id: c.name for c in companies}
    sectors_by_id = {c.company_id: c.sector for c in companies}
    signals = await source.screen(companies)
    events: list[TriggerEvent] = []
    for signal in signals:
        if store.open_issues_for_theme(signal.company_id, signal.theme):
            continue
        name = names_by_id.get(signal.company_id, signal.company_id)
        _record, issue = store.open_issue(
            signal.company_id,
            name,
            theme=signal.theme,
            severity=signal.severity,
            source=TriggerSource.CONTROVERSY_SCREEN,
            source_detail=signal.detail,
            sector=sectors_by_id.get(signal.company_id),
        )
        events.append(
            TriggerEvent(
                company_id=signal.company_id,
                theme=signal.theme,
                source=TriggerSource.CONTROVERSY_SCREEN,
                severity=signal.severity,
                detail=signal.detail,
                raised_issue_id=issue.issue_id,
            )
        )
    return events


def scan_for_stalled_issues(store: EngagementStore, sla_days: int) -> list[TriggerEvent]:
    """The SLA half of the trigger layer: no external feed needed, just a
    sweep over every open issue comparing last activity against the SLA.
    Marks newly-stalled issues STALLED and raises a trigger event for each
    so they land in the same orchestrator queue as controversy triggers."""
    events: list[TriggerEvent] = []
    for record in store.list_all():
        for issue in record.issues:
            if issue.status != IssueStatus.OPEN:
                continue
            if not is_stalled(issue, sla_days):
                continue
            store.set_issue_status(record.company_id, issue.issue_id, IssueStatus.STALLED)
            events.append(
                TriggerEvent(
                    company_id=record.company_id,
                    theme=issue.theme,
                    source=TriggerSource.SLA_STALL,
                    severity=issue.severity,
                    detail=f"No activity for >= {sla_days} days at milestone '{issue.milestone_stage.value}'.",
                    raised_issue_id=issue.issue_id,
                )
            )
    return events
