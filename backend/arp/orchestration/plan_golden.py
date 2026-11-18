"""Planner golden set: does the real model turn known briefs into scripts that pass and take the expected steps?"""
from __future__ import annotations

import json
from pathlib import Path

from arp.llm.base import LLMClient
from arp.orchestration.plan_planner import PlanRejected, draft_plan
from arp.orchestration.plan_store import _checked_dry_run

# The ids the planner may name in golden runs; fixed so a case does not depend on the local library.
CONTEXT = """Ratified taxonomies (universe_build taxonomy_id):
- tax_grid_storage: Grid-scale energy storage
- tax_green_hydrogen: Green hydrogen
- tax_heat_pumps: Heat pumps

Ratified decision frameworks (decision_score framework_id):
- fw_capex_quality: Green capex quality

Universe source files: data/universes/eu_listed.csv, data/universes/us_listed.csv
Extraction schemas: green_capex, transition_plan_indicators
Index calibrations (index_construct calibration_id): cal_eu_pab
Candidate files: data/index/candidates_eu.json"""


class _MemoryStore:
    """Checks and dry-runs like PlanStore.create, without a database."""

    def __init__(self) -> None:
        self.dry_runs: dict[str, list[dict]] = {}

    def create(self, brief: str, script: str, check=None) -> str:
        plan_id = f"golden_{len(self.dry_runs) + 1}"
        self.dry_runs[plan_id] = _checked_dry_run(script, check=check)
        return plan_id


def in_order(kinds: list[str], expected: list[str]) -> bool:
    """`expected` appears in `kinds` in this relative order; other steps may sit in between."""
    it = iter(kinds)
    return all(k in it for k in expected)


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def run_case(case: dict, llm: LLMClient) -> tuple[bool, str]:
    store = _MemoryStore()
    try:
        plan_id = await draft_plan(case["brief"], llm, store, CONTEXT)
    except PlanRejected as exc:
        return False, f"rejected: {str(exc).splitlines()[0]}"
    kinds = [c["kind"] for c in store.dry_runs[plan_id]]
    ok = in_order(kinds, case["expected_kinds"])
    return ok, " -> ".join(kinds)
