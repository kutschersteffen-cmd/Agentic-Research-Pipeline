from __future__ import annotations

from pathlib import Path

from arp.llm.base import LLMClient
from arp.reporting.content_planner import draft_report_plan
from arp.reporting.deck_builder import build_deck
from arp.reporting.design import theme_from_template
from arp.reporting.pdf_builder import build_pdf
from arp.reporting.report_builder import build_docx
from arp.schemas.reporting import OutputFormat, ReportManifest, ReportPlan, ReportRequest, ReportStatus
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

    def __init__(self, store: ReportingStore) -> None:
        self.store = store

    async def create_and_plan(self, request: ReportRequest, llm: LLMClient) -> ReportManifest:
        manifest = ReportManifest(title=request.title, output_format=request.layout.output_format, template_id=request.template_id)
        manifest.status = ReportStatus.PLANNING
        self.store.save_request(manifest.report_id, request)
        self.store.save_manifest(manifest)

        template_style = self.store.load_template_style(request.template_id) if request.template_id else None
        try:
            plan, usage = await draft_report_plan(request, llm, template_style)
        except Exception as exc:  # noqa: BLE001 -- persisted as a manifest field for API/CLI/UI visibility, not swallowed
            manifest.status = ReportStatus.FAILED
            manifest.error = str(exc)
            self.store.save_manifest(manifest)
            raise

        self.store.save_plan(manifest.report_id, plan)
        manifest.status = ReportStatus.PLAN_READY
        manifest.input_tokens = usage.input_tokens
        manifest.output_tokens = usage.output_tokens
        manifest.model = usage.model
        self.store.save_manifest(manifest)
        return manifest

    def render_from_plan(self, report_id: str) -> ReportManifest:
        """Renders whatever plan is currently persisted for this report --
        the LLM-drafted one, or a human-edited version saved over it via
        ReportingStore.save_plan. Never calls the model."""
        manifest = self.store.load_manifest(report_id)
        if manifest is None:
            raise ValueError(f"Unknown report_id {report_id!r}")
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

        manifest.status = ReportStatus.COMPLETED
        manifest.output_filename = filename
        manifest.error = None
        self.store.save_manifest(manifest)
        return manifest

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
