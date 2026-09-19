"""Shared setup for the opt-in Postgres suites.

Every one of them points at the same scratch database, and several assert
on *unfiltered* queries -- "total market value by sector across all
portfolios" is exactly the question the relational backend exists to
answer, so narrowing those assertions to the rows one test happens to have
written would stop testing the thing. That makes an empty starting state
part of each test's setup, not just polite cleanup: one row left behind by
another suite (or by a developer's manual `arp` command against the same
scratch database) silently changes a total.

So `reset_postgres_tables` is called before *and* after each such test.
Deleting rather than dropping keeps the schema (and the recorded schema
steps) intact, which is what the tests are running against.
"""

from __future__ import annotations

# Child-before-parent, so the deletes satisfy every foreign key that
# remains: engagement commitments reference their issue, holdings
# reference portfolios and securities, securities reference companies, and
# a company_fact references the fact it supersedes.
_DELETE_ORDER = (
    "CompanyFactModel",
    "CompanyRecordModel",
    "EngagementCommitmentModel",
    "EngagementIssueModel",
    "HoldingModel",
    "SecurityResolutionModel",
    "SecurityModel",
    "CompanyModel",
    "PortfolioModel",
    "DocumentRegistryModel",
    "ChunkEmbeddingModel",
    "IndexCheckpointModel",
)


def reset_postgres_tables(dsn: str) -> None:
    """Empties every table the opt-in store defines, leaving the schema in
    place. Note the exception: `schema_migrations` (see
    arp/storage/postgres_schema.py) is deliberately NOT emptied -- it
    records which schema steps this database has had applied, and wiping it
    would make the next `ensure_schema` re-run them."""
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from arp.storage import postgres_models
    from arp.storage.postgres import get_engine

    with Session(get_engine(dsn)) as session:
        for model_name in _DELETE_ORDER:
            session.execute(delete(getattr(postgres_models, model_name)))
        session.commit()
