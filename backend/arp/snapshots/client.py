"""Pulls monthly snapshots from another ARP instance's `/api/v1/snapshots` and checks every file's sha256
against the manifest before writing it (E77)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import httpx

from arp.snapshots.build import FORMATS
from arp.snapshots.schema import CURRENT_MAJOR, DATASETS, DatasetEntry, SnapshotManifest
from arp.storage.atomic_io import atomic_write_bytes


class SnapshotHashMismatch(RuntimeError):
    """A pulled file's sha256 differs from the manifest's."""


class SnapshotClient:
    def __init__(self, base_url: str, token: str | None, *, http: httpx.Client | None = None) -> None:
        self.base = base_url.rstrip("/") + "/api/v1/snapshots"
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = http or httpx.Client(timeout=60)

    def _get(self, path: str, **params) -> httpx.Response:
        r = self.http.get(self.base + path, params={k: v for k, v in params.items() if v is not None},
                          headers=self.headers)
        r.raise_for_status()
        return r

    def manifest(self, month: str | None = None) -> SnapshotManifest:
        return SnapshotManifest.model_validate(self._get(f"/{_month(month)}/manifest" if month else "/latest").json())

    def _fetch(self, m: SnapshotManifest, entry: DatasetEntry, fmt: str) -> bytes:
        data = self._get(f"/{m.month}/{entry.name}", format=fmt, revision=m.revision, major=entry.major).content
        if hashlib.sha256(data).hexdigest() != entry.files[fmt]:
            raise SnapshotHashMismatch(f"{entry.name}: hash differs from the manifest")
        return data

    def _entries(self, m: SnapshotManifest, names: list[str], major: int) -> list[DatasetEntry]:
        by_name = {d.name: d for d in m.datasets if d.major == major and d.name in DATASETS}
        missing = [n for n in names if n not in by_name]
        if missing:
            raise ValueError(f"{m.snapshot_id} has no v{major} {missing}")
        return [by_name[n] for n in names]

    def pull(self, month: str, datasets: list[str] | Literal["all"], dest: Path, *, fmt: str = "csv",
             major: int = CURRENT_MAJOR) -> list[Path]:
        """Fetches and verifies every file first, then writes them, so a mismatch writes nothing."""
        if fmt not in FORMATS:
            raise ValueError(f"bad format {fmt!r}")
        m = self.manifest(month)
        if m.month != month:
            raise ValueError(f"asked for {month}, got {m.snapshot_id}")
        entries = self._entries(m, list(DATASETS) if datasets == "all" else list(datasets), major)
        blobs = [(e, self._fetch(m, e, fmt)) for e in entries]
        out = Path(dest) / month  # month checked by _month, names by DATASETS, major is an int
        paths = []
        for e, data in blobs:
            path = out / f"{e.name}.v{int(major)}.{fmt}"
            atomic_write_bytes(path, data)
            paths.append(path)
        atomic_write_bytes(out / "manifest.json", m.model_dump_json(indent=2).encode())
        return paths

    def rows(self, month: str, dataset: str, *, major: int = CURRENT_MAJOR) -> tuple[SnapshotManifest, list[dict]]:
        m = self.manifest(month)
        data = self._fetch(m, self._entries(m, [dataset], major)[0], "jsonl")
        return m, [json.loads(line) for line in data.decode().splitlines()]


def _month(month: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError(f"bad month {month!r}; expected YYYY-MM")
    return month
