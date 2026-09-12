from __future__ import annotations

import shutil
from pathlib import Path

from lxml import etree
from pptx import Presentation

from arp.schemas.reporting import TemplateLayoutInfo, TemplateStyleProfile
from arp.storage.reporting_store import ReportingStore

_THEME_RELTYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
_A_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _theme_xml(prs: Presentation) -> etree._Element | None:
    """The theme part is an opaque, unparsed `Part` in python-pptx (no
    dedicated theme object model), so its color scheme/font scheme are
    read by parsing `.blob` directly rather than through any python-pptx
    API -- the same relationship-based lookup PowerPoint itself uses to
    resolve a slide master's theme.
    """
    try:
        theme_part = prs.slide_masters[0].part.part_related_by(_THEME_RELTYPE)
    except (IndexError, KeyError, AttributeError):
        return None
    try:
        return etree.fromstring(theme_part.blob)
    except etree.XMLSyntaxError:
        return None

# Maps python-pptx's placeholder type enum names to short, stable labels
# used in TemplateStyleProfile.layouts[].placeholder_types -- the Content
# Planner only needs to know a layout *has* a title/body/chart/picture slot,
# not python-pptx's internal enum values.
_PLACEHOLDER_LABELS = {
    "TITLE": "title",
    "CENTER_TITLE": "title",
    "SUBTITLE": "subtitle",
    "BODY": "body",
    "OBJECT": "object",
    "PICTURE": "picture",
    "CHART": "chart",
    "TABLE": "table",
    "DATE": "date",
    "FOOTER": "footer",
    "SLIDE_NUMBER": "slide_number",
}


def _theme_colors(prs: Presentation) -> dict[str, str]:
    """Reads the 12 named theme colors (dk1/lt1/dk2/lt2/accent1-6/hlink/
    folHlink) straight from the template's theme XML -- the same palette
    PowerPoint itself offers when a user picks "Theme Colors" for any
    shape, so charts/text built against these hex values visually match
    the template without guessing at screenshots or embedding a whole
    separate palette.
    """
    colors: dict[str, str] = {}
    theme_elm = _theme_xml(prs)
    if theme_elm is None:
        return colors
    scheme = theme_elm.find(".//a:clrScheme", _A_NS)
    if scheme is None:
        return colors
    for child in scheme:
        tag = etree.QName(child.tag).localname
        srgb = child.find("a:srgbClr", _A_NS)
        if srgb is not None and srgb.get("val"):
            colors[tag] = srgb.get("val").upper()
        else:
            sys_clr = child.find("a:sysClr", _A_NS)
            if sys_clr is not None and sys_clr.get("lastClr"):
                colors[tag] = sys_clr.get("lastClr").upper()
    return colors


def _theme_fonts(prs: Presentation) -> tuple[str | None, str | None]:
    theme_elm = _theme_xml(prs)
    if theme_elm is None:
        return None, None
    major = theme_elm.find(".//a:fontScheme/a:majorFont/a:latin", _A_NS)
    minor = theme_elm.find(".//a:fontScheme/a:minorFont/a:latin", _A_NS)
    return (major.get("typeface") if major is not None else None, minor.get("typeface") if minor is not None else None)


def extract_style_profile(pptx_path: Path, source_filename: str) -> TemplateStyleProfile:
    """Deterministically inspects an uploaded .pptx template -- slide
    dimensions, every slide layout's name and placeholder types, theme
    colors, and theme fonts. Nothing here is LLM-inferred: this is exactly
    the metadata DeckBuilder needs to build new slides that visually match
    the template, read straight from the OOXML the same way PowerPoint
    itself would.
    """
    prs = Presentation(str(pptx_path))
    layouts = []
    for idx, layout in enumerate(prs.slide_layouts):
        placeholder_types = []
        for ph in layout.placeholders:
            try:
                label = _PLACEHOLDER_LABELS.get(ph.placeholder_format.type.name, ph.placeholder_format.type.name.lower())
            except (AttributeError, ValueError):
                label = "unknown"
            placeholder_types.append(label)
        layouts.append(TemplateLayoutInfo(index=idx, name=layout.name, placeholder_types=placeholder_types))

    major_font, minor_font = _theme_fonts(prs)
    return TemplateStyleProfile(
        source_filename=source_filename,
        slide_width_emu=prs.slide_width,
        slide_height_emu=prs.slide_height,
        layouts=layouts,
        theme_colors=_theme_colors(prs),
        major_font=major_font,
        minor_font=minor_font,
        stored_path="",  # filled in by ingest_template once the file is saved
    )


def ingest_template(store: ReportingStore, source_path: Path, source_filename: str) -> TemplateStyleProfile:
    """Extracts the style profile, then copies the original template file
    into the store keyed by the new template_id -- DeckBuilder clones this
    exact file as its render base, so every downstream slide inherits its
    masters/layouts/theme byte-for-byte rather than an approximation.
    """
    style = extract_style_profile(source_path, source_filename)
    dest = store.template_source_path(style.template_id, "original.pptx")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, dest)
    style.stored_path = str(dest)
    store.save_template_style(style)
    return style
