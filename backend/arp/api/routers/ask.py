"""Ask ARP: one question, routed by the model to one read-only tool; code computes every figure. Every handled call
(answered or failed) leaves one audit row, like Ask the Portfolio and Smart Search."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from arp import ask, smart_search
from arp.api.auth import Principal, current_user
from arp.api.deps import (
    get_decision_store,
    get_identifier_map,
    get_index_store,
    get_llm_client,
    get_portfolio_store,
    get_reporting_store,
    get_run_store,
    get_stream_store,
    get_taxonomy_store,
    settings_dep,
)
from arp.api.routers.security_master import datahub_lists
from arp.config import Settings
from arp.llm.base import LLMClient
from arp.portfolio import qa_agent, qa_audit
from arp.stewardship.benchmark import BenchmarkStore
from arp.stewardship.process import StreamStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import portfolio_directories
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/ask", tags=["ask"])

ERROR_DETAIL = "Ask could not answer this question. Try again."

ROUTING_SYSTEM_PROMPT = """\
You route one question about an investment research tool's data to exactly one tool. You never answer the question
and never state a number: code runs the tool you pick and computes every figure.

tool:
- "portfolio": exposures, weights or counts over the firm's portfolio holdings (e.g. exposure to a company, sector
  or asset class).
- "smart_search": open data issues, stored outputs (universes, runs, publications, taxonomies, calibrations) or input
  feeds that failed or are behind.
- "transition_plan": a company's newest transition plan assessment. Set company to the company exactly as the user
  wrote it.
- "benchmark_sectors": the sector distribution or sector weights of a benchmark index such as MSCI World. Set
  benchmark_id to one id from the uploaded benchmarks below, or null if none fits.
- "none": anything else (what a document says, why something was flagged, how to use the tool).

standalone_question: the question rewritten so it reads on its own, using the earlier questions for anything it
leaves out (a follow-up like "now only equities" becomes the full earlier question restricted to equities).
"""


def _prompt(req: ask.AskRequest, benchmarks: list[dict]) -> str:
    listed = "\n".join(f"- {b['benchmark_id']}: {b['name']} (as of {b['as_of']})" for b in benchmarks) or "(none uploaded)"
    earlier = "\n".join(f"- {t.standalone_question} [{t.tool}]" for t in req.history) or "(none)"
    return f"Uploaded benchmarks:\n{listed}\n\nEarlier questions, oldest first:\n{earlier}\n\nQuestion: {req.question}"


@router.post("", response_model=ask.AskResponse)
async def post_ask(
    req: ask.AskRequest, settings: Settings = Depends(settings_dep), store=Depends(get_portfolio_store),
    idmap: IdentifierMapStore = Depends(get_identifier_map), run_store: RunStore = Depends(get_run_store),
    decisions=Depends(get_decision_store), taxonomy=Depends(get_taxonomy_store), index=Depends(get_index_store),
    reports=Depends(get_reporting_store), streams: StreamStore = Depends(get_stream_store),
    llm: LLMClient = Depends(get_llm_client), principal: Principal = Depends(current_user),
) -> ask.AskResponse:
    tool, response, error = None, None, None
    try:
        benchmarks = await run_in_threadpool(BenchmarkStore(streams.root).list)
        routing, _usage = await llm.complete_structured(system=ROUTING_SYSTEM_PROMPT, prompt=_prompt(req, benchmarks), output_model=ask.AskRouting)
        tool = routing.tool
        answer = {"tool": tool, "question": req.question, "standalone_question": routing.standalone_question}
        if tool == "portfolio":
            securities, companies = portfolio_directories(store)
            qa, _usage = await qa_agent.answer_question(routing.standalone_question, llm, store, securities, companies)
            answer |= {"portfolio": qa, "answer_text": qa.answer_text if qa.resolvable else qa.clarification_needed}
        elif tool == "smart_search":
            lists = await run_in_threadpool(datahub_lists, settings, store, idmap, run_store, decisions, taxonomy, index, reports, date.today())
            found, _usage = await smart_search.smart_search(routing.standalone_question, llm, **lists)
            answer |= {"smart_search": found, "answer_text": found.answer_text if found.resolvable else found.clarification_needed}
        elif tool == "transition_plan":
            card, text = await run_in_threadpool(ask.newest_transition_plan, run_store, principal, routing.company)
            answer |= {"transition_plan": card, "answer_text": text}
        elif tool == "benchmark_sectors":
            card, text = await run_in_threadpool(ask.benchmark_sectors, streams.root, routing.benchmark_id)
            answer |= {"benchmark_sectors": card, "answer_text": text}
        else:
            answer["answer_text"] = ask.NONE_TEXT
        response = ask.AskResponse(**answer, answered_at=datetime.now(UTC).isoformat())
        return response
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise HTTPException(502, ERROR_DETAIL) from exc
    finally:
        qa_audit.record_answer(
            settings, endpoint=f"ask.{tool or 'error'}", principal=principal, question=req.question,
            answer_text=response.answer_text if response else None, vintage={}, error=error,
        )
