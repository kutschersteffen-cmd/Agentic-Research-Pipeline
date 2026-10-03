from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from arp.schemas.common import now_iso
from arp.schemas.datapoints import DataPointSchema, FieldStatus
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.locks import KeyedLock
from arp.storage.safe_path import safe_id


class UnreleasedFieldError(ValueError):
    """A run was asked for on a schema that is not released."""


class FieldVersionError(ValueError):
    """A released field's content changed without a higher field version."""


_NOT_CONTENT = {"status", "version", "effective_from"}


def _content(schema: DataPointSchema) -> dict:
    """Everything a reader of the data could notice: the fields minus their
    lifecycle bookkeeping, plus the schema's name and description."""
    return {
        "name": schema.name,
        "description": schema.description,
        "fields": [f.model_dump(mode="json", exclude=_NOT_CONTENT) for f in schema.fields],
    }


class SchemaRegistry:
    """Versioned DataPointSchemas. Layout: `<root>/index.json` (one row per
    schema version) and `<root>/<schema_id>/v<N>.json`. A version's content
    is never rewritten; `release` only flips status flags on the same file."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = KeyedLock(lambda key: root / f".{key}.lock")

    def _path(self, schema_id: str, version: int) -> Path:
        return self.root / safe_id(schema_id, label="schema_id") / f"v{int(version)}.json"

    def _versions(self, schema_id: str) -> list[int]:
        d = self.root / safe_id(schema_id, label="schema_id")
        return sorted(int(p.stem[1:]) for p in d.glob("v*.json") if p.stem[1:].isdigit()) if d.exists() else []

    def _write(self, schema: DataPointSchema) -> None:
        atomic_write_text(self._path(schema.schema_id, schema.version), schema.model_dump_json(indent=2))
        rows = [r for r in self.list_index() if (r["schema_id"], r["version"]) != (schema.schema_id, schema.version)]
        rows.append(
            {"schema_id": schema.schema_id, "version": schema.version, "name": schema.name,
             "release_flag": schema.release_flag, "saved_at": now_iso()}
        )
        atomic_write_text(self.root / "index.json", json.dumps(rows, indent=2))

    def get(self, schema_id: str, version: int | None = None) -> DataPointSchema:
        if version is None:
            versions = self._versions(schema_id)
            if not versions:
                raise KeyError(schema_id)
            version = versions[-1]
        path = self._path(schema_id, version)
        if not path.exists():
            raise KeyError(f"{schema_id} v{version}")
        return DataPointSchema.model_validate_json(read_text_utf8(path))

    def list_index(self) -> list[dict]:
        path = self.root / "index.json"
        return json.loads(read_text_utf8(path)) if path.exists() else []

    def save(self, schema: DataPointSchema) -> DataPointSchema:
        with self._lock.acquire("registry"):
            versions = self._versions(schema.schema_id)
            if not versions:
                first = schema.model_copy(update={"version": 1, "release_flag": False})
                self._write(first)
                return first
            latest = self.get(schema.schema_id, versions[-1])
            old = {f.field_id: f for f in latest.fields}
            for f in schema.fields:
                prev = old.get(f.field_id)
                if (
                    prev is not None and prev.status == FieldStatus.RELEASED
                    and prev.model_dump(exclude=_NOT_CONTENT) != f.model_dump(exclude=_NOT_CONTENT)
                    and f.version <= prev.version
                ):
                    raise FieldVersionError(
                        f"Field {f.field_id} ({f.name}) is released at v{prev.version}; "
                        f"changing it needs version > {prev.version}."
                    )
            if _content(schema) == _content(latest):
                return latest
            new = schema.model_copy(update={"version": latest.version + 1, "release_flag": False})
            self._write(new)
            return new

    def release(self, schema_id: str, version: int) -> DataPointSchema:
        with self._lock.acquire("registry"):
            schema = self.get(schema_id, version)
            today = date.today().isoformat()
            fields = [
                f.model_copy(update={"status": FieldStatus.RELEASED, "effective_from": f.effective_from or today})
                if f.status == FieldStatus.DRAFT else f
                for f in schema.fields
            ]
            released = schema.model_copy(update={"fields": fields, "release_flag": True})
            self._write(released)
            return released
