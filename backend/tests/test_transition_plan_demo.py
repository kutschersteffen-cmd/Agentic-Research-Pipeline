"""The synthetic transition plan run (arp/transition_plan/demo.py)."""

import json
from pathlib import Path

from arp.decision import sources
from arp.decision.indicator_list import build_framework, parse_indicator_list
from arp.decision.mechanism import apply_mechanism
from arp.decision.parsing import load_table
from arp.decision.templates import import_template
from arp.schemas.common import JobStatus
from arp.storage.run_store import RunStore
from arp.transition_plan.demo import DEMO_COMPANIES, seed_demo_run

TP_LIST = Path(__file__).resolve().parents[2] / "docs/decision-studio/example-framework/transition-plan/indicators.csv"


async def test_seeds_a_finished_synthetic_run(tmp_path):
    store = RunStore(tmp_path)
    run_id = await seed_demo_run(store)
    manifest = store.load_manifest(run_id)
    records = store.read_jsonl(store.results_path(run_id))
    assert (manifest.run_type, manifest.status, manifest.params["synthetic"]) == ("transition_plan", JobStatus.COMPLETED, True)
    assert manifest.completed_count == len(records) == len(DEMO_COMPANIES)
    assert all(len(r["indicators"]) == 64 and not any(i["citations"] for i in r["indicators"]) for r in records)
    by_name = {r["name"]: r for r in records}
    assert by_name["Quiet Shell Ltd"]["disclosed_count"] == 0
    assert by_name["Northwind Utilities"]["disclosed_count"] > by_name["Iron Ridge Mining"]["disclosed_count"]


async def test_same_seed_same_verdicts(tmp_path):
    store = RunStore(tmp_path)
    a, b = await seed_demo_run(store), await seed_demo_run(store)
    verdicts = lambda run_id: sorted(  # noqa: E731
        (r["company_id"], [i["verdict"] for i in r["indicators"]]) for r in store.read_jsonl(store.results_path(run_id))
    )
    assert a != b and verdicts(a) == verdicts(b)


async def test_the_transition_plan_indicator_list_scores_the_run(tmp_path):
    store = RunStore(tmp_path)
    run_id = await seed_demo_run(store)
    dataset = sources.from_transition_plan_run(store, run_id, include_indicators=True)
    config, _ = build_framework(parse_indicator_list(load_table(TP_LIST)), name="TP")
    result = apply_mechanism(dataset, config)
    assert not result.missing_columns
    tiers = {e.name: e.tier_name for e in result.entities}
    assert tiers["Northwind Utilities"] == "Tier 1" and tiers["Quiet Shell Ltd"] == "Tier 4"


async def test_the_exported_framework_file_scores_the_run_the_same(tmp_path):
    store = RunStore(tmp_path)
    run_id = await seed_demo_run(store)
    dataset = sources.from_transition_plan_run(store, run_id, include_indicators=True)
    built, _ = build_framework(parse_indicator_list(load_table(TP_LIST)), name="TP")
    imported, _ = import_template(json.loads((TP_LIST.parent / "framework.json").read_text()))
    tiers = lambda config: {e.name: e.tier_name for e in apply_mechanism(dataset, config).entities}  # noqa: E731
    assert tiers(imported) == tiers(built)
