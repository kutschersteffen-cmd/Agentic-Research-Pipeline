from __future__ import annotations

import asyncio

from arp.bi.catalog import VIEW_DATASETS
from arp.bi.eval import evaluate_case, load_bi_cases, offline_metas
from arp.bi.plan import ChartPlan, ChartSpec, DatasetMeta
from arp.bi.planner import PlannerRefusal, plan_from_brief
from arp.llm.base import LLMClient, LLMUsage

METAS = offline_metas()


def _plan(**kw) -> ChartPlan:
    spec = dict(title="Exposure", viz_type="pie", dataset="holdings", metrics=["Exposure (EUR)"], groupby=["sector"])
    spec.update(kw)
    return ChartPlan(title="P", charts=[ChartSpec(**spec)])


class FakeLLM(LLMClient):
    def __init__(self, *outputs: PlannerRefusal) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def complete_structured(self, *, system, prompt, output_model, **kw):
        self.calls.append({"system": system, "prompt": prompt, "output_model": output_model})
        return self.outputs.pop(0), LLMUsage()


def run(brief, llm, metas=METAS):
    return asyncio.run(plan_from_brief(brief, metas, llm))


def test_prompt_contains_metric_descriptions_but_no_row_data():
    llm = FakeLLM(PlannerRefusal(plan=_plan()))
    plan, errs = run("exposure by sector", llm)
    assert errs == [] and plan is not None
    system = llm.calls[0]["system"]
    assert "Total market value in EUR." in system and "Exposure (EUR)" in system
    assert "echarts_timeseries_line" in system and "as_of_date" in system
    assert "never write SQL" in " ".join(system.split())
    assert "Acme" not in system and llm.calls[0]["prompt"].count("exposure by sector") == 1


def test_only_datasets_in_metas_are_offered():
    metas = {"documents": METAS["documents"]}
    llm = FakeLLM(PlannerRefusal(clarification_needed="x"))
    run("docs", llm, metas)
    system = llm.calls[0]["system"]
    assert "documents" in system and "holdings" not in system and "run_records" not in system


def test_pending_backlog_rule_is_stated():
    llm = FakeLLM(PlannerRefusal(clarification_needed="x"))
    run("hi", llm)
    system = llm.calls[0]["system"]
    assert "company_facts_pending" in system and "backlog" in system


def test_invalid_plan_gets_exactly_one_repair_round_with_reasons():
    bad = _plan(viz_type="echarts_timeseries_line", groupby=["sector"])
    llm = FakeLLM(PlannerRefusal(plan=bad), PlannerRefusal(plan=_plan()))
    plan, errs = run("trend", llm)
    assert errs == [] and plan is not None
    assert len(llm.calls) == 2
    assert "needs a date column first in groupby" in llm.calls[1]["prompt"]


def test_second_failure_returns_none_and_reasons():
    bad = _plan(metrics=["Nope"])
    llm = FakeLLM(PlannerRefusal(plan=bad), PlannerRefusal(plan=bad))
    plan, errs = run("x", llm)
    assert plan is None and len(llm.calls) == 2
    assert any("unknown metric 'Nope'" in e for e in errs)


def test_refusal_returned_as_clarification():
    llm = FakeLLM(PlannerRefusal(clarification_needed="No weather data here."))
    plan, errs = run("weather?", llm)
    assert plan is None and errs == ["No weather data here."] and len(llm.calls) == 1


def test_bundled_cases_reference_the_catalog():
    from arp.bi.catalog import VIZ_ALLOWLIST

    cases = load_bi_cases()
    assert len(cases) >= 6 and sum(c.must_refuse for c in cases) >= 2
    metrics = {m.name for d in VIEW_DATASETS.values() for m in d.metrics}
    for c in cases:
        assert set(c.must_include.datasets) <= set(VIEW_DATASETS)
        assert set(c.must_include.viz_types) <= set(VIZ_ALLOWLIST)
        assert set(c.must_include.metrics) <= metrics
    assert any("company_facts_pending" in c.must_include.datasets for c in cases)


def test_evaluate_case_scores_shape():
    case = next(c for c in load_bi_cases() if not c.must_refuse)
    assert not evaluate_case(case, None, ["unclear"]).passed
    refuse = next(c for c in load_bi_cases() if c.must_refuse)
    assert evaluate_case(refuse, None, ["no data"]).passed
    assert not evaluate_case(refuse, _plan(), []).passed
