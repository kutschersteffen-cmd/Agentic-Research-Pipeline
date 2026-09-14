from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import typer

from arp.cli._shared import _reporting_store
from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.reporting.datasets import parse_tabular_upload
from arp.reporting.service import ReportingService
from arp.reporting.style_profile import ingest_template
from arp.schemas.reporting import (
    AudienceProfile,
    LayoutInstructions,
    OutputFormat,
    QuantitativeDataset,
    ReportPlan,
    ReportRequest,
)
from arp.storage.reporting_store import ReportingStore

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
    out: Path = typer.Option(..., help="Where to write the parsed QuantitativeDataset JSON -- pass to `arp report run/plan --data`."),
    name: str = typer.Option(None, help="Dataset name; defaults to the filename."),
) -> None:
    dataset = parse_tabular_upload(file.name, file.read_bytes(), name=name)
    out.write_text(dataset.model_dump_json(indent=2))
    typer.echo(f"Wrote dataset {dataset.dataset_id} ({len(dataset.rows)} rows, {len(dataset.columns)} columns) to {out}")


def _build_request(
    *,
    title: str,
    notes: Path,
    data: list[Path],
    template_id: str | None,
    format: OutputFormat,
    audience_level: str,
    audience_description: str,
    target_length: int | None,
    layout_notes: str,
    include_appendix: bool,
) -> ReportRequest:
    datasets = [QuantitativeDataset.model_validate_json(p.read_text()) for p in data]
    return ReportRequest(
        title=title,
        qualitative_notes=notes.read_text(),
        datasets=datasets,
        audience=AudienceProfile(level=audience_level, description=audience_description),
        layout=LayoutInstructions(
            output_format=format, target_length=target_length, free_instructions=layout_notes, include_appendix=include_appendix
        ),
        template_id=template_id,
    )


def _copy_rendered_output(store: ReportingStore, manifest, out: Path) -> None:
    output_path = store.output_path(manifest.report_id, manifest.output_filename)
    shutil.copyfile(output_path, out)


_REQUEST_OPTIONS = {
    "title": typer.Option(...),
    "notes": typer.Option(..., exists=True, help="Text file with the qualitative notes/analysis to work from."),
    "data": typer.Option([], help="One or more QuantitativeDataset JSON files (see `arp report add-dataset`)."),
    "template_id": typer.Option(None, help="A previously ingested template's template_id (`arp report ingest-template`)."),
    "format": typer.Option(OutputFormat.PPTX),
    "audience_level": typer.Option("general", help="executive | technical | general"),
    "audience_description": typer.Option(""),
    "target_length": typer.Option(None, help="Target slide/section count."),
    "layout_notes": typer.Option("", help="Free-text layout/style direction."),
    "include_appendix": typer.Option(False),
}


@reporting_app.command("plan")
def reporting_plan(
    title: str = _REQUEST_OPTIONS["title"],
    notes: Path = _REQUEST_OPTIONS["notes"],
    out: Path = typer.Option(..., help="Where to write the drafted ReportPlan JSON, for hand-editing."),
    data: list[Path] = _REQUEST_OPTIONS["data"],
    template_id: str = _REQUEST_OPTIONS["template_id"],
    format: OutputFormat = _REQUEST_OPTIONS["format"],
    audience_level: str = _REQUEST_OPTIONS["audience_level"],
    audience_description: str = _REQUEST_OPTIONS["audience_description"],
    target_length: int = _REQUEST_OPTIONS["target_length"],
    layout_notes: str = _REQUEST_OPTIONS["layout_notes"],
    include_appendix: bool = _REQUEST_OPTIONS["include_appendix"],
) -> None:
    """Drafts a ReportPlan (the one LLM call) and stops -- does not render.
    Review/edit the written plan JSON by hand, then either push your edits
    back with `arp report update-plan <report_id> <edited.json>` or render
    the plan as-is with `arp report render <report_id> --out <file>`."""
    settings = get_settings()
    llm = build_llm_client(settings)
    store = _reporting_store()
    request = _build_request(
        title=title, notes=notes, data=data, template_id=template_id, format=format,
        audience_level=audience_level, audience_description=audience_description,
        target_length=target_length, layout_notes=layout_notes, include_appendix=include_appendix,
    )
    service = ReportingService(store)
    manifest = asyncio.run(service.create_and_plan(request, llm))
    plan = store.load_plan(manifest.report_id)
    out.write_text(plan.model_dump_json(indent=2))
    typer.echo(f"Report {manifest.report_id} planned ({len(plan.sections)} section(s)). Plan written to {out}")
    typer.echo(f"Edit {out} then run: arp report update-plan {manifest.report_id} {out}")
    typer.echo(f"When ready: arp report render {manifest.report_id} --out <output file>")


@reporting_app.command("show-plan")
def reporting_show_plan(
    report_id: str,
    out: Path = typer.Option(None, help="Also write the plan JSON to this file."),
) -> None:
    """Prints (and optionally saves) the plan currently stored for a
    report -- the one that `render` will use, including any prior edits
    made via `update-plan`."""
    store = _reporting_store()
    plan = store.load_plan(report_id)
    if plan is None:
        typer.echo("No plan found for this report_id", err=True)
        raise typer.Exit(1)
    text = plan.model_dump_json(indent=2)
    if out:
        out.write_text(text)
        typer.echo(f"Wrote plan to {out}")
    else:
        typer.echo(text)


@reporting_app.command("update-plan")
def reporting_update_plan(report_id: str, plan_file: Path = typer.Argument(..., exists=True, help="An edited ReportPlan JSON file.")) -> None:
    """Overwrites the stored plan for a report with a hand-edited version
    -- reorder sections, swap a chart_type, rewrite narrative text,
    anything in the ReportPlan schema. The next `arp report render` call
    renders exactly this."""
    store = _reporting_store()
    if store.load_manifest(report_id) is None:
        typer.echo("Unknown report_id", err=True)
        raise typer.Exit(1)
    plan = ReportPlan.model_validate_json(plan_file.read_text())
    store.save_plan(report_id, plan)
    typer.echo(f"Updated plan for {report_id} ({len(plan.sections)} section(s)).")


@reporting_app.command("render")
def reporting_render(report_id: str, out: Path = typer.Option(..., help="Where to write the rendered output file.")) -> None:
    """Deterministically renders whatever plan is currently stored for
    this report -- no LLM call. Run this after `arp report plan` (and any
    `update-plan` edits) once the plan looks right."""
    store = _reporting_store()
    service = ReportingService(store)
    try:
        manifest = service.render_from_plan(report_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if manifest.status.value == "failed":
        typer.echo(f"Failed: {manifest.error}", err=True)
        raise typer.Exit(1)
    _copy_rendered_output(store, manifest, out)
    typer.echo(f"Report {manifest.report_id} rendered to {out}")


@reporting_app.command("run")
def reporting_run(
    title: str = _REQUEST_OPTIONS["title"],
    notes: Path = _REQUEST_OPTIONS["notes"],
    out: Path = typer.Option(..., help="Where to write the rendered output file."),
    data: list[Path] = _REQUEST_OPTIONS["data"],
    template_id: str = _REQUEST_OPTIONS["template_id"],
    format: OutputFormat = _REQUEST_OPTIONS["format"],
    audience_level: str = _REQUEST_OPTIONS["audience_level"],
    audience_description: str = _REQUEST_OPTIONS["audience_description"],
    target_length: int = _REQUEST_OPTIONS["target_length"],
    layout_notes: str = _REQUEST_OPTIONS["layout_notes"],
    include_appendix: bool = _REQUEST_OPTIONS["include_appendix"],
) -> None:
    """End-to-end: drafts a ReportPlan (one LLM call) and renders it
    immediately, with no review step. For a review-before-render
    workflow, use `arp report plan` + (optionally) `arp report
    update-plan` + `arp report render` instead."""
    settings = get_settings()
    llm = build_llm_client(settings)
    store = _reporting_store()
    request = _build_request(
        title=title, notes=notes, data=data, template_id=template_id, format=format,
        audience_level=audience_level, audience_description=audience_description,
        target_length=target_length, layout_notes=layout_notes, include_appendix=include_appendix,
    )
    service = ReportingService(store)
    manifest = asyncio.run(service.run(request, llm))
    if manifest.status.value == "failed":
        typer.echo(f"Failed: {manifest.error}", err=True)
        raise typer.Exit(1)
    _copy_rendered_output(store, manifest, out)
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
