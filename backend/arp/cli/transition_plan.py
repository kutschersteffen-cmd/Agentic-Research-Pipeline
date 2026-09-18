from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _registry, _run_store
from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.transition_plan.indicators import load_indicators
from arp.transition_plan.pipeline import run_transition_plan_assessment
from arp.universe import load_company_universe

transition_plan_app = typer.Typer(help="Transition Plan Assessment: the 64-indicator RAG walk/talk disclosure assessment (Colesanti Senni et al. 2024).")


@transition_plan_app.command("indicators")
def transition_plan_indicators(out: Path = typer.Option(None, help="Write the 64 indicators as JSON here; omit to print a summary.")) -> None:
    indicators = load_indicators()
    if out:
        out.write_text(json.dumps([i.model_dump(mode="json") for i in indicators], indent=2))
        typer.echo(f"Wrote {len(indicators)} indicators to {out}")
        return
    for i in indicators:
        typer.echo(f"{i.number:>2}. [{i.category.value}/{i.walk_or_talk.value}] {i.question}")



@transition_plan_app.command("run")
def transition_plan_run(
    universe: Path = typer.Option(...),
) -> None:
    """Assesses each company's climate transition disclosures against the
    64 indicators from Colesanti Senni et al. (2024) -- target-setting
    ("talk") vs. concrete implementation ("walk") -- via one grounded RAG
    verdict per indicator, with the same programmatic citation-grounding
    check as `extract run`."""
    settings = get_settings()
    llm = build_llm_client(settings)
    companies = load_company_universe(universe)
    typer.echo(f"Assessing transition plans across {len(companies)} companies against 64 indicators...")
    run_id = asyncio.run(
        run_transition_plan_assessment(companies, llm=llm, registry=_registry(), settings=settings, run_store=_run_store())
    )
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")
