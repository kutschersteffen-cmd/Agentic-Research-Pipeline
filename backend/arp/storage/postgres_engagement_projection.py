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
    for `record.company_id` with the current state of `record`.

    Ordering matters in both directions of the commitment -> issue foreign
    key, and both halves are explicit here: commitments are deleted before
    issues, and issues are inserted *and flushed* before any commitment is
    added. That flush is not decoration. EngagementCommitmentModel has a
    plain ForeignKey column but no ORM `relationship()`, and SQLAlchemy
    derives flush ordering from mapper relationships -- with none declared
    it happened to flush `engagement_commitments` first, so every save of
    an issue that had a commitment raised ForeignKeyViolation. The
    best-effort hook swallowed it (see sync_record_if_enabled), which is
    why a projection that could never store a commitment still looked
    healthy.
    """
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from arp.storage.postgres_models import EngagementCommitmentModel, EngagementIssueModel

    engine = get_engine(dsn)
    with Session(engine) as session:
        session.execute(delete(EngagementCommitmentModel).where(EngagementCommitmentModel.company_id == record.company_id))
        session.execute(delete(EngagementIssueModel).where(EngagementIssueModel.company_id == record.company_id))
        session.add_all(
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
            for issue in record.issues
        )
        session.flush()  # every issue row exists before a commitment points at one
        session.add_all(
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
            for issue in record.issues
            for commitment in issue.commitments
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
