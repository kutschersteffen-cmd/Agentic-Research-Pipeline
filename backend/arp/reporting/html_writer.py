"""Render-model primitives -> absolutely positioned HTML for one slide; every element carries `data-name`.

Charts are inline Vega-Lite SVG drawn from the ChartPrim geometry (`vega.py`), so the box matches the PPTX chart frame.
"""

from __future__ import annotations

import base64
from html import escape

from arp.reporting.house_style import Mode, Tokens
from arp.reporting.image_embed import embedded
from arp.reporting.render_model import (
    ChartPrim,
    ImagePrim,
    Line,
    Primitive,
    Rect,
    TablePrim,
    Text,
    family,
    palette,
)
from arp.reporting.vega import chart_spec, to_svg
from arp.storage.report_images import LoadedImage

_JUSTIFY = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}


def _a(v: object) -> str:
    """An attribute value: colours, families and styles may come from an uploaded template, so they are always escaped."""
    return escape(str(v), quote=True)


def _box(name: str, x: float, y: float, w: float, h: float, style: str = "", tag: str = "div") -> str:
    return f'<{tag} data-name="{_a(name)}" style="{_a(f"position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;{style}")}"'


def _font(fam: str) -> str:
    quoted = "".join(ch for ch in fam if ch.isprintable()).replace("\\", "\\\\").replace("'", "\\'")  # a CSS string
    return f"font-family:'{quoted}',var(--font-body)"


def _rect(p: Rect) -> str:
    border = f"border:{p.line_w}px solid {p.line};" if p.line and p.line_w else ""
    return _box(p.name, p.x, p.y, p.w, p.h, f"box-sizing:border-box;background:{p.fill or 'transparent'};{border}") + "></div>"


def _text(p: Text) -> str:
    style = (f"box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;justify-content:{_JUSTIFY[p.anchor]};"
             f"text-align:{p.align};white-space:pre-line;{_font(p.family)};font-size:{p.size}px;font-weight:{p.weight};line-height:{p.leading};")
    style += f"color:transparent;-webkit-text-stroke:2px {p.color};" if p.outline else f"color:{p.color};"
    if p.fill_under:
        style += f"background:{p.fill_under};"
    return _box(p.name, p.x, p.y, p.w, p.h, style) + f">{escape(p.text)}</div>"


def _line(p: Line) -> str:
    xs, ys = [x for x, _ in p.points], [y for _, y in p.points]
    x0, y0 = min(xs), min(ys)
    pts = " ".join(f"{x - x0},{y - y0}" for x, y in p.points)
    head = ""
    if p.arrow and len(p.points) > 1:  # a filled triangle at the last point, 3x the stroke like PowerPoint's medium tailEnd
        (ax, ay), (bx, by) = p.points[-2], p.points[-1]
        d = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1
        ux, uy, s = (bx - ax) / d, (by - ay) / d, 3 * p.width
        bx, by = bx - x0, by - y0
        tri = [(bx, by), (bx - ux * s - uy * s / 2, by - uy * s + ux * s / 2), (bx - ux * s + uy * s / 2, by - uy * s - ux * s / 2)]
        head = f'<polygon points="{" ".join(f"{x},{y}" for x, y in tri)}" fill="{_a(p.color)}"/>'
    # An SVG with a zero width or height is not drawn at all; 0.1 px keeps a straight rule visible and its box at the PPTX one.
    return (_box(p.name, x0, y0, max(max(xs) - x0, 0.1), max(max(ys) - y0, 0.1), "overflow:visible;", "svg")
            + f'><polyline points="{pts}" fill="none" stroke="{_a(p.color)}" stroke-width="{p.width}"/>{head}</svg>')


def _chart(p: ChartPrim, tokens: Tokens, mode: Mode) -> str:
    """The Vega-Lite SVG in the chart's box: its root `<svg>` gets the box's `data-name` and absolute position."""
    svg = to_svg(chart_spec(p, tokens, mode), tokens)
    return _box(p.name, p.x, p.y, p.w, p.h, "", "svg") + svg.removeprefix("<svg")


def _table(p: TablePrim, c: dict[str, str], body: str, mono: str) -> str:
    c = {**c, **p.style}
    rows = [p.header, *p.rows, *([p.total] if p.total else [])]
    rh = p.h / len(rows)

    def cell(ri: int, ci: int, v: str) -> str:
        head, total, hl = ri == 0, p.total is not None and ri == len(rows) - 1, ci == p.highlight_col
        align = p.align[ci] if p.align else "left"
        style = f"height:{rh}px;box-sizing:border-box;padding:0 12px;text-align:{align};"
        if head:  # the highlighted column's header is an ink block with panel text (highlight is never a text colour)
            style += (f"{_font(mono)};font-size:18px;font-weight:400;text-transform:uppercase;color:{c['panel' if hl else 'muted']};"
                      f"border-bottom:2px solid {c['ink']};" + (f"background:{c['ink']};" if hl else ""))
        else:
            fam = mono if p.mono and p.mono[ci] else body
            style += (f"{_font(fam)};font-size:24px;font-weight:{600 if total or hl else 400};color:{c['ink']};"
                      + (f"background:{c['ground']};" if hl else "")
                      + (f"border-top:2px solid {c['ink']};" if total else f"border-bottom:1px solid {c['line']};"))
        return f'<td style="{_a(style)}">{escape(v)}</td>'

    trs = "".join("<tr>" + "".join(cell(ri, ci, v) for ci, v in enumerate(r)) + "</tr>" for ri, r in enumerate(rows))
    return (_box(p.name, p.x, p.y, p.w, p.h, "overflow:hidden;")
            + f'><table style="width:100%;height:100%;border-collapse:collapse;table-layout:fixed">{trs}</table></div>')


def _pos(a: float, b: float) -> float:
    """object-position percent for crop fractions `a` (left/top) and `b` (right/bottom): the PPTX crop's region."""
    return 100 * a / (a + b) if a + b else 50


def _image(p: ImagePrim, images: dict[str, LoadedImage]) -> str:
    left, top, right, bottom = p.crop
    data = images[p.image].data  # empty when only measuring (layout_images): the box is the same without pixels
    src = f' src="data:{p.media_type};base64,{base64.b64encode(embedded(data)).decode()}"' if data else ""
    style = f"display:block;object-fit:cover;object-position:{_pos(left, right):g}% {_pos(top, bottom):g}%;"
    return _box(p.name, p.x, p.y, p.w, p.h, style, "img") + f'{src} alt="{_a(p.alt)}">'


def html_slide(prims: list[Primitive], tokens: Tokens, mode: Mode, images: dict[str, LoadedImage] | None = None) -> str:
    """The slide's elements, in draw order; empty text is skipped. `images` holds the bytes behind the image primitives."""
    c = palette(tokens, mode)
    body, mono = family(tokens.fonts.body), family(tokens.fonts.mono or tokens.fonts.body)
    out = []
    for p in prims:
        if isinstance(p, Rect):
            out.append(_rect(p))
        elif isinstance(p, Text):
            if p.text:
                out.append(_text(p))
        elif isinstance(p, Line):
            out.append(_line(p))
        elif isinstance(p, ChartPrim):
            out.append(_chart(p, tokens, mode))
        elif isinstance(p, TablePrim):
            out.append(_table(p, c, body, mono))
        elif isinstance(p, ImagePrim):
            out.append(_image(p, images or {}))
    return "\n".join(out)
