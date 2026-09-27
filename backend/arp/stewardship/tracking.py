"""Stage 6 tracking: commitments with target dates, the loop back to
monitoring, closing an engagement with its outcome, and E7 case studies.

- Tracking triggers are raised from live engagement records, not company data,
  in the same shape as the monitoring rules' triggers so stage 1 shows both:
  a commitment the company missed, a commitment past its target date that
  nobody has verified yet, and an engagement stalled beyond the SLA. They are
  always attached to their engagement.
- A case study (E7) is drafted deterministically from the records of a closed
  engagement: trigger, steps with dates, correspondence by interaction type,
  commitments and outcome. It says it was compiled from records, and it runs
  through the E8 style check before anyone uses it.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime

from arp.engagement.orchestrator import is_stalled
from arp.schemas.engagement import (
    CommitmentStatus,
    CorrespondenceEntry,
    CorrespondenceType,
    EngagementRecord,
    IssueStatus,
)
from arp.stewardship.style import check
from arp.storage.engagement_store import EngagementStore

OPEN = (IssueStatus.OPEN, IssueStatus.STALLED)
CLOSED = (IssueStatus.RESOLVED, IssueStatus.CLOSED)


def _w(s: str) -> str:
    return s.replace("_", " ")


def _day(iso: str) -> str:
    return iso[:10]


def triggers(records: list[EngagementRecord], sla_days: int, today: date | None = None) -> list[dict]:
    today = today or datetime.now(UTC).date()
    out = []
    for r in records:
        for i in r.issues:
            if i.status not in OPEN:
                continue

            def raise_(type_: str, severity: str, rule: str, reason: str, _r=r, _i=i) -> None:
                out.append(
                    {
                        "issuer_id": _r.company_id,
                        "company": _r.name,
                        "sector": _r.sector,
                        "type": type_,
                        "theme": _i.theme,
                        "severity": severity,
                        "rule": rule,
                        "reason": reason,
                        "engagement_id": _i.issue_id,
                        "source": "tracking",
                    }
                )

            for c in i.commitments:
                if c.status == CommitmentStatus.MISSED:
                    raise_("commitment_missed", "high", "commitment_missed", f"Commitment missed: {c.text}")
                elif c.status == CommitmentStatus.OPEN and c.target_date and date.fromisoformat(c.target_date[:10]) < today:
                    raise_(
                        "commitment_missed",
                        "medium",
                        "commitment_overdue",
                        f"Past its target date {c.target_date[:10]}, not verified: {c.text}",
                    )
            if is_stalled(i, sla_days):
                raise_("engagement_stalled", "medium", "engagement_stalled", f"No activity for {sla_days} days or more")
    return out


def commitments(records: list[EngagementRecord], today: date | None = None) -> list[dict]:
    today = today or datetime.now(UTC).date()
    return [
        {
            "company_id": r.company_id,
            "company": r.name,
            "issue_id": i.issue_id,
            "theme": i.theme,
            "commitment_id": c.commitment_id,
            "text": c.text,
            "made_at": _day(c.made_at),
            "target_date": c.target_date,
            "status": c.status.value,
            "overdue": c.status == CommitmentStatus.OPEN
            and bool(c.target_date)
            and date.fromisoformat(c.target_date[:10]) < today,
            "validated_by": c.validated_by,
        }
        for r in records
        for i in r.issues
        for c in i.commitments
    ]


def close(engagements: EngagementStore, company_id: str, issue_id: str, status: IssueStatus, outcome: str, decided_by: str):
    """Closes an engagement with its outcome, logged as correspondence so the
    case study and the reports can cite it."""
    if status not in CLOSED:
        raise ValueError("An engagement is closed as resolved or closed")
    if not outcome.strip() or not decided_by.strip():
        raise ValueError("Closing needs an outcome and decided_by")
    record = engagements.get(company_id)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None) if record else None
    if issue is None:
        raise KeyError(f"{company_id}/{issue_id}")
    if issue.status in CLOSED:
        raise ValueError(f"Already {issue.status.value}")
    engagements.add_correspondence(
        company_id,
        issue_id,
        CorrespondenceEntry(type=CorrespondenceType.OTHER, summary=f"Outcome ({status.value}): {outcome}", logged_by=decided_by),
    )
    return engagements.set_issue_status(company_id, issue_id, status)


def case_study(record: EngagementRecord, issue_id: str, blocklist: dict) -> dict:
    """E7: a case study compiled from the records of a closed engagement."""
    issue = next((i for i in record.issues if i.issue_id == issue_id), None)
    if issue is None:
        raise KeyError(issue_id)
    if issue.status not in CLOSED:
        raise ValueError("Case studies are drafted only for closed engagements")
    steps = [f"{_day(t.changed_at)}: {_w(t.stage.value)} (decided by {t.decided_by})" for t in issue.escalation_history]
    top = issue.escalation_history[-1].stage.value if issue.escalation_history else issue.escalation_stage.value
    contacts = Counter(
        f"{c.type.value}{' (' + _w(c.interaction_type.value) + ')' if c.interaction_type else ''}"
        for c in issue.correspondence
        if not c.summary.startswith("Outcome (")
    )
    logged = next((c.summary for c in reversed(issue.correspondence) if c.summary.startswith("Outcome (")), None)
    outcome = f"{issue.status.value.capitalize()}: {logged.split('): ', 1)[1]}" if logged else f"Closed as {issue.status.value}."
    kept = [c for c in issue.commitments if c.status == CommitmentStatus.VERIFIED]
    missed = [c for c in issue.commitments if c.status == CommitmentStatus.MISSED]
    paragraphs = [
        f"{record.name}: {_w(issue.theme)}",
        f"Why we engaged. Opened on {_day(issue.opened_at)} ({_w(issue.source.value)})"
        + (f": {issue.source_detail}." if issue.source_detail else "."),
        "What we did. "
        + (", ".join(f"{n} {k}" for k, n in sorted(contacts.items())) + "." if contacts else "No outreach logged.")
        + f" Highest escalation step: {_w(top)}.",
        ("Escalation steps. " + "; ".join(steps) + ".") if steps else "Escalation steps. None beyond private engagement.",
        "Commitments. "
        + (f"Kept: {'; '.join(c.text for c in kept)}. " if kept else "")
        + (f"Missed: {'; '.join(c.text for c in missed)}. " if missed else "")
        + ("None recorded." if not kept and not missed else ""),
        f"Outcome. {outcome}",
    ]
    text = "\n\n".join(paragraphs)
    return {
        "company_id": record.company_id,
        "company": record.name,
        "issue_id": issue_id,
        "theme": issue.theme,
        "status": issue.status.value,
        "text": text,
        "style_flags": check(text, blocklist),
        "provenance": "Compiled from the engagement record (escalation history, correspondence, commitments); no model-written text.",
    }
