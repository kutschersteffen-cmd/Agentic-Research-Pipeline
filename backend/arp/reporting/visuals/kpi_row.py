"""`kpi_row` (mockup 2): equal tiles, 24 px gaps, full body; label top, value and delta bottom, 40 px padding."""

from arp.reporting.render_model import S24, S32, S40, VISUALS, Primitive, Rect, Text, palette
from arp.reporting.visuals._common import LEADING, fonts, size


def render(visual, box, ctx):
    c, (heading, _, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    n, vs = len(visual.tiles), size("value", ctx)
    w = (box.w - S24 * (n - 1)) / n
    out: list[Primitive] = []
    for i, tile in enumerate(visual.tiles):
        emph = visual.emphasis == i  # out of range: no emphasis here; fill_slide drops it with a finding
        fill, text, secondary = (c["ink"], c["panel"], c["inverse_muted"]) if emph else (c["ground"], c["ink"], c["muted"])
        x, name, inner = box.x + i * (w + S24), f"kpi:tile:{i + 1}", w - 2 * S40
        delta_y = box.y + box.h - S40 - S32
        value_h = vs * LEADING
        out += [
            Rect(name, x, box.y, w, box.h, fill, emphasis=emph),
            Text(f"{name}:label", x + S40, box.y + S40, inner, 3 * 20 * LEADING, tile.label.upper(), 20, 400, mono, secondary,
                 fill_under=fill),
            Text(f"{name}:value", x + S40, delta_y - S24 - value_h, inner, value_h, tile.value, vs, 600, heading, text,
                 anchor="bottom", fill_under=fill),
            Text(f"{name}:delta", x + S40, delta_y, inner, S32, tile.delta, 22, 400, mono, text, anchor="bottom", fill_under=fill),
        ]
    return out


VISUALS["kpi_row"] = render
