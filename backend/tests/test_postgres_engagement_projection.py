"""EngagementStore mirrors each company's issues and commitments into Postgres on every save
(arp/storage/postgres_engagement_projection.py). The hook is best-effort, so these assert on rows
actually in Postgres: a constraint that rejected every row would otherwise only leave a log line."""

from __future__ import annotations

import os

import pytest

from arp.schemas.engagement import Commitment, IssueSeverity, IssueStatus
from arp.storage.engagement_store import EngagementStore
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = [
    pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres integration test"),
    pytest.mark.usefixtures("pg"),
]

# A company that exists only in a universe file: engagement rows carry no FK to any company table.
UNIVERSE_ONLY_COMPANY = "acme-universe-only"


@pytest.fixture(autouse=True)
def _schema_and_cleanup():
    from arp.storage.postgres import ensure_schema

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    yield
    reset_postgres_tables(DSN)


def _rows(model) -> list:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from arp.storage.postgres import get_engine

    with Session(get_engine(DSN)) as session:
        return list(session.scalars(select(model)).all())


def test_engagement_issues_and_commitments_project_on_save(tmp_path):
    from arp.storage.postgres_models import EngagementCommitmentModel, EngagementIssueModel

    store = EngagementStore(
        tmp_path / "engagements",
        dsn=DSN,
    )
    _record, issue = store.open_issue(
        UNIVERSE_ONLY_COMPANY, "Acme Corp", theme="climate transition plan", severity=IssueSeverity.HIGH
    )
    store.add_commitment(
        UNIVERSE_ONLY_COMPANY,
        issue.issue_id,
        Commitment(text="Publish a 1.5C-aligned plan", target_date="2026-12-31"),
    )

    issues = _rows(EngagementIssueModel)
    commitments = _rows(EngagementCommitmentModel)
    assert [(i.company_id, i.theme, i.severity, i.status) for i in issues] == [
        (UNIVERSE_ONLY_COMPANY, "climate transition plan", "high", "open")
    ]
    assert [(c.issue_id, c.text, c.status) for c in commitments] == [
        (issue.issue_id, "Publish a 1.5C-aligned plan", "open")
    ]
    assert issues[0].payload["issue_id"] == issue.issue_id


def test_engagement_projection_replaces_rather_than_accumulates(tmp_path):
    """Engagement state is a live document, not an append-only run output,
    so each save replaces that company's rows -- a status change must not
    leave two rows for one issue."""
    from arp.storage.postgres_models import EngagementIssueModel

    store = EngagementStore(
        tmp_path / "engagements",
        dsn=DSN,
    )
    _record, issue = store.open_issue(UNIVERSE_ONLY_COMPANY, "Acme Corp", theme="board independence")

    store.set_issue_status(UNIVERSE_ONLY_COMPANY, issue.issue_id, IssueStatus.STALLED)

    issues = _rows(EngagementIssueModel)
    assert [(i.issue_id, i.status) for i in issues] == [(issue.issue_id, "stalled")]
