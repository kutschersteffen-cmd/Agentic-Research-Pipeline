"""Read-model projection of EngagementRecord (arp/storage/
engagement_store.py -- `record.json` stays authoritative; `events.jsonl`
remains the separate, untouched audit trail) into EngagementIssueModel/
EngagementCommitmentModel (arp/storage/postgres_models.py).

Unlike the run-based projections (postgres_company_records_projection.py,
postgres_company_facts_projection.py), engagement state is a
continuously-mutated live document, not an append-only run output --
record.json itself is a materialized snapshot, not a log. So this
projection is a full replace-by-company_id on every save, never
versioned/insert-only.
"""

from __future__ import annotations

import logging

from arp.schemas.engagement import EngagementRecord
from arp.storage.postgres import get_engine
from arp.storage.postgres_projection_config import ProjectionConfig

logger = logging.getLogger(__name__)


def sync_record(dsn: str, record: EngagementRecord) -> None:
    """Replaces every EngagementIssueModel/EngagementCommitmentModel row
    for `record.company_id` with the current state of `record` --
    commitments deleted before issues (and inserted after), respecting
    the commitment -> issue foreign key."""
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from arp.storage.postgres_models import EngagementCommitmentModel, EngagementIssueModel

    engine = get_engine(dsn)
    with Session(engine) as session:
        session.execute(delete(EngagementCommitmentModel).where(EngagementCommitmentModel.company_id == record.company_id))
        session.execute(delete(EngagementIssueModel).where(EngagementIssueModel.company_id == record.company_id))
        for issue in record.issues:
            session.add(
                EngagementIssueModel(
                    issue_id=issue.issue_id,
                    company_id=record.company_id,
                    theme=issue.theme,
                    severity=issue.severity.value,
                    status=issue.status.value,
                    source=issue.source.value,
                    milestone_stage=issue.milestone_stage.value,
                    escalation_stage=issue.escalation_stage.value,
                    opened_at=issue.opened_at,
                    payload=issue.model_dump(mode="json"),
                )
            )
            for commitment in issue.commitments:
                session.add(
                    EngagementCommitmentModel(
                        commitment_id=commitment.commitment_id,
                        issue_id=issue.issue_id,
                        company_id=record.company_id,
                        text=commitment.text,
                        status=commitment.status.value,
                        target_date=commitment.target_date,
                        validated_by=commitment.validated_by,
                        validated_at=commitment.validated_at,
                    )
                )
        session.commit()


def sync_all(dsn: str, engagement_store) -> int:
    """Backfills every company's engagement record -- used by `arp db
    reindex engagement`. Returns the number of records synced."""
    count = 0
    for record in engagement_store.list_all():
        sync_record(dsn, record)
        count += 1
    return count


def sync_record_if_enabled(config: ProjectionConfig, record: EngagementRecord) -> None:
    """Best-effort: called from EngagementStore._save. Any failure is
    logged and swallowed -- never blocks the real (file-based) write
    it's attached to, same contract as every other projection hook."""
    if not config.engagement_enabled:
        return
    try:
        sync_record(config.postgres_dsn, record)
    except Exception:
        logger.warning("Postgres engagement sync failed for company_id=%s", record.company_id, exc_info=True)
