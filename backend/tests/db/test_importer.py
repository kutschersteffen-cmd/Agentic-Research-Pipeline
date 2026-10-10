from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, func, select
from typer.testing import CliRunner

from arp.config import Settings
from arp.db import importer
from arp.db import models as m
from arp.db.companies import lookup
from arp.db.company_view import facts
from arp.db.session import transaction
from arp.schemas.common import CompanyRef, JobStatus, RunManifest
from arp.schemas.datapoints import DataPointSchema, FieldDefinition
from arp.storage.run_store import LegacyRunStore

LEI = "5493001KJTIIGC8Y1R13"
FY24 = "2024-12-31"
EMP_KEY = f"acme:fld_emp:{FY24}"


def _ext_row(run_id, fields):
    return {"company_id": "acme", "name": "Acme", "schema_id": "s", "run_id": run_id, "_key": "acme", "fields": [
        {"field_id": fid, "field_name": fid, "value": v, "confidence": 0.9, "period_end": FY24, "route": route,
         "citations": [{"doc_id": "doc_a", "doc_type": "10-K", "quote": "q", "page": 3}]}
        for fid, v, route in fields
    ]}


def _run(legacy, run_id, run_type, created, rows, *, companies=True):
    legacy.save_manifest(RunManifest(run_id=run_id, run_type=run_type, status=JobStatus.COMPLETED, created_at=created))
    if companies:
        legacy.save_companies(run_id, [CompanyRef(company_id="acme", name="Acme", lei=LEI)])
    for row in rows:
        legacy.append_result(run_id, row)


@pytest.fixture
def legacy_settings(pg, tmp_path):
    """Three runs over two dates (two extraction, one theme), a universe file, an identifier map, one
    schema registry version and a content.db documents table."""
    s = Settings(
        postgres_dsn=pg, runs_dir=tmp_path / "runs", schema_registry_dir=tmp_path / "schemas",
        identifier_map_path=tmp_path / "identifier_map.jsonl", document_store_dir=tmp_path / "docstore",
        portfolios_dir=tmp_path / "portfolios", discovery_schedule_universe_path=tmp_path / "universe.json",
    )
    (tmp_path / "universe.json").write_text(json.dumps([{"company_id": "acme", "name": "Acme", "lei": LEI}]))
    s.identifier_map_path.write_text(json.dumps({"issuer_key": "ISS1", "scheme": "ISIN", "value": "US0000000001"}) + "\n"
                                     + json.dumps({"issuer_key": "ISS1", "scheme": "LEI", "value": LEI}) + "\n")
    schema = DataPointSchema(schema_id="s", name="S", fields=[
        FieldDefinition(field_id=fid, name=fid, description="d", data_type="number", extraction_instructions="x")
        for fid in ("fld_rev", "fld_emp")
    ])
    (s.schema_registry_dir / "s").mkdir(parents=True)
    (s.schema_registry_dir / "s" / "v1.json").write_text(schema.model_dump_json())
    (s.schema_registry_dir / "index.json").write_text(json.dumps([{"schema_id": "s", "version": 1, "name": "S"}]))
    s.document_store_dir.mkdir()
    with sqlite3.connect(s.document_store_dir / "content.db") as conn:
        conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, company_id TEXT, doc_type TEXT, content_key TEXT, "
                     "title TEXT, local_path TEXT, source_url TEXT, storage_uri TEXT, first_seen_at TEXT, "
                     "last_seen_at TEXT, family_id TEXT, version INTEGER, supersedes TEXT, published_at TEXT, "
                     "identity_confidence REAL, identity_review INTEGER)")
        conn.execute("INSERT INTO documents VALUES ('doc_a', 'acme', '10-K', 'ck1', 'AR 2024', NULL, NULL, NULL, "
                     "'2025-03-01T00:00:00+00:00', '2025-03-02T00:00:00+00:00', 'fam1', 1, NULL, '2025-02-28', 0.9, 0)")
    conn.close()

    legacy = LegacyRunStore(s.runs_dir)
    # written newest first: the import must order by created_at, not by directory or write order
    _run(legacy, "r_new", "extraction", "2026-02-01T00:00:00+00:00", [_ext_row("r_new", [("fld_rev", 12.0, "auto_accept")])])
    _run(legacy, "r_theme", "theme", "2026-02-01T00:00:00+00:00",
         [{"_key": "acme", "company_matches": [{"activity_id": "a1", "verdict": "yes", "flagged_for_review": False}]}])
    _run(legacy, "r_old", "extraction", "2026-01-01T00:00:00+00:00",
         [_ext_row("r_old", [("fld_rev", 10.0, "auto_accept"), ("fld_emp", 5.0, "review")])])
    legacy.append_error("r_old", {"key": "beta", "error": "boom"})
    legacy.append_review_item("r_old", {"item_key": EMP_KEY, "company_id": "acme", "field_id": "fld_emp",
                                        "period_end": FY24, "queued_at": "2026-01-01T00:01:00+00:00"})
    legacy.append_decision_row("r_old", {"item_key": EMP_KEY, "decision": "edit", "reviewer": "bob",
                                         "edited_value": {"value": 6.0}, "decided_at": "2026-01-02T00:00:00+00:00"})
    legacy.append_cosign("r_old", {"item_key": EMP_KEY, "user_id": "u2", "name": "Carol", "role": "approver",
                                   "decision_decided_at": "2026-01-02T00:00:00+00:00",
                                   "cosigned_at": "2026-01-03T00:00:00+00:00"})
    return s


def _current(pg, field_id):
    with transaction(pg) as s:
        return [(f.value, f.status) for f in s.scalars(
            select(m.CompanyFact).where(m.CompanyFact.field_id == field_id, m.CompanyFact.valid_to.is_(None)))]


def _count(pg, model):
    with transaction(pg) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_import_replays_oldest_first(pg, legacy_settings):
    report = importer.import_all(pg, legacy_settings, dry_run=False)
    assert report.counts["runs"] == 3 and report.counts["results"] == 3
    assert report.counts["documents"] == 1 and report.counts["schemas"] == 1 and report.counts["identifiers"] == 1
    assert _current(pg, "fld_rev") == [(12.0, m.FactStatus.AUTO_ACCEPTED)]
    assert _current(pg, "fld_emp") == [(6.0, m.FactStatus.EDITED)]  # edit + cosign applied in order
    assert _current(pg, "theme:a1") == [({"verdict": "yes", "exposure_estimate": None}, m.FactStatus.AUTO_ACCEPTED)]
    (conflict,) = report.fact_conflicts
    assert (conflict["field_id"], conflict["previous"], conflict["value"]) == ("fld_rev", 10.0, 12.0)
    with transaction(pg) as s:
        acme = lookup(s, m.IdScheme.UNIVERSE, "acme")
        assert lookup(s, m.IdScheme.ISIN, "US0000000001") == acme
        doc = s.get(m.Document, "doc_a")
        assert (doc.company_id, doc.family_id, doc.published_at) == (acme, "fam1", date(2025, 2, 28))
        assert s.scalar(select(func.count()).select_from(m.RunResult).where(m.RunResult.company_id == acme)) == 3
        item = s.scalar(select(m.ReviewItem))
        assert item.item_key == EMP_KEY and item.observation_id is not None
        decision = s.scalar(select(m.ReviewDecision))
        assert decision.decided_at == datetime(2026, 1, 2, tzinfo=UTC)
        assert s.scalar(select(m.Run.created_at).where(m.Run.run_id == "r_old")) == datetime(2026, 1, 1, tzinfo=UTC)
        # the company page reads these facts
        rows = facts(s, acme)
        assert {(r.field_id, str(r.value)) for r in rows} >= {("fld_rev", "12.0"), ("fld_emp", "6.0")}
        assert next(r for r in rows if r.field_id == "fld_rev").source_label == "AR 2024 p.3"


def test_import_is_idempotent(pg, legacy_settings):
    importer.import_all(pg, legacy_settings, dry_run=False)
    observations = _count(pg, m.FieldObservation)
    again = importer.import_all(pg, legacy_settings, dry_run=False)
    assert set(again.counts.values()) == {0}
    assert _count(pg, m.FieldObservation) == observations
    assert _count(pg, m.ReviewDecision) == 1


def test_import_resumes_after_interruption(pg, legacy_settings, monkeypatch):
    real, calls = importer._import_run, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("interrupted")
        return real(*args, **kwargs)

    monkeypatch.setattr(importer, "_import_run", flaky)
    with pytest.raises(RuntimeError):
        importer.import_all(pg, legacy_settings, dry_run=False)
    assert _count(pg, m.Run) == 1  # the first run committed, nothing of the second
    monkeypatch.setattr(importer, "_import_run", real)
    report = importer.import_all(pg, legacy_settings, dry_run=False)
    assert report.counts["runs"] == 2
    assert _count(pg, m.RunResult) == 3 and _count(pg, m.ReviewItem) == 1 and _count(pg, m.RunError) == 1
    assert _current(pg, "fld_rev") == [(12.0, m.FactStatus.AUTO_ACCEPTED)]
    assert importer.verify(pg, legacy_settings).differences == []


def test_dry_run_writes_nothing(pg, legacy_settings):
    report = importer.import_all(pg, legacy_settings, dry_run=True)
    assert report.counts["runs"] == 3 and report.counts["results"] == 3
    for model in (m.Company, m.Run, m.RunResult, m.Document, m.DataSchema, m.CompanyFact, m.FieldObservation):
        assert _count(pg, model) == 0, model


def test_verify_reports_zero_differences_after_import(pg, legacy_settings):
    importer.import_all(pg, legacy_settings, dry_run=False)
    assert importer.verify(pg, legacy_settings).differences == []


def test_verify_detects_missing_row(pg, legacy_settings):
    importer.import_all(pg, legacy_settings, dry_run=False)
    with transaction(pg) as s:
        s.execute(delete(m.RunResult).where(m.RunResult.run_id == "r_theme"))
    diffs = importer.verify(pg, legacy_settings).differences
    assert {"run_id": "r_theme", "area": "results", "files": 1, "db": 0} in diffs


def test_verify_detects_a_different_current_fact(pg, legacy_settings):
    importer.import_all(pg, legacy_settings, dry_run=False)
    with transaction(pg) as s:
        s.execute(delete(m.CompanyFact).where(m.CompanyFact.field_id == "theme:a1"))
    (diff,) = importer.verify(pg, legacy_settings).differences
    assert (diff["area"], diff["field_id"], diff["db"]) == ("fact", "theme:a1", None)


def test_cli_verify_exits_non_zero_on_differences(pg, legacy_settings, monkeypatch):
    from arp.cli import db as cli_db

    monkeypatch.setattr(cli_db, "get_settings", lambda: legacy_settings)
    runner = CliRunner()
    dry = runner.invoke(cli_db.db_app, ["import", "--dry-run"])
    assert dry.exit_code == 0 and "runs" in dry.output and _count(pg, m.Run) == 0
    assert runner.invoke(cli_db.db_app, ["verify"]).exit_code == 1
    assert runner.invoke(cli_db.db_app, ["import"]).exit_code == 0
    ok = runner.invoke(cli_db.db_app, ["verify"])
    assert ok.exit_code == 0, ok.output


def test_import_esg_loads_and_legacy_postgres_documents(pg, legacy_settings):
    from sqlalchemy import text

    from arp.portfolio.climate.esg_intake import FIELD_IDS
    from arp.portfolio.loads import LoadRecord, record_load
    from arp.schemas.portfolio import DataPointObservation
    from arp.storage.portfolio_store import PortfolioStore

    store = PortfolioStore(legacy_settings.portfolios_dir)
    store.save_company(CompanyRef(company_id="beta", name="Beta"))
    for i, fid in enumerate(FIELD_IDS):
        store.append_observation(DataPointObservation(company_id="beta", field_id=fid, field_name=fid, value=float(i),
                                                      period="2025-06", source="internal_api"))
    record_load(store, LoadRecord(kind="esg", source_id="msci", month="2025-06", status="ok", content_hash="h"))
    with transaction(pg) as s:  # a deployment that ran embeddings_backend=postgres
        s.execute(text("INSERT INTO document_registry (doc_id, company_id, doc_type, content_key, title, first_seen_at, "
                       "last_seen_at, family_id, version) VALUES ('doc_a', 'acme', '10-K', 'ck1', 'AR', 'x', 'x', 'fam2', 2), "
                       "('doc_b', 'beta', '10-K', 'ck2', 'B', '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00', NULL, NULL)"))

    report = importer.import_all(pg, legacy_settings, dry_run=False)
    assert report.counts["esg_loads"] == 1 and report.counts["documents"] == 2
    assert _current(pg, f"prov:esg_msci:{FIELD_IDS[1]}") == [(1.0, m.FactStatus.AUTO_ACCEPTED)]
    with transaction(pg) as s:
        doc = s.get(m.Document, "doc_a")
        assert (doc.title, doc.family_id, doc.version) == ("AR 2024", "fam2", 2)  # content.db row, Postgres identity
    assert importer.import_all(pg, legacy_settings, dry_run=False).counts["esg_loads"] == 0
    assert importer.verify(pg, legacy_settings).differences == []
