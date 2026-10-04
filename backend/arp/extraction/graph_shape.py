from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

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
    try_tagged: Callable[[Any], Awaitable[dict]] | None = None,
    route_after_tagged: Callable[[Any], str] | None = None,
) -> CompiledStateGraph:
    """The shared 5-node shape behind every extractor/verifier pipeline in
    this package: gather evidence, route on whether any was found, and
    either finalize immediately (no evidence) or run extract -> verify ->
    aggregate. field_graph.py and financials_graph.py both compile a graph
    from this one shape, supplying only their own domain-specific node
    bodies -- the topology itself, and the risk of the two drifting apart
    on a future edit, lives in exactly one place.

    `try_tagged` (with `route_after_tagged`, returning "gather_evidence" or
    "end") is an optional entry ahead of evidence gathering: a value taken
    from structured data ends the item there. Left out, the shape is as before.
    """
    graph = StateGraph(state_cls)
    graph.add_node("gather_evidence", gather_evidence)
    graph.add_node("finalize_no_evidence", finalize_no_evidence)
    graph.add_node("extract", extract)
    graph.add_node("verify", verify)
    graph.add_node("aggregate", aggregate)

    if try_tagged is None:
        graph.set_entry_point("gather_evidence")
    else:
        graph.add_node("try_tagged", try_tagged)
        graph.set_entry_point("try_tagged")
        graph.add_conditional_edges("try_tagged", route_after_tagged, {"gather_evidence": "gather_evidence", "end": END})
    graph.add_conditional_edges(
        "gather_evidence", route_after_evidence, {"extract": "extract", "finalize_no_evidence": "finalize_no_evidence"}
    )
    graph.add_edge("finalize_no_evidence", END)
    graph.add_edge("extract", "verify")
    graph.add_edge("verify", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()
