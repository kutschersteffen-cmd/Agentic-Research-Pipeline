from __future__ import annotations

import pytest
from sqlalchemy import func, select

from arp.db import models as m
from arp.db.fields import (
    FieldIdCollision,
    FieldVersionError,
    SchemaRegistry,
    alias_provider_code,
    ensure_extracted_field,
    normalise_metric_code,
    register_provider_field,
    retire_field,
)
from arp.db.session import transaction
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition


def _source(s) -> int:
    src = m.DataSource(slug="msci", name="MSCI", kind=m.SourceKindDS.API, licence=m.Licence.INTERNAL_ONLY)
    s.add(src)
    s.flush()
    return src.source_id


def _reg(s, code, source_id):
    return register_provider_field(s, source_id, code, name=code, unit="tCO2e", data_type="number")


def test_normalise_metric_code():
    assert normalise_metric_code("CARBON-Emissions Scope 1") == "carbon_emissions_scope_1"


def test_register_provider_field_is_idempotent(pg):
    with transaction(pg) as s:
        sid = _source(s)
        a, b = _reg(s, "Scope-1", sid), _reg(s, "Scope-1", sid)
        assert a == b == "prov:msci:scope_1"
        assert s.scalar(select(func.count()).select_from(m.Field)) == 1


def test_code_collision_raises(pg):
    with transaction(pg) as s:
        sid = _source(s)
        _reg(s, "Scope-1", sid)
        with pytest.raises(FieldIdCollision):
            _reg(s, "scope_1", sid)


def test_renamed_code_keeps_field(pg):
    with transaction(pg) as s:
        sid = _source(s)
        fid = _reg(s, "Scope-1", sid)
        alias_provider_code(s, sid, "S1", fid)
        assert _reg(s, "S1", sid) == fid
        assert s.scalar(select(func.count()).select_from(m.Field)) == 1


def test_retired_field_id_not_reissued(pg):
    with transaction(pg) as s:
        sid = _source(s)
        fid = _reg(s, "Scope-1", sid)
        retire_field(s, fid)
        assert _reg(s, "Scope-1", sid) == fid
        assert s.scalar(select(func.count()).select_from(m.Field)) == 1
        defn = lambda f: m.FieldDefinition(field_id=f, version=1, name="n", data_type="number", definition={})  # noqa: E731
        ensure_extracted_field(s, "fld_abc123", defn("fld_abc123"))
        retire_field(s, "fld_abc123")
        with pytest.raises(ValueError, match="retired"):
            ensure_extracted_field(s, "fld_abc123", defn("fld_abc123"))


def _schema(**kw) -> DataPointSchema:
    f = FieldDefinition(
        name="capex", description="Capex.", data_type=FieldDataType.NUMBER, extraction_instructions="Find it.", seed_keywords=["capex"]
    )
    return DataPointSchema(name="S", fields=[f], **kw)


def test_schema_registry_registers_fields_and_links(pg):
    s = SchemaRegistry(pg).save(_schema())
    with transaction(pg) as t:
        assert t.get(m.FieldDefinition, (s.fields[0].field_id, 1)).name == "capex"
        link = t.scalars(select(m.DataSchemaField)).one()
        assert (link.schema_id, link.schema_version, link.field_version) == (s.schema_id, 1, 1)


def test_schema_registry_rejects_invalid_field_id(pg):
    bad = _schema()
    for fid in ("Scope 1", "fld_ab\n"):
        bad.fields[0].field_id = fid
        with pytest.raises(ValueError, match="invalid field_id"):
            SchemaRegistry(pg).save(bad)


def test_schema_registry_get_missing_raises(pg):
    with pytest.raises(KeyError):
        SchemaRegistry(pg).get("nope")
    s = SchemaRegistry(pg).save(_schema())
    with pytest.raises(KeyError):
        SchemaRegistry(pg).get(s.schema_id, 7)


def test_schema_registry_released_field_change_requires_new_version(pg):
    reg = SchemaRegistry(pg)
    s = reg.release(*(lambda x: (x.schema_id, x.version))(reg.save(_schema())))
    edited = s.model_copy(deep=True)
    edited.fields[0].description = "Changed."
    with pytest.raises(FieldVersionError):
        reg.save(edited)
    edited.fields[0].version = 2
    assert reg.save(edited).version == 2
    assert reg.get(s.schema_id, 1).fields[0].description == "Capex."
    assert reg.get(s.schema_id).release_flag is False


def test_schema_registry_save_discards_client_release_metadata(pg):
    reg = SchemaRegistry(pg)
    s = reg.save(_schema(release_flag=True, released_by="mallory", released_at="2020-01-01"))
    assert (s.release_flag, s.released_by, s.released_at) == (False, None, None)
    stored = reg.get(s.schema_id)
    assert (stored.release_flag, stored.released_by, stored.released_at) == (False, None, None)
    edited = stored.model_copy(update={"name": "S2", "released_by": "mallory"})
    v2 = reg.save(edited)
    assert v2.version == 2 and v2.released_by is None


def test_schema_registry_resave_unchanged_returns_same_version(pg):
    reg = SchemaRegistry(pg)
    s = reg.save(_schema())
    assert reg.save(s).version == 1 and len(reg.list_index()) == 1


def test_schema_registry_new_field_quality_not_audited(pg):
    q = SchemaRegistry(pg).quality("f1", 1)
    assert (q.field_id, q.version, q.first_audit_passed, q.audited_by, q.audited_at) == ("f1", 1, False, None, None)


def test_schema_registry_record_first_audit_persists(pg):
    reg = SchemaRegistry(pg)
    fid = reg.save(_schema()).fields[0].field_id
    reg.record_first_audit(fid, 1, "u1")
    q = SchemaRegistry(pg).quality(fid, 1)
    assert q.first_audit_passed is True and q.audited_by == "u1" and q.audited_at


def test_schema_registry_new_version_starts_unaudited(pg):
    reg = SchemaRegistry(pg)
    fid = reg.save(_schema()).fields[0].field_id
    reg.record_first_audit(fid, 1, "u1")
    assert reg.quality(fid, 2).first_audit_passed is False


def test_schema_registry_first_audit_unknown_field_version_refused(pg):
    reg = SchemaRegistry(pg)
    fid = reg.save(_schema()).fields[0].field_id
    for args in ((fid, 2), ("nope", 1)):
        with pytest.raises(KeyError):
            reg.record_first_audit(*args, "u1")
        assert reg.quality(*args).first_audit_passed is False


def test_draft_field_edit_updates_registered_definition(pg):
    reg = SchemaRegistry(pg)
    s = reg.save(_schema())
    edited = s.model_copy(deep=True)
    edited.fields[0].name, edited.fields[0].unit = "capex2", "USD"
    v2 = reg.save(edited)
    rel = reg.release(v2.schema_id, v2.version)
    with transaction(pg) as t:
        row = t.get(m.FieldDefinition, (rel.fields[0].field_id, 1))
        assert (row.name, row.unit) == ("capex2", "USD")
        assert row.definition["name"] == "capex2" and row.effective_from.isoformat() == rel.fields[0].effective_from


def _released_v1(reg):
    s = reg.save(_schema())
    return reg.release(s.schema_id, s.version)


def _row(pg, rel):
    with transaction(pg) as t:
        r = t.get(m.FieldDefinition, (rel.fields[0].field_id, 1))
        return r.name, r.unit, r.effective_from.isoformat(), r.released_at


def test_release_sets_released_at(pg):
    rel = _released_v1(SchemaRegistry(pg))
    assert _row(pg, rel)[3] is not None


def test_released_field_effective_from_change_requires_new_version(pg):
    reg = SchemaRegistry(pg)
    rel = _released_v1(reg)
    before = _row(pg, rel)
    edited = rel.model_copy(deep=True)
    edited.name = "S2"
    edited.fields[0].effective_from = "2001-01-01"
    with pytest.raises(FieldVersionError):
        reg.save(edited)
    assert _row(pg, rel) == before


def test_released_field_readded_with_new_content_requires_new_version(pg):
    reg = SchemaRegistry(pg)
    rel = _released_v1(reg)
    before = _row(pg, rel)
    empty = rel.model_copy(update={"fields": []})
    assert reg.save(empty).version == 2
    readd = rel.model_copy(deep=True)
    readd.fields[0].name, readd.fields[0].unit = "changed", "EUR"
    with pytest.raises(FieldVersionError):
        reg.save(readd)
    assert _row(pg, rel) == before
