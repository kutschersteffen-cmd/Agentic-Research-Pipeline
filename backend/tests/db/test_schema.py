from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DataError, IntegrityError, StatementError

from arp.db import models as m
from arp.db.session import engine, transaction

TABLES = {
    "companies", "company_identifiers", "fields", "field_definitions", "data_schemas", "data_schema_fields",
    "provider_metric_codes", "runs", "run_companies", "run_results", "run_errors", "run_held_documents",
    "documents", "data_sources", "source_loads", "field_observations", "value_citations", "review_items",
    "review_decisions", "review_cosigns", "company_facts",
}


def test_tables_exist(pg):
    assert TABLES <= set(inspect(engine(pg)).get_table_names())


def _fact_setup(session):
    c = m.Company(name="Acme")
    session.add_all([c, m.Field(field_id="fld_ab12", kind=m.FieldKind.EXTRACTED)])
    session.flush()
    session.add(m.FieldDefinition(field_id="fld_ab12", version=1, name="n", data_type="number", definition={}))
    session.flush()
    obs = m.FieldObservation(
        company_id=c.id, field_id="fld_ab12", field_version=1, source_kind=m.SourceKind.MANUAL, value=1,
        value_state=m.ValueState.FOUND,
    )
    session.add(obs)
    session.flush()
    return c.id, obs.id


def _fact(cid, oid, valid_to=None):
    return m.CompanyFact(
        company_id=cid, field_id="fld_ab12", period_end=date(2025, 12, 31), value=1, status=m.FactStatus.APPROVED,
        observation_id=oid, valid_to=valid_to,
    )


def test_second_current_fact_is_rejected(pg):
    with pytest.raises(IntegrityError), transaction(pg) as s:
        cid, oid = _fact_setup(s)
        s.add_all([_fact(cid, oid), _fact(cid, oid)])


def test_closed_fact_allows_new_current(pg):
    with transaction(pg) as s:
        cid, oid = _fact_setup(s)
        s.add_all([_fact(cid, oid, valid_to=datetime.now(UTC)), _fact(cid, oid)])


def test_bad_field_id_rejected(pg):
    with pytest.raises(IntegrityError), transaction(pg) as s:
        s.add(m.Field(field_id="Scope 1", kind=m.FieldKind.EXTRACTED))
    with transaction(pg) as s:
        s.add_all([
            m.Field(field_id="fld_ab12", kind=m.FieldKind.EXTRACTED),
            m.Field(field_id="prov:msci:carbon_emissions_scope_1", kind=m.FieldKind.PROVIDER),
        ])


def test_active_alias_unique(pg):
    with transaction(pg) as s:
        c = m.Company(name="A")
        s.add(c)
        s.flush()
        cid = c.id
        s.add(m.CompanyIdentifier(company_id=cid, scheme=m.IdScheme.LEI, value="X"))
    with pytest.raises(IntegrityError), transaction(pg) as s:
        s.add(m.CompanyIdentifier(company_id=cid, scheme=m.IdScheme.LEI, value="X"))
    with transaction(pg) as s:
        s.add(m.CompanyIdentifier(company_id=cid, scheme=m.IdScheme.LEI, value="X", valid_to=date(2020, 1, 1)))


def test_unknown_decision_rejected(pg):
    with pytest.raises((DataError, StatementError)), transaction(pg) as s:
        s.add(m.ReviewDecision(review_item_id=1, decision="maybe"))


def test_legacy_tables_are_renamed_and_kept(pg):
    from arp.storage.postgres_schema import ensure_schema

    eng = engine(pg)
    with eng.begin() as c:
        c.execute(text(f"DROP TABLE {', '.join(sorted(TABLES))} CASCADE"))  # the new tables; create_all rebuilds them
        c.execute(text("DELETE FROM schema_migrations WHERE name LIKE '000%rename_legacy%' OR name = 'fields_id_check'"))
        c.execute(text("ALTER TABLE legacy_company_facts RENAME TO company_facts"))
        c.execute(text("ALTER TABLE legacy_companies RENAME TO companies"))
        c.execute(text("ALTER TABLE companies RENAME CONSTRAINT legacy_companies_pkey TO companies_pkey"))
        c.execute(text("ALTER TABLE company_facts RENAME CONSTRAINT legacy_company_facts_pkey TO company_facts_pkey"))
        c.execute(text("ALTER SEQUENCE legacy_company_facts_id_seq RENAME TO company_facts_id_seq"))
        c.execute(text("ALTER INDEX ix_legacy_company_facts_current RENAME TO ix_company_facts_current"))
        c.execute(text("ALTER INDEX ix_legacy_company_facts_type RENAME TO ix_company_facts_type"))
        c.execute(text("INSERT INTO companies (company_id, name) VALUES ('old1', 'Old Co')"))
    result = ensure_schema(pg)
    assert "0005_rename_legacy_companies" in result["steps_applied"]
    ensure_schema(pg)  # re-run is a no-op
    with eng.connect() as c:
        assert c.execute(text("SELECT name FROM legacy_companies WHERE company_id = 'old1'")).scalar() == "Old Co"
    cols = {col["name"] for col in inspect(eng).get_columns("companies")}
    assert "id" in cols and "company_id" not in cols
    assert "fact_key" in {col["name"] for col in inspect(eng).get_columns("legacy_company_facts")}
    assert "field_id" in {col["name"] for col in inspect(eng).get_columns("company_facts")}
