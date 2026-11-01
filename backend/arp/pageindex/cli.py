from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.cost_tracker import estimate_cost_usd
from arp.pageindex import golden as G
from arp.pageindex import tree as tree_mod
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


async def run_or_exit(pdf: Path, indicators, llm: LLMClient, model: str, pages=None) -> tuple[dict, list[LLMUsage]]:
    try:
        return await run_document(pdf, indicators, llm, model, pages)
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


@pageindex_app.command("golden")
def pageindex_golden(
    cases: Path = typer.Option(..., "--cases", exists=True, dir_okay=False),
    documents_dir: Path = typer.Option(None, "--documents-dir", help="Holds <company_id>/<document>. Defaults to the cases file's documents/ sibling."),
    min_recall: float = typer.Option(0.0, "--min-recall", min=0.0, max=1.0),
) -> None:
    rows = json.loads(cases.read_text())
    ddir = documents_dir or cases.parent / "documents"
    llm, model = make_llm()
    results: dict[str, dict] = {}
    pages: dict[str, list[str]] = {}
    for company_id, document in dict.fromkeys((r["company_id"], r["document"]) for r in rows):
        try:
            pdf = G.ensure_document(cases, ddir, company_id, document)
        except G.GoldenError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        fields = {r["field_id"] for r in rows if r["document"] == document}
        indicators = [i for i in load_indicators() if G.field_id(i.identifier) in fields]
        pages[document] = tree_mod.page_texts(pdf)
        data, _ = asyncio.run(run_or_exit(pdf, indicators, llm, model, pages[document]))
        by_id = {i.identifier: G.field_id(i.identifier) for i in indicators}
        results[document] = {by_id[r["identifier"]]: r for r in data["results"]}
    hit, total, stale, yes_rate = G.score(rows, results, pages)
    recall = hit / total if total else 0.0
    typer.echo(f"PageIndex golden: recall {recall:.2f} ({hit}/{total}), yes-rate {yes_rate:.2f}, stale {stale}")
    if recall < min_recall:
        raise typer.Exit(1)
