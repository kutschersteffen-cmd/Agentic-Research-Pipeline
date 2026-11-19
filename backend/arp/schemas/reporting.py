from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.chart_specs import NATIVE_CHART_TYPES, ChartSpec, ChartType, TableSpec  # noqa: F401  (re-exported)
from arp.schemas.common import JobStatus, new_id, now_iso
from arp.schemas.visuals import Figure, NextAction, SectionPlan, Visual, Words

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
    HOUSE_DECK = "house_deck"


class LayoutInstructions(BaseModel):
    """User-supplied constraints on shape and structure. Everything here is
    a *hint* the Content Planner must respect deterministically-checkable
    bounds on (target_length is enforced by the renderer, not just the
    LLM), not a suggestion it can silently ignore.
    """

    output_format: OutputFormat = OutputFormat.PPTX
    theme: Literal["light", "dark"] = Field(default="light", description="House deck colour mode; mirrors the app's light/dark themes.")
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


class Box(BaseModel):
    """A rectangle in house-canvas px (the slide width maps to 1920)."""

    x: float
    y: float
    w: float
    h: float


class FrameFont(BaseModel):
    family: str
    size_px: float
    bold: bool


class TemplateFrame(BaseModel):
    """Where a company template puts the headline, subheading and body, and in which fonts."""

    layout_name: str
    headline: Box
    subheading: Box
    body: Box
    headline_font: FrameFont
    subheading_font: FrameFont
    body_font_family: str


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
    frame: TemplateFrame | None = Field(default=None, description="Headline/subheading/body boxes for house decks; None when the template can't frame one.")
    frame_error: str | None = Field(default=None, description="Why `frame` is None, when it was checked.")
    font_dir: str | None = None


# ---- Content plan (LLM output, deterministically rendered) -----------------


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


# ---- House deck (HTML-first) -------------------------------------------------


class SlideContent(BaseModel):
    """One house-deck slide. `layout`/`variant` pick a VariantSpec from the
    layout library; `slots` fill its named text/list slots. The headline is
    not a slot -- it always renders in the fixed headline band."""

    headline: str
    subheading: str = ""
    kicker: str = ""
    layout: str = ""
    variant: str = ""
    slots: dict[str, str | list[str]] = Field(default_factory=dict)
    chart: ChartSpec | None = None
    table: TableSpec | None = None
    visual: Visual | None = None
    image_path: str | None = None
    speaker_notes: str = ""
    source_refs: list[str] = Field(default_factory=list)
    source_line: str = ""
    needs_review: bool = False
    type_step: int = Field(default=0, ge=-1, le=2, description="Fit ladder: 1-2 set the visual's text smaller, -1 one size larger.")


class Deck(BaseModel):
    title: str
    subtitle: str = ""
    slides: list[SlideContent]


class StorylineSlide(BaseModel):
    headline: str
    subheading: str = ""
    purpose: str
    source_refs: list[str] = Field(default_factory=list)
    visual: str | None = None
    chart_kind: str | None = None
    rationale: Words(20) = ""
    section: int | None = None
    kicker: str = ""


class Storyline(BaseModel):
    title: str
    subtitle: str = ""
    slides: list[StorylineSlide]
    approved: bool = False
    answer: Words(30) = ""
    figures: list[Figure] = Field(default_factory=list, max_length=2)
    sections: list[SectionPlan] = Field(default_factory=list)
    closing: list[NextAction] = Field(default_factory=list, max_length=5)


class Finding(BaseModel):
    """One problem found while building a house deck (data check, lint, fit or QA)."""

    slide: int
    slot: str | None = None
    stage: Literal["data", "lint", "fit", "qa"]
    rule: str
    message: str


class RunRef(BaseModel):
    kind: Literal["decision", "run"]
    ref_id: str


# ---- Request / run record ---------------------------------------------------


class DeckSettings(BaseModel):
    profile: Literal["executive", "client_pitch", "committee", "workshop"] = "committee"
    purpose: Literal["recommendation", "review", "process", "briefing"] = "recommendation"
    detail: Literal["concise", "balanced", "comprehensive"] = "balanced"
    max_slides: int = Field(default=12, ge=3, le=25)
    cover_image: str | None = Field(default=None, description="House deck: a registered image name drawn behind the cover.")


class StagedImage(BaseModel):
    """An uploaded image waiting to be named in a ReportRequest (POST /api/reports/images)."""

    image_id: str
    media_type: Literal["image/png", "image/jpeg"]
    width: int
    height: int
    sha256: str


class ReportImageIn(BaseModel):
    """An image a request names: a staged upload, under the name the deck uses for it.
    The name, focus and limits are checked by ReportingService (arp.reporting.images), not here."""

    image_id: str
    name: str
    alt: str = Field(default="", max_length=200)
    focus: list[float] | None = None


class ReportImage(BaseModel):
    """An image stored with a report under `reports/<id>/images/<name>.<ext>`."""

    name: str
    alt: str = Field(default="", max_length=200)
    focus: list[float] | None = Field(default=None, description="[x, y], each 0 to 1; None is the centre.")
    image_id: str | None = None
    media_type: Literal["image/png", "image/jpeg"]
    width: int
    height: int
    sha256: str


class ReportRequest(BaseModel):
    title: str
    qualitative_notes: str = Field(description="Free-text analysis, findings, talking points -- the raw qualitative input the planner works from.")
    datasets: list[QuantitativeDataset] = Field(default_factory=list)
    audience: AudienceProfile = Field(default_factory=AudienceProfile)
    layout: LayoutInstructions = Field(default_factory=LayoutInstructions)
    template_id: str | None = Field(default=None, description="A previously ingested TemplateStyleProfile.template_id, pptx only.")
    goal: str = ""
    run_refs: list[RunRef] = Field(default_factory=list)
    deck: DeckSettings = Field(default_factory=DeckSettings)
    images: list[ReportImage | ReportImageIn] = Field(default_factory=list, description="House deck: images the deck may show.")


class ReportStatus(StrEnum):
    PENDING = JobStatus.PENDING.value
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    """Plan drafted and persisted, awaiting render (a human may edit the plan first)."""
    STORYLINE_READY = "storyline_ready"
    """House deck only: storyline drafted, awaiting human approval before slides are built."""
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
    output_files: list[str] = Field(default_factory=list)
    rerun_of: str | None = Field(default=None, description="The report this one was re-run from (ReportingService.rerun).")
    has_deck: bool = False
    deck_edited_since_render: bool = False
