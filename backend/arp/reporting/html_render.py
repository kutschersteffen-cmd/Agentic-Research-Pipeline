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
from arp.reporting.house_style import _STYLE_DIR, Mode, Tokens, get_variant, load_tokens, slot_rect
from arp.schemas.reporting import Deck, QuantitativeDataset, SlideContent, TableSpec

_env = Environment(loader=FileSystemLoader(_STYLE_DIR / "templates"), autoescape=True)
_env.filters["title_body"] = lambda text: text.split(": ", 1)  # "Title: body" -> [title, body]; no colon -> [text]


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


def _font_faces(stacks: list[str]) -> str:
    # Files are style/fonts/<dir>/<FamilyWithoutSpaces>-<weight>.(woff2|ttf), e.g. HankenGrotesk-600.ttf.
    faces = []
    for family in dict.fromkeys(f.split(",")[0].strip().strip("'\"") for f in stacks):
        for path in sorted((_STYLE_DIR / "fonts").glob(f"*/{family.replace(' ', '')}-*")):
            weight, ext = path.stem.rsplit("-", 1)[1], path.suffix[1:]
            if weight.isdigit() and ext in ("woff2", "ttf"):
                b64 = base64.b64encode(path.read_bytes()).decode()
                fmt = "woff2" if ext == "woff2" else "truetype"
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
    r = slot_rect(tokens, spec)
    value = slide.slots.get(spec.name)
    # Fill by design: short content steps up to the slot's larger fixed role; it never scales freely.
    words = max((len(t.split()) for t in value), default=0) if isinstance(value, list) else len((value or "").split())
    role = spec.type_role_short if spec.type_role_short and 0 < words <= (spec.short_words or 0) else spec.type_role
    v = {"slide": i, "name": spec.name, "kind": spec.kind, "role": role, "x": r.x, "y": r.y, "w": r.w, "h": r.h}
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
            "index": i, "layout": s.layout, "variant": s.variant, "headline": s.headline, "refs": " · ".join(s.source_refs),
            "slots": [_slot_view(i, s, sp, tokens, by_id, theme) for sp in get_variant(s.layout, s.variant).slots],
        }
        for i, s in enumerate(deck.slides)
    ]
    fonts = {"heading": tokens.heading_font(mode), "body": tokens.fonts.body, "mono": tokens.fonts.mono or tokens.fonts.body}
    return _env.get_template("base.html.j2").render(
        deck=deck, slides=slides, t=tokens, c=tokens.colors(mode), fonts=fonts, mode=mode, font_faces=_font_faces(list(fonts.values())),
    )
