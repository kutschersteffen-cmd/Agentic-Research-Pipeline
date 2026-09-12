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
from arp.schemas.reporting import LayoutInstructions, QuantitativeDataset, ReportPlan, ReportSection, SectionLayoutHint

_IMAGE_WIDTH_IN = 6.0
_styles = getSampleStyleSheet()
_CAPTION_STYLE = ParagraphStyle("Caption", parent=_styles["Italic"], fontSize=9)


def _ordered_sections(plan: ReportPlan, layout: LayoutInstructions) -> list[ReportSection]:
    if not layout.include_appendix:
        return list(plan.sections)
    main = [s for s in plan.sections if not s.appendix]
    appendix = [s for s in plan.sections if s.appendix]
    return main + appendix


def _narrative_flowables(section: ReportSection) -> list:
    bullets = [item for item in section.narrative if item.bullet]
    paragraphs = [item for item in section.narrative if not item.bullet]
    flowables = []
    for item in paragraphs:
        flowables.append(Paragraph(item.text, _styles["BodyText"]))
    if bullets:
        flowables.append(
            ListFlowable([ListItem(Paragraph(item.text, _styles["BodyText"])) for item in bullets], bulletType="bullet")
        )
    return flowables


def _table_flowable(table_spec, datasets: list[QuantitativeDataset]) -> list:
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
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ]
        )
    )
    flowables = [table]
    if len(ds.rows) > table_spec.max_rows:
        flowables.append(Paragraph(f"(+{len(ds.rows) - table_spec.max_rows} more rows in the underlying dataset)", _CAPTION_STYLE))
    return flowables


def _chart_flowables(section: ReportSection, datasets: list[QuantitativeDataset], tmp_dir: Path) -> list:
    spec = section.chart
    png_path = tmp_dir / f"chart_{id(spec)}.png"
    chart_builder.render_chart_image(spec, datasets, png_path)
    flowables = [Image(str(png_path), width=_IMAGE_WIDTH_IN * inch, height=_IMAGE_WIDTH_IN * inch * 5 / 9)]
    if spec.notes:
        flowables.append(Paragraph(spec.notes, _CAPTION_STYLE))
    return flowables


def build_pdf(plan: ReportPlan, datasets: list[QuantitativeDataset], layout: LayoutInstructions, out_path: Path) -> Path:
    """Deterministically renders a ReportPlan into a .pdf report via
    reportlab -- pure-Python, no LibreOffice/Word dependency. Shares the
    same section-flow model as report_builder.build_docx (charts always
    embedded as static images; see that module's docstring for why)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    story: list = [Paragraph(plan.title, _styles["Title"])]
    if plan.subtitle:
        story.append(Paragraph(plan.subtitle, _styles["Italic"]))
    story.append(Spacer(1, 0.25 * inch))

    with tempfile.TemporaryDirectory(prefix="arp_report_chart_") as tmp:
        tmp_dir = Path(tmp)
        sections = _ordered_sections(plan, layout)
        appendix_started = False
        for section in sections:
            if layout.include_appendix and section.appendix and not appendix_started:
                appendix_started = True
                story.append(Paragraph("Appendix", _styles["Heading1"]))

            heading_style = _styles["Heading2"] if section.layout_hint == SectionLayoutHint.SECTION_HEADER else _styles["Heading1"]
            story.append(Paragraph(section.heading, heading_style))
            if section.layout_hint == SectionLayoutHint.SECTION_HEADER:
                story.append(Spacer(1, 0.2 * inch))
                continue

            story.extend(_narrative_flowables(section))
            if section.chart is not None:
                story.extend(_chart_flowables(section, datasets, tmp_dir))
            elif section.table is not None:
                story.extend(_table_flowable(section.table, datasets))
            story.append(Spacer(1, 0.2 * inch))

        doc.build(story)
    return out_path
