"""Shared helpers for the visual renderers: type steps, fonts, the strip, numbered rows, dataset cells."""

from __future__ import annotations

from math import ceil, isfinite

from arp.reporting.render_model import (
    S4,
    S12,
    S16,
    S24,
    S32,
    S40,
    Primitive,
    Rect,
    RenderCtx,
    Text,
    VisualDataError,
    family,
    palette,
)
from arp.schemas.reporting import Box, QuantitativeDataset

# Type size by role, indexed by ctx.type_step + 1 (step -1 is the underfill step-up).
TYPE = {"value": (160, 144, 112, 96), "body": (32, 28, 24, 24), "title": (40, 36, 30, 30)}
LEADING = 1.2  # the writers' line height
SQUARE = 56  # number square side


def size(role: str, ctx: RenderCtx) -> int:
    return TYPE[role][ctx.type_step + 1]


def fonts(ctx: RenderCtx) -> tuple[str, str, str]:
    """Heading, body and mono families."""
    f = ctx.tokens.fonts
    heading = f.heading_dark if ctx.mode == "dark" and f.heading_dark else f.heading
    return family(heading), family(f.body), family(f.mono or f.body)


def lines(text: str, px: float, width: float, mono: bool = False) -> int:
    # shortcut: average glyph width (0.5 em sans, 0.6 em mono), not measured; upgrade when the fit ladder measures text
    return max(1, ceil(len(text) * px * (0.6 if mono else 0.5) / width))


def strip(x: float, y: float, color: str, highlight: str) -> list[Primitive]:
    return [Rect(f"strip:{i}", x + (i - 1) * (S12 + S4), y, S12, S12, highlight if i == 3 else color) for i in range(1, 6)]


def numbered_rows(texts: list[str], box: Box, ctx: RenderCtx, emphasis: int | None,
                  extras: list[tuple[str, str]] | None = None) -> list[Primitive]:
    """Ground rows with an ink number square and the text; `extras` adds an owner column and a `when` pill per row.
    The stack is centred in the box; an emphasised row is set at weight 600 (not a block)."""
    c, (_, body, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    px, pad_y, owner_w, when_w = S40, S24, 320, 200
    text_x = box.x + px + SQUARE + S32
    text_w = box.x + box.w - px - text_x - (S32 + owner_w + S32 + when_w if extras else 0)
    fs = size("body", ctx)
    heights = [max(SQUARE, lines(t, fs, text_w) * fs * LEADING) + 2 * pad_y for t in texts]
    y = box.y + (box.h - sum(heights) - S16 * (len(texts) - 1)) / 2
    out: list[Primitive] = []
    for n, (t, h) in enumerate(zip(texts, heights, strict=True), start=1):
        sq_y = y + (h - SQUARE) / 2
        out += [
            Rect(f"row:{n}", box.x, y, box.w, h, c["ground"]),
            Rect(f"step:{n}", box.x + px, sq_y, SQUARE, SQUARE, c["ink"]),
            Text(f"step:{n}:num", box.x + px, sq_y, SQUARE, SQUARE, str(n), 24, 400, mono, c["panel"], "center", "middle", c["ink"]),
            Text(f"row:{n}:text", text_x, y + pad_y, text_w, h - 2 * pad_y, t, fs, 600 if emphasis == n - 1 else 400, body,
                 c["ink"], anchor="middle", fill_under=c["ground"]),
        ]
        if extras:
            owner, when = extras[n - 1]
            owner_x = text_x + text_w + S32
            out.append(Text(f"row:{n}:owner", owner_x, y + pad_y, owner_w, h - 2 * pad_y, owner.upper(), 20, 400, mono,
                            c["muted"], anchor="middle", fill_under=c["ground"]))
            if when:
                pill_w, pill_h = len(when) * 18 * 0.6 + 2 * S12, 36
                pill_x, pill_y = box.x + box.w - px - pill_w, y + (h - pill_h) / 2
                out += [
                    Rect(f"row:{n}:when", pill_x, pill_y, pill_w, pill_h, c["panel"], line=c["line"], line_w=1),
                    Text(f"row:{n}:when:text", pill_x, pill_y, pill_w, pill_h, when, 18, 400, mono, c["muted"], "center", "middle",
                         c["panel"]),
                ]
        y += h + S16
    return out


def dataset(ctx: RenderCtx, dataset_id: str, columns: list[str]) -> QuantitativeDataset:
    """The referenced dataset, after checking it has every named column."""
    ds = ctx.datasets.get(dataset_id)
    if ds is None:
        raise VisualDataError(f"unknown dataset {dataset_id!r}")
    missing = [c for c in columns if c not in ds.column_names()]
    if missing:
        raise VisualDataError(f"dataset {dataset_id!r} has no column {', '.join(map(repr, missing))}")
    return ds


def number(v: object) -> float:
    """A cell as a finite number: ints, floats and numeric strings (`1,234`, `−1`); anything else (NaN and infinity
    included) is a VisualDataError."""
    try:
        n = float(v) if isinstance(v, int | float) and not isinstance(v, bool) else float(str(v).replace(",", "").replace("−", "-"))
    except ValueError:
        raise VisualDataError(f"not a number: {v!r}") from None
    if not isfinite(n):
        raise VisualDataError(f"not a number: {v!r}")
    return n


def signed(text: str) -> str:
    """A number as text with a typographic minus."""
    return "−" + text[1:] if text.startswith("-") else text
