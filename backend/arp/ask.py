"""Ask ARP: one plain-language question goes to one read-only tool. The model only picks the tool and rewrites the
question so it reads on its own (routing has no number fields); the existing engines and the code below compute every
figure shown. Spec: docs/superpowers/specs/2026-10-24-ask-arp-panel-design.md.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from arp.api.auth import Principal
from arp.decision.sources import _normalised_name, from_transition_plan_run, is_transition_plan_preset_run
from arp.portfolio.qa_agent import QAAnswer
from arp.review.items import list_open_items
from arp.schemas.common import JobStatus
from arp.smart_search import SearchAnswer
from arp.stewardship.benchmark import BenchmarkStore
from arp.stewardship.process import SAMPLE_PATH
from arp.storage.run_store import RunStore

Tool = Literal["portfolio", "smart_search", "transition_plan", "benchmark_sectors", "none"]

NONE_TEXT = (
    "I can't answer that yet. I can answer: portfolio exposure; data issues, outputs and feeds; "
    "a company's newest transition plan assessment; a benchmark's sector weights."
)
SAMPLE_TEXT = (
    "Synthetic sample: 12 fictional companies standing in for MSCI World. Upload the iShares URTH holdings file "
    "under Stewardship → Benchmarks for the real index."
)


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # only questions and tool names travel, never answers or figures

    question: str
    tool: Tool
    standalone_question: str


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    history: list[HistoryTurn] = Field(default_factory=list, max_length=5)


class AskRouting(BaseModel):
    """The model's whole output: which tool, and the question rewritten so it reads without the history."""

    tool: Tool
    standalone_question: str
    company: str | None = None
    benchmark_id: str | None = None


class TransitionPlanFigures(BaseModel):
    """The run row's figures as extracted; None where the row has none (a run with no walk indicators has no walk share)."""

    indicators_disclosed_count: float | None
    walk_disclosed_count: float | None
    talk_disclosed_count: float | None
    walk_share_pct: float | None
    assessment_confidence_pct: float | None


class OlderRun(BaseModel):
    run_id: str
    run_date: str


class TransitionPlanCard(BaseModel):
    company: str
    company_id: str
    run_id: str
    run_type: Literal["transition_plan", "extraction"]
    run_date: str
    figures: TransitionPlanFigures
    open_review_items: int
    older_runs: list[OlderRun]


class BenchmarkCheck(BaseModel):
    source: str
    as_of: str | None
    constituents: int
    dropped: int
    unclassified_pct: float
    total_pct: float


class SectorWeight(BaseModel):
    sector: str
    weight_pct: float


class BenchmarkCard(BaseModel):
    benchmark_id: str | None
    name: str
    is_sample: bool
    check: BenchmarkCheck
    sectors: list[SectorWeight]


class AskResponse(BaseModel):
    tool: Tool
    question: str
    standalone_question: str
    answer_text: str
    answered_at: str
    portfolio: QAAnswer | None = None
    smart_search: SearchAnswer | None = None
    transition_plan: TransitionPlanCard | None = None
    benchmark_sectors: BenchmarkCard | None = None


def benchmark_sectors(streams_root: Path, benchmark_id: str | None) -> tuple[BenchmarkCard | None, str]:
    """Sector weights of an uploaded benchmark (or the synthetic sample when none is uploaded), with the data check
    shown above the chart. Returns (card, answer_text); the card is None when it is unclear which benchmark is meant."""
    store = BenchmarkStore(streams_root)
    uploaded = store.list()
    if uploaded:
        if benchmark_id not in {b["benchmark_id"] for b in uploaded}:
            return None, f"Which benchmark do you mean: {', '.join(sorted(b['name'] for b in uploaded))}?"
        b = store.get(benchmark_id)
        weights = [(c["sector"], c["weight_pct"]) for c in b["constituents"]]
        source, as_of, dropped, name = b["source"], b["as_of"], b["dropped"], b["name"]
        text = f"Sector weights of {name} as of {as_of}."
    else:
        issuers = json.loads(SAMPLE_PATH.read_text())["issuers"]
        weights = [(i["sector"], i["holding"]["index_weight_pct"]) for i in issuers]
        source, as_of, dropped, name, benchmark_id, text = "synthetic sample", None, 0, "Synthetic sample", None, SAMPLE_TEXT

    by_sector: dict[str, float] = defaultdict(float)
    for sector, weight in weights:
        by_sector[sector.strip() or "Unclassified"] += weight
    total = sum(w for _, w in weights)
    unclassified = sum(w for s, w in weights if not s.strip())
    check = BenchmarkCheck(
        source=source, as_of=as_of, constituents=len(weights), dropped=dropped, total_pct=round(total, 2),
        unclassified_pct=round(unclassified / total * 100, 2) if total else 0.0,
    )
    sectors = sorted((SectorWeight(sector=s, weight_pct=round(w, 2)) for s, w in by_sector.items()), key=lambda x: (-x.weight_pct, x.sector))
    return BenchmarkCard(benchmark_id=benchmark_id, name=name, is_sample=benchmark_id is None, check=check, sectors=sectors), text


_FINISHED = {JobStatus.COMPLETED, JobStatus.PARTIALLY_COMPLETED}  # a partial run can still hold a valid row for the company
_FIGURES = {
    "indicators_disclosed_count": "Indicators_Disclosed_Count", "walk_disclosed_count": "Walk_Disclosed_Count",
    "talk_disclosed_count": "Talk_Disclosed_Count", "walk_share_pct": "Walk_Share_pct",
    "assessment_confidence_pct": "Assessment_Confidence_pct",
}


def _rows(run_store: RunStore, run_id: str) -> list[dict]:
    try:
        return from_transition_plan_run(run_store, run_id).rows
    except ValueError:  # a finished run with no result rows
        return []


def newest_transition_plan(run_store: RunStore, principal: Principal, company: str | None) -> tuple[TransitionPlanCard | None, str]:
    """The newest finished transition plan assessment (stored `transition_plan` runs and preset extraction runs, never
    trial runs) that includes `company`. Returns (card, answer_text); the card is None when nothing or more than one
    company matches."""
    key = _normalised_name(company or "")
    if not key:
        return None, "Which company do you mean?"
    runs = sorted(
        (m for m in run_store.list_runs()
         if (m.run_type == "transition_plan" or is_transition_plan_preset_run(m)) and m.status in _FINISHED and not m.params.get("trial")),
        key=lambda m: (m.created_at, m.run_id), reverse=True,
    )
    for i, m in enumerate(runs):
        rows = _rows(run_store, m.run_id)
        matched = [r for r in rows if _normalised_name(r["Company"]) == key] or [r for r in rows if key in _normalised_name(r["Company"])]
        names = sorted({r["Company"] for r in matched})
        if len(names) > 1:
            return None, f'Several companies match "{company}": {", ".join(names)}. Which one do you mean?'
        if not names:
            continue
        row = matched[0]
        chosen = _normalised_name(row["Company"])
        older: list[OlderRun] = []
        for o in runs[i + 1:]:
            if len(older) == 2:
                break
            if any(_normalised_name(r["Company"]) == chosen for r in _rows(run_store, o.run_id)):
                older.append(OlderRun(run_id=o.run_id, run_date=o.created_at))
        open_items = sum(
            1 for item in list_open_items(run_store, principal, run_id=m.run_id) if item.payload.get("company_id") == row["Company_Id"]
        )
        card = TransitionPlanCard(
            company=row["Company"], company_id=row["Company_Id"], run_id=m.run_id, run_type=m.run_type, run_date=m.created_at,
            figures=TransitionPlanFigures(**{k: float(row[c]) if row.get(c) not in (None, "") else None for k, c in _FIGURES.items()}),
            open_review_items=open_items, older_runs=older,
        )
        text = f"{card.company}: newest transition plan assessment from {card.run_date[:10]} (run {card.run_id})."
        if open_items:
            text += " 1 item still waits for review." if open_items == 1 else f" {open_items} items still wait for review."
        return card, text
    return None, f"No completed transition plan assessment includes {company}."
