"""Mini-app HTML cleaning (spec agent-panel-code-mode, Phase 5, D14): what the stage puts in `<iframe sandbox="">`.

A real HTML parser and an allowlist: every element not listed goes with its content, every attribute not listed goes.
The result has no script, link, form, `<base>`, `<meta>`, SVG `a`/`use`/`set`/`animate*` and no `on*` attribute."""
from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import PreformattedString

HTML_ELEMENTS = frozenset(["html", "head", "body", "style", "div", "span", "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col", "strong", "em", "b", "i", "u", "small", "sub", "sup", "code", "pre", "blockquote", "figure", "figcaption", "details", "summary"])
SVG_ELEMENTS = frozenset(["svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "title", "desc"])
ATTRIBUTES = frozenset(["class", "style", "title", "colspan", "rowspan", "open", "lang", "dir"])
# Lower case: the parser lowers attribute names, and the browser's parser restores SVG's camel case (viewBox).
SVG_ATTRIBUTES = frozenset(a.lower() for a in ["viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "points", "fill", "stroke", "stroke-width", "opacity", "transform", "text-anchor", "font-size"])

ASKS_KEPT, ASK_CHARS = 5, 200


def _clean(tag: Tag) -> None:
    for child in list(tag.children):
        if isinstance(child, Tag):
            name = child.name.lower()
            if name not in HTML_ELEMENTS and name not in SVG_ELEMENTS:
                child.decompose()
                continue
            svg = name in SVG_ELEMENTS
            child.attrs = {k: v for k, v in child.attrs.items()
                           if k.lower() in ATTRIBUTES or (svg and k.lower() in SVG_ATTRIBUTES)}
            if name == "style":
                # Inside <svg> a browser parses <style> as markup, not raw text: no '<' may reach it either way.
                css = child.get_text().replace("<", "\\3C ")
                child.clear()
                child.append(NavigableString(css))
                continue
            _clean(child)
        elif isinstance(child, PreformattedString):  # comments, doctypes, CDATA, processing instructions
            child.extract()


def clean_miniapp_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _clean(soup)
    return soup.decode(formatter="html5")


def trim_asks(asks: list[str]) -> list[str]:
    """Empty and whitespace-only questions dropped, then the first 5, each cut to its first 200 characters."""
    return [a[:ASK_CHARS] for a in asks if a.strip()][:ASKS_KEPT]
