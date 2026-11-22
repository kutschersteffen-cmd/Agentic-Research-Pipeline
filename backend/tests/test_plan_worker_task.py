"""The API plan worker's task callback: it drops its strong reference and logs a worker that died."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from arp.api.routers import plans


async def _ended(coro_or_cancel) -> asyncio.Task:
    task = asyncio.create_task(asyncio.sleep(10) if coro_or_cancel == "cancel" else coro_or_cancel)
    plans._running.add(task)
    if coro_or_cancel == "cancel":
        task.cancel()
    with contextlib.suppress(BaseException):  # the callback is what is tested
        await task
    return task


async def _boom():
    raise RuntimeError("boom")


async def _ok():
    return None


def test_failed_worker_is_logged_and_released(caplog):
    caplog.set_level(logging.ERROR, logger=plans.logger.name)
    task = asyncio.run(_ended(_boom()))
    plans._done(task)
    assert task not in plans._running
    [record] = [r for r in caplog.records if r.name == plans.logger.name]
    assert (record.levelno, record.getMessage()) == (logging.ERROR, "plan worker failed")
    assert isinstance(record.exc_info[1], RuntimeError) and str(record.exc_info[1]) == "boom"


def test_cancelled_or_finished_worker_is_released_silently(caplog):
    caplog.set_level(logging.DEBUG, logger=plans.logger.name)
    for task in (asyncio.run(_ended("cancel")), asyncio.run(_ended(_ok()))):
        plans._done(task)
        assert task not in plans._running
    assert [r for r in caplog.records if r.name == plans.logger.name] == []
