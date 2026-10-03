"""Shape-only eval for the BI planner (mirrors golden_set/planner_runner.py).
Needs an API key; not run in CI. Metas are built offline from the catalog."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from arp.bi.catalog import VIEW_DATASETS
from arp.bi.plan import ChartPlan, DatasetMeta
from arp.bi.planner import plan_from_brief
from arp.llm.base import LLMClient

_BUNDLED_CASES_PATH = Path(__file__).parent.parent / "golden_set" / "data" / "bi_cases.json"


class MustInclude(BaseModel):
    datasets: list[str] = []
    viz_types: list[str] = []
    metrics: list[str] = []


class BiCase(BaseModel):
    brief: str
    must_include: MustInclude = MustInclude()
    must_refuse: bool = False


class BiCaseResult(BaseModel):
    brief: str
    passed: bool
    failures: list[str]


def load_bi_cases(path: Path | None = None) -> list[BiCase]:
    return [BiCase.model_validate(c) for c in json.loads((path or _BUNDLED_CASES_PATH).read_text())]


def offline_metas() -> dict[str, DatasetMeta]:
    return {n: DatasetMeta(columns=set(d.columns), metrics={m.name for m in d.metrics}) for n, d in VIEW_DATASETS.items()}


def evaluate_case(case: BiCase, plan: ChartPlan | None, reasons: list[str]) -> BiCaseResult:
    failures: list[str] = []
    if case.must_refuse:
        if plan is not None:
            failures.append("Expected a refusal; the planner produced a plan.")
    elif plan is None:
        failures.append(f"Expected a plan; got none ({'; '.join(reasons)}).")
    else:
        got = {
            "datasets": {c.dataset for c in plan.charts},
            "viz_types": {c.viz_type for c in plan.charts},
            "metrics": {m for c in plan.charts for m in c.metrics},
        }
        for kind, wanted in case.must_include.model_dump().items():
            failures += [
                f"No chart using {kind[:-1]} {w!r} (got: {', '.join(sorted(got[kind])) or 'none'})."
                for w in wanted
                if w not in got[kind]
            ]
    return BiCaseResult(brief=case.brief, passed=not failures, failures=failures)


async def run_bi_set(cases: list[BiCase], *, llm: LLMClient) -> list[BiCaseResult]:
    metas = offline_metas()
    results = []
    for case in cases:
        plan, reasons = await plan_from_brief(case.brief, metas, llm)
        results.append(evaluate_case(case, plan, reasons))
    return results
