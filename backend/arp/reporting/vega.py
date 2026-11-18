"""Charts as Vega-Lite specs, rendered in-process by vl-convert (no browser).

`chart_spec` turns a component `ChartPrim` into a Vega-Lite spec whose geometry is the render model's (`value_range`,
`bar_plot_x`, `column_plot_y`, `line_point`), so the HTML chart lines up with the PowerPoint chart and the callouts.
`layout_spec` does the same for a layout slide's `ChartSpec` (every `ChartType` but radar and table). Fonts, text sizes
and text colours come from `style/chart_theme.json` only. Every bar, point, wedge or cell carries an `aria-label`
`<category> | <series> | <label>` (heatmap: `<row> | <column> | <label>`); text marks and line paths are hidden from it.
Spec: docs/superpowers/specs/2026-11-18-house-deck-vega-lite-charts.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import vl_convert as vlc

from arp.reporting.chart_builder import ChartDataError, _as_float_or_zero, _column, _dataset_by_id
from arp.reporting.design import DesignTheme, categorical_color
from arp.reporting.house_style import Mode, Tokens
from arp.reporting.render_model import (
    CHART_LABEL,
    LINE_PAD,
    ChartPrim,
    Series,
    bar_label_width,
    bar_plot_x,
    column_plot_y,
    decimals,
    family,
    line_scale,
    palette,
    value_range,
)
from arp.schemas.chart_specs import ChartSpec, ChartType
from arp.schemas.reporting import QuantitativeDataset

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


def chart_spec(p: ChartPrim, tokens: Tokens, mode: Mode, highlight: bool = True) -> dict:
    """The Vega-Lite spec of a component chart, the full `p.w` × `p.h` box, no axes, no legend, no background.
    `highlight=False` (layout slides) draws every line 4 px."""
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
        lines = [{"x": i + 0.5, "y": v, "s": s.name, "stroke": s.colors[0], "sw": 6 if highlight and s.colors[0] == c["highlight"] else 4}
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


def _fmt(values: list[float], unit: str = "", sign: bool = False):
    """The data-label formatter: `decimals()` places over all values, the unit, `−` for minus (`+` too when signed)."""
    dec = decimals(values)
    return lambda v: f"{v:{'+' if sign else ''}.{dec}f}{unit}".replace("-", "−")


def _padded(values: list[float]) -> tuple[float, float]:
    """Min to max with 10% padding, as `line_scale`."""
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.1 or 1
    return lo - pad, hi + pad


def _hex(c: str) -> tuple[int, ...]:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def heatmap_layers(rows: list[str], cols: list[str], cells: dict[tuple[int, int], float], w: float, h: float,
                   tokens: Tokens, mode: Mode, fmt) -> list[dict]:
    """Cells filled `ground` (lowest) to `highlight` (highest) in RGB, each labelled `panel` above the midpoint, else `ink`;
    row labels left, column labels below. Cells are emitted row by row, each in column order; a missing cell has no mark."""
    c = palette(tokens, mode)
    lo, hi = min(cells.values()), max(cells.values())
    g, k = _hex(c["ground"]), _hex(c["highlight"])

    def look(v: float) -> tuple[str, str]:
        if hi == lo:
            return c["highlight"], c["panel"]
        t = (v - lo) / (hi - lo)
        return "#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(g, k, strict=True)), c["panel"] if v > (lo + hi) / 2 else c["ink"]

    lw = min(0.3 * w, 240)
    xs, ys = _lin((0, len(cols)), (lw + 16, w)), _lin((0, len(rows)), (0, h - 40))
    data = [{"x": j + 0.02, "x2": j + 0.98, "y": i + 0.02, "y2": i + 0.98, "xm": j + 0.5, "ym": i + 0.5, "fill": look(v)[0],
             "lc": look(v)[1], "t": fmt(v), "d": f"{rows[i]} | {cols[j]} | {fmt(v)}"} for (i, j), v in sorted(cells.items())]
    fill = {"field": "fill", "type": "nominal", "scale": None, "legend": None}
    labels = _text(data, _q("xm", xs), _q("ym", ys), "center", 0, CHART_LABEL / 3, "data-label")
    labels["encoding"]["fill"] = {"field": "lc", "type": "nominal", "scale": None, "legend": None}
    return [
        _layer(data, {"type": "rect"}, {"x": _q("x", xs), "x2": {"field": "x2"}, "y": _q("y", ys), "y2": {"field": "y2"},
                                        "fill": fill, "description": {"field": "d"}}),
        labels,
        _text([{"y": i + 0.5, "t": r} for i, r in enumerate(rows)], {"value": lw}, _q("y", ys), "right", 0, CHART_LABEL / 3,
              "category-label", lw),
        _text([{"x": j + 0.5, "t": col} for j, col in enumerate(cols)], _q("x", xs), {"value": h - 12}, "center", 0, 0,
              "category-label", (w - lw - 16) / len(cols)),
    ]


def layout_spec(spec: ChartSpec, datasets: list[QuantitativeDataset], w: float, h: float, theme: DesignTheme,
                tokens: Tokens, mode: Mode) -> dict:
    """The Vega-Lite spec of a layout slide's chart in a `w` × `h` slot: the component geometry for bar, column, stacked
    column and line (no highlight), own geometry for area, pie, doughnut, scatter, waterfall and heatmap.
    Labels use the data-label formatter with an empty unit; fills are `categorical_color` per series (pie: per category)."""
    ds = _dataset_by_id(datasets, spec.dataset_id)
    if not ds.rows:
        raise ChartDataError(f"Chart on dataset {ds.dataset_id!r} has no rows.")
    kind = spec.chart_type
    if kind == ChartType.HEATMAP:
        rc = _column(ds, spec.y_column, label="y_column (heatmap row axis)")
        cc = _column(ds, spec.category_column, label="category_column (heatmap column axis)")
        vc = _column(ds, spec.value_column, label="value_column (heatmap cell values)")
        rows = list(dict.fromkeys(str(r.get(rc)) for r in ds.rows))
        cols = list(dict.fromkeys(str(r.get(cc)) for r in ds.rows))
        cells: dict[tuple[int, int], float] = {}
        for r in ds.rows:
            key = rows.index(str(r.get(rc))), cols.index(str(r.get(cc)))
            if key in cells:
                raise ChartDataError(f"duplicate heatmap cell ({r.get(rc)}, {r.get(cc)})")
            cells[key] = _as_float_or_zero(r.get(vc))
        return _frame(w, h, heatmap_layers(rows, cols, cells, w, h, tokens, mode, _fmt(list(cells.values()))), tokens, mode)
    cols = [_column(ds, c, label="value_columns") for c in spec.value_columns]
    if not cols:
        raise ChartDataError("Chart needs at least one value_columns entry.")
    one = kind in (ChartType.PIE, ChartType.DOUGHNUT, ChartType.WATERFALL)
    xs: list[float] = []
    if kind == ChartType.SCATTER:
        x_col = _column(ds, spec.x_column, label="x_column")
        xs = [_as_float_or_zero(r.get(x_col)) for r in ds.rows]
        cats = [_fmt(xs)(x) for x in xs]
    else:
        cat_col = _column(ds, spec.category_column, label="category_column")
        cats = [str(r.get(cat_col, "")) for r in ds.rows]
    color = lambda i: "#" + categorical_color(theme, i).lstrip("#")  # noqa: E731
    series = [Series(c, [_as_float_or_zero(r.get(c)) for r in ds.rows],
                     [color(i) for i in range(len(cats))] if kind in (ChartType.PIE, ChartType.DOUGHNUT) else [color(j)] * len(cats))
              for j, c in enumerate(cols[:1] if one else cols)]
    p = ChartPrim("chart", 0, 0, w, h, kind.value, cats, series, "", True)
    if kind in (ChartType.BAR, ChartType.COLUMN, ChartType.STACKED_COLUMN, ChartType.LINE):
        return chart_spec(p, tokens, mode, highlight=False)
    if kind == ChartType.AREA:
        layers = _area(p)
    elif kind in (ChartType.PIE, ChartType.DOUGHNUT):
        layers = _pie(p, palette(tokens, mode)["panel"])
    elif kind == ChartType.SCATTER:
        layers = _scatter(p, xs)
    elif kind == ChartType.WATERFALL:
        layers = _waterfall(p)
    else:
        raise ChartDataError(f"{kind.value} charts are not drawn by Vega-Lite")
    return _frame(w, h, layers, tokens, mode)


_FILL = {"field": "fill", "type": "nominal", "scale": None, "legend": None}


def _points(p: ChartPrim, xs: list[float] | None = None) -> list[dict]:
    """One row per value, series by series, each in category order; `x` is the band centre or the scatter x."""
    fmt = _fmt([v for s in p.series for v in s.values])
    return [{"x": xs[i] if xs else i + 0.5, "y": v, "s": s.name, "fill": s.colors[i], "t": fmt(v),
             "d": f"{p.categories[i]} | {s.name} | {fmt(v)}"} for s in p.series for i, v in enumerate(s.values)]


def _area(p: ChartPrim) -> list[dict]:
    lo, hi = value_range(p)
    y0, y1 = column_plot_y(p)
    xs, vs = _lin((0, len(p.categories)), (0, p.w)), _lin((lo, hi), (y1, y0))
    pts = _points(p)
    enc = {"x": _q("x", xs), "y": _q("y", vs), "detail": {"field": "s"}}
    return [
        _layer(pts, {"type": "area", "aria": False, "opacity": 0.18}, {**enc, "y2": {"datum": 0}, "fill": _FILL}),
        _layer(pts, {"type": "line", "aria": False, "strokeWidth": 4}, {**enc, "stroke": {**_FILL, "field": "fill"}}),
        _layer(pts, {"type": "circle", "opacity": 1, "size": (2 * POINT_R) ** 2}, {**enc, "fill": _FILL, "description": {"field": "d"}}),
        _text(pts, _q("x", xs), _q("y", vs), "center", 0, -16, "data-label"),
        _text([{"x": i + 0.5, "t": c} for i, c in enumerate(p.categories)], _q("x", xs), {"value": p.h - 12}, "center", 0, 0,
              "category-label", p.w / len(p.categories)),
    ]


def _pie(p: ChartPrim, panel: str) -> list[dict]:
    """Radius 0.4 × min(w, h), centred; doughnut inner radius 0.6 × radius; `<category> <label>` outside each wedge."""
    r = 0.4 * min(p.w, p.h)
    pts = [{**d, "o": i, "t": f"{p.categories[i]} {d['t']}"} for i, d in enumerate(_points(p))]
    theta = {"theta": {"field": "y", "type": "quantitative", "stack": True}, "order": {"field": "o", "type": "quantitative"}}
    arc = {"type": "arc", "radius": r, "innerRadius": 0.6 * r if p.kind == "doughnut" else 0, "stroke": panel, "strokeWidth": 2}
    text = {"type": "text", "radius": r + 48, "align": "center", "baseline": "middle", "aria": False, "style": "data-label"}
    return [_layer(pts, arc, {**theta, "fill": _FILL, "description": {"field": "d"}}), _layer(pts, text, {**theta, "text": {"field": "t"}})]


def _scatter(p: ChartPrim, xs: list[float]) -> list[dict]:
    """Both scales min to max with 10% padding over the `LINE_PAD` plot extent; x labels below, y labels above the points."""
    top, right, bottom = LINE_PAD
    xsc, ysc = _lin(_padded(xs), (0, p.w - right)), _lin(line_scale(p), (p.h - bottom, top))
    pts = _points(p, xs)
    ticks = list({x: {"x": x, "t": c} for x, c in zip(xs, p.categories, strict=True)}.values())
    return [
        _layer(pts, {"type": "circle", "opacity": 1, "size": (2 * POINT_R) ** 2},
               {"x": _q("x", xsc), "y": _q("y", ysc), "fill": _FILL, "description": {"field": "d"}}),
        _text(pts, _q("x", xsc), _q("y", ysc), "center", 0, -16, "data-label"),
        _text(ticks, _q("x", xsc), {"value": p.h - 12}, "center", 0, 0, "category-label"),
    ]


def _waterfall(p: ChartPrim) -> list[dict]:
    """Each row a signed change from a running total that starts at 0; no total bar; labels signed."""
    s, n = p.series[0], len(p.categories)
    fmt, run, rows = _fmt(s.values, sign=True), 0.0, []
    for i, v in enumerate(s.values):
        rows.append({"a": run, "b": run + v, "o": i + 0.2, "o2": i + 0.8, "m": i + 0.5, "top": max(run, run + v),
                     "fill": s.colors[i], "t": fmt(v), "d": f"{p.categories[i]} | {s.name} | {fmt(v)}"})
        run += v
    ends = [0.0, *(r["b"] for r in rows)]
    lo, hi = min(ends), max(ends)
    y0, y1 = column_plot_y(p)
    vs, bs = _lin((lo, hi if hi > lo else lo + 1), (y1, y0)), _lin((0, n), (0, p.w))
    return [
        _layer(rows, {"type": "rect"}, {"x": _q("o", bs), "x2": {"field": "o2"}, "y": _q("a", vs), "y2": {"field": "b"},
                                        "fill": _FILL, "description": {"field": "d"}}),
        _text(rows, _q("m", bs), _q("top", vs), "center", 0, -8, "data-label"),
        _text([{"m": i + 0.5, "t": c} for i, c in enumerate(p.categories)], _q("m", bs), {"value": p.h - 12}, "center", 0, 0,
              "category-label", p.w / n),
    ]


def _frame(w: float, h: float, layers: list[dict], tokens: Tokens, mode: Mode) -> dict:
    return {"width": w, "height": h, "autosize": "none", "padding": 0, "background": None,
            "config": theme_config(tokens, mode), "layer": layers}


def _spec(p: ChartPrim, layers: list[dict], tokens: Tokens, mode: Mode) -> dict:
    return _frame(p.w, p.h, layers, tokens, mode)


def to_svg(spec: dict, tokens: Tokens) -> str:
    _register_fonts(tokens)
    return vlc.vegalite_to_svg(spec, vl_version=VL_VERSION)


def to_png(spec: dict, tokens: Tokens) -> bytes:
    """The PowerPoint picture: scale 2, so a `w` × `h` px box is `round(2w)` × `round(2h)` pixels."""
    _register_fonts(tokens)
    return vlc.vegalite_to_png(spec, vl_version=VL_VERSION, scale=2)
