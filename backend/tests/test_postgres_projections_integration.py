"""Integration tests for the Postgres read-model projections' WRITE paths,
against a real instance.

These did not exist, and their absence is exactly why three of the four
projections shipped unable to insert a single row: each projection had
careful unit tests for its pure mapping function (row -> kwargs) and
nothing that ever executed the INSERT. The live sync hooks swallow
exceptions by design -- "best-effort, never blocks the real file write" --
so a constraint that rejected every row produced an empty table and a log
line, and no test noticed.

Every test here therefore asserts on rows actually in Postgres, and the
first one pins the specific regression: a company that exists only in a
universe file, never in the `companies` table.

Skipped without ARP_TEST_POSTGRES_DSN, like the other Postgres suites.
"""

from __future__ import annotations

import os

import pytest

from arp.schemas.common import JobStatus, RunManifest
from arp.schemas.engagement import Commitment, IssueSeverity, IssueStatus
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.run_store import RunStore
from tests.postgres_helpers import reset_postgres_tables

DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set -- opt-in Postgres integration test")

# Never written to the `companies` table by any test here: that is the
# point. A run's companies come from the user-supplied universe file.
UNIVERSE_ONLY_COMPANY = "acme-universe-only"


@pytest.fixture(autouse=True)
def _schema_and_cleanup():
    """Empty tables either side of every test: these assertions count rows
    across the whole table, so they own the scratch database for their
    duration (see tests/postgres_helpers.py)."""
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


def _completed_run(tmp_path, *, run_type: str = "extraction", run_id: str = "run_1", rows: list[dict]) -> RunStore:
    """A RunStore holding one finished run, with the projections enabled on
    it so save_manifest fires the same live hook production does."""
    store = RunStore(
        tmp_path / "runs",
        projection_config=ProjectionConfig(
            postgres_dsn=DSN,
            company_records_projection_enabled=True,
            company_facts_projection_enabled=True,
        ),
    )
    for row in rows:
        RunStore.append_jsonl(store.results_path(run_id), row)
    store.save_manifest(RunManifest(run_id=run_id, run_type=run_type, status=JobStatus.COMPLETED))
    return store


# --- company_records -------------------------------------------------------


def test_completing_a_run_projects_its_rows_for_a_universe_only_company(tmp_path):
    """The regression: this used to insert nothing at all, because
    company_records carried a foreign key to a `companies` table that only
    the dual-write portfolio store ever populates."""
    from arp.storage.postgres_models import CompanyRecordModel

    _completed_run(
        tmp_path,
        rows=[{"_key": UNIVERSE_ONLY_COMPANY, "overall_confidence": 0.42, "needs_review": True, "field_id": "scope_1"}],
    )

    records = _rows(CompanyRecordModel)
    assert [(r.run_id, r.company_id, r.run_type) for r in records] == [("run_1", UNIVERSE_ONLY_COMPANY, "extraction")]
    assert records[0].overall_confidence == 0.42
    assert records[0].needs_review is True
    assert records[0].payload["field_id"] == "scope_1"


def test_sync_run_returns_the_number_of_rows_it_inserted(tmp_path):
    """`result.rowcount` reports -1 for this insert, so `arp db reindex
    company-records` used to print rows_inserted=-1 whether it had
    backfilled two thousand rows or none."""
    from arp.storage.postgres_company_records_projection import sync_run

    store = RunStore(tmp_path / "runs")
    for company_id in ("a", "b", "c"):
        RunStore.append_jsonl(store.results_path("run_1"), {"_key": company_id})
    store.save_manifest(RunManifest(run_id="run_1", run_type="extraction", status=JobStatus.COMPLETED))

    assert sync_run(DSN, store, "run_1") == 3
    assert sync_run(DSN, store, "run_1") == 0  # already synced: idempotent, and honestly counted


def test_sync_all_honours_the_since_checkpoint(tmp_path):
    """What `--full` and the recorded checkpoint are built on: a run whose
    manifest predates the checkpoint is not rescanned."""
    from arp.storage.atomic_io import atomic_write_text
    from arp.storage.postgres_company_records_projection import sync_all
    from arp.storage.postgres_models import CompanyRecordModel

    store = RunStore(tmp_path / "runs")
    for run_id, company_id, updated_at in (
        ("old_run", "a", "2026-01-01T00:00:00Z"),
        ("new_run", "b", "2026-06-01T00:00:00Z"),
    ):
        RunStore.append_jsonl(store.results_path(run_id), {"_key": company_id})
        # Written directly rather than via save_manifest, which stamps
        # updated_at with the current time -- that stamping is exactly what
        # makes the checkpoint meaningful in production, and exactly what
        # makes it untestable through that path.
        manifest = RunManifest(run_id=run_id, run_type="extraction", status=JobStatus.COMPLETED, updated_at=updated_at)
        atomic_write_text(store.manifest_path(run_id), manifest.model_dump_json(indent=2))

    assert sync_all(DSN, store, since="2026-03-01T00:00:00Z") == 1
    assert {r.run_id for r in _rows(CompanyRecordModel)} == {"new_run"}


def test_a_row_with_no_company_key_is_skipped_not_inserted(tmp_path):
    from arp.storage.postgres_models import CompanyRecordModel

    _completed_run(tmp_path, rows=[{"no_key_here": True}])

    assert _rows(CompanyRecordModel) == []


def test_checkpoints_round_trip(tmp_path):
    from arp.storage.postgres_checkpoints import get_checkpoint, set_checkpoint

    assert get_checkpoint(DSN, "never_run_projector") is None
    set_checkpoint(DSN, "company_records", "2026-06-01T00:00:00Z")
    set_checkpoint(DSN, "company_records", "2026-07-01T00:00:00Z")  # upsert, not a duplicate row

    assert get_checkpoint(DSN, "company_records") == "2026-07-01T00:00:00Z"


# --- company_facts ---------------------------------------------------------


def test_facts_are_materialized_with_confidence_and_citations(tmp_path):
    """Both columns were declared and documented from the start and never
    populated, so every fact read back NULL for the one number a caller is
    most likely to filter on."""
    from arp.storage.postgres_models import CompanyFactModel

    citation = {"doc_id": "doc_abc", "quote": "Scope 1 emissions were 1.2 Mt CO2e", "page": 42}
    _completed_run(
        tmp_path,
        rows=[
            {
                "_key": UNIVERSE_ONLY_COMPANY,
                "overall_confidence": 0.9,
                "fields": [{"field_id": "scope_1", "confidence": 0.9, "citations": [citation]}],
            }
        ],
    )

    facts = _rows(CompanyFactModel)
    assert len(facts) == 1
    assert facts[0].company_id == UNIVERSE_ONLY_COMPANY
    assert facts[0].fact_type == "extraction_record"
    assert facts[0].status == "auto_approved"
    assert facts[0].confidence == 0.9
    assert facts[0].citations == [citation]
    assert facts[0].is_current is True


def test_theme_matches_are_keyed_and_scored_per_activity(tmp_path):
    from arp.storage.postgres_models import CompanyFactModel

    _completed_run(
        tmp_path,
        run_type="theme",
        rows=[
            {
                "_key": UNIVERSE_ONLY_COMPANY,
                "company_matches": [
                    {"activity_id": "a1", "confidence": 0.8, "citations": [{"doc_id": "d1", "quote": "q"}]},
                    {"activity_id": "a2", "confidence": 0.3, "citations": []},
                ],
            }
        ],
    )

    facts = {f.fact_key: f for f in _rows(CompanyFactModel)}
    assert set(facts) == {f"{UNIVERSE_ONLY_COMPANY}:a1", f"{UNIVERSE_ONLY_COMPANY}:a2"}
    assert facts[f"{UNIVERSE_ONLY_COMPANY}:a1"].confidence == 0.8
    assert facts[f"{UNIVERSE_ONLY_COMPANY}:a2"].citations is None  # no citations, not an empty list
    assert all(f.fact_type == "theme_match" for f in facts.values())


def test_re_materializing_an_unchanged_run_is_a_no_op(tmp_path):
    from arp.storage.postgres_company_facts_projection import materialize_run
    from arp.storage.postgres_models import CompanyFactModel

    store = _completed_run(tmp_path, rows=[{"_key": UNIVERSE_ONLY_COMPANY, "overall_confidence": 0.5}])

    assert materialize_run(DSN, store, "run_1") == 0
    assert len(_rows(CompanyFactModel)) == 1


def test_a_changed_value_supersedes_rather_than_overwrites(tmp_path):
    """The versioning contract: a correction closes the old row and inserts
    a new current one, so "what did we believe on date X" stays answerable."""
    from arp.storage.postgres_company_facts_projection import materialize_run
    from arp.storage.postgres_models import CompanyFactModel

    store = _completed_run(tmp_path, rows=[{"_key": UNIVERSE_ONLY_COMPANY, "overall_confidence": 0.5}])
    # A re-run of the same run_id with a corrected figure.
    store.results_path("run_1").unlink()
    RunStore.append_jsonl(store.results_path("run_1"), {"_key": UNIVERSE_ONLY_COMPANY, "overall_confidence": 0.95})

    assert materialize_run(DSN, store, "run_1") == 1

    facts = sorted(_rows(CompanyFactModel), key=lambda f: f.id)
    assert len(facts) == 2
    closed, current = facts
    assert closed.is_current is False and closed.valid_to is not None and closed.superseded_by_id == current.id
    assert closed.confidence == 0.5
    assert current.is_current is True and current.valid_to is None
    assert current.confidence == 0.95


def test_a_reviewed_fact_records_the_decision_and_reviewer(tmp_path):
    from arp.orchestration import review_queue
    from arp.storage.postgres_company_facts_projection import materialize_run
    from arp.storage.postgres_models import CompanyFactModel

    store = RunStore(tmp_path / "runs")
    RunStore.append_jsonl(store.results_path("run_1"), {"_key": UNIVERSE_ONLY_COMPANY, "overall_confidence": 0.3})
    RunStore.append_jsonl(
        store.review_queue_path("run_1"), {"item_key": UNIVERSE_ONLY_COMPANY, "run_id": "run_1", "payload": {}}
    )
    store.save_manifest(RunManifest(run_id="run_1", run_type="extraction", status=JobStatus.COMPLETED))

    # Queued but undecided -> provisional.
    materialize_run(DSN, store, "run_1")
    assert [f.status for f in _rows(CompanyFactModel)] == ["pending_review"]

    review_queue.record_review_decision(
        store,
        "run_1",
        item_key=UNIVERSE_ONLY_COMPANY,
        decision="approve",
        reviewer="analyst@example.com",
        edited_value=None,
    )
    materialize_run(DSN, store, "run_1")

    current = [f for f in _rows(CompanyFactModel) if f.is_current]
    assert [(f.status, f.reviewer) for f in current] == [("approved", "analyst@example.com")]


# --- engagement ------------------------------------------------------------


def test_engagement_issues_and_commitments_project_on_save(tmp_path):
    from arp.storage.postgres_models import EngagementCommitmentModel, EngagementIssueModel

    store = EngagementStore(
        tmp_path / "engagements",
        projection_config=ProjectionConfig(postgres_dsn=DSN, engagement_projection_enabled=True),
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
        projection_config=ProjectionConfig(postgres_dsn=DSN, engagement_projection_enabled=True),
    )
    _record, issue = store.open_issue(UNIVERSE_ONLY_COMPANY, "Acme Corp", theme="board independence")

    store.set_issue_status(UNIVERSE_ONLY_COMPANY, issue.issue_id, IssueStatus.STALLED)

    issues = _rows(EngagementIssueModel)
    assert [(i.issue_id, i.status) for i in issues] == [(issue.issue_id, "stalled")]


def test_a_disabled_projection_writes_nothing(tmp_path):
    """The default configuration: the file stores work exactly as before and
    Postgres is never touched."""
    from arp.storage.postgres_models import CompanyRecordModel, EngagementIssueModel

    run_store = RunStore(tmp_path / "runs", projection_config=ProjectionConfig(postgres_dsn=DSN))
    RunStore.append_jsonl(run_store.results_path("run_1"), {"_key": UNIVERSE_ONLY_COMPANY})
    run_store.save_manifest(RunManifest(run_id="run_1", run_type="extraction", status=JobStatus.COMPLETED))

    engagement_store = EngagementStore(tmp_path / "engagements", projection_config=ProjectionConfig(postgres_dsn=DSN))
    engagement_store.open_issue(UNIVERSE_ONLY_COMPANY, "Acme Corp", theme="climate")

    assert _rows(CompanyRecordModel) == []
    assert _rows(EngagementIssueModel) == []
