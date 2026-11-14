"""A company template's frame: the headline, subheading and body boxes (and their fonts) of one content layout.

Read straight from the .pptx, never guessed. Boxes are in house-canvas px: the slide width maps to 1920.
"""

from __future__ import annotations

import re

from pptx.enum.shapes import PP_PLACEHOLDER

from arp.reporting.house_style import load_tokens
from arp.schemas.reporting import Box, FrameFont, TemplateFrame

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_TITLES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
_OTHERS = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.SUBTITLE, PP_PLACEHOLDER.OBJECT}
BUNDLED = {"geist", "geistmono", "hankengrotesk"}
_FONT_FILE = re.compile(r"^(?P<family>.+)-\d+\.(ttf|otf|woff2)$", re.IGNORECASE)


def font_family_of(filename: str) -> str | None:
    """`TestaSerif-700.ttf` -> `testaserif`; None for any other name."""
    m = _FONT_FILE.match(filename)
    return _norm(m["family"]) if m else None


def _norm(family: str) -> str:
    return family.replace(" ", "").lower()


def _kind(ph):
    try:
        return ph.placeholder_format.type
    except (AttributeError, ValueError):
        return None


def _theme_font(prs, typeface: str | None, major: bool) -> str | None:
    from arp.reporting.style_profile import _theme_fonts  # local: style_profile imports this module

    mj, mn = _theme_fonts(prs)
    if typeface == "+mj-lt":
        return mj
    if typeface == "+mn-lt":
        return mn
    return typeface or (mj if major else mn)


def _rpr(element):
    return element.find(f".//{_A}lstStyle/{_A}lvl1pPr/{_A}defRPr") if element is not None else None


def _font(prs, ph, title: bool, fallback_px: float) -> FrameFont:
    """Size/bold/family from the layout placeholder, then the master's placeholder, then the master text style."""
    master = prs.slide_masters[0]
    base = next((m for m in master.placeholders if (_kind(m) in _TITLES) == title and (title or _kind(m) == PP_PLACEHOLDER.BODY)), None)
    style = master._element.find(f"{_P}txStyles/{_P}{'titleStyle' if title else 'bodyStyle'}/{_A}lvl1pPr/{_A}defRPr")
    sources = [r for r in (_rpr(ph._element), _rpr(base._element if base is not None else None), style) if r is not None]
    sz = next((int(r.get("sz")) for r in sources if r.get("sz")), None)
    b = next((r.get("b") in ("1", "true") for r in sources if r.get("b") is not None), False)
    latin = next((r.find(f"{_A}latin").get("typeface") for r in sources if r.find(f"{_A}latin") is not None), None)
    scale = 1920 / (prs.slide_width / 12700)  # px per pt
    return FrameFont(family=_theme_font(prs, latin, title) or "", size_px=sz / 100 * scale if sz else fallback_px, bold=b)


def _box(prs, ph) -> Box:
    s = 1920 / prs.slide_width
    return Box(x=ph.left * s, y=ph.top * s, w=ph.width * s, h=ph.height * s)


def _pick(layout, slide_h: int):
    """(headline, subheading, body) placeholders, or None when the layout lacks one."""
    titles = [p for p in layout.placeholders if _kind(p) in _TITLES]
    others = [p for p in layout.placeholders if _kind(p) in _OTHERS]
    if len(titles) != 1 or len(others) < 2:
        return None
    title = titles[0]
    subs = [p for p in others if p.top >= title.top and p.height < slide_h / 3]
    if not subs:
        return None
    sub = min(subs, key=lambda p: p.top)
    body = max((p for p in others if p is not sub), key=lambda p: p.width * p.height)
    return title, sub, body


def extract_frame(prs, layout_name: str | None, font_families: set[str]) -> tuple[TemplateFrame | None, str | None]:
    """The frame, or (None, the first reason it can't be built). `font_families` come from font_family_of."""
    w, h = prs.slide_width, prs.slide_height
    if abs(w * 9 - h * 16) > h * 16 * 0.01:
        return None, f"Template must be 16:9 (got {w}×{h})."
    layouts = list(prs.slide_layouts)
    if layout_name is not None:
        layouts = [ly for ly in layouts if ly.name == layout_name]
        if not layouts:
            return None, f'No layout named "{layout_name}".'
    picked = next(((ly, p) for ly in layouts if (p := _pick(ly, h))), None)
    if picked is None:
        return None, "No layout has a title, a subheading and a body placeholder."
    layout, (title, sub, body) = picked
    type_ = load_tokens().type
    head_font = _font(prs, title, True, type_["headline"].size)
    sub_font = _font(prs, sub, False, type_["subhead"].size)
    body_family = _theme_font(prs, None, False) or sub_font.family
    for family in (head_font.family, sub_font.family, body_family):
        if _norm(family) not in BUNDLED | font_families:
            return None, f'Upload the font file for "{family}".'
    return TemplateFrame(
        layout_name=layout.name, headline=_box(prs, title), subheading=_box(prs, sub), body=_box(prs, body),
        headline_font=head_font, subheading_font=sub_font, body_font_family=body_family,
    ), None


def frame_preview_html(frame: TemplateFrame) -> str:
    """One 1920x1080 slide with the frame's three boxes outlined and labelled, for checking an upload."""
    boxes = "".join(
        f'<div style="position:absolute;left:{b.x:g}px;top:{b.y:g}px;width:{b.w:g}px;height:{b.h:g}px;'
        f'border:3px dashed #ea4c14;box-sizing:border-box;font:600 28px sans-serif;color:#ea4c14;padding:8px">{label}</div>'
        for label, b in (("Headline", frame.headline), ("Subheading", frame.subheading), ("Body", frame.body))
    )
    return (
        '<html><body style="margin:0"><section class="slide" style="position:relative;width:1920px;height:1080px;background:#fff">'
        f"{boxes}</section></body></html>"
    )
