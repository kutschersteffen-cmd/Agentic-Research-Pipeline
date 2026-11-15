"""`chart` (mockups 3, 8): a native chart over a dataset; with an insight, a 520 px card on the right, 48 px gap.

Bars are `well`, the second series `series_2`, the highlighted category or series `highlight` (lines have no `well`:
it does not show on `panel`). Over 10 bar/column categories: the top 9 by value plus "Other", with a `chart_capped` finding.
"""

from arp.reporting.render_model import (
    S12,
    S16,
    S24,
    S48,
    VISUALS,
    ChartPrim,
    Line,
    Primitive,
    Rect,
    Series,
    Text,
    VisualDataError,
    line_point,
    palette,
)
from arp.reporting.visuals._common import LEADING, dataset, fonts, lines, number
from arp.schemas.reporting import Finding

CARD_W, CAP, STAT, CALLOUT = 520, 10, 96, 24


def _capped(cats: list[str], cols: list[list[float]], ctx) -> tuple[list[str], list[list[float]]]:
    n = len(cats)
    totals = [sum(col[i] for col in cols) for i in range(n)]
    keep = sorted(sorted(range(n), key=lambda i: -totals[i])[:CAP - 1])  # the top 9, in dataset order
    rest = [i for i in range(n) if i not in keep]
    ctx.findings.append(Finding(slide=ctx.index, stage="fit", rule="chart_capped",
                                message=f"{n} categories: the top {CAP - 1} by value are shown, the other {len(rest)} as Other"))
    return [cats[i] for i in keep] + ["Other"], [[col[i] for i in keep] + [sum(col[i] for i in rest)] for col in cols]


def _callout(visual, chart: ChartPrim, c, body) -> list[Primitive]:
    i = chart.categories.index(visual.callout.category)
    text = visual.callout.text
    bw, bh = len(text) * CALLOUT * 0.5 + 2 * S16, CALLOUT * LEADING + 2 * S12
    leader = None
    if chart.kind == "bar":  # right end of the category's band (the writers' bands are equal)
        band = chart.h / len(chart.categories)
        bx, by = chart.x + chart.w - bw, chart.y + (i + 0.5) * band - bh / 2
    elif chart.kind == "line":  # above the point (below when there is no room), with a leader
        s = next((s for s in chart.series if s.name == visual.highlight), chart.series[0])
        px, py = line_point(chart, i, s.values[i])
        above = py - S16 - S48 - bh >= chart.y
        bx, by = px - S12, py - S16 - S48 - bh if above else py + S16 + S48
        leader = [(px, by + bh), (px, py - S16)] if above else [(px, py + S16), (px, by)]
    else:  # column: over the category, at the top of the chart
        bx, by = chart.x + (i + 0.5) * chart.w / len(chart.categories) - S12, chart.y
    bx = min(bx, chart.x + chart.w - bw)
    out: list[Primitive] = [Rect("callout", bx, by, bw, bh, c["ink"]),
                            Text("callout:text", bx + S16, by + S12, bw - 2 * S16, bh - 2 * S12, text, CALLOUT, 400, body,
                                 c["panel"], fill_under=c["ink"])]
    if leader:
        out.append(Line("callout:rule", leader, c["ink"], 2))
    return out


def _insight(ins, x, box, c, heading, body) -> list[Primitive]:
    ix, iw, y = x + S48, CARD_W - 2 * S48, box.y + S48
    out: list[Primitive] = [Rect("card:insight", x, box.y, CARD_W, box.h, c["ground"]),
                            Rect("card:insight:rule", x, box.y, 4, box.h, c["ink"]),
                            Text("card:insight:stat", ix, y, iw, STAT * LEADING, ins.stat, STAT, 600, heading, c["ink"],
                                 fill_under=c["ground"])]
    y += STAT * LEADING + S24
    h = lines(ins.headline, 30, iw) * 30 * LEADING
    out.append(Text("card:insight:headline", ix, y, iw, h, ins.headline, 30, 600, body, c["ink"], fill_under=c["ground"]))
    y += h + S24
    for k, point in enumerate(ins.points, start=1):
        point = f"■  {point}"
        h = lines(point, 24, iw) * 24 * LEADING
        out.append(Text(f"card:insight:point:{k}", ix, y, iw, h, point, 24, 400, body, c["muted"], fill_under=c["ground"]))
        y += h + S16
    return out


def render(visual, box, ctx):
    c, (heading, body, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    spec = visual.data
    ds = dataset(ctx, spec.dataset_id, [spec.category_column or "", *spec.value_columns])
    if not ds.rows:
        raise VisualDataError(f"dataset {spec.dataset_id!r} has no rows")
    cats = [str(r.get(spec.category_column, "")) for r in ds.rows]
    cols = [[number(r.get(col)) for r in ds.rows] for col in spec.value_columns]
    if visual.kind != "line" and len(cats) > CAP:
        cats, cols = _capped(cats, cols, ctx)
    series = []
    for j, (name, values) in enumerate(zip(spec.value_columns, cols, strict=True)):
        base = c["series_2"] if j or visual.kind == "line" else c["well"]
        colors = [c["highlight"] if visual.highlight in (name, cat) else base for cat in cats]
        series.append(Series(name, values, colors))
    chart_w = box.w - (CARD_W + S48 if visual.insight else 0)
    label = (spec.title or ds.name) + (f", {visual.unit}" if visual.unit else "")
    top = S24 + S16
    chart = ChartPrim("chart", box.x, box.y + top, chart_w, box.h - top, visual.kind, cats, series, visual.unit, visual.data_labels)
    out: list[Primitive] = [Text("chart:label", box.x, box.y, chart_w, S24, label.upper(), 20, 400, mono, c["muted"],
                                 fill_under=c["panel"]), chart]
    if visual.callout and visual.callout.category in cats:  # a callout on an unknown category is not drawn
        out += _callout(visual, chart, c, body)
    if visual.insight:
        out += _insight(visual.insight, box.x + box.w - CARD_W, box, c, heading, body)
    return out


VISUALS["chart"] = render
