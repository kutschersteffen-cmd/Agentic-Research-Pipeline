"""Read-model projection of every run's results.jsonl rows into
CompanyRecordModel (arp/storage/postgres_models.py -- see that model's
own docstring for the full design rationale). results.jsonl stays
authoritative; this module only ever reads it and writes derived rows,
never the other way around.
"""

from __future__ import annotations

import logging

from arp.storage.postgres import get_engine
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


def row_to_record_kwargs(manifest, row: dict) -> dict | None:
    """Pure mapping from one results.jsonl row to CompanyRecordModel
    constructor kwargs, or None if the row has no company_id.
    `run_batch` (arp/orchestration/batch_runner.py) injects "_key" into
    every row it writes, set to whatever `item_key` the caller supplied
    -- company_id for every run type today (extraction, financials,
    theme, proxy_voting all pass `item_key=lambda c: c.company_id`) --
    so this is the one reliable, run-type-agnostic way to recover
    company_id from a row without depending on each pipeline's own
    result schema having a top-level `company_id` field (it doesn't,
    for theme -- see fact_candidates in
    postgres_company_facts_projection.py for the verified row shapes).
    """
    company_id = row.get("_key")
    if not company_id:
        return None
    return {
        "run_id": manifest.run_id,
        "run_type": manifest.run_type,
        "company_id": company_id,
        "record_key": "",
        "overall_confidence": row.get("overall_confidence") or row.get("confidence"),
        "needs_review": row.get("needs_review"),
        "generated_at": manifest.updated_at,
        "payload": row,
    }


def sync_run(dsn: str, run_store: RunStore, run_id: str) -> int:
    """Inserts one CompanyRecordModel row per results.jsonl row for this
    run, idempotently -- ON CONFLICT DO NOTHING against
    uq_company_records_run_company_key means a re-sync of an
    already-synced run is a no-op, not a duplicate insert. Returns the
    number of rows actually inserted (0 on a repeat sync or an empty/
    missing run)."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        return 0
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    kwargs_list = []
    for row in rows:
        kwargs = row_to_record_kwargs(manifest, row)
        if kwargs is not None:
            kwargs_list.append(kwargs)
    if not kwargs_list:
        return 0

    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.orm import Session

    from arp.storage.postgres_models import CompanyRecordModel

    engine = get_engine(dsn)
    with Session(engine) as session:
        stmt = insert(CompanyRecordModel).values(kwargs_list)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_company_records_run_company_key")
        result = session.execute(stmt)
        session.commit()
        return result.rowcount


def sync_all(dsn: str, run_store: RunStore, *, since: str | None = None) -> int:
    """Backfills every run (optionally only those updated after `since`,
    an ISO timestamp) -- used by `arp db reindex company-records`."""
    total = 0
    for manifest in run_store.list_runs():
        if since is not None and manifest.updated_at <= since:
            continue
        total += sync_run(dsn, run_store, manifest.run_id)
    return total


def sync_run_if_enabled(config: ProjectionConfig, run_store: RunStore, run_id: str) -> None:
    """Best-effort: called from RunStore.save_manifest on a terminal
    status. Any failure is logged and swallowed -- never blocks the real
    (file-based) write it's attached to, same contract as the OpenSearch/
    object-store live-ingestion hooks."""
    if not config.company_records_enabled:
        return
    try:
        sync_run(config.postgres_dsn, run_store, run_id)
    except Exception:
        logger.warning("Postgres company-records sync failed for run_id=%s", run_id, exc_info=True)
