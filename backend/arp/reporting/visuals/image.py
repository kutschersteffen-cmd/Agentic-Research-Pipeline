"""`image`: registered pictures cropped to their slots, as a `hero`, a `split` beside points, or a captioned `gallery`.
Spec: docs/superpowers/specs/2026-11-18-house-deck-image-slides.md, "Geometry" and "Crop"."""

from math import ceil

from arp.reporting.render_model import (
    S16,
    S24,
    S32,
    S48,
    S64,
    VISUALS,
    ImagePrim,
    Line,
    Primitive,
    Text,
    VisualDataError,
    crop,
    palette,
)
from arp.reporting.visuals._common import LEADING, fonts, lines, size

CAPTION_BAND = S48  # a captioned image is this much shorter; its caption sits 16 px below it, 32 px tall
SPLIT_W = 1000  # split: the image's width; the points column takes the rest of the body box after a 64 px gap
GAP = S32  # gallery: between cells


def picture(n: int, name: str, caption: str, x: float, y: float, w: float, h: float, ctx) -> list[Primitive]:
    """`image:<n>` in the box (less the caption band when there is a caption), and its caption below it."""
    loaded = ctx.images.get(name)
    if loaded is None:
        raise VisualDataError(f"unknown image '{name}'; registered: {', '.join(ctx.images)}")
    e = loaded.entry
    ih = h - CAPTION_BAND if caption else h
    out: list[Primitive] = [ImagePrim(f"image:{n}", x, y, w, ih, name, e.media_type,
                                      crop(e.width, e.height, w, ih, tuple(e.focus) if e.focus else None), e.alt or name)]
    if caption:
        out.append(Text(f"image:{n}:caption", x, y + ih + S16, w, S32, caption, 24, 400, fonts(ctx)[1], palette(ctx.tokens, ctx.mode)["muted"]))
    return out


def _points(points: list[str], emphasis: int | None, x: float, w: float, box, ctx) -> list[Primitive]:
    """One `two_column` column without its title and title rule, vertically centred in the body box."""
    c, (_, body, mono) = palette(ctx.tokens, ctx.mode), fonts(ctx)
    fs, num_w = size("body", ctx), 32
    text_x = x + num_w + S24
    text_w = x + w - text_x
    heights = [lines(p, fs, text_w) * fs * LEADING for p in points]
    ry = box.y + (box.h - sum(th + 2 * S24 for th in heights)) / 2
    out: list[Primitive] = []
    for n, (point, th) in enumerate(zip(points, heights, strict=True), start=1):
        out += [
            Text(f"points:num:{n}", x, ry + S24 + (fs * LEADING - S24) / 2, num_w, S24, f"{n:02d}", 20, 600, mono, c["ink"],
                 fill_under=c["panel"]),
            Text(f"points:row:{n}", text_x, ry + S24, text_w, th, point, fs, 600 if emphasis == n - 1 else 400, body, c["ink"],
                 fill_under=c["panel"]),
        ]
        ry += th + 2 * S24
        out.append(Line(f"points:rule:{n}", [(x, ry), (x + w, ry)], c["line"], 1))
    return out


def _gallery(items, box, ctx) -> list[Primitive]:
    n = len(items)
    cols, rows = (n, 1) if n <= 3 else (ceil(n / 2), 2)
    cw, ch = (box.w - GAP * (cols - 1)) / cols, (box.h - GAP * (rows - 1)) / rows
    out: list[Primitive] = []
    for k, item in enumerate(items):
        r, col = divmod(k, cols)
        in_row = min(cols, n - r * cols)
        x0 = box.x + (box.w - in_row * cw - GAP * (in_row - 1)) / 2  # a short second row is centred
        out += picture(k + 1, item.name, item.caption, x0 + col * (cw + GAP), box.y + r * (ch + GAP), cw, ch, ctx)
    return out


def render(visual, box, ctx):
    item = visual.images[0]
    if visual.variant == "hero":
        return picture(1, item.name, item.caption, box.x, box.y, box.w, box.h, ctx)
    if visual.variant == "gallery":
        return _gallery(visual.images, box, ctx)
    col_w = box.w - SPLIT_W - S64
    img_x, col_x = (box.x, box.x + SPLIT_W + S64) if visual.side == "left" else (box.x + col_w + S64, box.x)
    return [*picture(1, item.name, item.caption, img_x, box.y, SPLIT_W, box.h, ctx),
            *_points(visual.points, visual.emphasis, col_x, col_w, box, ctx)]


VISUALS["image"] = render
