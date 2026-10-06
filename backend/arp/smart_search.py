"""Data Hub · Smart Search: a plain-language question about the data becomes a filter over a closed vocabulary, and code
applies it to the lists Data Hub already computes (open issues, the output catalog, the feeds). The model only picks the
filter; it never sees the rows and never states a number. Same discipline as Ask the Portfolio (portfolio/qa_agent.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage

_SYSTEM_PROMPT = """\
You turn a question about the tool's stored data into a filter. You never answer the question yourself and never state
a number: code applies your filter and counts the result.

target, then the fields that apply to it (leave the others null):
- "issues": open data problems. source: "feed" (a feed failed or is behind), "security_master" (a held security the
  master does not map to exactly one issuer), "check" (an extracted value failing a data check). severity: "block"
  or "warn".
- "outputs": stored outputs other functions consume. kind: "universe", "run", "publication", "taxonomy",
  "calibration". status: e.g. "draft", "ratified", "approved", "published", "failed", "completed". unused: true for
  outputs nothing has used yet.
- "feeds": input feeds. feed: "security_master", "holdings", "index", "esg", "news". behind: true for feeds behind.
  failed: true for feeds whose last load failed.
contains: optional words to match in a row's name, title, subject or detail (a company, ISIN, portfolio or field id),
exactly as the user wrote them.

If the question is about anything else (for example changes in a reported figure over time, or exposure amounts), set
resolvable=false and say in clarification_needed what Smart Search can answer instead.
"""


class SearchFilter(BaseModel):
    resolvable: bool = True
    clarification_needed: str = ""
    target: Literal["issues", "outputs", "feeds"] = "issues"
    source: Literal["feed", "security_master", "check"] | None = None
    severity: Literal["block", "warn"] | None = None
    kind: Literal["universe", "run", "publication", "taxonomy", "calibration"] | None = None
    status: str | None = None
    unused: bool | None = None
    feed: Literal["security_master", "holdings", "index", "esg", "news"] | None = None
    behind: bool | None = None
    failed: bool | None = None
    contains: str = ""


class SearchAnswer(BaseModel):
    question: str
    resolvable: bool
    clarification_needed: str = ""
    filter: SearchFilter | None = None
    rows: list[dict] = []
    answer_text: str = ""


_TEXT_KEYS = ("title", "name", "subject", "detail", "source_id", "id")


def apply(f: SearchFilter, *, issues: list[dict], outputs: list[dict], feeds: list[dict]) -> list[dict]:
    """The rows of `f.target` that pass every set field of the filter."""
    words = f.contains.lower().split()

    def text_ok(r: dict) -> bool:
        hay = " ".join(str(r.get(k) or "") for k in _TEXT_KEYS).lower()
        return all(w in hay for w in words)

    if f.target == "issues":
        rows = [r for r in issues if (f.source is None or r["source"] == f.source) and (f.severity is None or r["severity"] == f.severity)]
    elif f.target == "outputs":
        rows = [r for r in outputs if (f.kind is None or r["kind"] == f.kind)
                and (f.status is None or str(r.get("status") or "").lower() == f.status.lower())
                and (f.unused is None or (not r.get("used_by")) == f.unused)]
    else:
        rows = [r for r in feeds if (f.feed is None or r["feed"] == f.feed) and (f.behind is None or bool(r.get("stale")) == f.behind)
                and (f.failed is None or ((r.get("last_load") or {}).get("status") == "failed") == f.failed)]
    return [r for r in rows if text_ok(r)]


def describe(f: SearchFilter) -> str:
    parts = [f"{k}={v}" for k, v in f.model_dump(exclude={"resolvable", "clarification_needed", "target", "contains"}).items() if v is not None]
    if f.contains:
        parts.append(f'containing "{f.contains}"')
    return ", ".join(parts) or "no filter"


async def smart_search(question: str, llm: LLMClient, *, issues: list[dict], outputs: list[dict], feeds: list[dict]) -> tuple[SearchAnswer, LLMUsage]:
    f, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=f"Question: {question}", output_model=SearchFilter)
    if not f.resolvable:
        return SearchAnswer(question=question, resolvable=False, clarification_needed=f.clarification_needed), usage
    rows = apply(f, issues=issues, outputs=outputs, feeds=feeds)
    text = f"{len(rows)} {f.target if len(rows) != 1 else f.target.rstrip('s')} ({describe(f)})."
    return SearchAnswer(question=question, resolvable=True, filter=f, rows=rows, answer_text=text), usage
