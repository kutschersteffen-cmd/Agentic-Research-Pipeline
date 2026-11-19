from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import click
import typer

from arp.cli._shared import _reporting_store
from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.reporting.datasets import parse_tabular_upload
from arp.reporting.scheduler import ReportScheduler
from arp.reporting.service import ReportingService
from arp.reporting.storyline import content_cap
from arp.reporting.style_profile import ingest_template
from arp.schemas.reporting import (
    AudienceProfile,
    DeckSettings,
    LayoutInstructions,
    OutputFormat,
    QuantitativeDataset,
    ReportImageIn,
    ReportPlan,
    ReportRequest,
    RunRef,
)
from arp.storage.report_images import ImageError, check_known, check_name, check_unique_and_count, decode_image, parse_focus
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
    goal: str = "",
    theme: str = "light",
    run_ref: list[str] = (),
    deck: DeckSettings | None = None,
) -> ReportRequest:
    datasets = [QuantitativeDataset.model_validate_json(p.read_text()) for p in data]
    try:
        run_refs = [RunRef(kind=kind, ref_id=ref_id) for kind, _, ref_id in (r.partition(":") for r in run_ref)]
    except ValueError as exc:
        raise typer.BadParameter(f"--run-ref takes kind:id, kind one of decision|run ({exc})") from exc
    return ReportRequest(
        title=title,
        goal=goal,
        run_refs=run_refs,
        qualitative_notes=notes.read_text(),
        datasets=datasets,
        audience=AudienceProfile(level=audience_level, description=audience_description),
        layout=LayoutInstructions(
            output_format=format, target_length=target_length, free_instructions=layout_notes, include_appendix=include_appendix, theme=theme,
        ),
        template_id=template_id,
        deck=deck or DeckSettings(),
    )


def _copy_rendered_output(store: ReportingStore, manifest, out: Path) -> None:
    output_path = store.output_path(manifest.report_id, manifest.output_filename)
    shutil.copyfile(output_path, out)


def _pairs(values: list[str], flag: str) -> list[tuple[str, str]]:
    out = []
    for v in values:
        name, sep, rest = v.partition("=")
        if not sep:
            raise ImageError(f"{flag} takes NAME=VALUE (got {v!r})")
        out.append((name, rest))
    return out


def _stage_cli_images(
    store: ReportingStore, format: OutputFormat, image: list[str], image_alt: list[str], image_focus: list[str], cover_image: str | None,
) -> list[ReportImageIn]:
    """Checks every image flag and file, then stages the files: a bad one fails before any report exists."""
    given = [flag for flag, v in (("--image", image), ("--image-alt", image_alt), ("--image-focus", image_focus), ("--cover-image", cover_image)) if v]
    try:
        if given and format != OutputFormat.HOUSE_DECK:
            raise ImageError(f"{given[0]} needs --format house_deck")
        files = []
        for name, path in _pairs(image, "--image"):
            check_name(name)
            if not Path(path).is_file():
                raise ImageError(f"image '{name}': file not found: {path}")
            data = Path(path).read_bytes()
            decode_image(data, name)
            files.append((name, data))
        names = [n for n, _ in files]
        check_unique_and_count(names)
        focus = {n: parse_focus(n, v) for n, v in _pairs(image_focus, "--image-focus")}
        alt = dict(_pairs(image_alt, "--image-alt"))
        for n in [*alt, *focus, *([cover_image] if cover_image else [])]:
            check_known(n, names)
        if too_long := [n for n, a in alt.items() if len(a) > 200]:
            raise ImageError(f"alt text for '{too_long[0]}' is longer than 200 characters")
        return [
            ReportImageIn(image_id=store.stage_image(data, name).image_id, name=name, alt=alt.get(name, ""), focus=focus.get(name))
            for name, data in files
        ]
    except ImageError as exc:
        # Printed plainly rather than as typer.BadParameter: rich would wrap the message inside its error box.
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


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
    goal: str = typer.Option("", help="House deck: the decision or question the deck serves."),
    theme: str = typer.Option("light", click_type=click.Choice(["light", "dark"]), metavar="light|dark", help="House deck colour mode."),
    run_ref: list[str] = typer.Option([], help="House deck: pipeline output to load as data, kind:id (kind is decision or run); repeatable."),
    max_slides: int = typer.Option(12, min=3, max=25, help="House deck: most content slides (the executive profile keeps at most 8)."),
    profile: str = typer.Option("committee", click_type=click.Choice(["executive", "client_pitch", "committee", "workshop"]), help="House deck: storyline arc."),
    purpose: str = typer.Option("recommendation", click_type=click.Choice(["recommendation", "review", "process", "briefing"]), help="House deck: what the deck is for."),
    detail: str = typer.Option("balanced", click_type=click.Choice(["concise", "balanced", "comprehensive"]), help="House deck: how much detail per slide."),
    image: list[str] = typer.Option([], help="House deck: an image the deck may show, NAME=PATH (PNG or JPEG); repeatable."),
    image_alt: list[str] = typer.Option([], help="House deck: alt text for an image, NAME=TEXT; repeatable."),
    image_focus: list[str] = typer.Option([], help="House deck: the point a crop keeps, NAME=X,Y (each 0 to 1); repeatable."),
    cover_image: str = typer.Option(None, help="House deck: the registered image drawn behind the cover."),
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
        goal=goal, theme=theme, run_ref=run_ref,
        deck=DeckSettings(profile=profile, purpose=purpose, detail=detail, max_slides=max_slides, cover_image=cover_image),
    )
    if format == OutputFormat.HOUSE_DECK and target_length and target_length > content_cap(request):
        raise typer.BadParameter(
            f"--target-length {target_length} is more than the deck keeps ({content_cap(request)}); raise --max-slides or pick another --profile",
            param_hint="--target-length",
        )
    request.images = _stage_cli_images(store, format, image, image_alt, image_focus, cover_image)
    service = ReportingService(store, settings)
    manifest = asyncio.run(service.create_and_plan(request, llm))
    if format == OutputFormat.HOUSE_DECK:
        storyline = store.load_storyline(manifest.report_id)
        out.write_text(storyline.model_dump_json(indent=2))
        for i, s in enumerate(storyline.slides, 1):
            typer.echo(f"{i}. {s.headline}")
        typer.echo(f"Storyline written to {out}. When the headlines are right: arp report approve {manifest.report_id}")
        return
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
        manifest = asyncio.run(service.render_from_plan(report_id))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if manifest.status.value == "failed":
        typer.echo(f"Failed: {manifest.error}", err=True)
        raise typer.Exit(1)
    _copy_rendered_output(store, manifest, out)
    typer.echo(f"Report {manifest.report_id} rendered to {out}")


@reporting_app.command("approve")
def reporting_approve(report_id: str) -> None:
    """House deck: approves the drafted storyline and builds the deck: output.pdf, output.pptx and slide previews."""
    store = _reporting_store()
    try:
        manifest = asyncio.run(ReportingService(store).approve_storyline(report_id, build_llm_client(get_settings())))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    findings = store.load_findings(report_id)
    typer.echo(f"Report {report_id} built: {', '.join(manifest.output_files)} ({len(findings)} finding(s))")
    for f in findings:
        typer.echo(f"  slide {f.slide}{f' [{f.slot}]' if f.slot else ''} {f.stage}/{f.rule}: {f.message}")


@reporting_app.command("rerun")
def reporting_rerun(report_id: str) -> None:
    """House deck: re-runs an approved storyline on fresh pipeline data, as a new report."""
    settings = get_settings()
    try:
        manifest = asyncio.run(ReportingService(_reporting_store(), settings).rerun(report_id, build_llm_client(settings)))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Report {manifest.report_id}: {manifest.status.value}")


@reporting_app.command("schedule")
def reporting_schedule(
    every_hours: int = typer.Option(None, min=1, help="Re-run interval in hours (default 720, about monthly)."),
    add: list[str] = typer.Option([], help="Report id to re-run on the schedule; repeatable."),
    remove: list[str] = typer.Option([], help="Report id to take off the schedule; repeatable."),
    enable: bool = typer.Option(None, "--enable/--disable"),
) -> None:
    """Edits the periodic re-run schedule. The API server process owns the scheduler and picks this up on start."""
    settings = get_settings()
    scheduler = ReportScheduler(settings, llm_factory=lambda: build_llm_client(settings))
    config = scheduler.load_config()
    if every_hours is not None:
        config.interval_hours = every_hours
    if enable is not None:
        config.enabled = enable
    config.report_ids = [r for r in dict.fromkeys([*config.report_ids, *add]) if r not in remove]
    scheduler.save_config(config)
    typer.echo(f"Schedule saved: enabled={config.enabled}, every {config.interval_hours}h, reports={', '.join(config.report_ids) or 'none'}")


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
    try:
        manifest = asyncio.run(service.run(request, llm))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
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


@reporting_app.command("sheet")
def reporting_sheet(out: Path = typer.Option(..., help="Directory for the review sheet PNGs.")) -> None:
    """Renders the slide-component review sheet: one 1920×1080 PNG per fixture slide, named like the mockups, plus sheet.png."""
    from arp.reporting.sheet import write_sheet

    paths = write_sheet(out)
    typer.echo(f"Wrote {len(paths)} PNGs to {out}")


@reporting_app.command("flow")
def reporting_flow(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="A Mermaid flowchart (.mmd)."),
    out: str = typer.Option(..., help="Directory for flow.pptx, flow.pdf and flow.png; created if missing."),
    headline: str | None = typer.Option(None, help="Slide headline; default: FILE's name without its extension."),
    kicker: str = typer.Option("", help="Slide kicker."),
    theme: str = typer.Option("light", click_type=click.Choice(["light", "dark"]), metavar="light|dark", help="Colour mode."),
) -> None:
    """Turns one Mermaid flowchart into one house slide (PPTX, PDF, 1920×1080 PNG); no report, database or model."""
    from arp.reporting.browser import write_pdf, write_pngs
    from arp.reporting.flow_layout import layout_flows
    from arp.reporting.house_pptx import build_house_pptx
    from arp.reporting.house_style import load_tokens
    from arp.reporting.html_render import render_deck_html
    from arp.reporting.mermaid_flow import MermaidError, parse_mermaid
    from arp.schemas.reporting import Deck, SlideContent
    from arp.schemas.visuals import Flow

    text = file.read_text(encoding="utf-8")
    try:
        parse_mermaid(text)
    except MermaidError as exc:  # the parser's message is the whole error; nothing is written
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    title = file.stem if headline is None else headline
    deck = Deck(title=title, slides=[SlideContent(headline=title, kicker=kicker, visual=Flow(mermaid=text))])
    tokens = load_tokens()
    dest = Path(out)

    async def write() -> list:
        laid, findings = await layout_flows(deck, tokens, theme)
        html = render_deck_html(laid, [], tokens, theme)
        await write_pdf(html, dest / "flow.pdf")
        (page,) = await write_pngs(html, dest, scale=1)
        page.replace(dest / "flow.png")
        build_house_pptx(laid, [], dest / "flow.pptx", tokens, theme)
        return findings

    for f in asyncio.run(write()):
        typer.echo(f"{f.rule}: {f.message}", err=True)
    typer.echo(f"Wrote flow.pptx, flow.pdf, flow.png to {out}")
