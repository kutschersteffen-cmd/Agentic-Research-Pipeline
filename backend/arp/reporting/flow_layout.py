"""Lay out `flow` visuals with ELK (vendored elkjs) in the Chromium page ARP already launches.

Text is measured in the same page with the deck's fonts; each flow then goes down a fit ladder (28 px, wrapped,
24 px, wrapped) until it fits the body box. The diagram is never scaled; a flow that fits nowhere keeps the last
try and gets a `flow_too_big` finding.
"""

from __future__ import annotations

import json
from pathlib import Path

from arp.reporting.browser import _page
from arp.reporting.house_style import Mode, Tokens
from arp.reporting.html_render import _font_faces
from arp.reporting.render_model import body_box, family
from arp.schemas.reporting import Box, Deck, Finding
from arp.schemas.visuals import Flow, FlowArrowLayout, FlowBox, FlowLayout, FlowStepLayout

ELK_JS = Path(__file__).parent / "vendor" / "elkjs" / "elk.bundled.js"

LABEL_SIZES = (28, 24)  # by type step
SMALL = 20  # tags and arrow labels, mono
LEADING = 1.2
WRAP_AT = 320
PAD = 24
MIN_W = 160
LABEL_PAD = 8  # around an arrow label, each side
LEGEND_BAND = 40

_MEASURE_JS = """async (items) => {
  const ctx = document.createElement('canvas').getContext('2d');
  for (const f of new Set(items.map(i => i[0]))) await document.fonts.load(f);
  return items.map(([f, t]) => { ctx.font = f; return ctx.measureText(t).width; });
}"""

_ELK_JS = "async (graph) => await new ELK().layout(graph)"


def _ladder(flow: Flow) -> list[tuple[int, bool]]:
    if flow.direction == "LR":
        return [(0, False), (0, True), (1, False), (1, True)]
    return [(0, False), (1, False)]


def _area(flow: Flow, tokens: Tokens) -> Box:
    b = body_box(tokens)
    legend = bool(flow.actors) or any(s.stored for s in flow.steps)
    return Box(x=b.x, y=b.y, w=b.w, h=b.h - (LEGEND_BAND if legend else 0))


def _splits(label: str) -> list[tuple[str, str]]:
    words = label.split()
    return [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]


def _label_lines(label: str, width) -> list[str]:
    """One line when it fits WRAP_AT; else the word break that makes the longer line shortest (first on a tie)."""
    label = " ".join(label.split())
    if width(label) <= WRAP_AT or not _splits(label):
        return [label]
    best = min(_splits(label), key=lambda p: max(width(p[0]), width(p[1])))
    return list(best)


def _fonts(tokens: Tokens) -> tuple[str, str]:
    body = family(tokens.fonts.body)
    mono = family(tokens.fonts.mono or tokens.fonts.body)
    return body, mono


def _texts(flow: Flow, tokens: Tokens) -> list[tuple[str, str]]:
    """Every (CSS font, text) the ladder may measure, so one round trip measures them all."""
    body, mono = _fonts(tokens)
    out = []
    for s in flow.steps:
        label = " ".join(s.label.split())
        for size in LABEL_SIZES:
            f = f"600 {size}px '{body}'"
            out += [(f, label), *((f, part) for pair in _splits(label) for part in pair)]
        if s.tag.strip():
            out.append((f"400 {SMALL}px '{mono}'", s.tag.strip()))
    out += [(f"400 {SMALL}px '{mono}'", a.label.strip()) for a in flow.arrows if a.label.strip()]
    return list(dict.fromkeys(out))


def _graph(flow: Flow, tokens: Tokens, widths: dict, type_step: int, wrapped: bool, area: Box):
    body, mono = _fonts(tokens)
    size = LABEL_SIZES[type_step]
    lab = f"600 {size}px '{body}'"
    small = f"400 {SMALL}px '{mono}'"
    lines, children = {}, []
    for s in flow.steps:
        ls = _label_lines(s.label, lambda t: widths[(lab, t)])
        tag = s.tag.strip()
        w = max(MIN_W, *(widths[(lab, line)] for line in ls), widths[(small, tag)] if tag else 0) + 2 * PAD
        h = PAD + len(ls) * size * LEADING + (8 + SMALL * LEADING if tag else 0) + PAD + (8 if s.stored else 0)
        lines[s.id] = ls
        children.append({"id": s.id, "width": w, "height": h})
    edges = []
    for n, a in enumerate(flow.arrows):
        e = {"id": f"e{n}", "sources": [a.source], "targets": [a.target]}
        if a.label.strip():
            t = a.label.strip()
            e["labels"] = [{"text": t, "width": widths[(small, t)] + 2 * LABEL_PAD, "height": SMALL * LEADING + 2 * LABEL_PAD}]
        edges.append(e)
    opts = {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT" if flow.direction == "LR" else "DOWN",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.padding": "[top=0,left=0,bottom=0,right=0]",
        "elk.layered.spacing.nodeNodeBetweenLayers": "48",
        "elk.spacing.nodeNode": "40",
        "elk.spacing.edgeNode": "24",
        "elk.spacing.edgeEdge": "16",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    }
    if wrapped:
        opts["elk.layered.wrapping.strategy"] = "MULTI_EDGE"
        opts["elk.aspectRatio"] = str(area.w / area.h)
    return {"id": "root", "layoutOptions": opts, "children": children, "edges": edges}, lines


def _place(flow: Flow, result: dict, lines: dict, area: Box, type_step: int, wrapped: bool) -> FlowLayout:
    nodes = {c["id"]: c for c in result["children"]}
    routes, label_boxes = [], []
    for e in sorted(result["edges"], key=lambda e: int(e["id"][1:])):
        pts: list[tuple[float, float]] = []
        for sec in e.get("sections", []):
            for p in [sec["startPoint"], *sec.get("bendPoints", []), sec["endPoint"]]:
                if not pts or pts[-1] != (p["x"], p["y"]):
                    pts.append((p["x"], p["y"]))
        routes.append(pts)
        lb = (e.get("labels") or [None])[0]
        label_boxes.append((lb["x"], lb["y"], lb["width"], lb["height"]) if lb else None)
    xs, ys = [], []
    for c in nodes.values():
        xs += [c["x"], c["x"] + c["width"]]
        ys += [c["y"], c["y"] + c["height"]]
    for pts in routes:
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    for b in filter(None, label_boxes):
        xs += [b[0], b[0] + b[2]]
        ys += [b[1], b[1] + b[3]]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    dx = area.x + (area.w - width) / 2 - min(xs)
    dy = area.y + (area.h - height) / 2 - min(ys)
    steps = [
        FlowStepLayout(id=s.id, label_lines=lines[s.id], box=FlowBox(
            x=nodes[s.id]["x"] + dx, y=nodes[s.id]["y"] + dy, w=nodes[s.id]["width"], h=nodes[s.id]["height"]))
        for s in flow.steps
    ]
    arrows = [
        FlowArrowLayout(points=[(x + dx, y + dy) for x, y in pts],
                        label_box=FlowBox(x=b[0] + dx, y=b[1] + dy, w=b[2], h=b[3]) if b else None)
        for pts, b in zip(routes, label_boxes, strict=True)
    ]
    return FlowLayout(type_step=type_step, wrapped=wrapped, width=width, height=height, steps=steps, arrows=arrows)


async def _lay_out(page, flow: Flow, tokens: Tokens) -> FlowLayout:
    texts = _texts(flow, tokens)
    widths = dict(zip(texts, await page.evaluate(_MEASURE_JS, [list(t) for t in texts]), strict=True))
    area = _area(flow, tokens)
    for type_step, wrapped in _ladder(flow):
        graph, lines = _graph(flow, tokens, widths, type_step, wrapped, area)
        # A JSON round trip drops elkjs's private fields ($H) so the result is plain data.
        result = json.loads(json.dumps(await page.evaluate(_ELK_JS, graph)))
        layout = _place(flow, result, lines, area, type_step, wrapped)
        if layout.width <= area.w and layout.height <= area.h:
            return layout
    return layout.model_copy(update={"too_big": True})


async def layout_flows(deck: Deck, tokens: Tokens, mode: Mode = "light") -> tuple[Deck, list[Finding]]:
    """Lay out every flow slide whose `layout` is none, in one Chromium launch. No such slide: the deck as given, no browser."""
    todo = [i for i, s in enumerate(deck.slides) if isinstance(s.visual, Flow) and s.visual.layout is None]
    if not todo:
        return deck, []
    deck = deck.model_copy(deep=True)
    body, mono = _fonts(tokens)
    html = f"<!doctype html><html><head><style>{_font_faces([body, mono], tokens.font_dir)}</style></head><body></body></html>"
    findings = []
    async with _page(html) as page:
        await page.add_script_tag(path=str(ELK_JS))
        for i in todo:
            slide = deck.slides[i]
            layout = await _lay_out(page, slide.visual, tokens)
            slide.visual.layout = layout
            if layout.too_big:
                area = _area(slide.visual, tokens)
                slide.needs_review = True
                findings.append(Finding(
                    slide=i, slot="visual", stage="fit", rule="flow_too_big",
                    message=f"laid out {round(layout.width)}×{round(layout.height)} px at 24 px text; "
                            f"the body has {round(area.w)}×{round(area.h)} px; merge steps",
                ))
    return deck, findings
