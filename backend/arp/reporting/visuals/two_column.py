"""`two_column` (mockup 6): an optional KPI strip on `ground`, then two titled columns of numbered points."""

from arp.reporting.render_model import S8, S12, S16, S24, S32, S40, S64, VISUALS, Line, Primitive, Rect, Text, palette
from arp.reporting.visuals._common import LEADING, fonts, lines, size

KPI_VALUE = 72


def render(visual, box, ctx):
    c, (heading, body, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    out: list[Primitive] = []
    y = box.y
    if visual.kpis:
        deltas = any(k.delta for k in visual.kpis)
        h = S32 + KPI_VALUE * LEADING + S12 + S24 + (S8 + S24 if deltas else 0) + S32
        out.append(Rect("kpis", box.x, y, box.w, h, c["ground"]))
        w = box.w / len(visual.kpis)
        for i, k in enumerate(visual.kpis, start=1):
            x = box.x + (i - 1) * w
            if i > 1:
                out.append(Line(f"kpis:rule:{i}", [(x, y), (x, y + h)], c["line"], 1))
            ty = y + S32
            out.append(Text(f"kpis:{i}:value", x + S40, ty, w - 2 * S40, KPI_VALUE * LEADING, k.value, KPI_VALUE, 600, heading,
                            c["ink"], fill_under=c["ground"]))
            ty += KPI_VALUE * LEADING + S12
            out.append(Text(f"kpis:{i}:label", x + S40, ty, w - 2 * S40, S24, k.label.upper(), 20, 400, mono, c["muted"],
                            fill_under=c["ground"]))
            if k.delta:
                out.append(Text(f"kpis:{i}:delta", x + S40, ty + S24 + S8, w - 2 * S40, S24, k.delta, 20, 400, mono, c["ink"],
                                fill_under=c["ground"]))
        y += h + S40
    col_w, fs = (box.w - S64) / 2, size("body", ctx)
    for side, col, x in (("left", visual.left, box.x), ("right", visual.right, box.x + (box.w + S64) / 2)):
        name = f"col:{side}"
        out += [
            Text(name, x, y, col_w, S24, col.title.upper(), 20, 400, mono, c["muted"], fill_under=c["panel"]),
            Line(f"{name}:rule", [(x, y + S24 + S16), (x + col_w, y + S24 + S16)], c["ink"], 2),
        ]
        ry, num_w = y + S24 + S16 + 2, 32
        text_x = x + num_w + S24
        text_w = x + col_w - text_x
        for n, point in enumerate(col.points, start=1):
            th = lines(point, fs, text_w) * fs * LEADING
            first_line = fs * LEADING
            out += [
                Text(f"{name}:num:{n}", x, ry + S24 + (first_line - S24) / 2, num_w, S24, f"{n:02d}", 20, 600, mono, c["ink"],
                     fill_under=c["panel"]),
                Text(f"{name}:row:{n}", text_x, ry + S24, text_w, th, point, fs, 400, body, c["ink"], fill_under=c["panel"]),
            ]
            ry += th + 2 * S24
            out.append(Line(f"{name}:rule:{n}", [(x, ry), (x + col_w, ry)], c["line"], 1))
    return out


VISUALS["two_column"] = render
