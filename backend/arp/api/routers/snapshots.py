"""Read-only monthly snapshots for other ARP applications (E77). Only frozen revisions are served."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from arp.api.auth import Principal, require_grant
from arp.api.deps import settings_dep
from arp.config import Settings
from arp.snapshots import schema
from arp.snapshots.build import dataset_path, list_months, read_manifest
from arp.snapshots.schema import SnapshotManifest

_reader = require_grant("snapshot_reader")
router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"], dependencies=[Depends(_reader)])
MEDIA = {"csv": "text/csv", "jsonl": "application/x-ndjson"}


def _root(settings: Settings = Depends(settings_dep)) -> Path:
    return settings.snapshot_store_dir


def _manifest(root: Path, month: str, revision: int | None) -> SnapshotManifest:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, f"bad month {month!r}; expected YYYY-MM")
    try:
        manifest = read_manifest(root, month, revision)  # None for a missing or unfrozen revision
    except ValueError as exc:  # month 13, say
        raise HTTPException(400, str(exc)) from None
    if manifest is None:
        raise HTTPException(404, f"no snapshot for {month}" + (f" r{revision}" if revision else ""))
    return manifest


@router.get("")
def months(root: Path = Depends(_root)) -> dict:
    out = []
    for m in list_months(root):
        if manifest := read_manifest(root, m["month"]):
            out.append({"month": manifest.month, "latest_revision": manifest.revision,
                        "snapshot_id": manifest.snapshot_id})
    return {"months": out}


@router.get("/latest")
def latest(root: Path = Depends(_root)) -> SnapshotManifest:
    for m in reversed(list_months(root)):
        if manifest := read_manifest(root, m["month"]):
            return manifest
    raise HTTPException(404, "no snapshot yet")


@router.get("/{month}/manifest")
def manifest(month: str, revision: int | None = Query(None, ge=1), root: Path = Depends(_root)) -> SnapshotManifest:
    return _manifest(root, month, revision)


@router.get("/{month}/{dataset}")
def dataset(
    month: str,
    dataset: str,
    fmt: Literal["csv", "jsonl"] = Query("csv", alias="format"),
    revision: int | None = Query(None, ge=1),
    major: int | None = None,
    root: Path = Depends(_root),
    user: Principal = Depends(_reader),
) -> FileResponse:
    if dataset == "portfolio_holdings" and "holdings_reader" not in user.roles:
        raise HTTPException(403, "Requires role 'holdings_reader'")
    m = _manifest(root, month, revision)
    major = schema.CURRENT_MAJOR if major is None else major
    entry = next((d for d in m.datasets if d.name == dataset and d.major == major), None)
    if entry is None:
        raise HTTPException(404, f"{m.snapshot_id} has no {dataset} v{major}")
    path = dataset_path(root, m.month, m.revision, entry.name, fmt, major)
    sha = entry.files.get(fmt)
    if sha is None or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(404, f"{m.snapshot_id} has no {dataset} v{major} {fmt} file")
    # The manifest's hash, not the served bytes': a file changed on disk then fails the client's check.
    return FileResponse(path, media_type=MEDIA[fmt], headers={"ETag": f'"{sha}"'})
