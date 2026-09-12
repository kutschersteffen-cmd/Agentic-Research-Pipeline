from __future__ import annotations

import tempfile
from pathlib import Path

from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from arp.reporting import chart_builder
from arp.schemas.reporting import (
    ContentItem,
    LayoutInstructions,
    QuantitativeDataset,
    ReportPlan,
    ReportSection,
    SectionLayoutHint,
    TemplateStyleProfile,
)

_SLIDE_MARGIN = Inches(0.5)
_TITLE_BAND_HEIGHT = Inches(1.15)

_BODY_TYPES = {"BODY", "OBJECT"}


def _placeholder_type_name(ph) -> str | None:
    try:
        return ph.placeholder_format.type.name
    except (AttributeError, ValueError, KeyError):
        return None


def _layout_by_name_hint(prs: Presentation, hints: list[str]):
    for layout in prs.slide_layouts:
        name = layout.name.lower()
        if any(h in name for h in hints):
            return layout
    return None


def _layout_with_placeholders(prs: Presentation, required: set[str], forbidden: set[str] = frozenset()):
    best = None
    for layout in prs.slide_layouts:
        types = {_placeholder_type_name(ph) for ph in layout.placeholders}
        if required <= types and not (types & forbidden) and (best is None or len(types) < len({_placeholder_type_name(p) for p in best.placeholders})):
            best = layout
    return best


def _pick_title_layout(prs: Presentation):
    return _layout_by_name_hint(prs, ["title slide"]) or _layout_with_placeholders(prs, {"TITLE", "SUBTITLE"}) or prs.slide_layouts[0]


def _pick_content_layout(prs: Presentation):
    return (
        _layout_by_name_hint(prs, ["title and content", "content"])
        or _layout_with_placeholders(prs, {"TITLE", "OBJECT"})
        or _layout_with_placeholders(prs, {"TITLE", "BODY"})
        or prs.slide_layouts[min(1, len(prs.slide_layouts) - 1)]
    )


def _pick_section_header_layout(prs: Presentation):
    return (
        _layout_by_name_hint(prs, ["section header"])
        or _layout_with_placeholders(prs, {"TITLE"}, forbidden={"OBJECT", "BODY"})
        or prs.slide_layouts[0]
    )


def _set_title(slide, text: str) -> None:
    if slide.shapes.title is not None:
        slide.shapes.title.text = text


def _find_body_placeholder(slide):
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 0:
            continue
        if _placeholder_type_name(ph) in _BODY_TYPES:
            return ph
    return None


def _rect_of(slide, ph) -> tuple[int, int, int, int] | None:
    """A placeholder copied onto a slide only carries an explicit position
    if the layout's placeholder had one and python-pptx chose to inherit
    it into the slide XML; when it didn't, .left/.top/.width/.height come
    back None even though PowerPoint would still render it at the layout's
    position. Falls back to reading the layout placeholder of the same idx
    directly, since that one is defined by the template.
    """
    if None not in (ph.left, ph.top, ph.width, ph.height):
        return ph.left, ph.top, ph.width, ph.height
    idx = ph.placeholder_format.idx
    for lph in slide.slide_layout.placeholders:
        if lph.placeholder_format.idx == idx and None not in (lph.left, lph.top, lph.width, lph.height):
            return lph.left, lph.top, lph.width, lph.height
    return None


def _default_body_rect(prs: Presentation) -> tuple[int, int, int, int]:
    left = _SLIDE_MARGIN
    top = _TITLE_BAND_HEIGHT
    width = prs.slide_width - 2 * _SLIDE_MARGIN
    height = prs.slide_height - _TITLE_BAND_HEIGHT - _SLIDE_MARGIN
    return left, top, width, height


def _body_rect(slide, prs: Presentation) -> tuple[int, int, int, int]:
    ph = _find_body_placeholder(slide)
    if ph is not None:
        rect = _rect_of(slide, ph)
        if rect is not None:
            return rect
    return _default_body_rect(prs)


def _remove_bullet(paragraph) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("a:buChar")) + pPr.findall(qn("a:buAutoNum")) + pPr.findall(qn("a:buNone")):
        pPr.remove(existing)
    pPr.append(pPr.makeelement(qn("a:buNone"), {}))


def _fill_narrative(text_frame, items: list, max_items: int) -> None:
    text_frame.word_wrap = True
    shown = items[:max_items]
    if not shown:
        text_frame.text = ""
        return
    for i, item in enumerate(shown):
        p = text_frame.paragraphs[0] if i == 0 else text_frame.add_paragraph()
        p.text = item.text
        if not item.bullet:
            _remove_bullet(p)
    if len(items) > max_items:
        p = text_frame.add_paragraph()
        p.text = f"(+{len(items) - max_items} more)"
        p.font.italic = True
        p.font.size = Pt(11)


def _add_caption(slide, text: str, left, top, width, height) -> None:
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.text = text
    for p in tf.paragraphs:
        p.font.size = Pt(11)
        p.font.italic = True


def _add_chart_or_table(slide, section: ReportSection, datasets: list[QuantitativeDataset], rect: tuple[int, int, int, int], tmp_dir: Path) -> None:
    left, top, width, height = rect
    caption_h = Inches(0.35)
    chart_height = height - caption_h if (section.chart and section.chart.notes) or (section.table) else height

    if section.chart is not None:
        spec = section.chart
        if chart_builder.is_native(spec):
            xl_type, chart_data = chart_builder.build_native_chart_data(spec, datasets)
            graphic_frame = slide.shapes.add_chart(xl_type, left, top, width, chart_height, chart_data)
            chart = graphic_frame.chart
            if spec.title:
                chart.has_title = True
                chart.chart_title.text_frame.text = spec.title
            else:
                chart.has_title = False
        else:
            png_path = tmp_dir / f"chart_{id(spec)}.png"
            chart_builder.render_chart_image(spec, datasets, png_path, width_in=Emu(width).inches, height_in=Emu(chart_height).inches)
            slide.shapes.add_picture(str(png_path), left, top, width, chart_height)
        if spec.notes:
            _add_caption(slide, spec.notes, left, top + chart_height, width, caption_h)

    elif section.table is not None:
        _add_table(slide, section.table, datasets, left, top, width, chart_height)


def _add_table(slide, table_spec, datasets: list[QuantitativeDataset], left, top, width, height) -> None:
    ds = next((d for d in datasets if d.dataset_id == table_spec.dataset_id), None)
    if ds is None:
        return
    columns = table_spec.columns or ds.column_names()
    rows = ds.rows[: table_spec.max_rows]
    n_rows = len(rows) + 1
    n_cols = max(len(columns), 1)
    graphic_frame = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    table = graphic_frame.table
    for c, col_name in enumerate(columns):
        cell = table.cell(0, c)
        cell.text = col_name
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.size = Pt(12)
    for r, row in enumerate(rows, start=1):
        for c, col_name in enumerate(columns):
            cell = table.cell(r, c)
            cell.text = "" if row.get(col_name) is None else str(row.get(col_name))
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(11)
    if len(ds.rows) > table_spec.max_rows:
        note = slide.shapes.add_textbox(left, top + height, width, Inches(0.3))
        note.text_frame.text = f"(+{len(ds.rows) - table_spec.max_rows} more rows in the underlying dataset)"
        note.text_frame.paragraphs[0].font.italic = True
        note.text_frame.paragraphs[0].font.size = Pt(10)


def _ordered_sections(plan: ReportPlan, layout: LayoutInstructions) -> list[ReportSection]:
    if not layout.include_appendix:
        return list(plan.sections)
    main = [s for s in plan.sections if not s.appendix]
    appendix = [s for s in plan.sections if s.appendix]
    return main + appendix


def build_deck(
    plan: ReportPlan,
    datasets: list[QuantitativeDataset],
    layout: LayoutInstructions,
    template_style: TemplateStyleProfile | None,
    out_path: Path,
) -> Path:
    """Deterministically renders a ReportPlan (already LLM-drafted and
    optionally human-edited) into a .pptx file. No LLM calls happen here --
    every layout/chart/table decision below is code, so the same plan
    always renders identically.
    """
    if template_style is not None and template_style.stored_path:
        prs = Presentation(template_style.stored_path)
        # Strip any pre-existing slides the template shipped with (a
        # ready-made example deck, common in corporate templates) --
        # only its masters/layouts/theme are wanted as the render base.
        xml_slides = prs.slides._sldIdLst
        for sld_id in list(xml_slides):
            xml_slides.remove(sld_id)
    else:
        prs = Presentation()

    with tempfile.TemporaryDirectory(prefix="arp_chart_") as tmp:
        tmp_dir = Path(tmp)
        sections = _ordered_sections(plan, layout)
        appendix_started = False

        if layout.include_title_slide:
            slide = prs.slides.add_slide(_pick_title_layout(prs))
            _set_title(slide, plan.title)
            for ph in slide.placeholders:
                if _placeholder_type_name(ph) == "SUBTITLE" and plan.subtitle:
                    ph.text = plan.subtitle

        if layout.include_agenda_slide and sections:
            slide = prs.slides.add_slide(_pick_content_layout(prs))
            _set_title(slide, "Agenda")
            body_ph = _find_body_placeholder(slide)
            headings = [ContentItem(text=s.heading, bullet=True) for s in sections if not s.appendix]
            if body_ph is not None:
                _fill_narrative(body_ph.text_frame, headings, max_items=len(headings) or 1)

        for section in sections:
            if layout.include_appendix and section.appendix and not appendix_started:
                appendix_started = True
                divider = prs.slides.add_slide(_pick_section_header_layout(prs))
                _set_title(divider, "Appendix")

            if section.layout_hint == SectionLayoutHint.SECTION_HEADER:
                slide = prs.slides.add_slide(_pick_section_header_layout(prs))
                _set_title(slide, section.heading)
                continue

            slide = prs.slides.add_slide(_pick_content_layout(prs))
            _set_title(slide, section.heading)
            rect = _body_rect(slide, prs)
            has_visual = section.chart is not None or section.table is not None

            if section.layout_hint == SectionLayoutHint.TEXT_ONLY or not has_visual:
                body_ph = _find_body_placeholder(slide)
                if body_ph is not None:
                    _fill_narrative(body_ph.text_frame, section.narrative, layout.max_bullets_per_slide)
                else:
                    left, top, width, height = rect
                    box = slide.shapes.add_textbox(left, top, width, height)
                    _fill_narrative(box.text_frame, section.narrative, layout.max_bullets_per_slide)
            elif section.layout_hint == SectionLayoutHint.CHART_FOCUS:
                left, top, width, height = rect
                caption_h = Inches(0.6) if section.narrative else 0
                _add_chart_or_table(slide, section, datasets, (left, top, width, height - caption_h), tmp_dir)
                if section.narrative:
                    box = slide.shapes.add_textbox(left, top + height - caption_h, width, caption_h)
                    _fill_narrative(box.text_frame, section.narrative, max_items=2)
            else:  # STANDARD with a chart/table: narrative left half, visual right half
                left, top, width, height = rect
                half = Emu(int(width * 0.45))
                gap = Inches(0.25)
                body_ph = _find_body_placeholder(slide)
                if body_ph is not None and section.narrative:
                    body_ph.left, body_ph.top, body_ph.width, body_ph.height = left, top, half, height
                    _fill_narrative(body_ph.text_frame, section.narrative, layout.max_bullets_per_slide)
                elif section.narrative:
                    box = slide.shapes.add_textbox(left, top, half, height)
                    _fill_narrative(box.text_frame, section.narrative, layout.max_bullets_per_slide)
                visual_left = left + half + gap
                visual_width = width - half - gap
                _add_chart_or_table(slide, section, datasets, (visual_left, top, visual_width, height), tmp_dir)

            if section.speaker_notes:
                slide.notes_slide.notes_text_frame.text = section.speaker_notes

        out_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(out_path))
    return out_path
