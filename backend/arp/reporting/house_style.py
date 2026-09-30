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


class TypeStyle(BaseModel):
    size: int
    line_height: float
    weight: int
    font: str


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


class Tokens(BaseModel):
    canvas: Canvas
    grid: Grid
    type: dict[str, TypeStyle]
    color: Colors
    fonts: Fonts


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


def slot_rect(tokens: Tokens, slot: SlotSpec) -> Rect:
    g = tokens.grid
    col_w = (tokens.canvas.width - 2 * g.margin_x - (g.columns - 1) * g.gutter) / g.columns
    body_top = g.margin_top + g.headline_band
    body_h = tokens.canvas.height - g.margin_bottom - g.footer_band - body_top
    row_h = body_h / 12
    return Rect(
        x=g.margin_x + slot.col * (col_w + g.gutter),
        y=body_top + slot.row * row_h,
        w=slot.span * col_w + (slot.span - 1) * g.gutter,
        h=slot.rows * row_h,
    )


def get_variant(layout: str, variant: str) -> VariantSpec:
    ly = load_layouts().get(layout)
    if ly is None:
        raise KeyError(f"unknown layout {layout!r}; known: {sorted(load_layouts())}")
    for v in ly.variants:
        if v.id == variant:
            return v
    raise KeyError(f"unknown variant {layout}/{variant}; known: {[v.id for v in ly.variants]}")
