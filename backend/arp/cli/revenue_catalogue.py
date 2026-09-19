from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _resolve_taxonomy_ref_or_exit
from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.research.revenue_exposure.catalogue import distinct_labels, load_catalogue
from arp.research.revenue_exposure.mapping import suggest_catalogue_mapping

revenue_catalogue_app = typer.Typer(help="Structured revenue/capex data catalogue mapping.")


@revenue_catalogue_app.command("suggest-mapping")
def revenue_catalogue_suggest_mapping(
    taxonomy_ref: str,
    catalogue_file: Path = typer.Argument(..., help="A structured revenue/capex catalogue CSV."),
    out: Path = typer.Option(..., help="Where to write the draft activity->catalogue-label mapping JSON (review before use)."),
) -> None:
    """Proposes which catalogue labels represent each taxonomy activity's
    revenue/capex, for both metrics -- a draft only; review/edit the output
    file, then pass it to `theme run --catalogue-mapping`. Never applied
    automatically."""
    settings = get_settings()
    llm = build_llm_client(settings)
    taxonomy = _resolve_taxonomy_ref_or_exit(taxonomy_ref)
    catalogue = load_catalogue(catalogue_file)
    labels_by_metric = {"revenue": distinct_labels(catalogue, "revenue"), "capex": distinct_labels(catalogue, "capex")}
    mappings, _usage = asyncio.run(suggest_catalogue_mapping(taxonomy.theme, labels_by_metric, llm))
    out.write_text(json.dumps([m.model_dump(mode="json") for m in mappings], indent=2))
    typer.echo(f"Wrote {len(mappings)} proposed mapping(s) to {out}. Review before using with `theme run --catalogue-mapping`.")
