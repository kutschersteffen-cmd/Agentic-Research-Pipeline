"""The planner: one LLM call turns a research brief into a plan script; one retry with the checker's errors."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from pydantic import BaseModel, Field

from arp.errors import ClientInputError
from arp.llm.base import LLMClient
from arp.orchestration.plan_api import BUILTINS, STEPS
from arp.orchestration.plan_check import MAX_LINES
from arp.orchestration.plan_store import PlanNotReplannable, PlanStore


class PlanScript(BaseModel):
    script: str = Field(description="The plan script: restricted Python, step calls with keyword arguments only.")


class PlanRejected(ClientInputError):
    """Both attempts failed the checker; the message is the second attempt's errors."""


def step_stubs() -> str:
    """The step functions as Python signatures, the way the planner sees them."""
    lines = []
    for kind, model in STEPS.items():
        args = ", ".join(
            f"{name}: {_type(f.annotation)}" + ("" if f.is_required() else f" = {f.default!r}")
            for name, f in model.model_fields.items())
        lines.append(f"def {kind}(*, {args}) -> Result: ...")
    return "\n".join(lines)


def _type(annotation) -> str:
    return str(annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")


SYSTEM = f"""You write plan scripts for ARP, an investment research pipeline. A plan script chains ARP's
existing run types to answer a research brief. It is a restricted subset of Python:

Allowed: assignments to plain names, for loops, if/else, comparisons, and/or/not, list and dict literals,
list comprehensions, reading attributes and indexes, calls to the step functions below (keyword arguments
only) and to {", ".join(BUILTINS)}.
Not allowed: import, def, class, lambda, while, try, with, arithmetic operators, names starting with _, any
other call. At most {MAX_LINES} lines. Never compute numbers: every number comes from a step.

Step functions:
{{stubs}}

Every step returns a Result with fields: id (str), run_id (str or None), companies (a list; each company
has id, name, included (bool), exposure: one of "pure_play", "significant", "minor", "none").
universe_build starts every plan; pass its run_id on (e.g. universe_run_id=u.run_id). Its source must be one of
the saved universes' file names listed below.
Return only the script."""


def planner_context(taxonomies, frameworks, calibrations=(), universes=()) -> str:
    """What the planner may name: ratified taxonomies (universe_build), decision frameworks, index calibrations,
    saved universes (universe_build source, by file name)."""
    tax = [f"- {t.taxonomy_id}: {t.theme.name}" for t in taxonomies if t.status == "ratified"]
    fw = [f"- {f.framework_id}: {f.name}" for f in frameworks if f.ratified]
    return ("Ratified taxonomies (universe_build taxonomy_id):\n" + ("\n".join(tax) or "- none") +
            "\n\nRatified decision frameworks (decision_score framework_id):\n" + ("\n".join(fw) or "- none") +
            "\n\nIndex calibrations (index_construct calibration_id; it also needs a candidates JSON file the brief "
            "names):\n" + ("\n".join(f"- {c.calibration_id}: {c.name}" for c in calibrations) or "- none") +
            "\n\nSaved universes (universe_build source):\n" + ("\n".join(f"- {u}" for u in universes)
                                                              or "- none saved yet"))


# Extra checks on a script's dry run (one error line each), e.g. the API's saved-universe check.
StepCheck = Callable[[list[dict]], list[str]]


async def draft_plan(brief: str, llm: LLMClient, store: PlanStore, context: str = "",
                     check: StepCheck | None = None) -> str:
    """Store the planner's script as a draft plan and return its id. Raises PlanRejected."""
    system = SYSTEM.replace("{stubs}", step_stubs())
    base = f"Research brief:\n{brief}" + (f"\n\n{context}" if context else "")
    prompt = base
    errors: list[str] = []
    for _ in range(2):
        out, _usage = await llm.complete_structured(system=system, prompt=prompt, output_model=PlanScript)
        try:  # checks the script, then dry-runs it off the event loop
            return await asyncio.to_thread(store.create, brief, out.script, check=check)
        except ValueError as exc:
            errors = str(exc).splitlines()
        prompt = (f"{base}\n\nYour previous script:\n{out.script}\n\n"
                  "It was rejected:\n" + "\n".join(errors) + "\nFix every error.")
    raise PlanRejected("\n".join(errors))


def replan_prompt(plan: dict, calls: list[dict], context: str = "") -> str:
    """What the planner sees when it re-plans a failed plan: the brief, the failed script and its error, and the
    finished steps the new script reads as `previous`."""
    done = [c for c in calls if c["status"] == "done"]
    kept = "\n".join(
        f"- previous[{i}]: step {c['seq']} {c['kind']} {c['params']} run_id={c['run_id']} "
        f"companies={len((c['result'] or {}).get('companies') or [])}" for i, c in enumerate(done)) or "- none"
    return (f"Research brief:\n{plan['brief']}" + (f"\n\n{context}" if context else "") +
            f"\n\nThis plan script failed:\n{plan['script']}\n\nError:\n{plan['error'] or ''}\n\n"
            "Finished steps (they are kept and never run again):\n" + kept +
            "\n\nWrite a script for the remaining work only: do not repeat the finished steps. Read their results "
            "from the read-only list `previous` (e.g. previous[0].run_id, previous[0].companies); never assign to it.")


async def replan_plan(plan_id: str, llm: LLMClient, store: PlanStore, context: str = "",
                      user: str | None = None, check: StepCheck | None = None) -> None:
    """Have the planner rewrite a failed plan's remaining work; the plan becomes a draft at the next version.
    Raises PlanNotReplannable unless the plan is failed (before any model call), PlanRejected after two rejected
    scripts (the plan is left unchanged)."""
    plan = store.get(plan_id)
    if plan["status"] != "failed":
        raise PlanNotReplannable("only a failed plan can be re-planned")
    system = SYSTEM.replace("{stubs}", step_stubs())
    base = replan_prompt(plan, store.calls(plan_id), context)
    prompt = base
    errors: list[str] = []
    for _ in range(2):
        out, _usage = await llm.complete_structured(system=system, prompt=prompt, output_model=PlanScript)
        try:  # checks the script, then dry-runs it with the finished steps' results, off the event loop
            return await asyncio.to_thread(store.replan, plan_id, out.script, user, check)
        except ValueError as exc:
            errors = str(exc).splitlines()
        prompt = (f"{base}\n\nYour previous script:\n{out.script}\n\n"
                  "It was rejected:\n" + "\n".join(errors) + "\nFix every error.")
    raise PlanRejected("\n".join(errors))
