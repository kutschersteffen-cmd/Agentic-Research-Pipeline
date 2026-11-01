from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.cost_tracker import estimate_cost_usd
from arp.pageindex.navigate import TreeError, run_document
from arp.transition_plan.indicators import load_indicators

pageindex_app = typer.Typer(help="PageIndex: answer the transition-plan indicators by LLM navigation of a PDF's page tree.")


def make_llm() -> tuple[LLMClient, str]:
    from arp.config import get_settings
    from arp.llm.factory import build_llm_client

    settings = get_settings()
    return build_llm_client(settings), settings.llm_model


def cost(usages: list[LLMUsage], model: str) -> float:
    return sum(estimate_cost_usd(u.model or model, u) for u in usages)


async def run_or_exit(pdf: Path, indicators, llm: LLMClient, model: str) -> tuple[dict, list[LLMUsage]]:
    try:
        return await run_document(pdf, indicators, llm, model)
    except TreeError as exc:
        typer.echo(f"Could not build page tree: {exc}", err=True)
        raise typer.Exit(1) from exc


@pageindex_app.command("run")
def pageindex_run(
    pdf: Path = typer.Option(..., "--pdf", exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    indicator: list[str] = typer.Option(None, "--indicator", help="Indicator identifier, e.g. A_headline_1. Repeatable."),
) -> None:
    indicators = [i for i in load_indicators() if not indicator or i.identifier in indicator]
    llm, model = make_llm()
    data, usages = asyncio.run(run_or_exit(pdf, indicators, llm, model))
    out.write_text(json.dumps(data, indent=1))
    res = data["results"]
    line = (f"PageIndex: {len(res)} indicators, {sum(r['answer'] == 'YES' for r in res)} YES, "
            f"{sum(len(r['pages_opened']) for r in res)} pages read, ${cost(usages, model):.2f}")
    errors = sum(r["answer"] == "ERROR" for r in res)
    typer.echo(line + (f", {errors} errors" if errors else ""))
