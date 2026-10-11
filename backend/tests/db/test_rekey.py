"""Step `phase1_rekey`: legacy-keyed rows (issuer_key/issuer_scheme, ISIN, universe id) gain the registry
company UUID; rows that match nothing stay, with company_id NULL, and are counted by schema_report."""

from __future__ import annotations

import uuid

from sqlalchemy import inspect, select, text

from arp.db import models as m
from arp.db.session import engine, transaction
from arp.storage.postgres_models import (
    FactEventModel,
    HoldingModel,
    PublishedFactModel,
    ReleaseModel,
    SecurityModel,
    SecurityResolutionModel,
)

LEI = "5493001KJTIIGC8Y1R12"
ISIN = "US0000000001"
T = "2026-01-01T00:00:00+00:00"


def _company(s, name: str, *ids: tuple[str, str]) -> uuid.UUID:
    c = m.Company(name=name)
    s.add(c)
    s.flush()
    s.add_all(m.CompanyIdentifier(company_id=c.id, scheme=scheme, value=value) for scheme, value in ids)
    s.flush()
    return c.id


def _fact(fact_id: str, issuer_key: str, scheme: str) -> PublishedFactModel:
    return PublishedFactModel(
        fact_id=fact_id, issuer_key=issuer_key, issuer_scheme=scheme, field_id="f1", period_end="2025-12-31", basis="",
        value=1, state="approved", citation={}, source_run_id="r", observed_at=T, item_key="k", version=1,
        valid_from=T, release_id="rel1",
    )


def _seed(pg) -> tuple[uuid.UUID, uuid.UUID]:
    with transaction(pg) as s:
        acme = _company(s, "Acme", ("LEI", LEI), ("UNIVERSE", "ACME"), ("ISIN", ISIN))
        beta = _company(s, "Beta")
        s.add(ReleaseModel(release_id="rel1", doc_id="d", content_key="ck", storage_uri="u", issuer_key=LEI,
                           issuer_scheme="LEI", run_id="r", published_at=T, published_by="u", published_by_role="approver"))
        s.flush()
        s.add_all([
            _fact("f_lei", LEI, "LEI"),
            _fact("f_uuid", str(beta), "INTERNAL"),  # R3: an INTERNAL issuer key that is a company UUID
            _fact("f_none", "ARP:unmatched", "ARP_PROVISIONAL"),
        ])
        s.flush()
        s.add_all(FactEventModel(event_type="published", fact_id=f, issuer_key="x", field_id="f1", period_end="2025-12-31",
                                 basis="", release_id="rel1", at=T) for f in ("f_lei", "f_none"))
        s.add_all([
            SecurityModel(security_id="s1", isin=ISIN, name="A", asset_class="equity", currency="EUR"),
            SecurityModel(security_id="s2", isin=None, name="X", asset_class="equity", currency="EUR"),
        ])
        s.flush()
        s.add(SecurityResolutionModel(security_id="s1", company_id="acme", confidence=1.0, method="isin_exact",
                                      resolved_at=T))
        s.add_all([
            HoldingModel(portfolio_id="p", security_id="s1", as_of_date="2026-01-31", isin=ISIN, issuer_key="ISS-1",
                         issuer_scheme="INTERNAL"),
            HoldingModel(portfolio_id="p", security_id="s2", as_of_date="2026-01-31", isin="XX0000000000",
                         issuer_key="ARP:x", issuer_scheme="ARP_PROVISIONAL"),
        ])
    return acme, beta


def _rerun_step(pg) -> dict:
    from arp.storage.postgres_schema import ensure_schema

    with engine(pg).begin() as c:
        c.execute(text("DELETE FROM schema_migrations WHERE name = 'phase1_rekey'"))
    return ensure_schema(pg)


def test_rekey_backfills_company_id_and_reports_unmatched(pg):
    from arp.storage.postgres_schema import schema_report

    acme, beta = _seed(pg)
    assert "phase1_rekey" in _rerun_step(pg)["steps_applied"]

    with transaction(pg) as s:
        facts = dict(s.execute(select(PublishedFactModel.fact_id, PublishedFactModel.company_id)).all())
        assert facts == {"f_lei": acme, "f_uuid": beta, "f_none": None}  # unmatched kept, not deleted
        assert s.scalar(select(ReleaseModel.company_id)) == acme
        assert dict(s.execute(select(FactEventModel.fact_id, FactEventModel.company_id)).all()) == {
            "f_lei": acme, "f_none": None}
        assert dict(s.execute(select(SecurityModel.security_id, SecurityModel.company_uuid)).all()) == {
            "s1": acme, "s2": None}
        assert s.scalar(select(SecurityResolutionModel.company_uuid)) == acme  # universe id 'acme'
        assert dict(s.execute(select(HoldingModel.security_id, HoldingModel.company_id)).all()) == {
            "s1": acme, "s2": None}  # by ISIN: the issuer key is a security-master id

    assert schema_report(pg)["unmatched_company_rows"] == {
        "fact_events": 1, "holdings": 1, "published_facts": 1, "securities": 1}


def test_rekey_reruns_for_companies_that_arrive_later(pg):
    """ensure_schema runs before `arp db import` creates the companies, so the import re-keys again."""
    from arp.storage.postgres_schema import rekey_company_ids

    with transaction(pg) as s:
        s.add(ReleaseModel(release_id="rel1", doc_id="d", content_key="ck", storage_uri="u", issuer_key=LEI,
                           issuer_scheme="LEI", run_id="r", published_at=T, published_by="u", published_by_role="approver"))
        s.flush()
        s.add(_fact("f_lei", LEI, "LEI"))
    _rerun_step(pg)
    with transaction(pg) as s:
        assert s.scalar(select(PublishedFactModel.company_id)) is None
        acme = _company(s, "Acme", ("LEI", LEI))
    with engine(pg).begin() as c:
        rekey_company_ids(c)
    with transaction(pg) as s:
        assert s.scalar(select(PublishedFactModel.company_id)) == acme


def test_legacy_tables_and_keys_are_kept(pg):
    with engine(pg).begin() as c:  # no model defines it any more; a deployment still has it
        c.execute(text("CREATE TABLE IF NOT EXISTS document_registry (doc_id varchar PRIMARY KEY)"))
    try:
        _rerun_step(pg)
        assert "document_registry" in inspect(engine(pg)).get_table_names()
    finally:
        with engine(pg).begin() as c:
            c.execute(text("DROP TABLE document_registry"))
    insp = inspect(engine(pg))
    assert "legacy_companies" in insp.get_table_names()
    assert {"issuer_key", "issuer_scheme"} <= {c["name"] for c in insp.get_columns("published_facts")}
    uniques = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("published_facts")}
    assert uniques["uq_published_facts_key_version"] == ["issuer_key", "field_id", "period_end", "basis", "version"]
    indexes = {i["name"]: i["column_names"] for i in insp.get_indexes("published_facts")}
    assert indexes["ix_published_facts_company_key"] == ["company_id", "field_id", "period_end", "basis"]


def test_live_writers_set_company_id(pg, tmp_path):
    from arp.publish.facts import FactCandidate, PublishStore, Release, plan_version
    from arp.schemas.common import Citation
    from arp.schemas.portfolio import Holding, SecurityRef, SecurityResolution
    from arp.storage.portfolio_store import PortfolioStore
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    with transaction(pg) as s:
        acme = _company(s, "Acme", ("UNIVERSE", "ACME"), ("ISIN", ISIN))
    store = PostgresPortfolioStore(pg, PortfolioStore(tmp_path))
    store.save_security(SecurityRef(security_id="s1", isin=ISIN, name="A", asset_class="equity", currency="EUR"))
    store.save_resolution(SecurityResolution(security_id="s1", company_id="acme", confidence=1.0, method="isin_exact"))
    store.save_snapshot("p", "2026-01-31", [Holding(holder_id="p", security_id="s1", as_of_date="2026-01-31",
                                                    issuer_key=str(acme), issuer_scheme="INTERNAL", market_value_eur=1.0)])

    cand = FactCandidate(
        issuer_key=str(acme), issuer_scheme="INTERNAL", field_id="f1", period_end="2025-12-31", value=1.0,
        state="approved", citation=Citation(doc_id="d", doc_type="10-K", quote="1", grounded=True, content_key="ck"),
        source_run_id="r", observed_at=T, item_key="k",
    )
    rel = Release(doc_id="d", content_key="ck", storage_uri="u", issuer_key=str(acme), issuer_scheme="INTERNAL",
                  run_id="r", published_at=T, published_by="u", published_by_role="approver")
    plan = plan_version(None, cand, release_id=rel.release_id, now=T)
    from arp.publish.release import _event

    PublishStore(pg).save_release(rel, [plan], [_event("published", plan.fact, T)])

    with transaction(pg) as s:
        assert s.scalar(select(SecurityModel.company_uuid)) == acme
        assert s.scalar(select(SecurityResolutionModel.company_uuid)) == acme
        assert s.scalar(select(HoldingModel.company_id)) == acme
        assert s.scalar(select(ReleaseModel.company_id)) == acme
        assert s.scalar(select(PublishedFactModel.company_id)) == acme
        assert s.scalar(select(FactEventModel.company_id)) == acme


def test_init_postgres_links_rows_whose_company_arrived_later(pg):
    from typer.testing import CliRunner

    from arp.cli import app

    with transaction(pg) as s:
        s.add(ReleaseModel(release_id="rel1", doc_id="d", content_key="ck", storage_uri="u", issuer_key=LEI,
                           issuer_scheme="LEI", run_id="r", published_at=T, published_by="u", published_by_role="approver"))
    with transaction(pg) as s:
        acme = _company(s, "Acme", ("LEI", LEI))
    result = CliRunner().invoke(app, ["db", "init-postgres"])
    assert result.exit_code == 0, result.output
    with transaction(pg) as s:
        assert s.scalar(select(ReleaseModel.company_id)) == acme
