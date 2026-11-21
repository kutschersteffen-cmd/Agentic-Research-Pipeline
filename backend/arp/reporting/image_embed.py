"""The bytes both writers embed for a registered image: the stored file, or a copy scaled to a 3840 px long edge.
Spec: docs/superpowers/specs/2026-11-18-house-deck-image-slides.md, "Downscale"."""

from __future__ import annotations

import io
from functools import lru_cache

from PIL import Image

MAX_EDGE = 3840


@lru_cache(maxsize=32)
def embedded(data: bytes) -> bytes:
    """Same format; JPEG at quality 90. Cached, so every use of an image embeds the same bytes (one PPTX media part)."""
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        if max(w, h) <= MAX_EDGE:
            return data
        fmt = im.format
        k = MAX_EDGE / max(w, h)
        small = im.resize((round(w * k), round(h * k)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, fmt, **({"quality": 90} if fmt == "JPEG" else {}))
    return buf.getvalue()


PREVIEW_EDGE = 768


def preview(data: bytes) -> bytes:
    """The PNG the fill call shows the model: long edge 768 px, never upscaled (spec "Model calls")."""
    with Image.open(io.BytesIO(data)) as im:
        k = min(1, PREVIEW_EDGE / max(im.size))
        small = im.resize((round(im.width * k), round(im.height * k)), Image.Resampling.LANCZOS) if k < 1 else im.copy()
    if small.mode not in ("RGB", "RGBA", "L", "LA", "P"):  # e.g. a CMYK JPEG, which PNG can't hold
        small = small.convert("RGB")
    buf = io.BytesIO()
    small.save(buf, "PNG")
    return buf.getvalue()
