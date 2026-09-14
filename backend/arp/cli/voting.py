from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _ballot_platform, _engagement_store, _registry, _run_store
from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.universe import load_company_universe
from arp.voting.pipeline import cast_approved_votes, get_ballots, run_voting

voting_app = typer.Typer(help="Proxy voting: proposal analysis, policy application, review, and ballot casting.")


@voting_app.command("run")
def voting_run(
    universe: Path = typer.Option(...),
    meeting_dates: Path = typer.Option(None, help="Optional JSON object mapping company_id -> meeting_date."),
) -> None:
    settings = get_settings()
    llm = build_llm_client(settings)
    companies = load_company_universe(universe)
    dates = json.loads(meeting_dates.read_text()) if meeting_dates else {}
    typer.echo(f"Running proxy voting analysis across {len(companies)} companies...")
    run_id = asyncio.run(
        run_voting(
            companies, llm=llm, registry=_registry(), engagement_store=_engagement_store(),
            settings=settings, run_store=_run_store(), meeting_dates=dates, fund_name=settings.fund_name,
        )
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/). Every proposal is queued for review -- use `arp voting review`.")



@voting_app.command("ballots")
def voting_ballots(run_id: str) -> None:
    for ballot in get_ballots(_run_store(), run_id):
        typer.echo(f"{ballot.company_id}\t{ballot.name}\t{len(ballot.votes)} proposal(s)")
        for v in ballot.votes:
            rec = v.policy_recommendation
            flag = " [ALIGNMENT FLAG]" if rec and rec.engagement_alignment_flag else ""
            typer.echo(f"  #{v.proposal.proposal_number} ({v.proposal.type.value}): recommend {rec.vote.value if rec else '?'}{flag}")



@voting_app.command("review")
def voting_review(
    run_id: str,
    item_key: str = typer.Argument(..., help="'{company_id}:{proposal_number}', as shown by `arp voting ballots`."),
    decision: str = typer.Option(..., help="approve | edit | reject"),
    by: str = typer.Option(...),
    vote: str = typer.Option(None, help="Required if --decision edit: for | against | abstain | withhold."),
    co_signed_by: str = typer.Option(None, help="Required before casting when the item carries an engagement alignment flag."),
    comment: str = typer.Option(None),
) -> None:
    from arp.orchestration.review_queue import record_review_decision

    if decision not in ("approve", "edit", "reject"):
        typer.echo("decision must be approve, edit, or reject", err=True)
        raise typer.Exit(1)
    if decision == "edit" and not vote:
        typer.echo("--vote is required with --decision edit", err=True)
        raise typer.Exit(1)
    edited_value = {"vote": vote, "co_signed_by": co_signed_by} if decision == "edit" else ({"co_signed_by": co_signed_by} if co_signed_by else None)
    record_review_decision(_run_store(), run_id, item_key, decision, by, edited_value, comment)
    typer.echo("Recorded.")



@voting_app.command("cast")
def voting_cast(run_id: str) -> None:
    """Ballot Casting Agent: casts every reviewed-and-approved vote not
    already cast. Never casts an item with no recorded human decision, and
    refuses an engagement-alignment-flagged item with no co-sign."""
    cast = asyncio.run(cast_approved_votes(run_id, _run_store(), _ballot_platform()))
    typer.echo(f"Cast {len(cast)} vote(s).")
    for v in cast:
        typer.echo(f"  {v.proposal.company_id} #{v.proposal.proposal_number}: {v.human_decision.vote.value} ({v.cast_confirmation.confirmation_id})")
