"""Render-model primitives -> absolutely positioned HTML for one slide; every element carries `data-name`.

Charts are inline SVG drawn from the ChartPrim geometry (no matplotlib), so the box matches the PPTX chart frame.
"""

from __future__ import annotations

from html import escape

from arp.reporting.house_style import Mode, Tokens
from arp.reporting.render_model import ChartPrim, Line, Primitive, Rect, TablePrim, Text, decimals, family, palette

_LABEL = 20  # chart label size, px
_JUSTIFY = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}


def _box(name: str, x: float, y: float, w: float, h: float, style: str = "", tag: str = "div") -> str:
    return f'<{tag} data-name="{escape(name)}" style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;{style}"'


def _font(fam: str) -> str:
    return f"font-family:'{fam.replace(chr(39), '')}',var(--font-body)"


def _rect(p: Rect) -> str:
    border = f"border:{p.line_w}px solid {p.line};" if p.line and p.line_w else ""
    return _box(p.name, p.x, p.y, p.w, p.h, f"box-sizing:border-box;background:{p.fill or 'transparent'};{border}") + "></div>"


def _text(p: Text) -> str:
    style = (f"box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;justify-content:{_JUSTIFY[p.anchor]};"
             f"text-align:{p.align};white-space:pre-line;{_font(p.family)};font-size:{p.size}px;font-weight:{p.weight};line-height:1.2;")
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
        head = f'<polygon points="{" ".join(f"{x},{y}" for x, y in tri)}" fill="{p.color}"/>'
    # An SVG with a zero width or height is not drawn at all; 0.1 px keeps a straight rule visible and its box at the PPTX one.
    return (_box(p.name, x0, y0, max(max(xs) - x0, 0.1), max(max(ys) - y0, 0.1), "overflow:visible;", "svg")
            + f'><polyline points="{pts}" fill="none" stroke="{p.color}" stroke-width="{p.width}"/>{head}</svg>')


def _chart(p: ChartPrim, c: dict[str, str], body: str) -> str:
    n, dec = len(p.categories), decimals([v for s in p.series for v in s.values])
    fmt = lambda v: f"{v:.{dec}f}{p.unit}"  # noqa: E731
    txt = lambda x, y, s, anchor="middle": (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{_LABEL}" '  # noqa: E731
                                            f'fill="{c["muted"]}">{escape(s)}</text>')
    stacked = p.kind == "stacked_column"
    if stacked:
        tops = [sum(max(s.values[i], 0) for s in p.series) for i in range(n)]
        lows = [sum(min(s.values[i], 0) for s in p.series) for i in range(n)]
    else:
        tops = lows = [v for s in p.series for v in s.values]
    lo, hi = min(0, *lows), max(0, *tops)
    hi = hi if hi > lo else lo + 1
    out = []
    if p.kind == "bar":  # horizontal: category labels left, value labels right of the bar
        lw, band = min(0.3 * p.w, 320), p.h / max(n, 1)
        x0, x1 = lw + 16, p.w - (96 if p.labels else 0)
        sx = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)  # noqa: E731
        bh = band * 0.6 / len(p.series)
        for i, cat in enumerate(p.categories):
            out.append(txt(0, i * band + band / 2 + _LABEL / 3, cat, "start"))
            for j, s in enumerate(p.series):
                v, y = s.values[i], i * band + band * 0.2 + j * bh
                out.append(f'<rect x="{min(sx(0), sx(v))}" y="{y}" width="{abs(sx(v) - sx(0))}" height="{bh}" fill="{s.colors[i]}"/>')
                if p.labels:
                    out.append(txt(max(sx(0), sx(v)) + 8, y + bh / 2 + _LABEL / 3, fmt(v), "start"))
    else:
        band, y0, y1 = p.w / max(n, 1), (32 if p.labels else 0), p.h - 40
        sy = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
        for i, cat in enumerate(p.categories):
            out.append(txt(i * band + band / 2, p.h - 12, cat))
        if p.kind == "line":
            for s in p.series:
                pts = [(i * band + band / 2, sy(v)) for i, v in enumerate(s.values)]
                out.append(f'<polyline points="{" ".join(f"{x},{y}" for x, y in pts)}" fill="none" stroke="{s.colors[0]}" stroke-width="3"/>')
                for i, (x, y) in enumerate(pts):
                    out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{s.colors[i]}"/>')
                    if p.labels:
                        out.append(txt(x, y - 14, fmt(s.values[i])))
        else:
            bw = band * 0.6 / (1 if stacked else len(p.series))
            for i in range(n):
                pos = neg = 0.0
                for j, s in enumerate(p.series):
                    v = s.values[i]
                    if stacked:
                        base = pos if v >= 0 else neg
                        a, b, x = base, base + v, i * band + band * 0.2
                        pos, neg = (b, neg) if v >= 0 else (pos, b)
                    else:
                        a, b, x = 0, v, i * band + band * 0.2 + j * bw
                    top, bot = sy(max(a, b)), sy(min(a, b))
                    out.append(f'<rect x="{x}" y="{top}" width="{bw}" height="{bot - top}" fill="{s.colors[i]}"/>')
                    if p.labels:
                        out.append(txt(x + bw / 2, (top + bot) / 2 + _LABEL / 3 if stacked else top - 8, fmt(v)))
    return (_box(p.name, p.x, p.y, p.w, p.h, "", "svg") + f' viewBox="0 0 {p.w} {p.h}" font-family="{escape(body)}">'
            + "".join(out) + "</svg>")


def _table(p: TablePrim, c: dict[str, str], body: str, mono: str) -> str:
    c = {**c, **p.style}
    rows = [p.header, *p.rows, *([p.total] if p.total else [])]
    rh = p.h / len(rows)

    def cell(ri: int, ci: int, v: str) -> str:
        head, total = ri == 0, p.total is not None and ri == len(rows) - 1
        style = f"height:{rh}px;box-sizing:border-box;padding:0 12px;text-align:left;"
        if head:
            style += f"{_font(mono)};font-size:18px;font-weight:400;text-transform:uppercase;color:{c['muted']};border-bottom:2px solid {c['ink']};"
        else:
            hl = ci == p.highlight_col
            style += (f"{_font(body)};font-size:24px;font-weight:{600 if total or hl else 400};color:{c['highlight'] if hl else c['ink']};"
                      + (f"border-top:2px solid {c['ink']};" if total else f"border-bottom:1px solid {c['line']};"))
        return f'<td style="{style}">{escape(v)}</td>'

    trs = "".join("<tr>" + "".join(cell(ri, ci, v) for ci, v in enumerate(r)) + "</tr>" for ri, r in enumerate(rows))
    return (_box(p.name, p.x, p.y, p.w, p.h, "overflow:hidden;")
            + f'><table style="width:100%;height:100%;border-collapse:collapse;table-layout:fixed">{trs}</table></div>')


def html_slide(prims: list[Primitive], tokens: Tokens, mode: Mode) -> str:
    """The slide's elements, in draw order; empty text is skipped."""
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
            out.append(_chart(p, c, body))
        elif isinstance(p, TablePrim):
            out.append(_table(p, c, body, mono))
    return "\n".join(out)
