import asyncio
import json
import subprocess
import sys
import threading

import pytest

from arp.config import Settings
from arp.discovery.identity_pipeline import create_identity_run
from arp.discovery.pipeline import create_discovery_run
from arp.extraction.financials_pipeline import create_financials_extraction_run
from arp.orchestration.batch_runner import read_done_keys
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import LocalJobLauncher, RunBusy, run_lease
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore
from arp.transition_plan.pipeline import create_transition_plan_run

COMPANIES = [CompanyRef(company_id="c1", name="One"), CompanyRef(company_id="c2", name="Two", ticker="TWO")]


def test_run_lease_refuses_second_holder(tmp_path):
    store = RunStore(tmp_path)
    with run_lease(store, "r1"):
        with pytest.raises(RunBusy), run_lease(RunStore(tmp_path), "r1"):
            pass
        seen = []

        def other():
            try:
                with run_lease(store, "r1"):
                    pass
            except RunBusy:
                seen.append("busy")

        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert seen == ["busy"]
    with run_lease(store, "r1"):
        pass


def test_run_lease_released_when_process_killed(tmp_path):
    code = (
        "import sys, time; from pathlib import Path\n"
        "from arp.orchestration.jobs import run_lease\n"
        "from arp.storage.run_store import RunStore\n"
        "with run_lease(RunStore(Path(sys.argv[1])), 'r1'):\n"
        "    print('ready', flush=True); time.sleep(60)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "ready"
        with pytest.raises(RunBusy), run_lease(RunStore(tmp_path), "r1"):
            pass
    finally:
        proc.kill()
        proc.wait()
    with run_lease(RunStore(tmp_path), "r1"):
        pass


def test_local_launcher_runs_job_under_lease(tmp_path):
    store = RunStore(tmp_path)
    outcome = []

    async def job():
        try:
            with run_lease(store, "r1"):
                outcome.append("got lease")
        except RunBusy:
            outcome.append("busy")

    async def go():
        launcher = LocalJobLauncher(lambda: store)
        launcher.launch("r1", job)
        await asyncio.gather(*launcher._tasks)
        assert not launcher._tasks

    asyncio.run(go())
    assert outcome == ["busy"]


def test_create_run_stores_companies(tmp_path):
    store = RunStore(tmp_path)
    jm = JobManager(store)
    run = jm.create_run("extraction", {}, 2, companies=COMPANIES)
    assert store.load_companies(run.run_id) == COMPANIES
    assert store.load_companies(jm.create_run("extraction", {}, 0).run_id) is None


def test_review_stopped_key_counts_as_done(tmp_path):
    results, errors = tmp_path / "results.jsonl", tmp_path / "errors.jsonl"
    results.write_text(json.dumps({"_key": "c0"}) + "\n")
    errors.write_text(
        json.dumps({"key": "c1", "error": "x", "review": True, "report": {}}) + "\n" + json.dumps({"key": "c2", "error": "y"}) + "\n"
    )
    assert read_done_keys(results, errors) == {"c0", "c1"}
    assert read_done_keys(results) == {"c0"}


def test_creators_store_companies(tmp_path):
    store = RunStore(tmp_path)
    settings = Settings()
    ids = [
        create_financials_extraction_run(COMPANIES, settings, store),
        create_transition_plan_run(COMPANIES, settings, store),
        create_identity_run(COMPANIES, store),
        create_discovery_run(COMPANIES, None, "test", store),
    ]
    for run_id in ids:
        assert store.load_companies(run_id) == COMPANIES


def test_concurrent_discovery_execute_is_refused(tmp_path, monkeypatch):
    import arp.discovery.pipeline as discovery

    store = RunStore(tmp_path)
    run_id = create_discovery_run(COMPANIES, None, "test", store)
    started, release = asyncio.Event(), asyncio.Event()

    async def _discover(company, **_kwargs):
        started.set()
        await release.wait()
        raise RuntimeError("stub")

    monkeypatch.setattr(discovery, "_discover_for_company", _discover)
    settings = Settings(runs_dir=tmp_path)

    def _execute():
        return discovery.execute_discovery_run(run_id, COMPANIES, settings=settings, run_store=store, search_client=object())

    async def go():
        task = asyncio.create_task(_execute())
        await started.wait()
        with pytest.raises(RunBusy):
            await _execute()
        release.set()
        await task

    asyncio.run(go())
