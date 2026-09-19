"""The one write-then-rename helper every file-based store uses.

`RunStore.save_manifest`, `EngagementStore._save` and
`ReportingStore._atomic_write` each grew their own copy of this; they now
all call here, and `PortfolioStore`/`TaxonomyStore` -- which previously
used a bare `path.write_text` -- do too.

Why it matters beyond crash-safety: `Path.write_text` truncates the file
before writing it, so a concurrent reader can observe zero bytes or a
partial document and fail to parse a file that is perfectly valid before
and after the write. `os.replace` is atomic on POSIX, so a reader sees
either the old file in full or the new one in full.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, prefix: str = ".tmp_") -> None:
    """Writes `text` to `path` via a temp file in the same directory plus
    `os.replace`. The temp file must share the destination's directory:
    `os.replace` is only atomic within one filesystem, and /tmp is
    routinely a different one. Cleans the temp file up on any exception
    (`BaseException`, so a KeyboardInterrupt mid-write doesn't leak one)
    rather than leaving a stray `.tmp_*` behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, text: str) -> None:
    """Writes `text` to `path` only if `path` does not exist yet, raising
    `FileExistsError` if it does -- for a file whose whole contract is
    that it's written once (a taxonomy version record). Deliberately not
    atomic-then-rename: `os.replace` would happily clobber the existing
    file, which is precisely the outcome this guards against. A reader
    can in principle catch a partial file here, but only in the window
    before the first successful write of a path that never existed
    before, where there is nothing valid to observe anyway.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        f.write(text)
