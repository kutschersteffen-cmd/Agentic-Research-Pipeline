"""Deck -> editable .pptx from the same tokens and slot grid as the HTML renderer.

Shapes sit on the blank layout at slot_rect positions (named `slot:<name>`), so the
positions match the HTML by construction. Text is the already-fitted deck text; nothing
is re-fitted here. Fonts are named, not embedded (python-pptx cannot embed them).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from arp.reporting.chart_builder import build_native_chart_data, is_native, render_chart_image, style_native_chart
from arp.reporting.house_style import Mode, Rect, Tokens, TypeStyle, get_variant, load_tokens, slot_rect
from arp.reporting.html_render import table_view, theme_from_tokens
from arp.schemas.reporting import Deck, QuantitativeDataset, SlideContent

_PX = 9525  # EMU per px
_ROW_PX = 46  # table row: caption line + 2x10px padding, as in the HTML


def _e(px: float) -> int:
    return round(px * _PX)


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.lstrip("#"))


def _family(stack: str) -> str:
    return stack.split(",")[0].strip().strip("'\"")


class _Builder:
    def __init__(self, tokens: Tokens, mode: Mode):
        self.t, self.mode, self.c = tokens, mode, tokens.colors(mode)
        self.theme = theme_from_tokens(tokens, mode)

    def _box(self, slide, name: str, r: Rect, shape=None):
        shape = slide.shapes.add_shape(shape, _e(r.x), _e(r.y), _e(r.w), _e(r.h)) if shape else slide.shapes.add_textbox(_e(r.x), _e(r.y), _e(r.w), _e(r.h))
        shape.name = name
        # Float rects round to the same EMU as the HTML px, but add_* may truncate; pin them.
        shape.left, shape.top, shape.width, shape.height = _e(r.x), _e(r.y), _e(r.w), _e(r.h)
        return shape

    def _fill(self, shape, hex_color: str) -> None:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(hex_color)
        shape.line.fill.background()
        shape.shadow.inherit = False

    def _rule(self, slide, name: str, r: Rect, color: str) -> None:
        self._fill(self._box(slide, name, r, MSO_SHAPE.RECTANGLE), color)

    def _text(self, slide, name: str, r: Rect, paras: list[str], ts: TypeStyle, *, font: str, color: str, wrap=True, anchor=MSO_ANCHOR.TOP,
              align=PP_ALIGN.LEFT, bullet: str | None = None, pad_top: float = 0):
        shape = self._box(slide, name, r)
        tf = shape.text_frame
        tf.word_wrap, tf.vertical_anchor, tf.auto_size = wrap, anchor, MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = tf.margin_bottom = 0
        tf.margin_top = _e(pad_top)
        for i, text in enumerate(paras):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment, p.line_spacing = align, Pt(ts.size * ts.line_height * 0.75)
            if bullet and len(paras) > 1 or bullet == "num":
                p.space_after = Pt(ts.size * 0.5 * 0.75)
            run = p.add_run()
            run.text = text
            f = run.font
            f.name, f.size, f.bold, f.color.rgb = font, Pt(ts.size * 0.75), ts.weight >= 600, _rgb(color)
            if ts.tracking:
                run._r.get_or_add_rPr().set("spc", str(round(ts.tracking * ts.size * 0.75 * 100)))
            if bullet:
                pPr = p._p.get_or_add_pPr()
                pPr.set("marL", str(_e(ts.size * 1.1 if bullet != "num" else ts.size * 1.5)))
                pPr.set("indent", str(-_e(ts.size * 1.1 if bullet != "num" else ts.size * 1.5)))
                bu = etree.SubElement(pPr, qn("a:buAutoNum" if bullet == "num" else "a:buChar"))
                bu.set("type", "arabicPeriod") if bullet == "num" else bu.set("char", "•")
        return shape

    def _table(self, slide, spec, r: Rect, slide_content: SlideContent, ds: QuantitativeDataset) -> None:
        columns, rows, more = table_view(slide_content.table, ds)
        if not columns:
            return
        ts, mono = self.t.type[spec.type_role], _family(self.t.fonts.mono or self.t.fonts.body)
        cap = self.t.type["caption"]
        n = len(rows) + 1
        shape = slide.shapes.add_table(n, max(len(columns), 1), _e(r.x), _e(r.y), _e(r.w), _e(_ROW_PX * n))
        shape.name = f"slot:{spec.name}"
        tbl = shape.table
        tbl.horz_banding = False
        for row in tbl.rows:
            row.height = _e(_ROW_PX)
        for i, col in enumerate(tbl.columns):
            col.width = _e(r.w / len(columns)) if i < len(columns) - 1 else _e(r.w) - _e(r.w / len(columns)) * (len(columns) - 1)
        for ri, values in enumerate([columns, *rows]):
            for ci, value in enumerate(values):
                cell = tbl.cell(ri, ci)
                cell.fill.solid()
                cell.fill.fore_color.rgb = _rgb(self.c.background)
                cell.margin_left = cell.margin_right = _e(12)
                cell.margin_top = cell.margin_bottom = _e(10)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                run = cell.text_frame.paragraphs[0].add_run()
                f = run.font
                if ri == 0:  # small uppercase mono header, as deck.css.j2
                    run.text = str(value).upper()
                    f.name, f.size, f.bold = mono, Pt(cap.size * 0.75), False
                    run._r.get_or_add_rPr().set("spc", str(round(0.08 * cap.size * 0.75 * 100)))
                else:
                    run.text = str(value)
                    f.name, f.size, f.bold = _family(self.t.fonts.body), Pt(ts.size * 0.75), False
                f.color.rgb = _rgb(self.c.ink_muted if ri == 0 else self.c.ink)
                tcPr = cell._tc.get_or_add_tcPr()
                # a:tcPr takes lnL, lnR, lnT, lnB (then the fill); the table style's default grid is switched off on three sides.
                for i, side in enumerate(("lnL", "lnR", "lnT", "lnB")):
                    ln = etree.Element(qn(f"a:{side}"), w=str(_e(2 if ri == 0 else 1)))
                    if side == "lnB":
                        etree.SubElement(etree.SubElement(ln, qn("a:solidFill")), qn("a:srgbClr")).set("val", (self.c.ink if ri == 0 else self.c.neutral).lstrip("#"))
                    else:
                        etree.SubElement(ln, qn("a:noFill"))
                    tcPr.insert(i, ln)
        shape.left, shape.top, shape.width, shape.height = _e(r.x), _e(r.y), _e(r.w), _e(r.h)
        if more:
            y = min(r.y + _ROW_PX * n + 8, r.y + r.h - ts.size * ts.line_height)
            self._text(slide, f"slot:{spec.name}:more", Rect(r.x, y, r.w, ts.size * ts.line_height), [f"+{more} more rows"], ts,
                       font=_family(self.t.fonts.body), color=self.c.ink_muted)

    def _picture(self, slide, spec, r: Rect, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"image_path does not exist: {path}")
        pic = slide.shapes.add_picture(str(path), _e(r.x), _e(r.y), _e(r.w), _e(r.h))
        pic.name = f"slot:{spec.name}"
        with Image.open(path) as im:
            w, h = im.size
        # object-fit: contain, keeping the frame at slot_rect: negative crop pads the short side.
        if w / h > r.w / r.h:
            pic.crop_top = pic.crop_bottom = -((r.h * w / r.w / h) - 1) / 2
        else:
            pic.crop_left = pic.crop_right = -((r.w * h / r.h / w) - 1) / 2

    def _slot(self, slide, i: int, spec, content: SlideContent, datasets: dict[str, QuantitativeDataset]) -> None:
        r, ts, value = slot_rect(self.t, spec), self.t.type[spec.type_role], content.slots.get(spec.name)
        name, body = f"slot:{spec.name}", _family(self.t.fonts.body if ts.font == "body" else self.t.heading_font(self.mode))
        if spec.kind == "chart" and content.chart:
            if is_native(content.chart):
                kind, data = build_native_chart_data(content.chart, list(datasets.values()))
                frame = slide.shapes.add_chart(kind, _e(r.x), _e(r.y), _e(r.w), _e(r.h), data)
                frame.name = name
                style_native_chart(frame.chart, content.chart, self.theme, min_pt=18)  # 24px floor on the 1920px canvas
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    img = render_chart_image(content.chart, list(datasets.values()), Path(tmp) / "c.png", width_in=r.w / 96, height_in=r.h / 96, theme=self.theme)
                    slide.shapes.add_picture(str(img), _e(r.x), _e(r.y), _e(r.w), _e(r.h)).name = name
        elif spec.kind == "table" and content.table and content.table.dataset_id in datasets:
            self._table(slide, spec, r, content, datasets[content.table.dataset_id])
        elif spec.kind == "image" and content.image_path:
            self._picture(slide, spec, r, Path(content.image_path))
        elif spec.kind == "list":
            items = value if isinstance(value, list) else ([value] if value else [])
            # Timeline: numbered steps (the HTML's dots-on-a-rule would need per-step shapes); other lists get bullets.
            self._text(slide, name, r, items, ts, font=body, color=self.c.ink, bullet="num" if content.layout == "timeline" else "dot")
        else:
            text = " ".join(value) if isinstance(value, list) else (value or "")
            if spec.kind == "number":
                # Metric numbers are ink (DESIGN.md); bottom-aligned on its label, like the HTML; the descent padding is 0.2em
                self._text(slide, name, Rect(r.x, r.y, r.w, r.h), [text], ts, font=body, color=self.c.ink, wrap=False, anchor=MSO_ANCHOR.BOTTOM)
            elif spec.name.startswith("label_"):
                self._rule(slide, f"{name}:rule", Rect(r.x, r.y, r.w, 1), self.c.neutral)
                self._text(slide, name, r, [text], ts, font=_family(self.t.fonts.mono or self.t.fonts.body), color=self.c.ink, pad_top=16)
            else:
                self._text(slide, name, r, [text] if text else [], ts, font=body, color=self.c.ink)

    def slide(self, prs, i: int, content: SlideContent, datasets: dict[str, QuantitativeDataset]) -> None:
        t, g = self.t, self.t.grid
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = _rgb(self.c.background)
        self._rule(slide, "accent_rule", Rect(g.margin_x, g.margin_top - 32 - g.rule_height, g.rule_width, g.rule_height), self.c.ink)
        if content.layout not in ("title", "section"):  # those show the title in their own slot, as in the HTML
            self._text(slide, "headline", Rect(g.margin_x, g.margin_top, t.canvas.width - 2 * g.margin_x, g.headline_band - 32), [content.headline], t.type["headline"],
                       font=_family(t.heading_font(self.mode)), color=self.c.ink)
        for spec in get_variant(content.layout, content.variant).slots:
            self._slot(slide, i, spec, content, datasets)
        top, mono = t.canvas.height - g.margin_bottom - g.footer_band, _family(t.fonts.mono or t.fonts.body)
        cap = t.type["caption"]
        self._rule(slide, "footer:rule", Rect(g.margin_x, top, t.canvas.width - 2 * g.margin_x, 1), self.c.neutral)
        row = Rect(g.margin_x, top, t.canvas.width - 2 * g.margin_x, g.footer_band)
        self._text(slide, "footer:refs", row, [" · ".join(content.source_refs)], cap, font=mono, color=self.c.ink_muted, anchor=MSO_ANCHOR.MIDDLE)
        self._text(slide, "footer:page", row, [str(i + 1)], cap, font=mono, color=self.c.ink_muted, anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.RIGHT)
        if content.speaker_notes:
            slide.notes_slide.notes_text_frame.text = content.speaker_notes


def build_house_pptx(deck: Deck, datasets: list[QuantitativeDataset], out: Path, tokens: Tokens | None = None, mode: Mode = "light") -> Path:
    tokens = tokens or load_tokens()
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(_e(tokens.canvas.width)), Emu(_e(tokens.canvas.height))
    b, by_id = _Builder(tokens, mode), {d.dataset_id: d for d in datasets}
    for i, content in enumerate(deck.slides):
        b.slide(prs, i, content, by_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)
    return out
