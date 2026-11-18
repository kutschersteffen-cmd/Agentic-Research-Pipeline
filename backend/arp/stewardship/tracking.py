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
    ObjectiveResult,
    ObjectiveStatus,
    WatchFlag,
    WatchListEntry,
    evidence_text,
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
                elif c.status == CommitmentStatus.OPEN and (due := _iso(c.target_date)) and date.fromisoformat(due) < today:
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
            and bool(due := _iso(c.target_date))
            and date.fromisoformat(due) < today,
            "validated_by": c.validated_by,
        }
        for r in records
        for i in r.issues
        for c in i.commitments
    ]


def _iso(value: str | None) -> str | None:
    """The `YYYY-MM-DD` date `value` starts with, else None: intake stores free-text due dates, which count as none,
    and the API stores datetimes as given (the same date part `triggers()` reads)."""
    day = (value or "")[:10]
    try:
        return day if date.fromisoformat(day).isoformat() == day else None
    except ValueError:
        return None


def _flag_order(f: WatchFlag) -> tuple:
    return (f.kind != "broken", f.target_date is None, f.target_date or "", f.item_kind != "commitment", f.item_id)


def watch_flags_by_company(records: list[EngagementRecord | None], today: date | None = None) -> dict[str, list[WatchFlag]]:
    """Overdue and broken commitments and objectives on open or stalled engagements, keyed by company; only companies
    with a flag are keys (spec "Flags and the ballot banner")."""
    today_iso = (today or datetime.now(UTC).date()).isoformat()
    out: dict[str, list[WatchFlag]] = {}
    for r in records:
        if r is None:
            continue
        flags = []
        for i in r.issues:
            if i.status not in OPEN:
                continue
            for c in i.commitments:
                due = _iso(c.target_date)
                if c.status == CommitmentStatus.MISSED:
                    since = _iso(c.validated_at) or due or _day(c.made_at)
                    kind, message = "broken", f'Commitment broken: "{c.text}" was marked not met on {since}.'
                elif c.status == CommitmentStatus.OPEN and due and due < today_iso:
                    since, kind, message = due, "overdue", f'Commitment overdue: "{c.text}" was due {due}.'
                else:
                    continue
                flags.append(WatchFlag(item_kind="commitment", item_id=c.commitment_id, engagement_id=i.issue_id, kind=kind,
                                       text=c.text, target_date=due, since=since, message=message))
            for o in i.objectives:
                due = _iso(o.target_date)
                if o.result in (ObjectiveResult.NOT_ACHIEVED, ObjectiveResult.DETERIORATION):
                    since = _iso(o.closed_at) or due
                    kind = "broken"
                    message = f'Objective failed: "{o.description}" was closed as {_w(o.result.value)}' + (f" on {since}." if since else ".")
                elif o.status in (ObjectiveStatus.INITIATED, ObjectiveStatus.IN_PROGRESS) and due and due < today_iso:
                    since, kind, message = due, "overdue", f'Objective overdue: "{o.description}" was due {due}.'
                else:
                    continue
                flags.append(WatchFlag(item_kind="objective", item_id=o.objective_id, engagement_id=i.issue_id, kind=kind,
                                       text=o.description, target_date=due, since=since, message=message))
        if flags:
            out[r.company_id] = sorted(flags, key=_flag_order)
    return out


def watch_flags(store: EngagementStore, company_id: str, today: date | None = None) -> list[WatchFlag]:
    return watch_flags_by_company([store.get(company_id)], today).get(company_id, [])


def watch_list(store: EngagementStore, company_id: str, issue_id: str, today: date | None = None) -> list[WatchListEntry]:
    """The engagement's watch items plus its broken commitments and objectives, flagged first in `watch_flags` order,
    each with its confirmed evidence (spec "The watch list in the dossier"). The file store has no topics or evidence."""
    from arp.storage.postgres_engagement_store import PostgresEngagementStore

    record = store.get(company_id)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None) if record else None
    if issue is None or issue.status not in OPEN:
        return []
    flags = [f for f in watch_flags_by_company([record], today).get(company_id, []) if f.engagement_id == issue_id]
    flag_of = {f.item_id: f.kind for f in flags}
    entries = [
        WatchListEntry(item_kind="objective", item_id=o.objective_id, text=o.description, proof_statement=o.proof_statement,
                       target_date=o.target_date, status=o.status.value, flag=flag_of.get(o.objective_id), evidence=[])
        for o in issue.objectives
        if o.status in (ObjectiveStatus.INITIATED, ObjectiveStatus.IN_PROGRESS) or o.objective_id in flag_of
    ] + [
        WatchListEntry(item_kind="commitment", item_id=c.commitment_id, text=c.text, proof_statement=c.proof_statement,
                       target_date=c.target_date, status=c.status.value, flag=flag_of.get(c.commitment_id), evidence=[])
        for c in issue.commitments
        if c.status == CommitmentStatus.OPEN or c.commitment_id in flag_of
    ]
    if isinstance(store, PostgresEngagementStore):
        entries += [
            WatchListEntry(item_kind="topic", item_id=t.topic_id, text=t.question, proof_statement=t.proof_statement,
                           target_date=t.target_date, status=t.status, flag=None, evidence=[])
            for t in store.list_watch_topics(company_id)
            if t.engagement_id == issue_id and t.status == "open"
        ]
        by_id = {e.item_id: e for e in entries}
        for s in reversed(store.list_suggestions(company_id, "confirmed")):  # newest first -> oldest first
            if s.kind == "evidence" and s.item_id in by_id:
                label = "Evidence against" if s.verdict == "against" else "Evidence"
                by_id[s.item_id].evidence.append(f"{label}: {evidence_text(s)} (confirmed by {s.decided_by})")
    rank = {f.item_id: n for n, f in enumerate(flags)}
    kind_order = {"objective": 0, "commitment": 1, "topic": 2}
    due = {e.item_id: _iso(e.target_date) for e in entries}
    return sorted(entries, key=lambda e: (e.item_id not in rank, rank.get(e.item_id, 0), due[e.item_id] is None,
                                          due[e.item_id] or "", kind_order[e.item_kind], e.item_id))


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
