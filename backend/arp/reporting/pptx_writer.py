"""Render-model primitives -> native PPTX shapes for one slide, each named after its primitive.

python-pptx has no API for arrowheads or table cell borders, so `a:tailEnd` and `a:lnT`/`a:lnB` are written as XML.
"""

from __future__ import annotations

from lxml import etree
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_TICK_LABEL_POSITION, XL_TICK_MARK
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from arp.reporting.house_style import Mode, Tokens
from arp.reporting.render_model import (
    LINE_PAD,
    ChartPrim,
    Line,
    Primitive,
    Rect,
    TablePrim,
    Text,
    bar_plot_x,
    column_plot_y,
    decimals,
    family,
    line_scale,
    palette,
    value_range,
)

_KINDS = {"bar": XL_CHART_TYPE.BAR_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
          "stacked_column": XL_CHART_TYPE.COLUMN_STACKED, "line": XL_CHART_TYPE.LINE_MARKERS}
_ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
_ANCHOR = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.lstrip("#"))


def _number_format(values: list[float], unit: str) -> str:
    dec = decimals(values)
    unit = unit.replace('"', "")  # a quote would end the format code's literal early
    fmt = ("0." + "0" * dec if dec else "0") + (f'"{unit}"' if unit else "")
    return fmt if min(values, default=0) >= 0 else f'{fmt};"−"{fmt}'  # a negative section for the typographic minus


def _fmt_value(v: float, values: list[float], unit: str) -> str:
    return f"{v:.{decimals(values)}f}{unit}".replace("-", "−")


class _Writer:
    def __init__(self, slide, tokens: Tokens, mode: Mode, emu_per_px: float):
        self.slide, self.k, self.c = slide, emu_per_px, palette(tokens, mode)
        self.pt = emu_per_px / 12700  # pt per canvas px
        self.body, self.mono = family(tokens.fonts.body), family(tokens.fonts.mono or tokens.fonts.body)

    def e(self, px: float) -> int:
        return round(px * self.k)

    def place(self, shape, p) -> None:
        shape.name = p.name
        shape.left, shape.top, shape.width, shape.height = self.e(p.x), self.e(p.y), self.e(p.w), self.e(p.h)

    def font(self, run, fam: str, size: float, weight: int, color: str) -> None:
        f = run.font
        f.name, f.size, f.bold, f.color.rgb = fam, Pt(size * self.pt), weight >= 600, _rgb(color)

    def rect(self, p: Rect) -> None:
        shape = self.slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, self.e(p.x), self.e(p.y), self.e(p.w), self.e(p.h))
        self.place(shape, p)
        if p.fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = _rgb(p.fill)
        else:
            shape.fill.background()
        if p.line and p.line_w:
            shape.line.color.rgb, shape.line.width = _rgb(p.line), Emu(self.e(p.line_w))
        else:
            shape.line.fill.background()
        shape.shadow.inherit = False

    def text(self, p: Text) -> None:
        shape = self.slide.shapes.add_textbox(self.e(p.x), self.e(p.y), self.e(p.w), self.e(p.h))
        self.place(shape, p)
        if p.fill_under:
            shape.fill.solid()
            shape.fill.fore_color.rgb = _rgb(p.fill_under)
        tf = shape.text_frame
        tf.word_wrap, tf.vertical_anchor, tf.auto_size = True, _ANCHOR[p.anchor], MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        for i, line in enumerate(p.text.split("\n")):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment, para.line_spacing = _ALIGN[p.align], Pt(p.size * p.leading * self.pt)
            run = para.add_run()
            run.text = line
            self.font(run, p.family, p.size, p.weight, p.color)
            if p.outline:  # outlined glyphs: a 2 px stroke in the colour, no fill (a:ln comes first in a:rPr)
                run.font.fill.background()
                ln = etree.Element(qn("a:ln"), w=str(self.e(2)))
                etree.SubElement(etree.SubElement(ln, qn("a:solidFill")), qn("a:srgbClr")).set("val", p.color.lstrip("#"))
                run._r.get_or_add_rPr().insert(0, ln)

    def line(self, p: Line) -> None:
        pts = [(self.e(x), self.e(y)) for x, y in p.points]
        ff = self.slide.shapes.build_freeform(*pts[0], scale=1.0)
        ff.add_line_segments(pts[1:], close=False)
        shape = ff.convert_to_shape()
        shape.name = p.name
        shape.fill.background()
        shape.line.color.rgb, shape.line.width = _rgb(p.color), Emu(self.e(p.width))
        shape.shadow.inherit = False
        if p.arrow:
            etree.SubElement(shape.line._get_or_add_ln(), qn("a:tailEnd"), type="triangle", w="med", len="med")

    def chart(self, p: ChartPrim) -> None:
        values = [v for s in p.series for v in s.values]
        fmt = _number_format(values, p.unit)
        data = CategoryChartData(number_format=fmt)
        data.categories = p.categories
        for s in p.series:
            data.add_series(s.name, s.values)
        frame = self.slide.shapes.add_chart(_KINDS[p.kind], self.e(p.x), self.e(p.y), self.e(p.w), self.e(p.h), data)
        self.place(frame, p)
        chart = frame.chart
        chart.font.size, chart.font.name = Pt(24 * self.pt), self.body
        chart.font.color.rgb = _rgb(self.c["muted"])
        chart.has_title = False  # a one-series chart otherwise shows the series name as its title
        chart.has_legend = len(p.series) > 1 and p.kind != "line"  # lines are labelled at their ends
        if chart.has_legend:
            chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
        plot = chart.plots[0]
        for s, ser in zip(p.series, plot.series, strict=True):
            if p.kind == "line":
                ser.smooth = False
                ser.format.line.color.rgb, ser.format.line.width = _rgb(s.colors[0]), Emu(self.e(6 if s.colors[0] == self.c["highlight"] else 4))
            for i, color in enumerate(s.colors):
                point = ser.points[i]
                fill = point.marker.format.fill if p.kind == "line" else point.format.fill
                fill.solid()
                fill.fore_color.rgb = _rgb(color)
        if p.kind != "line":
            plot.gap_width = 67  # bars take 60% of the band, as in the HTML
            if p.kind != "stacked_column":
                plot.overlap = 0
        if p.labels:
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.number_format, dl.number_format_is_linked, dl.show_value = fmt, False, p.kind != "line"
            dl.font.color.rgb = _rgb(self.c["ink"])
            if p.kind == "line":  # the series name and last value at the line end, as in the HTML
                for s, ser in zip(p.series, plot.series, strict=True):
                    end = ser.points[len(s.values) - 1].data_label
                    end.position = XL_LABEL_POSITION.RIGHT
                    run = end.text_frame.paragraphs[0].add_run()
                    run.text = f"{s.name} {_fmt_value(s.values[-1], values, p.unit)}"
                    run.font.color.rgb = _rgb(self.c["ink"])
        va = chart.value_axis
        va.has_major_gridlines, va.visible = False, not p.labels
        va.tick_labels.number_format, va.tick_labels.number_format_is_linked = fmt, False
        ca = chart.category_axis  # no axis line or ticks: only the category labels
        ca.format.line.fill.background()
        ca.major_tick_mark = ca.minor_tick_mark = XL_TICK_MARK.NONE
        # The HTML's plot rect and value scale, so bars and points (and the callout leader) line up with the PDF.
        if p.kind == "line":
            top, right, bottom = LINE_PAD
            va.minimum_scale, va.maximum_scale = line_scale(p)
            x, y, w, h = 0, top, p.w - right, p.h - top - bottom
        else:
            va.minimum_scale, va.maximum_scale = value_range(p)
            ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW  # at the axis end, not on the zero line over negative bars
            if p.kind == "bar":
                (x0, x1), (y0, y1) = bar_plot_x(p), (0, p.h)
            else:
                (x0, x1), (y0, y1) = (0, p.w), column_plot_y(p)
            x, y, w, h = x0, y0, x1 - x0, y1 - y0
        area = chart._chartSpace.chart.plotArea
        if area.find(qn("c:layout")) is None:
            area.insert(0, etree.Element(qn("c:layout")))  # c:layout is plotArea's first child
        ml = etree.SubElement(area.find(qn("c:layout")), qn("c:manualLayout"))
        for tag, val in (("layoutTarget", "inner"), ("xMode", "edge"), ("yMode", "edge"), ("x", x / p.w), ("y", y / p.h),
                         ("w", w / p.w), ("h", h / p.h)):
            etree.SubElement(ml, qn(f"c:{tag}"), val=str(val))
        if p.kind == "bar":
            chart.category_axis.reverse_order = True  # first category on top, as in the HTML

    def table(self, p: TablePrim) -> None:
        c = {**self.c, **p.style}
        rows = [p.header, *p.rows, *([p.total] if p.total else [])]
        ncol = max(len(r) for r in rows)
        shape = self.slide.shapes.add_table(len(rows), ncol, self.e(p.x), self.e(p.y), self.e(p.w), self.e(p.h))
        tbl = shape.table
        tbl.first_row = tbl.horz_banding = False
        for row in tbl.rows:
            row.height = self.e(p.h / len(rows))
        for col in tbl.columns:
            col.width = self.e(p.w / ncol)
        for ri, values in enumerate(rows):
            head, total = ri == 0, p.total is not None and ri == len(rows) - 1
            for ci, v in enumerate(values):
                cell = tbl.cell(ri, ci)
                cell.fill.background()
                cell.margin_left = cell.margin_right = self.e(12)
                cell.margin_top = cell.margin_bottom = 0
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                para = cell.text_frame.paragraphs[0]
                para.alignment = _ALIGN[p.align[ci]] if p.align else PP_ALIGN.LEFT
                run = para.add_run()
                hl = ci == p.highlight_col
                if hl:  # an ink header block, ground cells; highlight is never a text colour
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = _rgb(c["ink" if head else "ground"])
                if head:
                    run.text = str(v).upper()
                    self.font(run, self.mono, 18, 400, c["panel" if hl else "muted"])
                else:
                    run.text = str(v)
                    self.font(run, self.mono if p.mono and p.mono[ci] else self.body, 24, 600 if total or hl else 400, c["ink"])
                # a:tcPr takes lnL, lnR, lnT, lnB before the fill: header and rows ruled below, the total ruled above.
                rule = ("lnT", 2, c["ink"]) if total else ("lnB", 2 if head else 1, c["ink"] if head else c["line"])
                tcPr = cell._tc.get_or_add_tcPr()
                for i, side in enumerate(("lnL", "lnR", "lnT", "lnB")):
                    ln = etree.Element(qn(f"a:{side}"), w=str(self.e(rule[1] if side == rule[0] else 0)))
                    if side == rule[0]:
                        etree.SubElement(etree.SubElement(ln, qn("a:solidFill")), qn("a:srgbClr")).set("val", rule[2].lstrip("#"))
                    else:
                        etree.SubElement(ln, qn("a:noFill"))
                    tcPr.insert(i, ln)
        self.place(shape, p)


def pptx_slide(slide_obj, prims: list[Primitive], tokens: Tokens, mode: Mode, emu_per_px: float) -> None:
    """Draws the primitives on `slide_obj` in order; empty text is skipped."""
    w = _Writer(slide_obj, tokens, mode, emu_per_px)
    for p in prims:
        if isinstance(p, Rect):
            w.rect(p)
        elif isinstance(p, Text):
            if p.text:
                w.text(p)
        elif isinstance(p, Line):
            w.line(p)
        elif isinstance(p, ChartPrim):
            w.chart(p)
        elif isinstance(p, TablePrim):
            w.table(p)
