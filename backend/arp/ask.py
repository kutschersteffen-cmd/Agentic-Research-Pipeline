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

from arp.portfolio.qa_agent import QAAnswer
from arp.smart_search import SearchAnswer
from arp.stewardship.benchmark import BenchmarkStore
from arp.stewardship.process import SAMPLE_PATH

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
    indicators_disclosed_count: float
    walk_disclosed_count: float
    talk_disclosed_count: float
    walk_share_pct: float
    assessment_confidence_pct: float


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
