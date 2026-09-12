from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import JobStatus, new_id, now_iso

# ---- Audience & layout instructions ---------------------------------------


class AudienceLevel(StrEnum):
    EXECUTIVE = "executive"
    """Time-pressured, decision-focused: headline numbers, no methodology detail."""
    TECHNICAL = "technical"
    """Analysts/specialists: methodology, caveats, full detail welcome."""
    GENERAL = "general"
    """Non-specialist readership: plain language, minimal jargon."""


class Tone(StrEnum):
    FORMAL = "formal"
    CONVERSATIONAL = "conversational"
    PERSUASIVE = "persuasive"
    NEUTRAL_ANALYTICAL = "neutral_analytical"


class AudienceProfile(BaseModel):
    """Who the deck/report is for -- the single biggest lever on how the
    Content Planner compresses and frames the same underlying material."""

    level: AudienceLevel = AudienceLevel.GENERAL
    tone: Tone = Tone.NEUTRAL_ANALYTICAL
    description: str = Field(
        default="", description="Free text, e.g. 'Investment committee, 20 minutes, wants the recommendation up front.'"
    )
    focus_areas: list[str] = Field(
        default_factory=list, description="Topics/questions this audience cares most about -- steers section ordering and emphasis."
    )


class OutputFormat(StrEnum):
    PPTX = "pptx"
    DOCX = "docx"
    PDF = "pdf"


class LayoutInstructions(BaseModel):
    """User-supplied constraints on shape and structure. Everything here is
    a *hint* the Content Planner must respect deterministically-checkable
    bounds on (target_length is enforced by the renderer, not just the
    LLM), not a suggestion it can silently ignore.
    """

    output_format: OutputFormat = OutputFormat.PPTX
    target_length: int | None = Field(
        default=None, description="Target slide count (pptx) or section count (docx/pdf). None lets the planner decide."
    )
    max_bullets_per_slide: int = Field(default=6, ge=1, le=20)
    include_title_slide: bool = True
    include_agenda_slide: bool = Field(default=True, description="pptx only: a slide listing section titles up front.")
    include_appendix: bool = Field(
        default=False, description="Route detailed/technical supporting material into a trailing appendix section rather than the main flow."
    )
    section_order_hint: list[str] = Field(
        default_factory=list, description="Preferred section titles/order, e.g. ['Executive Summary', 'Market Context', 'Financials', 'Risks']. Advisory -- the planner may add sections it judges necessary."
    )
    free_instructions: str = Field(
        default="", description="Any other layout/style direction in plain language, e.g. 'lead with the risk section', 'one chart per slide max'."
    )


# ---- Quantitative data ------------------------------------------------------


class ColumnKind(StrEnum):
    CATEGORY = "category"
    NUMBER = "number"
    DATE = "date"
    PERCENT = "percent"


class DatasetColumn(BaseModel):
    name: str
    kind: ColumnKind = ColumnKind.NUMBER


class QuantitativeDataset(BaseModel):
    """A single tabular dataset the caller wants visualized or tabulated.
    Rows are kept as plain dicts (not a fixed schema) so this accepts
    anything that round-trips through CSV/XLSX -- the renderer only cares
    that every row has the declared columns.
    """

    dataset_id: str = Field(default_factory=lambda: new_id("ds"))
    name: str
    description: str = ""
    columns: list[DatasetColumn]
    rows: list[dict] = Field(default_factory=list)

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def summary(self, max_rows: int = 8) -> str:
        """Compact, deterministic text summary fed to the Content Planner
        prompt -- never the full dataset, which could be arbitrarily large."""
        cols = ", ".join(f"{c.name} ({c.kind.value})" for c in self.columns)
        lines = [f"Dataset '{self.name}' (id={self.dataset_id}, {len(self.rows)} rows). Columns: {cols}."]
        if self.description:
            lines.append(f"Description: {self.description}")
        for row in self.rows[:max_rows]:
            lines.append(" - " + ", ".join(f"{k}={row.get(k)}" for k in self.column_names()))
        if len(self.rows) > max_rows:
            lines.append(f" ... ({len(self.rows) - max_rows} more rows)")
        return "\n".join(lines)


# ---- Template style ingestion -----------------------------------------------


class TemplateLayoutInfo(BaseModel):
    index: int
    name: str
    placeholder_types: list[str] = Field(default_factory=list)


class TemplateStyleProfile(BaseModel):
    """Deterministically extracted from an uploaded .pptx template via
    python-pptx -- never LLM-guessed. Drives DeckBuilder's layout/color/font
    choices so a generated deck matches the house style instead of a
    generic default theme.
    """

    template_id: str = Field(default_factory=lambda: new_id("tpl"))
    source_filename: str
    slide_width_emu: int
    slide_height_emu: int
    layouts: list[TemplateLayoutInfo] = Field(default_factory=list)
    theme_colors: dict[str, str] = Field(default_factory=dict, description="Named theme color -> hex string, e.g. {'accent1': 'FF5733'}.")
    major_font: str | None = None
    minor_font: str | None = None
    stored_path: str = Field(description="Where the original template file is kept on disk, so DeckBuilder can clone it as the render base.")


# ---- Content plan (LLM output, deterministically rendered) -----------------


class ChartType(StrEnum):
    BAR = "bar"
    COLUMN = "column"
    STACKED_COLUMN = "stacked_column"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    DOUGHNUT = "doughnut"
    SCATTER = "scatter"
    RADAR = "radar"
    WATERFALL = "waterfall"
    HEATMAP = "heatmap"
    TABLE = "table"
    """Not a chart at all -- an explicit signal the data reads better as a table than any chart."""


NATIVE_CHART_TYPES = {
    ChartType.BAR, ChartType.COLUMN, ChartType.STACKED_COLUMN, ChartType.LINE,
    ChartType.AREA, ChartType.PIE, ChartType.DOUGHNUT, ChartType.SCATTER, ChartType.RADAR,
}
"""Chart types python-pptx can build as a native, still-editable-in-PowerPoint chart object.
Everything else (waterfall, heatmap) is rendered to a static image instead -- see chart_builder.py."""


class ChartSpec(BaseModel):
    dataset_id: str
    chart_type: ChartType = ChartType.BAR
    title: str = ""
    category_column: str | None = Field(default=None, description="Column used for category/x-axis labels. Required for every type except scatter/heatmap.")
    value_columns: list[str] = Field(default_factory=list, description="One or more numeric columns to plot as series.")
    x_column: str | None = Field(default=None, description="scatter only: numeric column for the x-axis (category_column is unused).")
    y_column: str | None = Field(default=None, description="heatmap only: the row-axis category column (category_column is the column axis).")
    value_column: str | None = Field(default=None, description="heatmap only: the numeric cell value column.")
    notes: str = Field(default="", description="Caption/takeaway text rendered under the chart.")


class TableSpec(BaseModel):
    dataset_id: str
    columns: list[str] = Field(default_factory=list, description="Subset/order of dataset columns to include. Empty = all columns.")
    max_rows: int = Field(default=20, description="Renderer truncates to this many rows; a truncation note is added if the dataset has more.")


class ContentItem(BaseModel):
    """One paragraph or bullet of narrative text within a section."""

    text: str
    bullet: bool = True


class SectionLayoutHint(StrEnum):
    STANDARD = "standard"
    """Title + bullets, optionally a chart or table alongside."""
    CHART_FOCUS = "chart_focus"
    """Chart/table given most of the slide/page; narrative is a short caption."""
    TEXT_ONLY = "text_only"
    SECTION_HEADER = "section_header"
    """pptx only: a divider slide with just a title, no body content."""


class ReportSection(BaseModel):
    """The single content unit shared by every output format: one slide in
    a pptx, one heading + body in a docx/pdf. Keeping one plan shape across
    formats is what lets the Content Planner stay format-agnostic --
    DeckBuilder/ReportBuilder/PdfBuilder each interpret the same plan
    according to their medium's conventions.
    """

    heading: str
    layout_hint: SectionLayoutHint = SectionLayoutHint.STANDARD
    narrative: list[ContentItem] = Field(default_factory=list)
    chart: ChartSpec | None = None
    table: TableSpec | None = None
    speaker_notes: str = Field(default="", description="pptx only: presenter notes, not shown on the slide itself.")
    appendix: bool = Field(default=False, description="Routed to the appendix if layout_instructions.include_appendix is set.")


class ReportPlan(BaseModel):
    """The Content Planner's full structured output -- deliberately the
    *only* LLM-authored artifact in this pipeline. Every subsequent step
    (chart/table rendering, file assembly) is deterministic code, so the
    same plan always renders identically and can be hand-edited by a human
    between planning and rendering (see ReportingService.render_from_plan).
    """

    title: str
    subtitle: str = ""
    sections: list[ReportSection] = Field(default_factory=list)


# ---- Request / run record ---------------------------------------------------


class ReportRequest(BaseModel):
    title: str
    qualitative_notes: str = Field(description="Free-text analysis, findings, talking points -- the raw qualitative input the planner works from.")
    datasets: list[QuantitativeDataset] = Field(default_factory=list)
    audience: AudienceProfile = Field(default_factory=AudienceProfile)
    layout: LayoutInstructions = Field(default_factory=LayoutInstructions)
    template_id: str | None = Field(default=None, description="A previously ingested TemplateStyleProfile.template_id, pptx only.")


class ReportStatus(StrEnum):
    PENDING = JobStatus.PENDING.value
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    """Plan drafted and persisted, awaiting render (a human may edit the plan first)."""
    RENDERING = "rendering"
    COMPLETED = JobStatus.COMPLETED.value
    FAILED = JobStatus.FAILED.value


class ReportManifest(BaseModel):
    report_id: str = Field(default_factory=lambda: new_id("rpt"))
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    status: ReportStatus = ReportStatus.PENDING
    title: str = ""
    output_format: OutputFormat = OutputFormat.PPTX
    template_id: str | None = None
    output_filename: str | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
