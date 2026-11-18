"""House-deck design tokens and layout library, loaded from style/*.json.

The JSON is the single source of truth for the look (tokens) and the slot
geometry (layouts); renderers and the fit/lint stages read it from here.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import BaseModel

from arp.schemas.reporting import TemplateFrame

_STYLE_DIR = Path(__file__).parent / "style"


class Canvas(BaseModel):
    width: int
    height: int


class Grid(BaseModel):
    columns: int
    margin_x: int
    margin_top: int
    margin_bottom: int
    gutter: int
    headline_band: int
    footer_band: int
    rule_width: int = 96  # accent rule above the headline; the content width makes it a full rule
    rule_height: int = 8


class TypeStyle(BaseModel):
    size: float
    line_height: float
    weight: int
    font: Literal["heading", "body"]
    tracking: float = 0.0  # letter-spacing in em


class TypeScale(BaseModel):
    """Exactly five sizes -- adding a role is a design decision, not a config tweak."""

    headline: TypeStyle
    subhead: TypeStyle
    body: TypeStyle
    caption: TypeStyle
    big_number: TypeStyle


class Colors(BaseModel):
    ink: str
    ink_muted: str
    neutral: str
    accent: str
    background: str
    categorical: list[str]


class Fonts(BaseModel):
    heading: str
    body: str
    heading_dark: str | None = None  # dark mode's heading face; None = heading
    mono: str | None = None  # footer/source line (the app's label face); None = body


Mode = Literal["light", "dark"]


class Tokens(BaseModel):
    canvas: Canvas
    grid: Grid
    type: dict[str, TypeStyle]
    color: Colors  # light mode
    color_dark: Colors
    graphite: dict[str, str]  # the slide-component palette (light)
    graphite_dark: dict[str, str]
    fonts: Fonts
    frame: TemplateFrame | None = None  # a company template's boxes; None = the house frame
    font_dir: str | None = None  # the template's uploaded font files
    emu_per_px: float = 9525  # the PPTX scale: a 20 in slide, or the template's own width / 1920

    def colors(self, mode: Mode) -> Colors:
        return self.color_dark if mode == "dark" else self.color

    def heading_font(self, mode: Mode) -> str:
        return (self.fonts.heading_dark if mode == "dark" else None) or self.fonts.heading


class SlotSpec(BaseModel):
    """One fillable region. `col`/`row` are 0-based; `row`/`rows` count the 12 body rows."""

    name: str
    kind: Literal["text", "list", "number", "chart", "table", "image"]
    col: int
    span: int
    row: int
    rows: int
    max_words: int | None = None  # per item for list slots
    max_items: int | None = None
    type_role: str


class VariantSpec(BaseModel):
    id: str
    slots: list[SlotSpec]
    roomier: str | None = None


class LayoutSpec(BaseModel):
    id: str
    purpose: str
    variants: list[VariantSpec]


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float


@cache
def load_tokens() -> Tokens:
    tokens = Tokens.model_validate_json((_STYLE_DIR / "tokens.json").read_text())
    TypeScale.model_validate(tokens.type)  # enforce the five-role scale
    return tokens


@cache
def load_layouts() -> dict[str, LayoutSpec]:
    raw = json.loads((_STYLE_DIR / "layouts.json").read_text())
    return {ly.id: ly for ly in (LayoutSpec.model_validate(x) for x in raw["layouts"])}


def slot_rect(tokens: Tokens, slot: SlotSpec, house: bool = False) -> Rect:
    """The slot's box on the 12x12 body grid: the house body area, or a template frame's body box.
    `house` keeps the house geometry under a frame (title and section slides)."""
    g, f = tokens.grid, tokens.frame
    if f is not None and not house:
        left, top, width, body_h = f.body.x, f.body.y, f.body.w, f.body.h
    else:
        left, top, width = g.margin_x, g.margin_top + g.headline_band, tokens.canvas.width - 2 * g.margin_x
        body_h = tokens.canvas.height - g.margin_bottom - g.footer_band - top
    col_w = (width - (g.columns - 1) * g.gutter) / g.columns
    row_h = body_h / 12
    return Rect(
        x=left + slot.col * (col_w + g.gutter),
        y=top + slot.row * row_h,
        w=slot.span * col_w + (slot.span - 1) * g.gutter,
        h=slot.rows * row_h,
    )


def with_frame(tokens: Tokens, frame: TemplateFrame, font_dir: str | None, slide_width_emu: int) -> Tokens:
    """`tokens` drawn inside a company template: its boxes, its families (dark mode too), its slide width."""
    def stack(family: str) -> str:
        return f"'{family}', {tokens.fonts.body}"

    fonts = Fonts(heading=stack(frame.headline_font.family), body=stack(frame.body_font_family), mono=stack(frame.body_font_family))
    return tokens.model_copy(update={"frame": frame, "font_dir": font_dir, "fonts": fonts, "emu_per_px": slide_width_emu / tokens.canvas.width})


def footer_fits(tokens: Tokens) -> bool:
    """The footer keeps its house row only when the body box ends above it (always, without a frame)."""
    g, f = tokens.grid, tokens.frame
    return f is None or f.body.y + f.body.h <= tokens.canvas.height - g.margin_bottom - g.footer_band + 0.5


def get_variant(layout: str, variant: str) -> VariantSpec:
    ly = load_layouts().get(layout)
    if ly is None:
        raise KeyError(f"unknown layout {layout!r}; known: {sorted(load_layouts())}")
    for v in ly.variants:
        if v.id == variant:
            return v
    raise KeyError(f"unknown variant {layout}/{variant}; known: {[v.id for v in ly.variants]}")
