from __future__ import annotations

import asyncio
from pathlib import Path

from arp.config import Settings
from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.adapters import with_run_datasets
from arp.reporting.content_planner import draft_report_plan
from arp.reporting.deck_builder import build_deck
from arp.reporting.design import theme_from_template
from arp.reporting.house_pipeline import build_house_deck, render_house_outputs
from arp.reporting.lint import lint_deck
from arp.reporting.pdf_builder import build_pdf
from arp.reporting.report_builder import build_docx
from arp.reporting.storyline import draft_storyline
from arp.schemas.reporting import Deck, OutputFormat, ReportManifest, ReportPlan, ReportRequest, ReportStatus, SlideContent
from arp.storage.reporting_store import ReportingStore

_EXTENSION = {OutputFormat.PPTX: "pptx", OutputFormat.DOCX: "docx", OutputFormat.PDF: "pdf"}


class ReportingService:
    """Orchestrates the two-step pipeline every report goes through:
    Content Planner (the one LLM call, arp.reporting.content_planner) then
    a deterministic renderer (deck_builder/report_builder/pdf_builder,
    chosen by output_format). Split into `create_and_plan` /
    `render_from_plan` rather than one `run` call so a human can review or
    hand-edit the persisted plan (ReportingStore.save_plan) before the
    final render -- exactly the same LLM-plans/code-executes shape as
    every other pipeline in this codebase.
    """

    def __init__(self, store: ReportingStore, settings: Settings | None = None) -> None:
        self.store = store
        self.settings = settings  # for run_refs; None reads get_settings() when a request has any

    async def create_and_plan(self, request: ReportRequest, llm: LLMClient) -> ReportManifest:
        manifest = ReportManifest(title=request.title, output_format=request.layout.output_format, template_id=request.template_id)
        manifest.status = ReportStatus.PLANNING
        self.store.save_request(manifest.report_id, request)
        self.store.save_manifest(manifest)

        house = request.layout.output_format == OutputFormat.HOUSE_DECK
        template_style = self.store.load_template_style(request.template_id) if request.template_id else None
        try:
            if house:
                draft, usage = await draft_storyline(request, llm)
            else:
                draft, usage = await draft_report_plan(request, llm, template_style)
        except Exception as exc:  # noqa: BLE001 -- persisted as a manifest field for API/CLI/UI visibility, not swallowed
            manifest.status = ReportStatus.FAILED
            manifest.error = str(exc)
            self.store.save_manifest(manifest)
            raise

        if house:
            self.store.save_storyline(manifest.report_id, draft)
            manifest.status = ReportStatus.STORYLINE_READY
        else:
            self.store.save_plan(manifest.report_id, draft)
            manifest.status = ReportStatus.PLAN_READY
        manifest.input_tokens = usage.input_tokens
        manifest.output_tokens = usage.output_tokens
        manifest.model = usage.model
        self.store.save_manifest(manifest)
        return manifest

    async def approve_storyline(self, report_id: str, llm: LLMClient) -> ReportManifest:
        """House deck: approves the stored storyline and builds the deck from it.
        The approval is persisted before the build. A build that failed before deck.json was written
        can be approved again (the retry); once a deck exists, re-render it instead."""
        manifest = self.store.load_manifest(report_id)
        storyline = self.store.load_storyline(report_id)
        request = self.store.load_request(report_id)
        if manifest is None or storyline is None or request is None:
            raise ValueError(f"No storyline drafted for report {report_id!r}")
        retry = manifest.status == ReportStatus.FAILED and self.store.load_deck(report_id) is None
        if storyline.approved and not retry:
            raise ValueError("Storyline already approved")
        if not storyline.slides:
            raise ValueError("Storyline has no slides")
        storyline.approved = True
        self.store.save_storyline(report_id, storyline)
        manifest.status = ReportStatus.RENDERING
        self.store.save_manifest(manifest)
        usage = LLMUsage()
        try:
            await build_house_deck(report_id, request, storyline, llm, self.store, usage, self.settings)
        except Exception as exc:  # noqa: BLE001
            manifest.status = ReportStatus.FAILED
            manifest.error = str(exc)
            self.store.save_manifest(manifest)
            raise
        finally:
            manifest.input_tokens += usage.input_tokens
            manifest.output_tokens += usage.output_tokens
        return self._completed(manifest, "output.pdf", ["output.pdf", "output.pptx"])

    async def rerun(self, report_id: str, llm: LLMClient) -> ReportManifest:
        """A new report from `report_id`'s request and approved storyline, on freshly loaded run data; the original
        is untouched. If the fresh data no longer backs a headline number, the new storyline goes back for approval
        (STORYLINE_READY, findings saved) instead of being built."""
        old, request, storyline = self.store.load_manifest(report_id), self.store.load_request(report_id), self.store.load_storyline(report_id)
        if old is None or request is None or storyline is None or not storyline.approved:
            raise ValueError(f"No approved storyline for report {report_id!r}")
        request = with_run_datasets(request, self.settings)
        storyline = storyline.model_copy(update={"approved": False})
        manifest = ReportManifest(title=old.title, output_format=old.output_format, template_id=old.template_id, status=ReportStatus.STORYLINE_READY)
        self.store.save_request(manifest.report_id, request)
        self.store.save_storyline(manifest.report_id, storyline)
        self.store.save_manifest(manifest)
        # Headlines only, numbered like the built deck (slide 0 is the title).
        heads = Deck(title=storyline.title, slides=[SlideContent(headline=h, layout="", variant="") for h in [storyline.title, *(s.headline for s in storyline.slides)]])
        stale = [f for f in lint_deck(heads, request) if f.rule == "number_not_in_source" and f.slot == "headline"]
        if stale:
            self.store.save_findings(manifest.report_id, stale)
            return manifest
        return await self.approve_storyline(manifest.report_id, llm)

    def _completed(self, manifest: ReportManifest, filename: str, files: list[str] | None = None) -> ReportManifest:
        manifest.status = ReportStatus.COMPLETED
        manifest.output_filename = filename
        manifest.output_files = files or [filename]
        manifest.error = None
        self.store.save_manifest(manifest)
        return manifest

    def render_from_plan(self, report_id: str) -> ReportManifest:
        """Renders whatever plan is currently persisted for this report --
        the LLM-drafted one, or a human-edited version saved over it via
        ReportingStore.save_plan. Never calls the model. A house deck
        re-renders its stored deck.json instead."""
        manifest = self.store.load_manifest(report_id)
        if manifest is None:
            raise ValueError(f"Unknown report_id {report_id!r}")
        if manifest.output_format == OutputFormat.HOUSE_DECK:
            return self._rerender_house_deck(manifest)
        plan = self.store.load_plan(report_id)
        if plan is None:
            raise ValueError(f"No plan drafted yet for report {report_id!r} -- call create_and_plan first")
        request = self.store.load_request(report_id)
        if request is None:
            raise ValueError(f"No request found for report {report_id!r}")

        manifest.status = ReportStatus.RENDERING
        self.store.save_manifest(manifest)

        try:
            filename = f"output.{_EXTENSION[request.layout.output_format]}"
            out_path = self.store.output_path(report_id, filename)
            template_style = self.store.load_template_style(request.template_id) if request.template_id else None
            self._render(request.layout.output_format, plan, request.datasets, request.layout, template_style, out_path)
        except Exception as exc:  # noqa: BLE001
            manifest.status = ReportStatus.FAILED
            manifest.error = str(exc)
            self.store.save_manifest(manifest)
            raise

        return self._completed(manifest, filename)

    def _rerender_house_deck(self, manifest: ReportManifest) -> ReportManifest:
        report_id = manifest.report_id
        deck, request = self.store.load_deck(report_id), self.store.load_request(report_id)
        if deck is None or request is None:
            raise ValueError(f"No deck built yet for report {report_id!r} -- approve the storyline first")
        manifest.status = ReportStatus.RENDERING
        self.store.save_manifest(manifest)
        try:
            # ponytail: asyncio.run, so this sync path can't be called from inside a running loop; make it async if that's needed.
            asyncio.run(render_house_outputs(report_id, deck, request, self.store))
        except Exception as exc:  # noqa: BLE001
            manifest.status = ReportStatus.FAILED
            manifest.error = str(exc)
            self.store.save_manifest(manifest)
            raise
        return self._completed(manifest, "output.pdf", ["output.pdf", "output.pptx"])

    @staticmethod
    def _render(output_format: OutputFormat, plan: ReportPlan, datasets, layout, template_style, out_path: Path) -> Path:
        if output_format == OutputFormat.PPTX:
            return build_deck(plan, datasets, layout, template_style, out_path)
        # docx/pdf have no template-file concept of their own, but an
        # ingested pptx template's colors/fonts still carry over -- so a
        # Word/PDF report generated alongside a pptx deck reads as the
        # same branded system rather than a generic default.
        theme = theme_from_template(template_style)
        if output_format == OutputFormat.DOCX:
            return build_docx(plan, datasets, layout, out_path, theme=theme)
        if output_format == OutputFormat.PDF:
            return build_pdf(plan, datasets, layout, out_path, theme=theme)
        raise ValueError(f"Unsupported output_format: {output_format}")

    async def run(self, request: ReportRequest, llm: LLMClient) -> ReportManifest:
        """Convenience end-to-end path (plan + render in one call) for the
        CLI and a single-request API flow. Equivalent to
        create_and_plan(...) followed immediately by render_from_plan(...)."""
        manifest = await self.create_and_plan(request, llm)
        return self.render_from_plan(manifest.report_id)
