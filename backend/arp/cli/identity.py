from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _run_store, cli_principal
from arp.config import get_settings
from arp.discovery.identity_pipeline import enriched_universe, run_identity_resolution
from arp.llm.factory import build_llm_client
from arp.universe import load_company_universe

identity_app = typer.Typer(help="Agentic company identity resolution: resolve bare company names to website/CIK before discovery.")


@identity_app.command("resolve")
def identity_resolve(
    names_file: Path = typer.Option(
        ..., "--names-file", help="CSV/JSON of company names (same shape arp.universe.load_company_universe reads; website/cik not required)."
    ),
) -> None:
    """Resolves each company's real-world identity (website/CIK) via the
    propose -> resolve -> challenge -> adjudicate graph -- a separate,
    one-time-per-company enrichment run, not part of document discovery
    itself. Anything ambiguous is queued for review (`arp identity
    review-queue` / `arp identity review`) instead of guessed. Once
    resolved, export a usable universe with `arp identity
    enriched-universe` and feed it into `arp discover run --universe`.
    """
    settings = get_settings()
    companies = load_company_universe(names_file)
    llm = build_llm_client(settings)
    run_store = _run_store()
    typer.echo(f"Resolving identity for {len(companies)} companies...")
    run_id = asyncio.run(run_identity_resolution(companies, llm=llm, settings=settings, run_store=run_store))
    manifest = run_store.load_manifest(run_id)
    typer.echo(f"Run complete: {run_id} ({manifest.review_count}/{len(companies)} flagged for review)")



@identity_app.command("review-queue")
def identity_review_queue(run_id: str) -> None:
    import os

    from arp.api.auth import Principal
    from arp.review.items import list_open_items

    settings = get_settings()
    if settings.auth_mode == "dev" and not os.environ.get("ARP_CLI_TOKEN", "").strip():  # as current_user's dev bypass
        principal = Principal(user_id=settings.dev_user, name=settings.dev_user, role="approver")
    else:
        principal = cli_principal(settings)
    items = list_open_items(_run_store(), principal, run_id=run_id)
    if not items:
        typer.echo("Nothing pending review.")
        return
    for i in items:
        r = i.payload
        flag = " (escalated)" if i.escalated else ""
        typer.echo(f"{i.item_key} [{i.state}{flag}]: {r.get('input_name')!r} -> verdict={r.get('verdict')} "
                   f"confidence={r.get('confidence') or 0:.2f}")
        typer.echo(f"  rationale: {r.get('rationale')}")



@identity_app.command("review")
def identity_review(
    run_id: str,
    item_key: str = typer.Argument(..., help="The company_id, as shown by `arp identity review-queue`."),
    decision: str = typer.Option(..., help="approve | correct | reject | escalate"),
    reason: str = typer.Option(None, help="Decision reason (approve: confirmed, the default; else e.g. wrong_entity)."),
    website: str = typer.Option(None, help="Corrected website. With --decision correct, at least one of --website/--cik is required."),
    cik: str = typer.Option(None, help="Corrected CIK."),
    comment: str = typer.Option(None, help="Required with --decision correct: the source of the correction."),
) -> None:
    from pydantic import ValidationError

    from arp.cli._shared import _document_content_store
    from arp.review.context import build_context
    from arp.review.decide import DecisionError, decide
    from arp.schemas.review import ItemDecisionRequest

    if decision not in ("approve", "correct", "reject", "escalate"):
        typer.echo("decision must be approve, correct, reject or escalate", err=True)
        raise typer.Exit(1)
    if decision != "approve" and not reason:
        typer.echo("--reason is required with --decision " + decision, err=True)
        raise typer.Exit(1)
    if decision == "correct" and not (website or cik):
        typer.echo("--website and/or --cik is required with --decision correct", err=True)
        raise typer.Exit(1)
    if decision == "correct" and not (comment or "").strip():
        typer.echo("--comment naming the correction's source is required with --decision correct", err=True)
        raise typer.Exit(1)
    settings, run_store, content_store = get_settings(), _run_store(), _document_content_store()
    principal = cli_principal(settings)
    bundle = build_context(run_store, run_id, item_key, principal, settings=settings, content_store=content_store)
    if bundle is None:
        typer.echo("Review item not found.", err=True)
        raise typer.Exit(1)
    try:
        req = ItemDecisionRequest(
            decision=decision, reason_code=reason or "confirmed",
            corrected_value={"resolved_website": website, "resolved_cik": cik} if decision == "correct" else None,
            comment=comment, context_etag=bundle["etag"],
        )
        out = decide(run_store, run_id, item_key, req, principal, settings=settings, content_store=content_store)
    except ValidationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    except DecisionError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Recorded ({out['state']}).")



@identity_app.command("enriched-universe")
def identity_enriched_universe(
    run_id: str, out: Path = typer.Option(..., help="Where to write the enriched universe JSON.")
) -> None:
    """Writes a normal company universe (website/cik filled in for every
    resolved-and-clean or reviewer-approved company), directly usable as
    `arp discover run --universe <out>`."""
    run_store = _run_store()
    companies = enriched_universe(run_store, run_id)
    out.write_text(json.dumps([c.model_dump(mode="json") for c in companies], indent=2))
    typer.echo(f"Wrote {len(companies)} resolved companies to {out}")
