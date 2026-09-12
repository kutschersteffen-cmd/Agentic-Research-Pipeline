from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _reporting_store
from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.reporting.datasets import parse_tabular_upload
from arp.reporting.service import ReportingService
from arp.reporting.style_profile import ingest_template
from arp.schemas.reporting import AudienceProfile, LayoutInstructions, OutputFormat, ReportRequest

reporting_app = typer.Typer(help="Presentation & Reporting Tool: LLM-drafted content plan, deterministically rendered to pptx/docx/pdf.")


@reporting_app.command("ingest-template")
def reporting_ingest_template(pptx_path: Path = typer.Argument(..., exists=True, help="A .pptx template to extract the house style from.")) -> None:
    style = ingest_template(_reporting_store(), pptx_path, pptx_path.name)
    typer.echo(f"Ingested template {style.template_id} ({len(style.layouts)} layouts, {len(style.theme_colors)} theme colors)")
    typer.echo(json.dumps(style.model_dump(mode="json"), indent=2))


@reporting_app.command("templates")
def reporting_list_templates() -> None:
    for t in _reporting_store().list_template_styles():
        typer.echo(f"{t.template_id}\t{t.source_filename}\t{len(t.layouts)} layout(s)")


@reporting_app.command("add-dataset")
def reporting_add_dataset(
    file: Path = typer.Argument(..., exists=True, help="CSV or XLSX file."),
    out: Path = typer.Option(..., help="Where to write the parsed QuantitativeDataset JSON -- pass to `arp report run --data`."),
    name: str = typer.Option(None, help="Dataset name; defaults to the filename."),
) -> None:
    dataset = parse_tabular_upload(file.name, file.read_bytes(), name=name)
    out.write_text(dataset.model_dump_json(indent=2))
    typer.echo(f"Wrote dataset {dataset.dataset_id} ({len(dataset.rows)} rows, {len(dataset.columns)} columns) to {out}")


@reporting_app.command("run")
def reporting_run(
    title: str = typer.Option(...),
    notes: Path = typer.Option(..., exists=True, help="Text file with the qualitative notes/analysis to work from."),
    out: Path = typer.Option(..., help="Where to write the rendered output file."),
    data: list[Path] = typer.Option([], help="One or more QuantitativeDataset JSON files (see `arp report add-dataset`)."),
    template_id: str = typer.Option(None, help="A previously ingested template's template_id (`arp report ingest-template`)."),
    format: OutputFormat = typer.Option(OutputFormat.PPTX),
    audience_level: str = typer.Option("general", help="executive | technical | general"),
    audience_description: str = typer.Option(""),
    target_length: int = typer.Option(None, help="Target slide/section count."),
    layout_notes: str = typer.Option("", help="Free-text layout/style direction."),
    include_appendix: bool = typer.Option(False),
) -> None:
    """End-to-end: drafts a ReportPlan (one LLM call) and renders it
    immediately. For a review-before-render workflow, use the API's
    POST /api/reports?render=false + PUT .../plan + POST .../render instead
    -- the CLI's headless-batch use case doesn't need that intermediate
    step."""
    from arp.schemas.reporting import QuantitativeDataset

    settings = get_settings()
    llm = build_llm_client(settings)
    store = _reporting_store()
    datasets = [QuantitativeDataset.model_validate_json(p.read_text()) for p in data]
    request = ReportRequest(
        title=title,
        qualitative_notes=notes.read_text(),
        datasets=datasets,
        audience=AudienceProfile(level=audience_level, description=audience_description),
        layout=LayoutInstructions(
            output_format=format, target_length=target_length, free_instructions=layout_notes, include_appendix=include_appendix
        ),
        template_id=template_id,
    )
    service = ReportingService(store)
    manifest = asyncio.run(service.run(request, llm))
    if manifest.status.value == "failed":
        typer.echo(f"Failed: {manifest.error}", err=True)
        raise typer.Exit(1)
    import shutil

    output_path = store.output_path(manifest.report_id, manifest.output_filename)
    shutil.copyfile(output_path, out)
    typer.echo(f"Report {manifest.report_id} rendered to {out}")


@reporting_app.command("list")
def reporting_list() -> None:
    for m in _reporting_store().list_reports():
        typer.echo(f"{m.report_id}\t{m.status.value}\t{m.output_format.value}\t{m.title}")


@reporting_app.command("show")
def reporting_show(report_id: str) -> None:
    manifest = _reporting_store().load_manifest(report_id)
    if manifest is None:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(manifest.model_dump(mode="json"), indent=2))
