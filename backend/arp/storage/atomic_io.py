"""The write-then-rename and read helpers every file-based store uses.

`RunStore.save_manifest`, `EngagementStore._save` and
`ReportingStore._atomic_write` each grew their own copy of the writer;
they now all call here, and `PortfolioStore`/`TaxonomyStore` -- which
previously used a bare `path.write_text` -- do too.

Why it matters beyond crash-safety: `Path.write_text` truncates the file
before writing it, so a concurrent reader can observe zero bytes or a
partial document and fail to parse a file that is perfectly valid before
and after the write. `os.replace` is atomic on POSIX, so a reader sees
either the old file in full or the new one in full.

**Every function here names its encoding explicitly, and the readers are
here for the same reason the writer is.** A bare `Path.read_text()` /
`open()` resolves to `locale.getpreferredencoding()`, which is UTF-8 on
Linux and macOS but cp1252 on a Western-European Windows install. Pairing
these UTF-8 writers with a locale-default reader is worse than having
neither: the write succeeds, and the read then either yields mojibake
(`Münchener Rück` -> `MÃ¼nchener RÃ¼ck`, no exception raised) or dies on
a byte cp1252 has no mapping for. Store readers therefore go through
`read_text_utf8` rather than calling `read_text()` themselves -- see
tests/test_file_store_encoding.py.

`PYTHONUTF8=1` (set in backend/Dockerfile and .vscode/settings.json)
fixes the same class of bug for the CLI and ingestion paths that still
use plain `open()`. These helpers do not depend on it being set.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _atomic_write(path: Path, data: str | bytes, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w" if isinstance(data, str) else "wb", **({"encoding": "utf-8"} if isinstance(data, str) else {})) as f:
            f.write(data)
        os.replace(tmp_path, path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str, *, prefix: str = ".tmp_") -> None:
    """Writes `text` to `path` via a temp file in the same directory plus
    `os.replace`. The temp file must share the destination's directory:
    `os.replace` is only atomic within one filesystem, and /tmp is
    routinely a different one. Cleans the temp file up on any exception
    (`BaseException`, so a KeyboardInterrupt mid-write doesn't leak one)
    rather than leaving a stray `.tmp_*` behind.
    """
    _atomic_write(path, text, prefix)


def atomic_write_bytes(path: Path, data: bytes, *, prefix: str = ".tmp_") -> None:
    """`atomic_write_text` for raw bytes (stored source documents)."""
    _atomic_write(path, data, prefix)


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
    with path.open("x", encoding="utf-8") as f:
        f.write(text)


def read_text_utf8(path: Path) -> str:
    """Reads a file this module wrote. The counterpart to
    `atomic_write_text`/`write_text_exclusive`, and the reason it exists
    rather than callers passing `encoding="utf-8"` at each of ~30 read
    sites: the encoding has to match the writer's, so it belongs next to
    the writer where the two cannot drift apart again.
    """
    return path.read_text(encoding="utf-8")
