"""Deck -> one self-contained HTML document (1920x1080 slides) from the house-style tokens/layouts.

Every slot is an absolutely positioned, fixed-size, overflow:hidden box tagged
data-slide/data-slot, so browser.measure() can compare what the text needs
against what the layout allows. Jinja autoescape is on; slot text is never
marked safe -- only the chart SVG we generate ourselves is.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from arp.reporting.chart_builder import render_chart_svg
from arp.reporting.design import DesignTheme
from arp.reporting.house_style import _STYLE_DIR, Mode, Tokens, footer_fits, get_variant, load_tokens, slot_rect
from arp.reporting.template_frame import font_family_of
from arp.schemas.reporting import Deck, QuantitativeDataset, SlideContent, TableSpec

HOUSE_LAYOUTS = ("title", "section")  # keep the house geometry inside a template frame

_env = Environment(loader=FileSystemLoader(_STYLE_DIR / "templates"), autoescape=True)


def theme_from_tokens(tokens: Tokens, mode: Mode = "light") -> DesignTheme:
    c = tokens.colors(mode)
    bare = lambda h: h.lstrip("#")  # noqa: E731 -- DesignTheme stores colors without '#'
    return DesignTheme(
        accent=bare(c.accent), ink_primary=bare(c.ink), ink_secondary=bare(c.ink_muted), ink_muted=bare(c.ink_muted), gridline=bare(c.neutral),
        surface=bare(c.background), categorical=[bare(x) for x in c.categorical],
        font_major=tokens.heading_font(mode).split(",")[0], font_minor=tokens.fonts.body.split(",")[0],
    )


def _data_uri(path: Path) -> str:
    # The page has no file origin, so a local path would render blank; inline it.
    if not path.is_file():
        raise FileNotFoundError(f"image_path does not exist: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


_FORMATS = {"woff2": "woff2", "ttf": "truetype", "otf": "opentype"}


def _font_faces(stacks: list[str], font_dir: str | None = None) -> str:
    # Files are <FamilyWithoutSpaces>-<weight>.(woff2|ttf|otf), e.g. HankenGrotesk-600.ttf, in style/fonts/<dir>/
    # or in a template's font folder; the family match ignores case.
    files = [*(_STYLE_DIR / "fonts").glob("*/*"), *(Path(font_dir).glob("*") if font_dir else [])]
    faces = []
    for family in dict.fromkeys(f.split(",")[0].strip().strip("'\"") for f in stacks):
        for path in sorted(p for p in files if font_family_of(p.name) == family.replace(" ", "").lower()):
            weight, ext = path.stem.rsplit("-", 1)[1], path.suffix[1:].lower()
            if weight.isdigit() and ext in _FORMATS:
                b64 = base64.b64encode(path.read_bytes()).decode()
                fmt = _FORMATS[ext]
                faces.append(f"@font-face {{ font-family: '{family}'; font-weight: {weight}; font-style: normal; "
                             f"src: url(data:font/{ext};base64,{b64}) format('{fmt}'); }}")
    return "\n".join(faces)


def _as_text(v: str | list[str] | None) -> str:
    return " ".join(v) if isinstance(v, list) else (v or "")


def table_view(spec: TableSpec, ds: QuantitativeDataset) -> tuple[list[str], list[list], int]:
    """Columns, the visible row window, and how many rows lie beyond it; shared with the pptx export."""
    columns = spec.columns or ds.column_names()
    end = spec.row_offset + spec.max_rows
    return columns, [[row.get(c, "") for c in columns] for row in ds.rows[spec.row_offset : end]], max(0, len(ds.rows) - end)


def _slot_view(i: int, slide: SlideContent, spec, tokens: Tokens, datasets: dict[str, QuantitativeDataset], theme: DesignTheme) -> dict:
    r = slot_rect(tokens, spec, house=slide.layout in HOUSE_LAYOUTS)
    v = {"slide": i, "name": spec.name, "kind": spec.kind, "role": spec.type_role, "x": r.x, "y": r.y, "w": r.w, "h": r.h}
    value = slide.slots.get(spec.name)
    if spec.kind == "list":
        v["items"] = value if isinstance(value, list) else ([value] if value else [])
    elif spec.kind == "chart" and slide.chart:
        v["svg"] = render_chart_svg(slide.chart, list(datasets.values()), width_px=int(r.w), height_px=int(r.h), theme=theme)
    elif spec.kind == "table" and slide.table and slide.table.dataset_id in datasets:
        v["columns"], v["rows"], v["more"] = table_view(slide.table, datasets[slide.table.dataset_id])
    elif spec.kind == "image":
        v["image"] = _data_uri(Path(slide.image_path)) if slide.image_path else None
    else:
        v["text"] = _as_text(value)
    return v


def render_deck_html(deck: Deck, datasets: list[QuantitativeDataset], tokens: Tokens | None = None, mode: Mode = "light") -> str:
    tokens = tokens or load_tokens()
    theme = theme_from_tokens(tokens, mode)
    by_id = {d.dataset_id: d for d in datasets}
    slides = [
        {
            "index": i, "layout": s.layout, "headline": s.headline, "subheading": s.subheading, "framed": tokens.frame is not None,
            "refs": " · ".join(s.source_refs),
            "slots": [_slot_view(i, s, sp, tokens, by_id, theme) for sp in get_variant(s.layout, s.variant).slots],
        }
        for i, s in enumerate(deck.slides)
    ]
    fonts = {"heading": tokens.heading_font(mode), "body": tokens.fonts.body, "mono": tokens.fonts.mono or tokens.fonts.body}
    stacks = [*fonts.values(), *([tokens.frame.subheading_font.family] if tokens.frame else [])]
    return _env.get_template("base.html.j2").render(
        deck=deck, slides=slides, t=tokens, c=tokens.colors(mode), fonts=fonts, mode=mode, font_faces=_font_faces(stacks, tokens.font_dir),
        frame=tokens.frame, footer=footer_fits(tokens),
    )
