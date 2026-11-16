"""superset-ask-fixes-followup: two asks at the same time both land on arp-scratch, and a failed ask releases the lock."""
from __future__ import annotations

import asyncio
import contextlib
import threading
import time

import pytest

from arp.bi.plan import ChartPlan
from arp.bi.planner import PlannerRefusal
from arp.bi.service import BIError, ask_chart
from arp.llm.base import LLMClient, LLMUsage
from tests.test_bi_service import FakeClient, _spec


class ByQuestion(LLMClient):
    async def complete_structured(self, *, system, prompt, output_model, **kw):
        title = "A" if prompt.endswith("qa") else "B"
        return PlannerRefusal(plan=ChartPlan(title=title, charts=[_spec(title)])), LLMUsage()


class Barrier(FakeClient):
    """Makes the first ask wait in `at` until the second ask made the same call: without the lock both meet there."""

    def __init__(self, at: str) -> None:
        super().__init__()
        self.barrier, self.at = threading.Barrier(2), at

    def _meet(self):
        with contextlib.suppress(threading.BrokenBarrierError):
            self.barrier.wait(timeout=0.5)

    def dashboard_charts(self, dashboard_id):
        read = super().dashboard_charts(dashboard_id)  # read first, so both asks see the same charts
        if self.at == "dashboard_charts":
            self._meet()
        return read

    def find_dashboard(self, slug):
        read = super().find_dashboard(slug)
        if self.at == "find_dashboard":
            self._meet()
        return read


async def _both(client):
    llm = ByQuestion()
    return await asyncio.gather(ask_chart("qa", llm, client), ask_chart("qb", llm, client))


def test_two_asks_on_existing_scratch_keep_both_charts():  # AC-1, AC-2
    client = Barrier("dashboard_charts")
    client.charts[1] = "Existing"
    client.dashboards["arp-scratch"] = {"id": 5, "published": False, "charts": [1], "position": {}}
    results = asyncio.run(_both(client))
    assert [(r.slug, r.dashboard_id) for r in results] == [("arp-scratch", 5)] * 2
    layout = client.dashboards["arp-scratch"]["position"]
    assert sorted(k for k in layout if k.startswith("CHART-")) == sorted(f"CHART-{c}" for c in client.charts)
    assert len(client.charts) == 3


def test_two_first_asks_create_scratch_once():  # AC-3, AC-4
    client = Barrier("find_dashboard")
    asyncio.run(_both(client))
    assert [c for c in client.calls if c[0] == "create_dashboard"] == [("create_dashboard", "arp-scratch")]
    layout = client.dashboards["arp-scratch"]["position"]
    assert sorted(k for k in layout if k.startswith("CHART-")) == sorted(f"CHART-{c}" for c in client.charts)
    assert len(client.charts) == 2


def test_failed_ask_releases_the_lock():  # AC-5
    client = FakeClient(fail_on_chart=1)
    client.charts[1] = "Existing"
    client.dashboards["arp-scratch"] = {"id": 5, "published": False, "charts": [1], "position": {}}
    with pytest.raises(BIError):
        asyncio.run(ask_chart("qa", ByQuestion(), client))
    start = time.monotonic()
    result = asyncio.run(asyncio.wait_for(ask_chart("qb", ByQuestion(), client), 5))
    assert (result.slug, result.dashboard_id) == ("arp-scratch", 5) and time.monotonic() - start < 5
