"""Version guard for the normalisation tables: a table's bytes may only change with a new version file."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

TABLES = Path(__file__).parent / "tables"


def table_versions() -> dict[str, dict]:
    return json.loads((TABLES / "manifest.json").read_text(encoding="utf8"))


def check_manifest(tables_dir: Path, manifest: dict) -> list[str]:
    """Problems found, one string per table: missing file, version not matching the filename, changed bytes."""
    problems = []
    for name, entry in manifest.items():
        path = tables_dir / f"{name}.csv"
        if not path.exists():
            problems.append(f"{name}: {path.name} missing")
            continue
        m = re.fullmatch(r".+_v(\d+)", name)
        if not m or int(m[1]) != entry["version"]:
            problems.append(f"{name}: version {entry['version']} does not match the table name")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            problems.append(f"{name}: contents changed without a new version (add {name.rsplit('_v', 1)[0]}_v<next>.csv)")
    return problems
