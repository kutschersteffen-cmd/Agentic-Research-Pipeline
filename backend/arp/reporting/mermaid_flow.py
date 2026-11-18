"""Parse a Mermaid flowchart subset into a typed `Flow` (spec house-deck-flowchart-slides, "Mermaid subset").

The error messages are the contract: each is exactly the spec's table row.
"""

from __future__ import annotations

import re

from arp.schemas.visuals import Flow, FlowArrow, FlowStep

OTHER_DIAGRAMS = {
    "sequenceDiagram", "classDiagram", "stateDiagram", "stateDiagram-v2", "erDiagram", "gantt", "pie", "journey",
    "gitGraph", "mindmap", "timeline", "quadrantChart", "sankey-beta", "xychart-beta", "block-beta",
}
RESERVED = ("stored", "emphasis")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_NAME = re.compile(r"[A-Za-z_][\w-]*")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_CLASS = re.compile(r"class\s+([A-Za-z]\w*(?:\s*,\s*[A-Za-z]\w*)*)\s+([A-Za-z_][\w-]*)")
# (opener, closer, kind), longest opener first.
_SHAPES = (("[(", ")]", "data"), ("([", "])", "step"), ("[", "]", "step"), ("(", ")", "step"), ("{", "}", "decision"))
_BAD_SHAPES = ("((", "{{", "[/", "[\\", "[[", "@{", ">")
_BAD_ARROWS = ("<-->", "-.->", "---", "==>", "--o", "--x", "~~~")
_ARROW_RUN = re.compile(r"[-=.~<>]+")


class MermaidError(ValueError):
    """A flowchart the subset cannot read; `str()` is the user-facing message."""


class _Line:
    """Cursor over one statement line."""

    def __init__(self, text: str, n: int, raw: str):
        self.s, self.i, self.n, self.raw = text, 0, n, raw

    def fail(self, msg: str):
        raise MermaidError(f"line {self.n}: {msg}")

    def unreadable(self):
        self.fail(f'cannot read "{self.raw}"')

    def skip(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def done(self) -> bool:
        self.skip()
        return self.i >= len(self.s)

    def at(self, tok: str) -> bool:
        return self.s.startswith(tok, self.i)


class _Parser:
    def __init__(self):
        self.order: list[str] = []
        self.text: dict[str, str] = {}
        self.kind: dict[str, str] = {}
        self.arrows: list[tuple[str, str, str]] = []
        self.names: list[tuple[str, list[str] | None]] = []  # class names in order; ids for `class` lines
        self.classes: list[tuple[str, str]] = []  # (id, class name) in order

    def node(self, ln: _Line) -> str:
        ln.skip()
        if ln.at("&"):
            ln.fail("& is not supported; write one arrow per pair")
        m = _ID.match(ln.s, ln.i)
        if not m:
            ln.unreadable()
        nid, ln.i = m.group(), m.end()
        if len(nid) > 32:
            ln.unreadable()
        if nid not in self.order:
            self.order.append(nid)
            self.kind[nid] = "step"
        for bad in _BAD_SHAPES:
            if ln.at(bad):
                ln.fail(f"shape {bad} is not supported; use [ ], {{ }} or [( )]")
        for opener, closer, kind in _SHAPES:
            if ln.at(opener):
                ln.i += len(opener)
                self.give_text(ln, nid, self.read_text(ln, closer), kind)
                break
        if ln.at(":::"):
            m = _NAME.match(ln.s, ln.i + 3)
            if not m:
                ln.unreadable()
            ln.i = m.end()
            self.names.append((m.group(), None))
            self.classes.append((nid, m.group()))
        return nid

    def read_text(self, ln: _Line, closer: str) -> str:
        if ln.at('"'):
            end = ln.s.find('"', ln.i + 1)
            if end < 0 or not ln.s.startswith(closer, end + 1):
                ln.unreadable()
            text, ln.i = ln.s[ln.i + 1:end], end + 1 + len(closer)
        else:
            end = ln.s.find(closer, ln.i)
            if end < 0:
                ln.unreadable()
            text, ln.i = ln.s[ln.i:end], end + len(closer)
        if not text.strip():
            ln.unreadable()
        return text

    def give_text(self, ln: _Line, nid: str, text: str, kind: str):
        if nid in self.text:
            ln.fail(f"step {nid} is defined twice")
        if len(_BR.findall(text)) > 1:
            ln.fail(f"step {nid} has more than one <br>; write the label, then one tech tag")
        if not _BR.split(text)[0].strip():  # a tag with no label
            ln.unreadable()
        self.text[nid], self.kind[nid] = text, kind

    def arrow(self, ln: _Line) -> str | None:
        """Read an arrow at the cursor and return its label; None when the line ends."""
        if ln.done():
            return None
        if ln.at("&"):
            ln.fail("& is not supported; write one arrow per pair")
        for bad in _BAD_ARROWS:
            if ln.at(bad) and (bad[-1] not in "ox" or ln.i + 3 >= len(ln.s) or ln.s[ln.i + 3].isspace()):
                token = bad if bad[-1] in "ox" else _ARROW_RUN.match(ln.s, ln.i).group()
                ln.fail(f"arrow {token} is not supported; use -->")
        if ln.at("-->"):
            ln.i += 3
            ln.skip()
            if ln.at("|"):
                end = ln.s.find("|", ln.i + 1)
                if end < 0:
                    ln.unreadable()
                label, ln.i = ln.s[ln.i + 1:end], end + 1
                return label.strip().strip('"').strip()
            return ""
        if ln.at("-- "):
            end = ln.s.find("-->", ln.i + 3)
            if end < 0:
                ln.unreadable()
            label, ln.i = ln.s[ln.i + 3:end], end + 3
            return label.strip().strip('"').strip()
        m = _ARROW_RUN.match(ln.s, ln.i)
        if m:
            ln.fail(f"arrow {m.group()} is not supported; use -->")
        ln.unreadable()

    def statement(self, ln: _Line):
        source = self.node(ln)
        while (label := self.arrow(ln)) is not None:
            target = self.node(ln)
            self.arrows.append((source, target, label))
            source = target

    def line(self, text: str, n: int, raw: str):
        word = text.split(maxsplit=1)[0]
        if word == "subgraph":
            raise MermaidError(f"line {n}: subgraph is not supported")
        if word == "style":
            raise MermaidError(f"line {n}: style is not supported")
        if word == "linkStyle":
            raise MermaidError(f"line {n}: linkStyle is not supported")
        if word == "click":
            raise MermaidError(f"line {n}: click links are not supported")
        if word == "classDef":
            m = _NAME.fullmatch(text.split()[1]) if len(text.split()) > 1 else None
            if not m:
                raise MermaidError(f'line {n}: cannot read "{raw}"')
            self.names.append((m.group(), None))
            return
        if word == "class":
            m = _CLASS.fullmatch(text)
            if not m:
                raise MermaidError(f'line {n}: cannot read "{raw}"')
            ids = [i.strip() for i in m.group(1).split(",")]
            self.names.append((m.group(2), ids))
            self.classes.extend((i, m.group(2)) for i in ids)
            return
        self.statement(_Line(text, n, raw))

    def flow(self, direction: str) -> Flow:
        known = set(self.order)
        actors: list[str] = []
        for name, ids in self.names:  # a `class` line naming only unknown steps does not add an actor
            if name not in RESERVED and name not in actors and (ids is None or any(i in known for i in ids)):
                actors.append(name)
        steps = []
        for nid in self.order:
            label, _, tag = _BR.sub("\0", self.text.get(nid, nid)).partition("\0")
            names = [c for i, c in self.classes if i == nid]
            steps.append({"id": nid, "label": label.strip(), "tag": tag.strip(), "kind": self.kind[nid],
                          "actors": list(dict.fromkeys(c for c in names if c not in RESERVED)),
                          "stored": "stored" in names, "emphasis": "emphasis" in names})
        _limits(steps, actors, self.arrows, [i for i, _ in self.classes if i not in known])
        emphasis = next((s["id"] for s in steps if s["emphasis"]), None)
        return Flow(
            direction=direction,
            steps=[FlowStep(id=s["id"], label=s["label"], tag=s["tag"], kind=s["kind"],
                            actor=s["actors"][0] if s["actors"] else None, stored=s["stored"]) for s in steps],
            actors=actors,
            arrows=[FlowArrow(source=a, target=b, label=label) for a, b, label in self.arrows],
            emphasis=emphasis,
        )


def _limits(steps: list[dict], actors: list[str], arrows: list[tuple[str, str, str]], unknown: list[str]):
    k = len(steps)
    if k > 12:
        raise MermaidError(f"flow has {k} steps; at most 12")
    if k < 2:
        raise MermaidError(f"flow has {k} {'step' if k == 1 else 'steps'}; at least 2")
    if len(actors) > 4:
        raise MermaidError(f"flow has {len(actors)} actors; at most 4")
    if len(arrows) > 20:
        raise MermaidError(f"flow has {len(arrows)} arrows; at most 20")
    for s in steps:
        if (w := len(s["label"].split())) > 5:
            raise MermaidError(f"step {s['id']}: label has {w} words; at most 5")
    for s in steps:
        if (c := len(s["tag"])) > 24:
            raise MermaidError(f"step {s['id']}: tag has {c} characters; at most 24")
    for a, b, label in arrows:
        if (w := len(label.split())) > 3:
            raise MermaidError(f"arrow {a}→{b}: label has {w} words; at most 3")
    for a, b, _ in arrows:
        if a == b:
            raise MermaidError(f"arrow {a}→{a}: a step cannot point to itself")
    seen = set()
    for a, b, _ in arrows:
        if (a, b) in seen:
            raise MermaidError(f"arrow {a}→{b} appears twice")
        seen.add((a, b))
    for s in steps:
        if len(s["actors"]) > 1:
            raise MermaidError(f"step {s['id']} is in {len(s['actors'])} actors; at most 1")
    if actors:
        for s in steps:
            if not s["actors"]:
                raise MermaidError(f"step {s['id']} has no actor; give every step an actor or none")
    if sum(s["emphasis"] for s in steps) > 1:
        raise MermaidError("only one step can have class emphasis")
    if unknown:
        raise MermaidError(f"class names unknown step {unknown[0]}")


def parse_mermaid(text: str) -> Flow:
    """Parse Mermaid flowchart text into a `Flow` (layout none); raise `MermaidError` on anything outside the subset."""
    parser, direction = _Parser(), None
    for n, raw in enumerate(text.splitlines(), start=1):
        raw = raw.strip()
        line = raw[:-1].rstrip() if raw.endswith(";") else raw
        if not line or line.startswith("%%"):
            continue
        if direction is None:
            direction = _header(line, n)
            continue
        parser.line(line, n, raw)
    if direction is None:
        raise MermaidError('line 1: start with "flowchart LR" or "flowchart TB"')
    flow = parser.flow(direction)
    return flow.model_copy(update={"mermaid": text})


def _header(line: str, n: int) -> str:
    if line == "---":
        raise MermaidError(f"line {n}: front matter is not supported")
    words = line.split()
    if words[0] in OTHER_DIAGRAMS:
        raise MermaidError(f"line {n}: only flowcharts are supported, not {words[0]}")
    if words[0] in ("flowchart", "graph") and len(words) == 2:
        if words[1] in ("RL", "BT"):
            raise MermaidError(f"line {n}: direction {words[1]} is not supported; use LR or TB")
        if words[1] in ("LR", "TB", "TD"):
            return "LR" if words[1] == "LR" else "TB"
    raise MermaidError(f'line {n}: start with "flowchart LR" or "flowchart TB"')
