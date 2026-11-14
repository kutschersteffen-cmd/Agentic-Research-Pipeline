"""The spec's `frame.pptx`: a 16:9 template with one "Content" layout (title, subheading, body)."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.util import Emu, Inches

from arp.reporting.house_style import _STYLE_DIR

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_THEME = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"


def _set_box(ph, x, y, w, h):
    ph.left, ph.top, ph.width, ph.height = Inches(x), Inches(y), Inches(w), Inches(h)


def _set_size(ph, pt: int, bold: bool) -> None:
    body = ph._element.txBody
    lst = body.find(f"{{{_A}}}lstStyle")
    lvl = etree.SubElement(lst, f"{{{_A}}}lvl1pPr")
    etree.SubElement(lvl, f"{{{_A}}}defRPr", sz=str(pt * 100), b="1" if bold else "0")


def _set_theme_fonts(prs, major: str, minor: str) -> None:
    part = prs.slide_masters[0].part.part_related_by(_THEME)
    root = etree.fromstring(part.blob)
    root.find(f".//{{{_A}}}majorFont/{{{_A}}}latin").set("typeface", major)
    root.find(f".//{{{_A}}}minorFont/{{{_A}}}latin").set("typeface", minor)
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _configure(layout, name: str, with_subheading: bool, body_xfrm: bool) -> None:
    layout.name = name
    phs = {ph.placeholder_format.idx: ph for ph in layout.placeholders}
    for idx in [i for i in phs if i not in (0, 1)]:  # drop date/footer/slide number
        phs[idx]._element.getparent().remove(phs[idx]._element)
    title, body = phs[0], phs[1]
    _set_box(title, 1, 0.5, 11, 1)
    _set_size(title, 32, True)
    if with_subheading:
        sub = layout.shapes._spTree.insert_element_before(copy.deepcopy(body._element), "p:extLst")
        sub.nvSpPr.nvPr.ph.set("idx", "13")
        sub.nvSpPr.cNvPr.set("id", "99")
        sub.nvSpPr.cNvPr.set("name", "Subheading")
        sub_ph = next(p for p in layout.placeholders if p.placeholder_format.idx == 13)
        _set_box(sub_ph, 1, 1.6, 11, 0.5)
        _set_size(sub_ph, 18, False)
    if body_xfrm:
        _set_box(body, 1, 2.4, 11, 3.9)
    else:
        xfrm = body._element.spPr.find(f"{{{_A}}}xfrm")
        if xfrm is not None:
            body._element.spPr.remove(xfrm)


def make_frame_pptx(
    path: Path, *, width_emu: int = 12192000, height_emu: int = 6858000, with_subheading: bool = True,
    layouts: tuple[str, ...] = ("Content",), body_xfrm: bool = True, major: str = "Testa Serif",
    master_body: bool = True,
) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(width_emu), Emu(height_emu)
    keep = [prs.slide_layouts[1], prs.slide_layouts[3]][: len(layouts)]  # Title and Content, Two Content
    for layout in list(prs.slide_layouts):
        if all(layout is not k for k in keep):
            prs.slide_layouts.remove(layout)
    for layout, name in zip(keep, layouts, strict=True):
        _configure(layout, name, with_subheading, body_xfrm)
    _set_theme_fonts(prs, major, "Testa Sans")
    if not master_body:  # a layout placeholder then has nothing to inherit its position from
        for ph in list(prs.slide_masters[0].placeholders):
            if ph.placeholder_format.idx == 1:
                ph._element.getparent().remove(ph._element)
    prs.save(path)
    return path


def frame_fonts(directory: Path, names: tuple[str, ...] = ("TestaSerif-700.ttf", "TestaSans-400.ttf")) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    src = _STYLE_DIR / "fonts" / "geist" / "Geist-400.ttf"
    return [Path(shutil.copyfile(src, directory / n)) for n in names]
