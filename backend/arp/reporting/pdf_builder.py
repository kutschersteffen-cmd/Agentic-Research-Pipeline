from __future__ import annotations

import tempfile
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from arp.reporting import chart_builder
from arp.reporting.design import DesignTheme
from arp.schemas.reporting import LayoutInstructions, QuantitativeDataset, ReportPlan, ReportSection, SectionLayoutHint

_IMAGE_WIDTH_IN = 6.0
_BASE_STYLES = getSampleStyleSheet()


def _hex(hex_color: str):
    return colors.HexColor(f"#{hex_color}")


def _build_styles(theme: DesignTheme) -> dict[str, ParagraphStyle]:
    """A fresh, theme-colored stylesheet per render -- built locally
    rather than mutating reportlab's shared getSampleStyleSheet() singleton,
    since two reports with different templates/themes can render
    concurrently."""
    return {
        "Title": ParagraphStyle("ArpTitle", parent=_BASE_STYLES["Title"], textColor=_hex(theme.ink_primary), fontName="Helvetica-Bold"),
        "Subtitle": ParagraphStyle("ArpSubtitle", parent=_BASE_STYLES["Italic"], textColor=_hex(theme.ink_secondary), fontSize=13),
        "BodyText": ParagraphStyle("ArpBody", parent=_BASE_STYLES["BodyText"], textColor=_hex(theme.ink_secondary)),
        "Heading1": ParagraphStyle("ArpH1", parent=_BASE_STYLES["Heading1"], textColor=_hex(theme.accent)),
        "Heading2": ParagraphStyle("ArpH2", parent=_BASE_STYLES["Heading2"], textColor=_hex(theme.ink_primary)),
        "Caption": ParagraphStyle("ArpCaption", parent=_BASE_STYLES["Italic"], fontSize=9, textColor=_hex(theme.ink_muted)),
    }


def _ordered_sections(plan: ReportPlan, layout: LayoutInstructions) -> list[ReportSection]:
    if not layout.include_appendix:
        return list(plan.sections)
    main = [s for s in plan.sections if not s.appendix]
    appendix = [s for s in plan.sections if s.appendix]
    return main + appendix


def _narrative_flowables(section: ReportSection, styles: dict) -> list:
    bullets = [item for item in section.narrative if item.bullet]
    paragraphs = [item for item in section.narrative if not item.bullet]
    flowables = []
    for item in paragraphs:
        flowables.append(Paragraph(item.text, styles["BodyText"]))
    if bullets:
        flowables.append(
            ListFlowable([ListItem(Paragraph(item.text, styles["BodyText"])) for item in bullets], bulletType="bullet")
        )
    return flowables


def _table_flowable(table_spec, datasets: list[QuantitativeDataset], theme: DesignTheme, styles: dict) -> list:
    ds = next((d for d in datasets if d.dataset_id == table_spec.dataset_id), None)
    if ds is None:
        return []
    columns = table_spec.columns or ds.column_names()
    rows = ds.rows[: table_spec.max_rows]
    data = [columns] + [[("" if row.get(c) is None else str(row.get(c))) for c in columns] for row in rows]
    table = Table(data, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _hex(theme.accent)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 1), (-1, -1), _hex(theme.ink_secondary)),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, _hex(theme.accent)),
                ("LINEBELOW", (0, 1), (-1, -1), 0.5, _hex(theme.gridline)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _hex(theme.gridline)]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    flowables = [table]
    if len(ds.rows) > table_spec.max_rows:
        flowables.append(Paragraph(f"(+{len(ds.rows) - table_spec.max_rows} more rows in the underlying dataset)", styles["Caption"]))
    return flowables


def _chart_flowables(section: ReportSection, datasets: list[QuantitativeDataset], tmp_dir: Path, theme: DesignTheme, styles: dict) -> list:
    spec = section.chart
    png_path = tmp_dir / f"chart_{id(spec)}.png"
    chart_builder.render_chart_image(spec, datasets, png_path, theme=theme)
    flowables = [Image(str(png_path), width=_IMAGE_WIDTH_IN * inch, height=_IMAGE_WIDTH_IN * inch * 5 / 9)]
    if spec.notes:
        flowables.append(Paragraph(spec.notes, styles["Caption"]))
    return flowables


def build_pdf(
    plan: ReportPlan, datasets: list[QuantitativeDataset], layout: LayoutInstructions, out_path: Path, theme: DesignTheme | None = None
) -> Path:
    """Deterministically renders a ReportPlan into a .pdf report via
    reportlab -- pure-Python, no LibreOffice/Word dependency. Shares the
    same section-flow model as report_builder.build_docx (charts always
    embedded as static images; see that module's docstring for why)."""
    theme = theme or DesignTheme()
    styles = _build_styles(theme)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    story: list = [Paragraph(plan.title, styles["Title"])]
    if plan.subtitle:
        story.append(Paragraph(plan.subtitle, styles["Subtitle"]))
    story.append(Spacer(1, 0.25 * inch))

    with tempfile.TemporaryDirectory(prefix="arp_report_chart_") as tmp:
        tmp_dir = Path(tmp)
        sections = _ordered_sections(plan, layout)
        appendix_started = False
        for section in sections:
            if layout.include_appendix and section.appendix and not appendix_started:
                appendix_started = True
                story.append(Paragraph("Appendix", styles["Heading1"]))

            heading_style = styles["Heading2"] if section.layout_hint == SectionLayoutHint.SECTION_HEADER else styles["Heading1"]
            story.append(Paragraph(section.heading, heading_style))
            if section.layout_hint == SectionLayoutHint.SECTION_HEADER:
                story.append(Spacer(1, 0.2 * inch))
                continue

            story.extend(_narrative_flowables(section, styles))
            if section.chart is not None:
                story.extend(_chart_flowables(section, datasets, tmp_dir, theme, styles))
            elif section.table is not None:
                story.extend(_table_flowable(section.table, datasets, theme, styles))
            story.append(Spacer(1, 0.2 * inch))

        doc.build(story)
    return out_path
