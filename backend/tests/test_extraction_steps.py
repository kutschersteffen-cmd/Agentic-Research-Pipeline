"""The node editor's pipeline shapes, and the per-step counts a run records."""

import asyncio
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph

from arp.config import Settings
from arp.extraction.steps import PROFILES, SETTING_INFO, StepSettings, pipeline_shape, restart_overrides
from arp.llm.cache import DiskLLMCache
from arp.orchestration.step_tally import on_company, run_graph, step_counts, tally_run
from arp.storage.run_store import RunStore


@pytest.mark.parametrize("profile", list(PROFILES))
def test_shape_matches_the_graph_that_runs(profile):
    shape = pipeline_shape(profile, Settings())
    ids = {n["id"] for n in shape["nodes"]}
    assert {"item", "gather_evidence", "verify", "aggregate", "company", "rules"} <= ids
    # Every node that exposes settings is a real node, so a renamed graph node fails here.
    assert set(PROFILES[profile]["settings"]) <= ids
    assert all(k in SETTING_INFO for n in shape["nodes"] for k in n["settings"])
    assert {(e["source"], e["target"]) for e in shape["edges"]} >= {("item", "gather_evidence"), ("company", "rules")}
    assert set(shape["defaults"]) == set(StepSettings.model_fields)


class _S(TypedDict):
    found: bool
    out: str


def _toy_graph():
    g = StateGraph(_S)
    g.add_node("look", lambda s: {})
    g.add_node("none", lambda s: {"out": "none"})
    g.add_node("use", lambda s: {"out": "used"})
    g.set_entry_point("look")
    g.add_conditional_edges("look", lambda s: "use" if s["found"] else "none", {"use": "use", "none": "none"})
    g.add_edge("none", END)
    g.add_edge("use", END)
    return g.compile()


def test_run_graph_counts_each_visited_node(tmp_path):
    store, graph = RunStore(tmp_path), _toy_graph()

    async def run():
        with tally_run(store, "run_1"):
            finals = []
            for company, found in (("a", True), ("a", True), ("b", False)):
                with on_company(company):
                    finals.append(await run_graph(graph, {"found": found, "out": ""}))
            view, live = step_counts(store, "run_1")
            assert live and view["counts"] == {"look": 3, "use": 2, "none": 1}
        return finals

    finals = asyncio.run(run())
    assert [f["out"] for f in finals] == ["used", "used", "none"]
    view, live = step_counts(store, "run_1")
    assert not live and view["counts"] == {"look": 3, "use": 2, "none": 1} and set(view["seconds"]) == {"look", "use", "none"}
    assert step_counts(store, "run_1", "b")[0]["counts"] == {"look": 1, "none": 1}
    assert step_counts(store, "run_1", "nobody")[0]["counts"] == {}


def test_run_graph_outside_a_run_just_invokes():
    assert asyncio.run(run_graph(_toy_graph(), {"found": False, "out": ""}))["out"] == "none"


def test_restart_skips_caches_from_the_step_on():
    assert restart_overrides("gather_evidence") == {"document_cache_enabled": False, "llm_cache_refresh": True}
    assert restart_overrides("extract") == restart_overrides("answer") == {"llm_cache_refresh": True}
    assert restart_overrides("verify") == {"llm_verifier_cache_refresh": True}
    assert restart_overrides("aggregate") == {}


def test_a_refreshing_cache_writes_but_never_reads(tmp_path):
    DiskLLMCache(tmp_path).set("k", {"v": 1})
    refreshing = DiskLLMCache(tmp_path, refresh=True)
    assert refreshing.get("k") is None
    refreshing.set("k", {"v": 2})
    assert DiskLLMCache(tmp_path).get("k") == {"v": 2}
