"""Committee layouts encode structure as plain list items (`a :: b :: c`) the LLM can write; parsed here, deterministically.

Every parser raises ValueError with a message the slide-fill retry can act on. The tree is also drawn here, as
an SVG whose colours are CSS variables, so it follows the deck's light/dark tokens like the rest of the page.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from html import escape
from typing import NamedTuple

STATUSES = ("high", "mid", "low", "neutral")
MAX_TREE_DEPTH = 4  # questions on the longest path; the outcome column is one more
MAX_TREE_OUTCOMES = 6  # what fits one above the other in the slot
# (layout, slot) pairs whose items carry structure: fit never splits them in half (a half 2x2 or tree is not one).
NO_SPLIT = {("flow", "items"), ("profile", "meters"), ("profile", "left"), ("profile", "right"), ("scatter_zone", "items"),
            ("matrix2x2", "quadrants"), ("matrix2x2", "items"), ("tree", "items")}


def _parts(item: str) -> list[str]:
    return [p.strip() for p in item.split("::")]


class Stage(NamedTuple):
    title: str
    boxes: list[tuple[str, bool]]  # (text, preferred)


def parse_flow(items: list[str]) -> list[Stage]:
    if not 2 <= len(items) <= 5:
        raise ValueError(f"flow needs 2 to 5 stages, got {len(items)}")
    stages = []
    for item in items:
        title, *boxes = _parts(item)
        if not title or not 1 <= len(boxes) <= 3 or not all(boxes):
            raise ValueError(f"flow stage {item!r}: write 'Stage title :: box 1 :: box 2' (1 to 3 boxes; '*' marks the preferred box)")
        stages.append(Stage(title, [(b.lstrip("*").strip(), b.startswith("*")) for b in boxes]))
    return stages


class Meter(NamedTuple):
    label: str
    pct: float


def parse_meters(items: list[str]) -> list[Meter]:
    out = []
    for item in items:
        p = _parts(item)
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", p[-1]) if len(p) == 2 else None
        if not m or not p[0] or float(m[1]) > 100:
            raise ValueError(f"meter {item!r}: write 'Label :: 54%' (0 to 100%)")
        out.append(Meter(p[0], float(m[1])))
    return out


class Quadrant(NamedTuple):
    title: str
    sub: str
    text: str
    status: str


def parse_quadrants(items: list[str]) -> list[Quadrant]:
    if len(items) != 4:
        raise ValueError(f"matrix2x2 needs exactly 4 quadrants (top-left, top-right, bottom-left, bottom-right), got {len(items)}")
    out = []
    for item in items:
        p = _parts(item)
        if len(p) != 4 or p[3] not in STATUSES:
            raise ValueError(f"quadrant {item!r}: write 'Title :: subtitle :: text :: status' with status one of {', '.join(STATUSES)}")
        out.append(Quadrant(*p))
    return out


class Delta(NamedTuple):
    value: str
    text: str


def parse_deltas(items: list[str]) -> list[Delta]:
    out = []
    for item in items:
        p = _parts(item)
        if len(p) != 2 or not re.fullmatch(r"[+\-−–]?\d[\d,.]*%?", p[0]) or not p[1]:
            raise ValueError(f"delta {item!r}: write '+11 :: explanation' (a signed number, then the text)")
        out.append(Delta(*p))
    return out


@dataclass
class TreeNode:
    id: str
    text: str
    status: str = ""  # outcomes only
    yes: TreeNode | None = None
    no: TreeNode | None = None

    @property
    def outcome(self) -> bool:
        return self.yes is None


def parse_tree(items: list[str]) -> TreeNode:
    """`id :: question :: yes_id :: no_id` or `id :: =outcome :: status`; the first item is the root."""
    raw: dict[str, list[str]] = {}
    for item in items:
        p = _parts(item)
        if p[0] in raw:
            raise ValueError(f"tree node {p[0]!r} is defined twice")
        if not (len(p) == 4 and not p[1].startswith("=")) and not (len(p) == 3 and p[1].startswith("=")):
            raise ValueError(f"tree item {item!r}: write 'id :: question :: yes_id :: no_id' or 'id :: =outcome :: status'")
        if len(p) == 3 and p[2] not in STATUSES:
            raise ValueError(f"tree outcome {item!r}: status must be one of {', '.join(STATUSES)}")
        raw[p[0]] = p
    if not raw:
        raise ValueError("tree has no nodes")
    seen: set[str] = set()

    def build(node_id: str, depth: int) -> TreeNode:
        if node_id not in raw:
            raise ValueError(f"tree refers to unknown node {node_id!r}")
        if node_id in seen:
            raise ValueError(f"tree node {node_id!r} is reached twice; give each branch its own node")
        seen.add(node_id)
        p = raw[node_id]
        if len(p) == 3:
            return TreeNode(node_id, p[1][1:].strip(), p[2])
        if depth >= MAX_TREE_DEPTH:
            raise ValueError(f"tree is deeper than {MAX_TREE_DEPTH} questions; split it or merge questions")
        return TreeNode(node_id, p[1], yes=build(p[2], depth + 1), no=build(p[3], depth + 1))

    root = build(next(iter(raw)), 0)
    if unused := [k for k in raw if k not in seen]:
        raise ValueError(f"tree nodes never reached from the root: {unused}")
    if (n := sum(1 for _ in _leaves(root))) > MAX_TREE_OUTCOMES:
        raise ValueError(f"tree has {n} outcomes; at most {MAX_TREE_OUTCOMES} fit")
    return root


def _leaves(n: TreeNode):
    if n.outcome:
        yield n
    else:
        yield from _leaves(n.yes)
        yield from _leaves(n.no)


def _depth(n: TreeNode) -> int:
    return 0 if n.outcome else 1 + max(_depth(n.yes), _depth(n.no))


_FS, _LH, _PAD = 24, 30, 12  # chart text size: the 24px projector floor, like chart_builder's exhibits
_BOX_H = 2 * _LH + 2 * _PAD


class TreeLayout(NamedTuple):
    box_w: float
    nodes: list[tuple[TreeNode, float, float, list[str]]]  # node, left x, centre y, wrapped lines
    edges: list[tuple[str, float, float, float, float, float]]  # label, x0, y, elbow x, child y, arrow-tip x


def tree_layout(root: TreeNode, width: float, height: float) -> TreeLayout:
    """Left to right by depth; outcomes stacked in order, each question centred on its branches. Shared by the SVG and the pptx."""
    cols, leaves = _depth(root) + 1, list(_leaves(root))
    box_w = min(420, (width - (cols - 1) * 88) / cols)  # 88: the narrowest gap that holds a connector and its label
    gap = (width - cols * box_w) / (cols - 1) if cols > 1 else 0
    chars = int((box_w - 2 * _PAD) / (_FS * 0.52))  # ponytail: average-advance estimate, a measured wrap if a face runs wide
    # Outcomes spread from the slot's top to its bottom, so the tree fills the body (a lone outcome is centred).
    pitch = (height - _BOX_H) / (len(leaves) - 1) if len(leaves) > 1 else 0
    ys = {id(leaf): (_BOX_H / 2 + i * pitch if pitch else height / 2) for i, leaf in enumerate(leaves)}
    nodes: list = []
    edges: list = []

    def place(n: TreeNode, depth: int) -> float:
        x = depth * (box_w + gap)
        if not n.outcome:
            ys[id(n)] = (place(n.yes, depth + 1) + place(n.no, depth + 1)) / 2
        y = ys[id(n)]
        lines = textwrap.wrap(n.text, chars)
        if len(lines) > 2:
            raise ValueError(f"tree node {n.id!r} text is too long for its box: {n.text!r} (two lines of about {chars} characters)")
        nodes.append((n, x, y, lines))
        if not n.outcome:
            x0 = x + box_w
            edges.extend((label, x0, y, x0 + gap / 2, ys[id(child)], x0 + gap - 6) for label, child in (("Yes", n.yes), ("No", n.no)))
        return y

    place(root, 0)
    return TreeLayout(box_w, nodes, edges)


def tree_svg(root: TreeNode, width: float, height: float) -> str:
    box_w, nodes, edges = tree_layout(root, width, height)
    out: list[str] = []
    for n, x, y, lines in nodes:
        box = (f'fill="color-mix(in oklab, var(--status-{n.status}) 18%, var(--bg))" stroke="var(--neutral)" stroke-width="1"' if n.outcome
               else 'fill="var(--bg)" stroke="var(--ink)" stroke-width="2"')
        out.append(f'<rect x="{x:.1f}" y="{y - _BOX_H / 2:.1f}" width="{box_w:.1f}" height="{_BOX_H}" {box}/>')
        weight = 400 if n.outcome else 600
        for i, line in enumerate(lines):
            ty = y + (i - (len(lines) - 1) / 2) * _LH + _FS * 0.35
            out.append(f'<text x="{x + box_w / 2:.1f}" y="{ty:.1f}" text-anchor="middle" font-weight="{weight}">{escape(line)}</text>')
    for label, x0, y, xm, cy, xe in edges:
        out.append(f'<path d="M{x0:.1f},{y:.1f} H{xm:.1f} V{cy:.1f} H{xe:.1f}" fill="none" stroke="var(--ink-muted)" stroke-width="2"/>')
        out.append(f'<path d="M{xe - 8:.1f},{cy - 6:.1f} L{xe + 2:.1f},{cy:.1f} L{xe - 8:.1f},{cy + 6:.1f}" fill="none" stroke="var(--ink-muted)" stroke-width="2"/>')
        out.append(f'<text x="{xm + 8:.1f}" y="{cy - 10:.1f}" class="branch">{label}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" font-size="{_FS}" fill="var(--ink)">'
            + "".join(out) + "</svg>")


def structured_view(layout: str, name: str, items: list[str], r) -> dict:
    """Parsed view of a committee layout's structured list slot (ValueError on a malformed item)."""
    if (layout, name) == ("flow", "items"):
        return {"stages": parse_flow(items)}
    if (layout, name) == ("profile", "meters"):
        return {"meters": parse_meters(items)}
    if (layout, name) == ("scatter_zone", "items"):
        return {"deltas": parse_deltas(items)}
    if (layout, name) == ("matrix2x2", "quadrants"):
        return {"quadrants": parse_quadrants(items)}
    if (layout, name) == ("tree", "items"):
        return {"svg": tree_svg(parse_tree(items), r.w, r.h)}
    if (layout, name) == ("decisions", "items"):
        return {"pairs": [[p.strip() for p in (t.split("::", 1) + [""])[:2]] for t in items]}
    if (layout, name) in {("profile", "left"), ("profile", "right"), ("matrix2x2", "items")}:
        return {"panel": items[:1], "items": items[1:]}  # the first item titles the panel
    return {}
