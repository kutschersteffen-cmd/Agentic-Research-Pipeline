"""The planner: one LLM call turns a research brief into a plan script; one retry with the checker's errors."""
from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient
from arp.orchestration.plan_api import BUILTINS, STEPS
from arp.orchestration.plan_check import MAX_LINES, check_script
from arp.orchestration.plan_store import PlanStore


class PlanScript(BaseModel):
    script: str = Field(description="The plan script: restricted Python, step calls with keyword arguments only.")


class PlanRejected(ValueError):
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
has id, exposure, has_xbrl). Pass one step's id to the next (e.g. universe_id=u.id).
Return only the script."""


async def draft_plan(brief: str, llm: LLMClient, store: PlanStore) -> str:
    """Store the planner's script as a draft plan and return its id. Raises PlanRejected."""
    system = SYSTEM.replace("{stubs}", step_stubs())
    prompt = f"Research brief:\n{brief}"
    errors: list[str] = []
    for _ in range(2):
        out, _usage = await llm.complete_structured(system=system, prompt=prompt, output_model=PlanScript)
        errors = check_script(out.script)
        if not errors:
            return store.create(brief, out.script)
        prompt = (f"Research brief:\n{brief}\n\nYour previous script:\n{out.script}\n\n"
                  "The checker rejected it:\n" + "\n".join(errors) + "\nFix every error.")
    raise PlanRejected("\n".join(errors))
