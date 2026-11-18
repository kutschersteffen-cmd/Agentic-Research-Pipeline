"""Checks for images registered with a house-deck report (spec house-deck-image-slides).

Every message here is part of the spec: the CLI, the API and the store all raise these.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from math import isfinite

from PIL import Image, ImageOps, UnidentifiedImageError

from arp.schemas.reporting import ReportImage

MAX_IMAGES = 20
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 50_000_000
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_FORMATS = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg")}


class ImageError(ValueError):
    """A registered image or image flag failed a check; the message is the spec's."""


class ImageTooLarge(ImageError):
    """The file is over 20 MB (the API answers 413, not 400)."""


@dataclass(frozen=True)
class DecodedImage:
    data: bytes  # the bytes to store: the file as given, or re-encoded upright
    media_type: str
    ext: str
    width: int
    height: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class LoadedImage:
    entry: ReportImage
    data: bytes


def check_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ImageError(f"image name '{name}' must be 1-32 characters: a-z, 0-9, _ or -, starting with a letter or digit")


def check_focus(name: str, focus) -> list[float] | None:
    if focus is None:
        return None
    ok = isinstance(focus, list | tuple) and len(focus) == 2 and all(
        isinstance(v, int | float) and not isinstance(v, bool) and isfinite(v) and 0 <= v <= 1 for v in focus
    )
    if not ok:
        raise ImageError(f"focus for '{name}' must be two numbers from 0 to 1, like 0.5,0.3")
    return [float(v) for v in focus]


def parse_focus(name: str, text: str) -> list[float]:
    """`X,Y` from the CLI."""
    try:
        values = [float(v) for v in text.split(",")]
    except ValueError:
        values = []  # malformed: check_focus rejects it with the same message
    return check_focus(name, values)


def check_unique_and_count(names: list[str]) -> None:
    seen: set[str] = set()
    for n in names:
        if n in seen:
            raise ImageError(f"image name '{n}' is registered twice")
        seen.add(n)
    if len(names) > MAX_IMAGES:
        raise ImageError(f"at most {MAX_IMAGES} images per report")


def check_known(name: str, names: list[str]) -> None:
    if name not in names:
        raise ImageError(f"no image named '{name}'; registered: {', '.join(names)}")


def decode_image(data: bytes, label: str) -> DecodedImage:
    """Size, format and pixel checks, in the spec's order. A JPEG with an EXIF rotation is re-encoded upright."""
    if len(data) > MAX_BYTES:
        raise ImageTooLarge(f"image '{label}' is larger than 20 MB")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in _FORMATS:
                raise ImageError(f"image '{label}' is not a PNG or JPEG image")
            fmt = im.format
            if im.width * im.height > MAX_PIXELS:
                raise ImageError(f"image '{label}' has more than 50 megapixels")
            im.load()
            orientation = im.getexif().get(0x0112, 1) if fmt == "JPEG" else 1
            if orientation not in (1, None):
                upright = ImageOps.exif_transpose(im)
                buf = io.BytesIO()
                upright.save(buf, "JPEG", quality=95)
                data = buf.getvalue()
                width, height = upright.size
            else:
                width, height = im.size
    except ImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageError(f"image '{label}' has more than 50 megapixels") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:  # truncated or not an image at all
        raise ImageError(f"image '{label}' is not a PNG or JPEG image") from exc
    media_type, ext = _FORMATS[fmt]
    return DecodedImage(data=data, media_type=media_type, ext=ext, width=width, height=height)
