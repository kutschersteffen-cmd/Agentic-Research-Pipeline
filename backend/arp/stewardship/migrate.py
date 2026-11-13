"""Copy file-store engagement records (engagements/<company>/record.json + events.jsonl) into the stw_*
tables, idempotently: rows are keyed by (source='file_migration', external_id), so a re-run writes only what
changed. Objectives are not migrated (the file store predates them). Writes no events of its own."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect, select

from arp.db.session import transaction
from arp.errors import ClientInputError
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_engagement_store import _LOCK, _activity_type, _row, _ts
from arp.storage.postgres_models import (
    StwActivityModel,
    StwCommitmentModel,
    StwCompanyModel,
    StwContactModel,
    StwEngagementModel,
    StwEventModel,
    StwTransitionModel,
)

SOURCE = "file_migration"


def _build_rows(engagements_dir: Path) -> dict[str, list]:
    """Per company, every ORM row the files describe, parents before children, events in file line order."""
    store = EngagementStore(engagements_dir)
    by_company: dict[str, list] = {}
    for record in store.list_all():
        cid = record.company_id
        rows = by_company[cid] = []
        mark = {"source": SOURCE}
        try:
            rows.append(_row(StwCompanyModel, record, **mark, external_id=cid))
            for c in record.contacts:
                rows.append(_row(StwContactModel, c, **mark, external_id=c.contact_id, company_id=cid))
            for issue in record.issues:
                iid = issue.issue_id
                rows.append(
                    _row(
                        StwEngagementModel, issue, **mark, external_id=iid, engagement_id=iid, company_id=cid,
                        started_at=issue.opened_at, trigger_source=issue.source.value,
                    )
                )
                for e in issue.correspondence:
                    rows.append(
                        _row(
                            StwActivityModel, e, **mark, external_id=e.entry_id, activity_id=e.entry_id, engagement_id=iid,
                            occurred_at=e.date, activity_type=_activity_type(e),
                        )
                    )
                for m in issue.commitments:
                    rows.append(_row(StwCommitmentModel, m, **mark, external_id=m.commitment_id, engagement_id=iid))
                for kind, history in (("milestone", issue.milestone_history), ("escalation", issue.escalation_history)):
                    for i, t in enumerate(history):
                        key = f"{iid}:{kind}:{i}"
                        rows.append(_row(StwTransitionModel, t, **mark, external_id=key, transition_id=key, engagement_id=iid, kind=kind))
            for n, line in enumerate(store.events(cid), start=1):
                if "event_type" not in line:
                    raise ClientInputError(f"events.jsonl line {n} has no event_type")
                detail = {k: v for k, v in line.items() if k not in ("event_type", "at")}
                rows.append(
                    StwEventModel(
                        **mark, external_id=f"{cid}:{n}", company_id=cid, event_type=line["event_type"],
                        detail=detail, at=_ts(line.get("at"), "at"),
                    )
                )
        except ClientInputError as exc:
            raise ClientInputError(f"company {cid}: {exc}") from None
    return by_company


def migrate_files(engagements_dir: Path, dsn: str, dry_run: bool = False) -> dict[str, int]:
    by_company = _build_rows(engagements_dir)  # parses every timestamp before anything is written
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    with transaction(dsn) as session:
        for cid, rows in by_company.items():
            session.execute(_LOCK, {"id": cid})  # the store's per-company lock: no write races a live app
            current, mine = session.get(StwCompanyModel, cid), rows[0]
            if current is not None and current.source != SOURCE:
                raise ClientInputError(f"company {cid} already exists in Postgres with source {current.source!r}")
            if current is not None and current.updated_at and mine.updated_at and current.updated_at > mine.updated_at:
                counts["unchanged"] += len(rows)
                print(f"skipped {cid}: changed in Postgres since migration", file=sys.stderr)
                continue
            for new in rows:
                model = type(new)
                existing = session.scalar(select(model).where(model.source == SOURCE, model.external_id == new.external_id))
                if existing is None:
                    counts["created"] += 1
                    if not dry_run:
                        session.add(new)
                    continue
                changed = {k: v for k, v in inspect(new).dict.items() if k != "_sa_instance_state" and getattr(existing, k) != v}
                counts["updated" if changed else "unchanged"] += 1
                if not dry_run:
                    for k, v in changed.items():
                        setattr(existing, k, v)
        session.flush()
    return counts
