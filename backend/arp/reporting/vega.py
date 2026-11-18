"""Charts as Vega-Lite specs, rendered in-process by vl-convert (no browser).

`chart_spec` turns a component `ChartPrim` into a Vega-Lite spec whose geometry is the render model's (`value_range`,
`bar_plot_x`, `column_plot_y`, `line_point`), so the HTML chart lines up with the PowerPoint chart and the callouts.
Fonts, text sizes and text colours come from `style/chart_theme.json` only. Every bar or point carries an `aria-label`
`<category> | <series> | <label>`; text marks and line paths are hidden from it.
Spec: docs/superpowers/specs/2026-11-18-house-deck-vega-lite-charts.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import vl_convert as vlc

from arp.reporting.house_style import Mode, Tokens
from arp.reporting.render_model import (
    CHART_LABEL,
    LINE_PAD,
    ChartPrim,
    bar_label_width,
    bar_plot_x,
    column_plot_y,
    decimals,
    family,
    line_scale,
    palette,
    value_range,
)

VL_VERSION = "6.4"  # pinned per call, so a wheel upgrade cannot change the charts silently
STYLE_DIR = Path(__file__).parent / "style"
THEME_PATH = STYLE_DIR / "chart_theme.json"
POINT_R = 6
_fonts_registered: set[str] = set()


def theme_config(tokens: Tokens, mode: Mode) -> dict:
    """The theme file with `{key}` strings filled from the palette and `{body}` from the body font."""
    subs = {**palette(tokens, mode), "body": family(tokens.fonts.body)}

    def fill(v):
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fill(x) for x in v]
        if isinstance(v, str) and v.startswith("{") and v.endswith("}") and v[1:-1] in subs:
            return subs[v[1:-1]]
        return v

    return fill(json.loads(THEME_PATH.read_text()))


def _register_fonts(tokens: Tokens) -> None:
    """The house fonts and the template's, once per process, so label widths are measured with the real faces."""
    for d in (STYLE_DIR / "fonts", tokens.font_dir):
        if d and str(d) not in _fonts_registered and Path(d).is_dir():
            vlc.register_font_directory(str(d))
            _fonts_registered.add(str(d))


def _lin(domain: tuple[float, float], rng: tuple[float, float]) -> dict:
    return {"domain": list(domain), "range": list(rng), "nice": False, "zero": False}


def _q(f: str, scale: dict | None = None) -> dict:
    return {"field": f, "type": "quantitative", **({"scale": scale, "axis": None} if scale else {})}


def _layer(rows: list[dict], mark: dict, enc: dict) -> dict:
    return {"data": {"values": rows}, "mark": mark, "encoding": enc}


def _text(rows, x, y, align, dx, dy, style, limit=None) -> dict:
    mark = {"type": "text", "align": align, "baseline": "alphabetic", "dx": dx, "dy": dy, "aria": False, "style": style}
    if limit:
        mark["limit"] = limit
    return _layer(rows, mark, {"x": x, "y": y, "text": {"field": "t"}})


def chart_spec(p: ChartPrim, tokens: Tokens, mode: Mode) -> dict:
    """The Vega-Lite spec of a component chart, the full `p.w` × `p.h` box, no axes, no legend, no background."""
    n, dec = len(p.categories), decimals([v for s in p.series for v in s.values])
    fmt = lambda v: f"{v:.{dec}f}{p.unit}".replace("-", "−")  # noqa: E731
    desc = lambda i, s, v: f"{p.categories[i]} | {s.name} | {fmt(v)}"  # noqa: E731
    c = palette(tokens, mode)
    lab = CHART_LABEL / 3  # today's baseline offset: labels centred on their band or point
    marks, cats, vals = [], [], []  # data marks (series by series, category order), category and data labels
    fill = {"field": "fill", "type": "nominal", "scale": None, "legend": None}
    if p.kind == "line":
        top, right, bottom = LINE_PAD
        xs, ys = _lin((0, n), (0, p.w - right)), _lin(line_scale(p), (p.h - bottom, top))
        pts = [{"x": i + 0.5, "y": v, "s": s.name, "fill": s.colors[i], "d": desc(i, s, v)}
               for s in p.series for i, v in enumerate(s.values)]
        lines = [{"x": i + 0.5, "y": v, "s": s.name, "stroke": s.colors[0], "sw": 6 if s.colors[0] == c["highlight"] else 4}
                 for s in p.series for i, v in enumerate(s.values)]
        cats = [{"x": i + 0.5, "t": cat} for i, cat in enumerate(p.categories)]
        layers = [
            _layer(lines, {"type": "line", "aria": False},
                   {"x": _q("x", xs), "y": _q("y", ys), "detail": {"field": "s"},
                    "stroke": {"field": "stroke", "type": "nominal", "scale": None, "legend": None},
                    "strokeWidth": {"field": "sw", "type": "quantitative", "scale": None, "legend": None}}),
            _layer(pts, {"type": "circle", "opacity": 1, "size": (2 * POINT_R) ** 2},  # a symbol's size is its box area
                   {"x": _q("x", xs), "y": _q("y", ys), "fill": fill, "description": {"field": "d"}}),
            _text(cats, _q("x", xs), {"value": p.h - 12}, "center", 0, 0, "category-label", (p.w - right) / n),
        ]
        if p.labels:
            ends = [{"x": n - 0.5, "y": s.values[-1], "t": f"{s.name} {fmt(s.values[-1])}"} for s in p.series]
            layers.append(_text(ends, _q("x", xs), _q("y", ys), "left", 16, lab, "data-label"))
        return _spec(p, layers, tokens, mode)
    lo, hi = value_range(p)
    stacked = p.kind == "stacked_column"
    f = 0.6 / (1 if stacked else len(p.series))
    pos, neg = [0.0] * n, [0.0] * n
    for j, s in enumerate(p.series):
        for i, v in enumerate(s.values):
            if stacked:
                base = pos[i] if v >= 0 else neg[i]
                a, b, o = base, base + v, i + 0.2
                pos[i], neg[i] = (b, neg[i]) if v >= 0 else (pos[i], b)
            else:
                a, b, o = 0, v, i + 0.2 + j * f
            marks.append({"a": a, "b": b, "o": o, "o2": o + f, "fill": s.colors[i], "d": desc(i, s, v)})
            vals.append({"o": o + f / 2, "v": (a + b) / 2 if stacked else max(a, b), "t": fmt(v)})
    cats = [{"o": i + 0.5, "t": cat} for i, cat in enumerate(p.categories)]
    if p.kind == "bar":  # horizontal: bands top to bottom, labels right-aligned left of the bars, values right of them
        vs, bs = _lin((lo, hi), bar_plot_x(p)), _lin((0, n), (0, p.h))
        enc = {"x": _q("a", vs), "x2": {"field": "b"}, "y": _q("o", bs), "y2": {"field": "o2"}}
        layers = [_text(cats, {"value": bar_label_width(p)}, _q("o", bs), "right", 0, lab, "category-label", bar_label_width(p))]
        if p.labels:
            layers.append(_text(vals, _q("v", vs), _q("o", bs), "left", 8, lab, "data-label"))
    else:
        y0, y1 = column_plot_y(p)
        vs, bs = _lin((lo, hi), (y1, y0)), _lin((0, n), (0, p.w))
        enc = {"x": _q("o", bs), "x2": {"field": "o2"}, "y": _q("a", vs), "y2": {"field": "b"}}
        layers = [_text(cats, _q("o", bs), {"value": p.h - 12}, "center", 0, 0, "category-label", p.w / n)]
        if p.labels:
            layers.append(_text(vals, _q("o", bs), _q("v", vs), "center", 0, lab if stacked else -8, "data-label"))
    bars = _layer(marks, {"type": "rect"}, {**enc, "fill": fill, "description": {"field": "d"}})
    return _spec(p, [bars, *layers], tokens, mode)


def _spec(p: ChartPrim, layers: list[dict], tokens: Tokens, mode: Mode) -> dict:
    return {"width": p.w, "height": p.h, "autosize": "none", "padding": 0, "background": None,
            "config": theme_config(tokens, mode), "layer": layers}


def to_svg(spec: dict, tokens: Tokens) -> str:
    _register_fonts(tokens)
    return vlc.vegalite_to_svg(spec, vl_version=VL_VERSION)
