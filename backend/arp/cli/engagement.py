from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _engagement_store, _registry
from arp.config import get_settings
from arp.engagement.orchestrator import decide_next_action
from arp.engagement.reporting_agent import compile_report
from arp.engagement.triggers import ControversySignal, StaticControversySource, run_trigger_screen, scan_for_stalled_issues
from arp.llm.factory import build_llm_client
from arp.schemas.engagement import CorrespondenceEntry, EscalationStage, IssueSeverity, TriggerSource
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe
from arp.voting.pipeline import get_ballots, get_cast_votes

engagement_app = typer.Typer(help="Stewardship engagement: record store, triggers, and the escalation-lever checkpoint.")


@engagement_app.command("record-list")
def engagement_record_list() -> None:
    for r in _engagement_store().list_all():
        open_issues = sum(1 for i in r.issues if i.status.value == "open")
        typer.echo(f"{r.company_id}\t{r.name}\t{len(r.issues)} issue(s), {open_issues} open")



@engagement_app.command("record-show")
def engagement_record_show(company_id: str) -> None:
    record = _engagement_store().get(company_id)
    if record is None:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(record.model_dump(mode="json"), indent=2))



@engagement_app.command("issue-open")
def engagement_issue_open(
    company_id: str,
    name: str,
    theme: str = typer.Option(...),
    severity: IssueSeverity = typer.Option(IssueSeverity.MEDIUM),
) -> None:
    _record, issue = _engagement_store().open_issue(company_id, name, theme=theme, severity=severity, source=TriggerSource.ANALYST_RAISED)
    typer.echo(f"Opened issue {issue.issue_id} ({theme}) for {company_id}")



@engagement_app.command("issue-next-action")
def engagement_issue_next_action(company_id: str, issue_id: str) -> None:
    settings = get_settings()
    store = _engagement_store()
    record = store.get(company_id)
    if record is None:
        typer.echo("Record not found", err=True)
        raise typer.Exit(1)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None)
    if issue is None:
        typer.echo("Issue not found", err=True)
        raise typer.Exit(1)
    decision = decide_next_action(issue, settings.engagement_sla_days)
    typer.echo(f"{decision.action.value}: {decision.reason}")



@engagement_app.command("issue-escalate")
def engagement_issue_escalate(
    company_id: str,
    issue_id: str,
    stage: EscalationStage = typer.Option(..., help="The next escalation-ladder step."),
    by: str = typer.Option(..., help="Who made this escalation-lever decision -- the non-negotiable human checkpoint."),
    reason: str = typer.Option(""),
) -> None:
    _engagement_store().set_escalation_stage(company_id, issue_id, stage, by, reason)
    typer.echo(f"Escalated {company_id}/{issue_id} to {stage.value} (by {by})")



@engagement_app.command("log-correspondence")
def engagement_log_correspondence(
    company_id: str,
    issue_id: str,
    type: str = typer.Option(..., help="letter | call | meeting | email | other"),
    summary: str = typer.Option(...),
    logged_by: str = typer.Option(None),
) -> None:
    _engagement_store().add_correspondence(company_id, issue_id, CorrespondenceEntry(type=type, summary=summary, logged_by=logged_by))
    typer.echo("Logged.")



@engagement_app.command("verify-commitment")
def engagement_verify_commitment(company_id: str, issue_id: str, commitment_id: str, by: str = typer.Option(...)) -> None:
    from arp.engagement.tracking_agent import log_commitment_verified

    log_commitment_verified(_engagement_store(), company_id, issue_id, commitment_id, by)
    typer.echo("Verified.")



@engagement_app.command("dossier-draft")
def engagement_dossier_draft(
    company_id: str,
    issue_id: str,
    universe: Path = typer.Option(..., help="Universe CSV/JSON containing this company (for name/ticker/cik/website)."),
    out: Path = typer.Option(..., help="Where to write the ResearchDossier JSON."),
) -> None:
    """Research Agent: drafts a grounded briefing dossier for one issue.
    The result is written to disk, not auto-applied, so a human can run the
    dossier-accuracy review checkpoint before any Drafting Agent handoff."""
    from arp.engagement.research_agent import research_company_issue

    settings = get_settings()
    llm = build_llm_client(settings)
    store = _engagement_store()
    record = store.get(company_id)
    if record is None:
        typer.echo("Engagement record not found -- open an issue first with `arp engagement issue-open`.", err=True)
        raise typer.Exit(1)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None)
    if issue is None:
        typer.echo("Issue not found", err=True)
        raise typer.Exit(1)
    company = next((c for c in load_company_universe(universe) if c.company_id == company_id), None)
    if company is None:
        typer.echo(f"{company_id} not found in {universe}", err=True)
        raise typer.Exit(1)
    dossier, needs_review, _usage = asyncio.run(
        research_company_issue(
            company, issue, record, registry=_registry(), llm=llm,
            fuzzy_threshold=settings.grounding_fuzzy_threshold, confidence_review_threshold=settings.confidence_review_threshold,
        )
    )
    out.write_text(dossier.model_dump_json(indent=2))
    typer.echo(f"Wrote dossier to {out} (needs_review={needs_review})")



@engagement_app.command("trigger-scan")
def engagement_trigger_scan(
    universe: Path = typer.Option(...),
    signals: Path = typer.Option(None, help="JSON list of {company_id, theme, severity, detail} controversy signals."),
) -> None:
    """Runs the trigger & detection layer: opens a new issue for every
    controversy signal without an already-open issue on the same theme,
    plus an SLA sweep flagging stalled issues."""
    companies = load_company_universe(universe)
    store = _engagement_store()
    signal_list = [ControversySignal(**s) for s in json.loads(signals.read_text())] if signals else []
    source = StaticControversySource(signal_list)
    events = asyncio.run(run_trigger_screen(companies, source, store))
    events += scan_for_stalled_issues(store, get_settings().engagement_sla_days)
    for e in events:
        typer.echo(f"{e.source.value}\t{e.company_id}\t{e.theme}\t{e.severity.value}\tissue={e.raised_issue_id}")
    typer.echo(f"{len(events)} trigger event(s).")



@engagement_app.command("report")
def engagement_report(period_label: str = typer.Option(...), run_id: str = typer.Option(None, help="Include a voting run's cast votes.")) -> None:
    vote_records = []
    if run_id:
        run_store = RunStore(get_settings().runs_dir)
        for ballot in get_ballots(run_store, run_id):
            vote_records.extend(ballot.votes)
        cast_by_id = {v.vote_record_id: v for v in get_cast_votes(run_store, run_id)}
        vote_records = [cast_by_id.get(v.vote_record_id, v) for v in vote_records]
    report = compile_report(_engagement_store().list_all(), vote_records, period_label)
    typer.echo(json.dumps(report.model_dump(mode="json"), indent=2))
