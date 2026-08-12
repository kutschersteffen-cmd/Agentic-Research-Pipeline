from arp.orchestration.job_manager import JobManager
from arp.schemas.common import JobStatus
from arp.storage.run_store import RunStore


def test_create_run_and_progress_lifecycle(tmp_path):
    store = RunStore(tmp_path)
    jm = JobManager(store)

    manifest = jm.create_run("theme", {"a": 1}, company_count=10, model="claude-sonnet-5")
    assert manifest.status == JobStatus.RUNNING
    assert manifest.company_count == 10

    jm.record_progress(manifest.run_id, completed_delta=3, input_tokens_delta=100, cost_delta_usd=0.05)
    jm.record_progress(manifest.run_id, completed_delta=2, failed_delta=1, review_delta=1)
    updated = store.load_manifest(manifest.run_id)
    assert updated.completed_count == 5
    assert updated.failed_count == 1
    assert updated.review_count == 1
    assert updated.input_tokens == 100
    assert abs(updated.estimated_cost_usd - 0.05) < 1e-9

    final = jm.finish_run(manifest.run_id)
    assert final.status == JobStatus.PARTIALLY_COMPLETED  # because failed_count > 0


def test_finish_run_completed_when_no_failures(tmp_path):
    store = RunStore(tmp_path)
    jm = JobManager(store)
    manifest = jm.create_run("extraction", {}, company_count=1)
    jm.record_progress(manifest.run_id, completed_delta=1)
    final = jm.finish_run(manifest.run_id)
    assert final.status == JobStatus.COMPLETED


def test_finish_run_with_error(tmp_path):
    store = RunStore(tmp_path)
    jm = JobManager(store)
    manifest = jm.create_run("discovery", {}, company_count=1)
    final = jm.finish_run(manifest.run_id, error="boom")
    assert final.status == JobStatus.FAILED
    assert final.error == "boom"


def test_request_cancel_sets_flag(tmp_path):
    store = RunStore(tmp_path)
    jm = JobManager(store)
    manifest = jm.create_run("theme", {}, company_count=1)
    assert manifest.cancel_requested is False
    updated = jm.request_cancel(manifest.run_id)
    assert updated.cancel_requested is True
    assert store.load_manifest(manifest.run_id).cancel_requested is True


def test_finish_run_cancelled_when_incomplete_and_cancel_requested(tmp_path):
    store = RunStore(tmp_path)
    jm = JobManager(store)
    manifest = jm.create_run("theme", {}, company_count=5)
    jm.record_progress(manifest.run_id, completed_delta=2)
    jm.request_cancel(manifest.run_id)
    final = jm.finish_run(manifest.run_id)
    assert final.status == JobStatus.CANCELLED


def test_finish_run_completed_even_if_cancel_requested_after_everything_finished(tmp_path):
    """A cancel request that lands after the batch already finished shouldn't
    retroactively relabel a clean completion as cancelled."""
    store = RunStore(tmp_path)
    jm = JobManager(store)
    manifest = jm.create_run("theme", {}, company_count=2)
    jm.record_progress(manifest.run_id, completed_delta=2)
    jm.request_cancel(manifest.run_id)
    final = jm.finish_run(manifest.run_id)
    assert final.status == JobStatus.COMPLETED


def test_list_runs_filters_by_type(tmp_path):
    store = RunStore(tmp_path)
    jm = JobManager(store)
    jm.create_run("theme", {}, 1)
    jm.create_run("extraction", {}, 1)
    assert len(store.list_runs()) == 2
    assert len(store.list_runs("theme")) == 1
    assert store.list_runs("theme")[0].run_type == "theme"
