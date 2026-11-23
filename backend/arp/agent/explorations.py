"""Explorations: a question, the code written for it, and what the sandbox returned (spec agent-panel-code-mode,
Phase 4). Results stay `exploratory` until a person accepts them; nothing in the plan lane reads them."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from arp import standins
from arp.agent import sandbox
from arp.agent.miniapp_html import clean_miniapp_html, trim_asks
from arp.agent.models import AgentExploration
from arp.api.auth import Principal
from arp.config import Settings
from arp.llm.base import LLMClient
from arp.orchestration.capabilities import CATALOG
from arp.orchestration.plan_models import AgentAsk


def _out(row: AgentExploration) -> dict[str, Any]:
    out = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    out["id"] = str(row.id)
    out["cost_usd"] = float(row.cost_usd or 0)
    out["label"] = "accepted" if row.accepted_at else "exploratory"
    return out


def _with_source_ask(s: Session, rows: list[AgentExploration]) -> list[dict[str, Any]]:
    """Each row as `_out` gives it, plus `source_ask: {question, thread_id}` of the ask it came from, or None."""
    ids = {r.source_ask_id for r in rows if r.source_ask_id}
    asks = {a.id: {"question": a.question, "thread_id": a.thread_id}
            for a in s.scalars(select(AgentAsk).where(AgentAsk.id.in_(ids)))} if ids else {}
    return [{**_out(r), "source_ask": asks.get(r.source_ask_id)} for r in rows]


def _uuid(exploration_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(exploration_id)
    except ValueError:
        return None


class ExplorationStore:
    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.dsn = dsn  # AskStore checks a source_ask_id on it
        self.engine = get_engine(dsn)

    def add(self, *, question: str, code: str, run: dict[str, Any], model: str | None, cost_usd: float = 0.0,
            source_ask_id: str | None = None) -> dict:
        """Stores the exploration; `source_ask_id` is the ask whose `Explore` sent the question."""
        row = AgentExploration(
            id=uuid.uuid4(), question=question, code=code, status=run["status"], result=run["result"],
            error=run["error"], tool_calls=run["tool_calls"], model=model, cost_usd=Decimal(repr(cost_usd)),
            created_at=datetime.now(UTC), source_ask_id=source_ask_id)
        with Session(self.engine, expire_on_commit=False) as s, s.begin():
            s.add(row)
        return self.get(str(row.id))

    def list(self) -> list[dict]:
        """Every exploration, newest first."""
        with Session(self.engine) as s:
            rows = s.scalars(select(AgentExploration).order_by(AgentExploration.created_at.desc())).all()
            return _with_source_ask(s, list(rows))

    def get(self, exploration_id: str) -> dict | None:
        key = _uuid(exploration_id)
        with Session(self.engine) as s:
            row = s.get(AgentExploration, key) if key else None
            return _with_source_ask(s, [row])[0] if row else None

    def accept(self, exploration_id: str, user_id: str) -> dict | None:
        """Marks the exploration accepted by `user_id`; a second accept keeps the first one's name and time."""
        key = _uuid(exploration_id)
        with Session(self.engine, expire_on_commit=False) as s, s.begin():
            row = s.get(AgentExploration, key, with_for_update=True) if key else None
            if row is None:
                return None
            if row.accepted_at is None:
                row.accepted_by, row.accepted_at = user_id, datetime.now(UTC)
        return self.get(exploration_id)

    def set_miniapp(self, exploration_id: str, html: str, asks: list[str]) -> dict | None:
        key = _uuid(exploration_id)
        with Session(self.engine, expire_on_commit=False) as s, s.begin():
            row = s.get(AgentExploration, key, with_for_update=True) if key else None
            if row is None:
                return None
            row.miniapp_html, row.miniapp_asks = html, asks
        return self.get(exploration_id)


class ExplorationCode(BaseModel):
    code: str = Field(description="The body of an async JavaScript function that returns the answer as JSON.")


SYSTEM = """You write JavaScript that answers a question over ARP's data. Your code is the body of an async function:
use `await`, and `return` the answer. It runs in an isolate with no network, no file system and no secrets, so `fetch`,
`require` and `process` are unavailable. ARP's data comes only from the methods of the global `codemode` object
declared below; each takes one argument object and returns a Promise of JSON. Call only those methods.

`codemode` exists only inside the sandbox when your code runs. It is not a tool: never call `codemode` or any of its
methods as a tool while answering. Your only output is the code, which calls them when it runs.

Rules:
- Return a JSON value. Prefer a list of flat objects (one row each, plain strings, numbers or booleans) so it shows as
  a table; keep the result under 256 KB.
- At most 400 lines and 50 `codemode` calls. Do not loop forever: the run stops after 30 seconds.
- A method resolves to null when ARP has nothing for the arguments; handle null.
- Never invent figures: every number you return comes from a `codemode` result or arithmetic on one."""


def _ts(schema: dict, defs: dict) -> str:
    """A TypeScript type for a JSON schema (the subset Pydantic writes for ARP's models)."""
    if "$ref" in schema:
        return _ts(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    if "anyOf" in schema:
        return " | ".join(_ts(s, defs) for s in schema["anyOf"])
    if "enum" in schema:
        return " | ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in schema["enum"])
    if "const" in schema:
        return f'"{schema["const"]}"' if isinstance(schema["const"], str) else str(schema["const"])
    kind = schema.get("type")
    if kind == "array":
        item = _ts(schema.get("items", {}), defs)
        return f"({item})[]" if "|" in item else f"{item}[]"
    if kind == "object" and "properties" in schema:
        required = set(schema.get("required", []))
        fields = "; ".join(f"{name}{'' if name in required else '?'}: {_ts(s, defs)}"
                           for name, s in schema["properties"].items())
        return f"{{ {fields} }}"
    if kind == "object":
        return "Record<string, unknown>"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(
        kind, "unknown")


def _output_models() -> dict[str, type[BaseModel]]:
    from arp import ask, smart_search
    from arp.portfolio import qa_agent

    return {"benchmark_sectors": ask.BenchmarkCard, "transition_plan": ask.TransitionPlanCard,
            "portfolio_exposure": qa_agent.QAAnswer, "smart_search": smart_search.SearchAnswer}


def declarations() -> str:
    """The sandbox lane as TypeScript declarations, generated from the capability catalog."""
    outputs = _output_models()
    lines = ["declare const codemode: {"]
    for cap in (c for c in CATALOG if c.lane == "sandbox"):
        args = cap.input_model.model_json_schema()
        out = outputs.get(cap.id)
        returns = _ts(out.model_json_schema(), out.model_json_schema().get("$defs", {})) if out else "unknown"
        nullable = cap.id in ("benchmark_sectors", "transition_plan")
        lines.append(f"  /** {cap.summary} Resolves to {cap.output_note}{' or null' if nullable else ''}. */")
        lines.append(f"  {cap.id}(args: {_ts(args, args.get('$defs', {}))}): Promise<{returns}{' | null' if nullable else ''}>;")
    lines.append("};")
    return "\n".join(lines)


def build_prompt(question: str, retry: tuple[str, str] | None = None) -> str:
    prompt = f"Methods available to your code:\n```ts\n{declarations()}\n```\n\nQuestion: {question}"
    if retry:
        code, error = retry
        prompt += f"\n\nYour previous code did not parse:\n```js\n{code}\n```\nError: {error}\nWrite it again so it parses."
    return prompt


async def write_code(settings: Settings, question: str, *, llm: LLMClient | None = None,
                     retry: tuple[str, str] | None = None) -> tuple[str, str, float]:
    """(code, model, cost) for the question from one model call; `retry` is the (code, error) that did not parse.
    With stand-ins, entry 1 of explore.json answers the first attempt and entry 2 the retry."""
    if settings.standins_dir is not None:
        return standins.exploration_code(settings.standins_dir, question, 2 if retry else 1), "stand-in", 0.0
    from arp.llm.factory import build_llm_client
    from arp.orchestration.cost_tracker import estimate_cost_usd

    llm = llm or build_llm_client(settings)
    out, usage = await llm.complete_structured(system=SYSTEM, prompt=build_prompt(question, retry),
                                               output_model=ExplorationCode)
    model = usage.model or settings.llm_model
    return out.code, model, estimate_cost_usd(model, usage)


def _parse_error(checked: dict) -> str | None:
    error = checked.get("error") or ""
    return None if checked.get("ok") or not error.startswith("code does not parse") else error


async def run_question(settings: Settings, question: str, principal: Principal, *,
                       llm: LLMClient | None = None) -> tuple[str, str, float, dict[str, Any]]:
    """Writes code for the question (one retry when it does not parse) and runs it in the sandbox:
    (code, model, cost, run), `run` as `sandbox.execute` returns it."""
    code, model, cost = await write_code(settings, question, llm=llm)
    error = _parse_error(await sandbox.check(code, settings))
    if error:
        code, model, retry_cost = await write_code(settings, question, llm=llm, retry=(code, error))
        cost += retry_cost
        error = _parse_error(await sandbox.check(code, settings))
    if error:
        return code, model, cost, {"status": "failed", "result": None, "error": error, "tool_calls": []}
    return code, model, cost, await sandbox.execute(code, principal, settings)


async def explore(store: ExplorationStore, settings: Settings, question: str, principal: Principal, *,
                  llm: LLMClient | None = None, source_ask_id: str | None = None) -> dict:
    """Answers the question in the sandbox and stores the outcome, whatever it is."""
    code, model, cost, run = await run_question(settings, question, principal, llm=llm)
    return store.add(question=question, code=code, run=run, model=model, cost_usd=cost, source_ask_id=source_ask_id)


class NotDone(Exception):
    """Only a done exploration can be shown as a mini-app."""


class MiniApp(BaseModel):
    html: str = Field(description="One HTML file with no scripts: markup and CSS only, the data written into it.")
    asks: list[str] = Field(description="Up to 5 follow-up questions a person may ask about this result.")


MINIAPP_SYSTEM = """You write a small web page (a "mini-app") that shows the result of an exploration of ARP's data,
and up to 5 follow-up questions a person may want to ask about it.

The page runs no scripts and can reach nothing: write HTML and CSS only, with the data below written into the page.
Use tables, lists, <details> and inline SVG (rect, circle, line, path, polyline, polygon, text) for charts. Scripts,
links, forms, images from URLs and external styles or fonts are removed before the page is shown.

Rules:
- Show the data; you may sort it and chart it. Never compute a new figure and present it as an ARP figure: every number
  labelled as ARP's comes straight from the data.
- Set the page's own background and text colours, and keep it readable in a narrow column (about 360 px wide).
- Each follow-up question stands alone, in one sentence, at most 200 characters; ARP shows them as buttons next to the
  page."""

MINIAPP_CONTEXT_BYTES = 20_000  # the same cut as the planner's exploration context


def miniapp_prompt(exploration: dict) -> str:
    data = json.dumps(exploration["result"], indent=1, default=str)
    if len(data.encode()) > MINIAPP_CONTEXT_BYTES:
        data = data.encode()[:MINIAPP_CONTEXT_BYTES].decode(errors="ignore") + "\n… (cut)"
    return f"Question: {exploration['question']}\n\nResult:\n```json\n{data}\n```"


async def write_miniapp(store: ExplorationStore, settings: Settings, exploration_id: str, *,
                        llm: LLMClient | None = None) -> dict | None:
    """One model call writes the exploration's mini-app: its HTML, cleaned, as `miniapp_html`, and its follow-up
    questions as `miniapp_asks`. None when there is no such exploration; raises NotDone for one that is not `done`."""
    found = store.get(exploration_id)
    if found is None:
        return None
    if found["status"] != "done":
        raise NotDone
    if settings.standins_dir is not None:
        html, asks = standins.miniapp(settings.standins_dir, found["question"])
    else:
        from arp.llm.factory import build_llm_client

        llm = llm or build_llm_client(settings)
        out, _ = await llm.complete_structured(system=MINIAPP_SYSTEM, prompt=miniapp_prompt(found), output_model=MiniApp)
        html, asks = out.html, out.asks
    return store.set_miniapp(exploration_id, clean_miniapp_html(html), trim_asks(asks))
