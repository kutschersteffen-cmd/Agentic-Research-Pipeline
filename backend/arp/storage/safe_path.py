from __future__ import annotations

import re
from pathlib import Path

# Every file-based store in this app builds paths as
# `some_dir / <client-supplied id> / ...`. An id that contains "/", "\",
# or ".." segments escapes the intended directory once joined with Path's
# "/" operator (which also happily discards everything to its left if the
# right-hand side is absolute). safe_id() is the one place every such id
# -- company_id, run_id, portfolio_id, field_id, taxonomy_id, as_of_date,
# analytic_id, ... -- must pass through before it touches a Path.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UnsafeIdentifierError(ValueError):
    pass


def safe_id(value: str, *, label: str = "id") -> str:
    """Validates an identifier destined to become a filesystem path
    segment. Accepts only a bounded run of alphanumerics/dot/underscore/
    hyphen starting with an alphanumeric -- which rejects a leading ".."
    or ".", any "/" or "\\", and absolute-path-like values, before the
    value ever reaches Path.__truediv__."""
    if not isinstance(value, str) or not _SAFE_ID_RE.match(value):
        raise UnsafeIdentifierError(f"Invalid {label}: {value!r}")
    return value


def safe_filename(filename: str | None, *, label: str = "filename") -> str:
    """Validates a client-supplied filename (e.g. an upload's original
    name) has no directory component -- rejects anything where
    Path(filename).name != filename, which covers "../..", absolute
    paths, and embedded "/" separators."""
    if not filename or Path(filename).name != filename or filename in (".", ".."):
        raise UnsafeIdentifierError(f"Invalid {label}: {filename!r}")
    return filename
