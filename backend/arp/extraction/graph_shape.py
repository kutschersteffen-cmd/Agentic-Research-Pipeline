from __future__ import annotations

from typing import Any, Awaitable, Callable

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph


def build_extract_verify_graph(
    state_cls: type,
    *,
    gather_evidence: Callable[[Any], Awaitable[dict]],
    route_after_evidence: Callable[[Any], str],
    finalize_no_evidence: Callable[[Any], Awaitable[dict]],
    extract: Callable[[Any], Awaitable[dict]],
    verify: Callable[[Any], Awaitable[dict]],
    aggregate: Callable[[Any], Awaitable[dict]],
) -> CompiledStateGraph:
    """The shared 5-node shape behind every extractor/verifier pipeline in
    this package: gather evidence, route on whether any was found, and
    either finalize immediately (no evidence) or run extract -> verify ->
    aggregate. field_graph.py and financials_graph.py both compile a graph
    from this one shape, supplying only their own domain-specific node
    bodies -- the topology itself, and the risk of the two drifting apart
    on a future edit, lives in exactly one place.
    """
    graph = StateGraph(state_cls)
    graph.add_node("gather_evidence", gather_evidence)
    graph.add_node("finalize_no_evidence", finalize_no_evidence)
    graph.add_node("extract", extract)
    graph.add_node("verify", verify)
    graph.add_node("aggregate", aggregate)

    graph.set_entry_point("gather_evidence")
    graph.add_conditional_edges(
        "gather_evidence", route_after_evidence, {"extract": "extract", "finalize_no_evidence": "finalize_no_evidence"}
    )
    graph.add_edge("finalize_no_evidence", END)
    graph.add_edge("extract", "verify")
    graph.add_edge("verify", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()
