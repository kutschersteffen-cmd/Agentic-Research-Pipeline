import asyncio
import logging
import tempfile
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

from arp.api.routers.stewardship import _deck_response
from arp.api.run_scheduling import _tasks, keep_task


async def test_keep_task_logs_a_failure_and_drops_the_task(caplog):
    async def boom() -> None:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR):
        keep_task(boom())
        assert len(_tasks) == 1
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert not _tasks
    assert any(r.exc_info and str(r.exc_info[1]) == "boom" for r in caplog.records)


async def test_keep_task_runs_a_task_that_succeeds(caplog):
    done = asyncio.Event()

    async def ok() -> None:
        done.set()

    keep_task(ok())
    await asyncio.wait_for(done.wait(), 1)
    await asyncio.sleep(0)
    assert not _tasks
    assert not caplog.records


def test_deck_response_removes_its_temp_dir_when_the_build_fails(monkeypatch):
    made: list[Path] = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(Path(real(**kw))) or made[-1])

    def build(data, path, pdf=False):
        raise ValueError("deck failed")

    with pytest.raises(ValueError, match="deck failed"):
        _deck_response(build, None, "x.pptx", BackgroundTasks())
    assert made and not made[0].exists()
