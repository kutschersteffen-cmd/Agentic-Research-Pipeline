from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from arp.cli import app
from arp.db.session import transaction
from arp.schemas.engagement import Contact, IssueStatus
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.postgres_models import StwCompanyModel, StwEngagementModel

FIXTURE = Path(__file__).parent / "fixtures" / "engagements_migration"


@pytest.fixture
def run(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_SKIP_CUTOVER_CHECK", "1")
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    shutil.copytree(FIXTURE, tmp_path / "engagements")
    return lambda *args: CliRunner().invoke(app, ["stewardship", "migrate-files", *args])


def test_migrate_counts(run):
    res = run()
    assert res.exit_code == 0, res.output
    assert res.stdout.strip() == "created 30, updated 0, unchanged 0"


def test_migrate_again(run):
    run()
    res = run()
    assert res.stdout.strip() == "created 0, updated 0, unchanged 30"


def test_changed_file_is_updated(run, tmp_path):
    run()
    path = tmp_path / "engagements" / "acme" / "record.json"
    path.write_text(path.read_text().replace("Say-on-pay 41% support", "Say-on-pay 38% support"))
    assert run().stdout.strip() == "created 0, updated 1, unchanged 29"


def test_dry_run(run, pg):
    res = run("--dry-run")
    assert res.exit_code == 0, res.output
    assert res.stdout.strip() == "would create 30"
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(StwEngagementModel)) == 0


def test_bad_timestamp_writes_nothing(run, pg, tmp_path):
    path = tmp_path / "engagements" / "cobalt" / "record.json"
    path.write_text(path.read_text().replace("2025-05-12T11:00:00+00:00", "last Tuesday"))
    res = run()
    assert res.exit_code == 1
    assert "cobalt" in res.stderr and "date" in res.stderr and "last Tuesday" in res.stderr
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(StwEngagementModel)) == 0


def test_migrated_rows_read_back_equal(run, pg):
    run()
    files, store = EngagementStore(FIXTURE), PostgresEngagementStore(pg)
    for record in files.list_all():
        # the only difference is provenance: migrated issues carry data_source "file_migration"
        issues = [i.model_copy(update={"data_source": "file_migration"}) for i in record.issues]
        assert store.get(record.company_id) == record.model_copy(update={"issues": issues})
        assert store.events(record.company_id) == files.events(record.company_id)


def test_rerun_keeps_newer_postgres_data(run, pg):
    run()
    store = PostgresEngagementStore(pg)
    issue = store.get("acme").issues[0]
    new = IssueStatus.CLOSED if issue.status != IssueStatus.CLOSED else IssueStatus.RESOLVED
    store.set_issue_status("acme", issue.issue_id, new)
    res = run()
    assert res.exit_code == 0, res.output
    assert res.stdout.strip().startswith("created 0, updated 0, unchanged 30")
    assert "skipped acme: changed in Postgres since migration" in res.stderr
    assert store.get("acme").issues[0].status == new


def test_existing_app_company_is_rejected(run, pg):
    PostgresEngagementStore(pg).get_or_create("acme", "Acme")
    res = run()
    assert res.exit_code == 1
    assert "acme" in res.stderr
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(StwCompanyModel)) == 1


def test_event_without_type_writes_nothing(run, pg, tmp_path):
    path = tmp_path / "engagements" / "cobalt" / "events.jsonl"
    path.write_text(path.read_text() + '{"at": "2025-05-12T11:00:00+00:00"}\n')
    res = run()
    assert res.exit_code == 1
    assert "cobalt" in res.stderr and "event_type" in res.stderr
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(StwCompanyModel)) == 0


def test_contacts_migrate(run, pg, tmp_path):
    files = EngagementStore(tmp_path / "engagements")
    files.add_contact("acme", Contact(name="Pat Lee", role="Chair", email="pat@example.com"))
    assert run().exit_code == 0
    got = PostgresEngagementStore(pg).get("acme")
    assert len(got.contacts) >= 1
    assert got.contacts == files.get("acme").contacts


def test_migrated_issues_have_no_voice_role(run, pg):
    run()
    assert all(i.engager_role is None for r in PostgresEngagementStore(pg).list_all() for i in r.issues)
