"""`cover` (mockup 0): a 760 px `ink` panel on the left with context, title and the slide's subtitle at the bottom;
the answer and up to two figures on the right, vertically centred. Full-bleed: `box` is the canvas.
With a cover image (spec 2026-11-18-house-deck-image-slides, "cover background") the image fills the right of the panel,
drawn first, and a `panel` card sits under the answer and figures."""

from dataclasses import replace

from arp.reporting.render_model import MARGIN, S12, S24, S48, VISUALS, Primitive, Rect, Text, palette
from arp.reporting.visuals._common import LEADING, fonts, lines, strip
from arp.reporting.visuals.image import picture

PANEL_W = 760
TITLE, ANSWER, FIGURE, SUB = 72, 44, 96, 28


def render(visual, box, ctx):
    c, (heading, body, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    slides = ctx.deck.slides
    sub = slides[ctx.index].subheading if ctx.index < len(slides) else ""
    out: list[Primitive] = []
    if ctx.cover_image:
        [img] = picture(1, ctx.cover_image, "", box.x + PANEL_W, box.y, box.w - PANEL_W, box.h, ctx)
        out.append(replace(img, name="cover:image"))
    out += [Rect("cover:panel", box.x, box.y, PANEL_W, box.h, c["ink"], emphasis=True),
                            *strip(box.x + MARGIN, box.y + MARGIN, c["panel"], c["highlight"])]

    # Left: stacked upward from 160 px above the bottom edge.
    x, w = box.x + MARGIN, PANEL_W - MARGIN - 64
    blocks = []
    if visual.context:
        blocks.append(("cover:context", visual.context.upper(), 20, 400, mono, c["inverse_muted"], 20 * LEADING))
    blocks.append(("cover:title", visual.title, TITLE, 600, heading, c["panel"], lines(visual.title, TITLE, w) * TITLE * LEADING))
    if sub:
        blocks.append(("cover:subtitle", sub, SUB, 400, body, c["inverse_muted"], lines(sub, SUB, w) * SUB * LEADING))
    y = box.y + box.h - 160 - sum(b[-1] for b in blocks) - S24 * (len(blocks) - 1)
    for name, text, fs, weight, fam, color, h in blocks:
        out.append(Text(name, x, y, w, h, text, fs, weight, fam, color, fill_under=c["ink"]))
        y += h + S24

    # Right: label, answer, figures; the stack centred on the canvas height.
    x = box.x + PANEL_W + MARGIN
    w = box.x + box.w - MARGIN - x
    answer_h = lines(visual.answer, ANSWER, w) * ANSWER * LEADING if visual.answer else 0
    fig_h = FIGURE * LEADING + S12 + 20 * LEADING if visual.figures else 0
    total = (20 * LEADING + S24 + answer_h if visual.answer else 0) + (S48 if visual.answer and fig_h else 0) + fig_h
    y = box.y + (box.h - total) / 2
    right = len(out)
    if visual.answer:
        out += [Text("cover:answer:label", x, y, w, 20 * LEADING, "THE ANSWER IN ONE LINE", 20, 400, mono, c["muted"],
                     fill_under=c["panel"]),
                Text("cover:answer", x, y + 20 * LEADING + S24, w, answer_h, visual.answer, ANSWER, 600, heading, c["ink"],
                     fill_under=c["panel"])]
        y += 20 * LEADING + S24 + answer_h + (S48 if fig_h else 0)
    fw = (w - S48) / 2
    for i, f in enumerate(visual.figures, start=1):
        fx = x + (i - 1) * (fw + S48)
        out += [Text(f"cover:figure:{i}", fx, y, fw, FIGURE * LEADING, f.value, FIGURE, 600, heading, c["ink"], fill_under=c["panel"]),
                Text(f"cover:figure:{i}:label", fx, y + FIGURE * LEADING + S12, fw, 20 * LEADING, f.label.upper(), 20, 400, mono,
                     c["muted"], fill_under=c["panel"])]
    if ctx.cover_image and len(out) > right:  # the card under the answer and figures, 48 px beyond them
        top, bottom = out[right].y - S48, out[-1].y + out[-1].h + S48
        out.insert(right, Rect("cover:card", box.x + PANEL_W + S48, top, box.w - PANEL_W - 2 * S48, bottom - top, c["panel"]))
    return out


VISUALS["cover"] = render
