"""Field registry (spec §2.2) and the table-backed SchemaRegistry.

Every stored value points at a `field_id`; ids are never reissued, so a retired field keeps its id."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from arp.db import models as m
from arp.db.session import transaction
from arp.schemas.common import now_iso
from arp.schemas.datapoints import DataPointSchema, FieldQuality, FieldStatus

_EXTRACTED_ID = re.compile(r"[a-z][a-z0-9_]*|theme:[^:\s]+|vote:[^:\s]+:[^:\s]+")
_REGISTRY_LOCK = 7243001  # pg_advisory_xact_lock key serialising schema saves/releases


class FieldIdCollision(ValueError):
    """Two different provider codes normalise to the same field_id."""


class UnreleasedFieldError(ValueError):
    """A run was asked for on a schema that is not released."""


class FieldVersionError(ValueError):
    """A released field's content changed without a higher field version."""


def normalise_metric_code(code: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", code.lower()).strip("_")


def provider_field_id(source_slug: str, code: str) -> str:
    return f"prov:{source_slug}:{normalise_metric_code(code)}"


def register_provider_field(
    session: Session, source_id: int, provider_code: str, *, name: str, unit: str | None, data_type: str
) -> str:
    code = session.scalar(
        select(m.ProviderMetricCode).where(
            m.ProviderMetricCode.source_id == source_id, m.ProviderMetricCode.provider_code == provider_code
        )
    )
    if code:  # also when the field is retired: ids are never reissued
        return code.field_id
    field_id = provider_field_id(session.get(m.DataSource, source_id).slug, provider_code)
    if session.get(m.Field, field_id):
        owner = session.scalar(select(m.ProviderMetricCode).where(m.ProviderMetricCode.field_id == field_id))
        raise FieldIdCollision(f"{provider_code!r} normalises to {field_id!r}, owned by {owner.provider_code!r}" if owner else field_id)
    session.add(m.Field(field_id=field_id, kind=m.FieldKind.PROVIDER, source_id=source_id))
    session.flush()
    session.add(m.FieldDefinition(
        field_id=field_id, version=1, name=name, data_type=data_type, unit=unit, definition={"provider_code": provider_code}
    ))
    session.add(m.ProviderMetricCode(source_id=source_id, provider_code=provider_code, field_id=field_id))
    session.flush()
    return field_id


def alias_provider_code(session: Session, source_id: int, new_code: str, field_id: str) -> None:
    have = session.scalar(
        select(m.ProviderMetricCode).where(
            m.ProviderMetricCode.source_id == source_id, m.ProviderMetricCode.provider_code == new_code
        )
    )
    if have and have.field_id != field_id:
        raise ValueError(f"{new_code!r} already maps to {have.field_id!r}")
    if not have:
        session.add(m.ProviderMetricCode(source_id=source_id, provider_code=new_code, field_id=field_id))
        session.flush()


def ensure_extracted_field(session: Session, field_id: str, definition: m.FieldDefinition) -> None:
    """Inserts the `Field` and this definition version if missing; a version that exists is left as is."""
    field = session.get(m.Field, field_id)
    if field is None:
        if not _EXTRACTED_ID.fullmatch(field_id):
            raise ValueError(f"invalid field_id {field_id!r}")
        session.add(m.Field(field_id=field_id, kind=m.FieldKind.EXTRACTED))
        session.flush()
    elif field.retired_at is not None:
        raise ValueError(f"field {field_id!r} is retired")
    elif field.kind != m.FieldKind.EXTRACTED:
        raise ValueError(f"field {field_id!r} is not an extracted field")
    if session.get(m.FieldDefinition, (field_id, definition.version)) is None:
        definition.field_id = field_id
        session.add(definition)
        session.flush()


def retire_field(session: Session, field_id: str) -> None:
    field = session.get(m.Field, field_id)
    if field is None:
        raise KeyError(field_id)
    if field.retired_at is None:
        field.retired_at = datetime.now(UTC)


_UNRELEASED = {"release_flag": False, "released_by": None, "released_at": None}
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
    """Versioned DataPointSchemas in `data_schemas` (full dump in `body`), their fields registered in
    `fields`/`field_definitions`. A version's content is never rewritten; `release` only flips status flags."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def _row(self, s: Session, schema_id: str, version: int | None) -> m.DataSchema:
        if version is None:
            row = s.scalar(
                select(m.DataSchema).where(m.DataSchema.schema_id == schema_id).order_by(m.DataSchema.version.desc()).limit(1)
            )
            if row is None:
                raise KeyError(schema_id)
            return row
        row = s.get(m.DataSchema, (schema_id, int(version)))
        if row is None:
            raise KeyError(f"{schema_id} v{version}")
        return row

    @staticmethod
    def _write(s: Session, schema: DataPointSchema) -> None:
        row = s.get(m.DataSchema, (schema.schema_id, schema.version))
        if row is None:
            row = m.DataSchema(schema_id=schema.schema_id, version=schema.version)
            s.add(row)
        row.name, row.release_flag, row.body = schema.name, schema.release_flag, schema.model_dump(mode="json")
        row.saved_at = datetime.now(UTC)
        row.released_by = schema.released_by
        row.released_at = datetime.now(UTC) if schema.released_at else None
        s.flush()
        for f in schema.fields:
            fd = m.FieldDefinition(
                field_id=f.field_id, version=f.version, name=f.name, data_type=str(f.data_type.value),
                unit=f.unit, definition=f.model_dump(mode="json"),
            )
            ensure_extracted_field(s, f.field_id, fd)
            # A draft's content may change without a version bump; a released version cannot (FieldVersionError).
            cur = s.get(m.FieldDefinition, (f.field_id, f.version))
            cur.name, cur.data_type, cur.unit, cur.definition = fd.name, fd.data_type, fd.unit, fd.definition
            if f.effective_from:
                cur.effective_from = date.fromisoformat(f.effective_from)
            if s.scalar(select(func.count()).select_from(m.DataSchemaField).where(
                m.DataSchemaField.schema_id == schema.schema_id, m.DataSchemaField.schema_version == schema.version,
                m.DataSchemaField.field_id == f.field_id,
            )) == 0:
                s.add(m.DataSchemaField(
                    schema_id=schema.schema_id, schema_version=schema.version, field_id=f.field_id, field_version=f.version
                ))
        s.flush()

    def get(self, schema_id: str, version: int | None = None) -> DataPointSchema:
        with transaction(self.dsn) as s:
            return DataPointSchema.model_validate(self._row(s, schema_id, version).body)

    def list_index(self) -> list[dict]:
        with transaction(self.dsn) as s:
            rows = s.scalars(select(m.DataSchema).where(m.DataSchema.body.is_not(None)).order_by(m.DataSchema.saved_at)).all()
            return [
                {"schema_id": r.schema_id, "version": r.version, "name": r.name,
                 "release_flag": r.release_flag, "saved_at": r.saved_at.isoformat()}
                for r in rows
            ]

    def save(self, schema: DataPointSchema) -> DataPointSchema:
        """Registers `schema` as a new version (or returns the latest when
        nothing changed). Release metadata (release_flag, released_by,
        released_at) from the caller is always discarded; only `release`
        sets it. A field `status` sent by the caller is stored as-is: the
        run gate also needs the schema's release_flag, which a save can
        never set, so a client-claimed "released" field opens nothing.
        """
        with transaction(self.dsn) as s:
            s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _REGISTRY_LOCK})
            try:
                latest = DataPointSchema.model_validate(self._row(s, schema.schema_id, None).body)
            except KeyError:
                first = schema.model_copy(update={"version": 1, **_UNRELEASED})
                self._write(s, first)
                return first
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
            new = schema.model_copy(update={"version": latest.version + 1, **_UNRELEASED})
            self._write(s, new)
            return new

    def release(self, schema_id: str, version: int, released_by: str | None = None) -> DataPointSchema:
        with transaction(self.dsn) as s:
            s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _REGISTRY_LOCK})
            schema = DataPointSchema.model_validate(self._row(s, schema_id, version).body)
            today = date.today().isoformat()
            fields = [
                f.model_copy(update={"status": FieldStatus.RELEASED, "effective_from": f.effective_from or today})
                if f.status == FieldStatus.DRAFT else f
                for f in schema.fields
            ]
            released = schema.model_copy(
                update={"fields": fields, "release_flag": True, "released_by": released_by, "released_at": now_iso()}
            )
            self._write(s, released)
            return released

    def quality(self, field_id: str, version: int) -> FieldQuality:
        with transaction(self.dsn) as s:
            row = s.get(m.FieldDefinition, (field_id, int(version)))
            if row is not None and row.quality:
                return FieldQuality.model_validate(row.quality)
        return FieldQuality(field_id=field_id, version=int(version))

    def record_first_audit(self, field_id: str, version: int, audited_by: str) -> FieldQuality:
        with transaction(self.dsn) as s:
            # Drafts are auditable (trial runs), but an unregistered field version is not.
            row = s.get(m.FieldDefinition, (field_id, int(version)), with_for_update=True)
            if row is None:
                raise KeyError(f"{field_id} v{version}")
            q = FieldQuality(
                field_id=field_id, version=int(version), first_audit_passed=True,
                audited_by=audited_by, audited_at=now_iso(),
            )
            row.quality = q.model_dump(mode="json")
            return q
