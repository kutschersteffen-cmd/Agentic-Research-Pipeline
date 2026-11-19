"""`flow`: a laid-out flowchart (`flow_layout.layout_flows`) as step boxes, arrows along their ELK routes and a legend.

Every position comes from `visual.layout`; actors are box fills, listed in a one-row legend on the body box's bottom edge.
Spec: docs/superpowers/specs/2026-11-18-house-deck-flowchart-slides.md, "Renderer".
"""

from arp.reporting.render_model import S8, S12, S24, S32, VISUALS, Line, Primitive, Rect, Text, VisualDataError, body_box, palette
from arp.reporting.visuals._common import LEADING, fonts

# As in flow_layout (which needs Chromium, so it is not imported here): label size by type step, tag and arrow-label size,
# box padding.
LABEL_SIZES, SMALL, PAD = (28, 24), 20, S24
ACTOR_FILLS = ("panel", "series_2", "well", "inverse_muted")
MONO_EM = 0.6  # Geist Mono advance per px of size, for the legend text boxes


def _legend_text(name: str, x: float, y: float, text: str, mono: str, color: str) -> Text:
    return Text(name, x, y, len(text) * SMALL * MONO_EM + S8, S24, text, SMALL, 400, mono, color, anchor="middle")


def render(visual, box, ctx):
    layout = visual.layout
    if layout is None:
        raise VisualDataError("flow has no layout")
    c, (_, body, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    size = LABEL_SIZES[layout.type_step]
    fills = {a: c[ACTOR_FILLS[i]] for i, a in enumerate(visual.actors)}
    boxes = {s.id: s for s in layout.steps}
    out: list[Primitive] = []
    for step in visual.steps:
        lay, fill = boxes[step.id], fills.get(step.actor, c["panel"])
        b = lay.box
        if step.id == visual.emphasis:
            line, line_w = c["highlight"], 4
        elif step.kind == "data":
            line, line_w = c["muted"], 2
        else:
            line, line_w = c["ink"], 4 if step.kind == "decision" else 2
        name = f"step:{step.id}"
        out.append(Rect(name, b.x, b.y, b.w, b.h, fill, line, line_w, emphasis=step.id == visual.emphasis))
        label_h = len(lay.label_lines) * size * LEADING
        out.append(Text(f"{name}:label", b.x + S12, b.y + PAD, b.w - 2 * S12, label_h, "\n".join(lay.label_lines), size, 600,
                        body, c["ink"], "center", "middle", fill))
        if step.tag.strip():
            out.append(Text(f"{name}:tag", b.x + S12, b.y + PAD + label_h + S8, b.w - 2 * S12, SMALL * LEADING, step.tag.strip(),
                            SMALL, 400, mono, c["ink"], "center", "middle", fill))
        if step.stored:
            out.append(Rect(f"{name}:stored", b.x, b.y + b.h - S8, b.w, S8, c["ink"]))
    for n, (arrow, lay) in enumerate(zip(visual.arrows, layout.arrows, strict=True), start=1):
        out.append(Line(f"arrow:{n}", list(lay.points), c["ink"], 2, arrow=True))
        if arrow.label.strip() and lay.label_box is not None:
            lb = lay.label_box
            out.append(Text(f"arrow:{n}:label", lb.x, lb.y, lb.w, lb.h, arrow.label.strip(), SMALL, 400, mono, c["muted"],
                            "center", "middle", c["panel"]))
    body_b = body_box(ctx.tokens)
    x, bottom = body_b.x, body_b.y + body_b.h
    for k, actor in enumerate(visual.actors, start=1):
        text = _legend_text(f"legend:{k}:text", x + S24 + S12, bottom - S24, actor.replace("_", " ").upper(), mono, c["muted"])
        out += [Rect(f"legend:{k}", x, bottom - S24, S24, S24, fills[actor], c["ink"], 2), text]
        x = text.x + text.w + S32
    if any(s.stored for s in visual.steps):
        text = _legend_text("legend:stored:text", x + S24 + S12, bottom - S24, "STORED RESULT", mono, c["muted"])
        out += [Rect("legend:stored", x, bottom - S8, S24, S8, c["ink"]), text]
    return out


VISUALS["flow"] = render
