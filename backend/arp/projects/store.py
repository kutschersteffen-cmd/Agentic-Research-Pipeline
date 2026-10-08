"""File-based project store: projects/<id>/{project.json,data/,dashboards/}."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from arp.schemas.common import now_iso
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.locks import KeyedLock
from arp.storage.safe_path import UnsafeIdentifierError, safe_filename

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Dashboard slugs: `arp-<project id>--<title part>`, up to 123 chars (Superset allows 255).
DASHBOARD_SLUG_RE = re.compile(r"^arp-[a-z0-9][a-z0-9-]{0,118}$")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class ProjectError(ValueError):
    pass


class ProjectNotFound(ProjectError):
    pass


class ForeignProjectDashboard(ProjectError):
    pass


class DataSource(BaseModel):
    kind: Literal["dws-constituents"]
    files: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class StoredDashboard(BaseModel):
    slug: str
    title: str
    source: Literal["template", "superset-export"]
    file: str


class Project(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: str
    data: list[DataSource] = Field(default_factory=list)
    dashboards: list[StoredDashboard] = Field(default_factory=list)


def _check_id(value: str, label: str = "project id") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ProjectError(f"Invalid {label}: {value!r}")
    return value


def _check_filename(name: str) -> str:
    try:
        if "\0" in name:
            raise UnsafeIdentifierError("NUL in filename")
        return safe_filename(name)
    except (UnsafeIdentifierError, OSError, TypeError) as e:
        raise ProjectError(str(e)) from e


class ProjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._locks = KeyedLock(lock_path=lambda pid: self.root / pid / ".lock")

    def lock(self, id: str):
        self.get(id)  # no stray directory for a nonexistent project
        return self._lock(id)

    def _create_lock(self, id: str):
        return self._lock(_check_id(id))

    @contextmanager
    def _lock(self, id: str) -> Iterator[None]:
        with self._locks.acquire(id):
            yield

    def _manifest(self, id: str) -> Path:
        return self.root / _check_id(id) / "project.json"

    def _save(self, p: Project) -> None:
        atomic_write_text(self._manifest(p.id), p.model_dump_json(indent=2))

    def create(self, id: str, name: str, description: str = "") -> Project:
        with self._create_lock(id):
            if self._manifest(id).exists():
                raise ProjectError(f"Project already exists: {id}")
            p = Project(
                id=id, name=name, description=description,
                created_at=now_iso(),
            )
            self._save(p)
            return p

    def get(self, id: str) -> Project:
        try:
            path = self._manifest(id)
        except ProjectError as e:
            raise ProjectNotFound(str(e)) from e
        if not path.exists():
            raise ProjectNotFound(f"Project not found: {id}")
        return Project.model_validate_json(read_text_utf8(path))

    def list(self) -> list[Project]:
        if not self.root.exists():
            return []
        return [
            self.get(d.name)
            for d in sorted(self.root.iterdir())
            if d.is_dir() and ID_RE.fullmatch(d.name) and (d / "project.json").exists()
        ]

    def file_path(self, id: str, kind_dir: Literal["data", "dashboards"], name: str) -> Path:
        if kind_dir not in ("data", "dashboards"):
            raise ProjectError(f"Invalid directory: {kind_dir!r}")
        name = _check_filename(name)
        if kind_dir == "dashboards" and not DASHBOARD_SLUG_RE.fullmatch(name.rsplit(".", 1)[0]):
            raise ProjectError(f"Invalid dashboard file name: {name!r}")
        return self.root / _check_id(id) / kind_dir / name

    def add_data_file(self, id: str, filename: str, content: bytes, params: dict) -> Project:
        # Validate everything before any write so a rejected upload leaves nothing.
        name = _check_filename(filename)
        if not name.lower().endswith(".xlsx"):
            raise ProjectError("Only .xlsx uploads are accepted")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ProjectError("Upload exceeds 50 MB limit")
        with self.lock(id):
            p = self.get(id)
            target = self.file_path(id, "data", name)
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes(target, content)
            src = next((s for s in p.data if s.kind == "dws-constituents"), None)
            if src is None:
                src = DataSource(kind="dws-constituents")
                p.data.append(src)
            if name not in src.files:
                src.files.append(name)
            src.params.update(params)
            self._save(p)
            return p

    def save_dashboard(
        self, id: str, slug: str, title: str,
        source: Literal["template", "superset-export"], payload: bytes,
    ) -> Project:
        if not isinstance(slug, str) or not DASHBOARD_SLUG_RE.fullmatch(slug):
            raise ProjectError(f"Invalid dashboard slug: {slug!r}")
        with self.lock(id):
            p = self.get(id)
            fname = f"{slug}.{'zip' if source == 'superset-export' else 'json'}"
            target = self.file_path(id, "dashboards", fname)
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes(target, payload)
            entry = StoredDashboard(slug=slug, title=title, source=source, file=fname)
            for d in p.dashboards:
                if d.slug == slug and d.file != fname:
                    self.file_path(id, "dashboards", d.file).unlink(missing_ok=True)
            p.dashboards = [d for d in p.dashboards if d.slug != slug] + [entry]
            self._save(p)
            return p


def _write_bytes(path: Path, content: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
