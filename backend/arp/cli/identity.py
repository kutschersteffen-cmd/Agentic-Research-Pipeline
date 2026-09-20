from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _run_store
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
    run_store = _run_store()
    from arp.orchestration.review_queue import latest_decisions

    rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    pending = [r for r in rows if r["item_key"] not in decisions]
    if not pending:
        typer.echo("Nothing pending review.")
        return
    for r in pending:
        typer.echo(f"{r['item_key']}: {r['input_name']!r} -> verdict={r['verdict']} confidence={r['confidence']:.2f}")
        typer.echo(f"  rationale: {r['rationale']}")



@identity_app.command("review")
def identity_review(
    run_id: str,
    item_key: str = typer.Argument(..., help="The company_id, as shown by `arp identity review-queue`."),
    decision: str = typer.Option(..., help="approve | edit | reject"),
    by: str = typer.Option(...),
    website: str = typer.Option(None, help="Corrected website. With --decision edit, at least one of --website/--cik is required."),
    cik: str = typer.Option(None, help="Corrected CIK."),
    comment: str = typer.Option(None),
) -> None:
    from arp.orchestration.review_queue import record_review_decision

    if decision not in ("approve", "edit", "reject"):
        typer.echo("decision must be approve, edit, or reject", err=True)
        raise typer.Exit(1)
    if decision == "edit" and not (website or cik):
        typer.echo("--website and/or --cik is required with --decision edit", err=True)
        raise typer.Exit(1)
    edited_value = {"resolved_website": website, "resolved_cik": cik} if decision == "edit" else None
    record_review_decision(_run_store(), run_id, item_key, decision, by, edited_value, comment)
    typer.echo("Recorded.")



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
