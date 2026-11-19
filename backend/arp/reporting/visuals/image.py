"""`image`: registered pictures cropped to their slots. This slice draws the `hero` variant.
Spec: docs/superpowers/specs/2026-11-18-house-deck-image-slides.md, "Geometry" and "Crop"."""

from arp.reporting.render_model import S16, S32, S48, VISUALS, ImagePrim, Primitive, Text, VisualDataError, crop, palette
from arp.reporting.visuals._common import fonts

CAPTION_BAND = S48  # a captioned image is this much shorter; its caption sits 16 px below it, 32 px tall


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


def render(visual, box, ctx):
    if visual.variant != "hero":
        raise VisualDataError(f"the {visual.variant} image variant is not drawn yet")
    item = visual.images[0]
    return picture(1, item.name, item.caption, box.x, box.y, box.w, box.h, ctx)


VISUALS["image"] = render
