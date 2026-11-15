"""`section` (mockup 1): full-bleed `ground`; an outlined number, title and summary centred on the left; the agenda
(every section slide of the deck, the current one marked with a square) bottom-right. `box` is the canvas."""

from arp.reporting.render_model import MARGIN, S8, S12, S24, VISUALS, Primitive, Rect, Text, palette
from arp.reporting.visuals._common import LEADING, fonts, lines, strip

NUMBER, TITLE, SUMMARY, AGENDA = 200, 72, 32, 22
AGENDA_W = 640


def render(visual, box, ctx):
    c, (heading, body, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    g = c["ground"]
    out: list[Primitive] = [Rect("background", box.x, box.y, box.w, box.h, g),
                            *strip(box.x + MARGIN, box.y + MARGIN, c["ink"], c["highlight"])]
    x, w = box.x + MARGIN, box.w - 2 * MARGIN
    num_h, title_h = NUMBER * LEADING, lines(visual.title, TITLE, w) * TITLE * LEADING
    sum_h = lines(visual.summary, SUMMARY, w) * SUMMARY * LEADING if visual.summary else 0
    y = box.y + (box.h - num_h - S8 - title_h - (S24 + sum_h if sum_h else 0)) / 2
    out += [
        Text("section:number", x, y, w, num_h, f"{visual.number:02d}", NUMBER, 600, heading, c["line"], fill_under=g, outline=True),
        Text("section:title", x, y + num_h + S8, w, title_h, visual.title, TITLE, 600, heading, c["ink"], fill_under=g),
    ]
    if sum_h:
        out.append(Text("section:summary", x, y + num_h + S8 + title_h + S24, w, sum_h, visual.summary, SUMMARY, 400, body,
                        c["muted"], fill_under=g))

    agenda = [(i, s.visual) for i, s in enumerate(ctx.deck.slides) if s.visual is not None and s.visual.type == "section"]
    line_h = AGENDA * LEADING
    ay = box.y + box.h - MARGIN - len(agenda) * line_h - S12 * (len(agenda) - 1)
    for n, (i, v) in enumerate(agenda, start=1):
        current = i == ctx.index
        out.append(Text(f"agenda:{n}", box.x + box.w - MARGIN - AGENDA_W, ay, AGENDA_W, line_h,
                        f"{'■ ' if current else ''}{v.number:02d}  {v.title}", AGENDA, 400, mono,
                        c["ink" if current else "muted"], align="right", fill_under=g))
        ay += line_h + S12
    return out


VISUALS["section"] = render
