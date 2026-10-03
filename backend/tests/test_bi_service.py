from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arp.bi import service
from arp.bi.catalog import BI_DATABASE, VIEW_DATASETS
from arp.bi.compiler import plan_hash
from arp.bi.plan import ChartPlan, ChartSpec, DatasetMeta
from arp.bi.planner import PlannerRefusal
from arp.bi.service import BIError, ask_chart, design_dashboard, embed_token
from arp.bi.superset_client import SupersetError
from arp.llm.base import LLMClient, LLMUsage

WRITES = {"create_chart", "create_dashboard", "update_dashboard", "delete_chart", "delete_dashboard", "ensure_embedded"}


class FakeLLM(LLMClient):
    def __init__(self, *outputs: PlannerRefusal) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    async def complete_structured(self, *, system, prompt, output_model, **kw):
        self.prompts.append(prompt)
        return self.outputs.pop(0), LLMUsage()


class FakeClient:
    """In-memory SupersetClient: records every call, can fail the Nth create_chart."""

    def __init__(self, fail_on_chart: int | None = None) -> None:
        self.calls: list[tuple] = []
        self.fail_on_chart = fail_on_chart
        self.charts: dict[int, str] = {}
        self.dashboards: dict[str, dict] = {}  # slug -> {id, published, charts, position}
        self.datasets = {d.table: i for i, d in enumerate(VIEW_DATASETS.values(), start=1)}
        self._next = 100

    def _id(self) -> int:
        self._next += 1
        return self._next

    def find_database(self, name):
        self.calls.append(("find_database", name))
        return 1 if name == BI_DATABASE else None

    def find_dataset(self, database_id, schema, table):
        self.calls.append(("find_dataset", table))
        return self.datasets.get(table)

    def dataset_meta(self, dataset_id):
        self.calls.append(("dataset_meta", dataset_id))
        name = next(n for n, d in VIEW_DATASETS.items() if self.datasets[d.table] == dataset_id)
        d = VIEW_DATASETS[name]
        return DatasetMeta(columns=set(d.columns), metrics={m.name for m in d.metrics})

    def create_chart(self, name, dataset_id, viz_type, params):
        self.calls.append(("create_chart", name))
        if self.fail_on_chart == len([c for c in self.calls if c[0] == "create_chart"]):
            raise SupersetError(422, "bad params")
        cid = self._id()
        self.charts[cid] = name
        return cid

    def create_dashboard(self, title, slug, position_json, chart_ids):
        self.calls.append(("create_dashboard", slug))
        did = self._id()
        # The real client always sends published=False; record it as the payload would.
        self.dashboards[slug] = {"id": did, "published": False, "charts": list(chart_ids), "position": position_json}
        return did

    def update_dashboard(self, dashboard_id, position_json, chart_ids):
        self.calls.append(("update_dashboard", dashboard_id))
        d = next(d for d in self.dashboards.values() if d["id"] == dashboard_id)
        d["charts"] += [c for c in chart_ids if c not in d["charts"]]
        d["position"] = position_json

    def dashboard_charts(self, dashboard_id):
        self.calls.append(("dashboard_charts", dashboard_id))
        d = next(d for d in self.dashboards.values() if d["id"] == dashboard_id)
        return {c: self.charts[c] for c in d["charts"]}

    def find_dashboard(self, slug):
        self.calls.append(("find_dashboard", slug))
        return self.dashboards[slug]["id"] if slug in self.dashboards else None

    def delete_chart(self, id):
        self.calls.append(("delete_chart", id))
        del self.charts[id]

    def delete_dashboard(self, id):
        self.calls.append(("delete_dashboard", id))

    def ensure_embedded(self, dashboard_id):
        self.calls.append(("ensure_embedded", dashboard_id))
        return "uuid-1"

    def guest_token(self, dashboard_id, rls):
        self.calls.append(("guest_token", dashboard_id, rls))
        return "tok"

    def writes(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in WRITES]


def _spec(title: str, **kw) -> ChartSpec:
    spec = dict(title=title, viz_type="pie", dataset="holdings", metrics=["Exposure (EUR)"], groupby=["sector"])
    spec.update(kw)
    return ChartSpec(**spec)


PLAN = ChartPlan(title="Exposure", charts=[_spec("A"), _spec("B"), _spec("C")])


def run(coro):
    return asyncio.run(coro)


def test_rejected_plan_makes_no_superset_writes():
    client = FakeClient()
    res = run(design_dashboard("weather?", FakeLLM(PlannerRefusal(clarification_needed="No weather data.")), client))
    assert res.dashboard_id is None and res.plan is None and res.url is None
    assert res.rejected == ["No weather data."]
    assert client.writes() == []


def test_missing_dataset_fails_clearly_before_planning():
    client = FakeClient()
    del client.datasets["holdings"]
    llm = FakeLLM()
    with pytest.raises(BIError, match="arp bi bootstrap"):
        run(design_dashboard("x", llm, client))
    assert llm.prompts == [] and client.writes() == []


def test_failure_on_third_chart_deletes_first_two():
    client = FakeClient(fail_on_chart=3)
    with pytest.raises(BIError, match="'C'"):
        run(design_dashboard("exposure", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    assert [c for c in client.calls if c[0] == "delete_chart"] == [("delete_chart", 101), ("delete_chart", 102)]
    assert client.charts == {} and not any(c[0] == "create_dashboard" for c in client.calls)


def test_dashboard_failure_deletes_charts_and_the_half_made_dashboard():
    client = FakeClient()

    def boom(title, slug, position_json, chart_ids):
        client.dashboards[slug] = {"id": 999, "published": False, "charts": [], "position": {}}  # created, attach failed
        raise SupersetError(500, "attach failed")

    client.create_dashboard = boom
    with pytest.raises(BIError, match="Exposure"):
        run(design_dashboard("exposure", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    assert client.charts == {} and ("delete_dashboard", 999) in client.calls


def test_dashboard_created_unpublished():
    client = FakeClient()
    res = run(design_dashboard("exposure", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    slug = f"arp-{plan_hash(PLAN)}"
    assert res.slug == slug and res.plan == PLAN and res.rejected == []
    assert res.url.endswith(f"/superset/dashboard/{slug}/")
    dash = client.dashboards[slug]
    assert res.dashboard_id == dash["id"] and dash["published"] is False
    assert dash["charts"] == [101, 102, 103]
    assert [k for k in dash["position"] if k.startswith("CHART-")] == ["CHART-101", "CHART-102", "CHART-103"]


def test_same_plan_reuses_dashboard_by_slug():
    client = FakeClient()
    first = run(design_dashboard("exposure", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    n_writes = len(client.writes())
    again = run(design_dashboard("exposure", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    assert again.dashboard_id == first.dashboard_id and again.slug == first.slug
    assert len(client.writes()) == n_writes


def test_ask_lands_on_scratch_dashboard():
    client = FakeClient()
    q1 = ChartPlan(title="Q", charts=[_spec("By sector"), _spec("Extra")])
    q2 = ChartPlan(title="Q", charts=[_spec("By portfolio", groupby=["portfolio_name"])])
    llm = FakeLLM(PlannerRefusal(plan=q1), PlannerRefusal(plan=q2))
    r1 = run(ask_chart("exposure by sector?", llm, client))
    r2 = run(ask_chart("exposure by portfolio?", llm, client))
    assert r1.slug == r2.slug == "arp-scratch" and r1.dashboard_id == r2.dashboard_id
    assert [c.title for c in r1.plan.charts] == ["By sector"]  # one chart per question
    assert "one chart" in llm.prompts[0]
    dash = client.dashboards["arp-scratch"]
    assert dash["published"] is False and dash["charts"] == [101, 103]
    # position_json rebuilt from all of the scratch dashboard's charts
    assert [k for k in dash["position"] if k.startswith("CHART-")] == ["CHART-101", "CHART-103"]
    assert [c[0] for c in client.writes()] == ["create_chart", "create_dashboard", "create_chart", "update_dashboard"]


def test_ask_failure_on_update_deletes_new_chart_but_keeps_scratch():
    client = FakeClient()
    llm = FakeLLM(
        PlannerRefusal(plan=ChartPlan(title="Q", charts=[_spec("A")])),
        PlannerRefusal(plan=ChartPlan(title="Q", charts=[_spec("B")])),
    )
    run(ask_chart("a", llm, client))

    def boom(*a):
        raise SupersetError(500, "nope")

    client.update_dashboard = boom
    with pytest.raises(BIError, match="'B'"):
        run(ask_chart("b", llm, client))
    assert list(client.charts.values()) == ["A"] and not any(c[0] == "delete_dashboard" for c in client.calls)


def test_no_code_path_publishes():
    client = FakeClient()
    run(design_dashboard("x", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    run(ask_chart("y", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    run(ask_chart("z", FakeLLM(PlannerRefusal(plan=PLAN)), client))
    assert all(d["published"] is False for d in client.dashboards.values())
    # The real client hardcodes published=False and has no publish path; nothing here may set it.
    src = Path(service.__file__).read_text()
    assert "published" not in src


def test_embed_token_ensures_embedded_first():
    client = FakeClient()
    assert embed_token(client, "7") == "tok"
    assert client.calls == [("ensure_embedded", 7), ("guest_token", "uuid-1", [])]
