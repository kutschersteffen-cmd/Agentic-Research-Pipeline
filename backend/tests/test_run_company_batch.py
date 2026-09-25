from dataclasses import dataclass

from arp.llm.base import LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef, JobStatus
from arp.storage.run_store import RunStore


@dataclass
class _Result:
    company_id: str
    flagged: bool
    usage: LLMUsage


def _companies(*ids: str) -> list[CompanyRef]:
    return [CompanyRef(company_id=i, name=i.title()) for i in ids]


async def _run(run_store: RunStore, run_id: str, companies: list[CompanyRef], worker) -> None:
    await run_company_batch(
        run_id,
        companies,
        run_store=run_store,
        worker=worker,
        result_to_json=lambda r: {"company_id": r.company_id},
        review_items=lambda c, r: [(c.company_id, {"company_id": c.company_id})] if r.flagged else [],
        cost_usd=lambda r: 0.5,
        concurrency=2,
    )


async def test_progress_review_queue_and_failures_are_recorded(tmp_path):
    run_store = RunStore(tmp_path)
    companies = _companies("ok", "flagged", "broken")
    run_id = JobManager(run_store).create_run("test", {}, len(companies)).run_id

    async def worker(c: CompanyRef) -> _Result:
        if c.company_id == "broken":
            raise RuntimeError("boom")
        return _Result(c.company_id, c.company_id == "flagged", LLMUsage(input_tokens=10, output_tokens=3))

    await _run(run_store, run_id, companies, worker)

    results = run_store.read_jsonl(run_store.results_path(run_id))
    assert sorted(r["company_id"] for r in results) == ["flagged", "ok"]
    assert [r["item_key"] for r in run_store.read_jsonl(run_store.review_queue_path(run_id))] == ["flagged"]
    assert [e["key"] for e in run_store.read_jsonl(run_store.errors_path(run_id))] == ["broken"]

    m = run_store.load_manifest(run_id)
    assert (m.completed_count, m.failed_count, m.review_count) == (2, 1, 1)
    assert (m.input_tokens, m.output_tokens, m.estimated_cost_usd) == (20, 6, 1.0)
    assert m.status == JobStatus.PARTIALLY_COMPLETED


async def test_cancel_requested_stops_new_items_and_marks_run_cancelled(tmp_path):
    run_store = RunStore(tmp_path)
    companies = _companies("a", "b", "c")
    job_manager = JobManager(run_store)
    run_id = job_manager.create_run("test", {}, len(companies)).run_id
    job_manager.request_cancel(run_id)

    async def worker(c: CompanyRef) -> _Result:
        raise AssertionError("no item should start after cancel")

    await _run(run_store, run_id, companies, worker)

    assert run_store.load_manifest(run_id).status == JobStatus.CANCELLED
