from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.thematic import MatchVerdict

MatchChangeType = Literal["verdict_changed", "confidence_changed"]


class MatchDiffEntry(BaseModel):
    """One (company, activity) pair whose result changed between two runs."""

    key: str = Field(description="'{company_id}:{activity_id}'")
    company_id: str
    activity_id: str
    change: MatchChangeType
    old_verdict: MatchVerdict
    new_verdict: MatchVerdict
    old_confidence: float
    new_confidence: float


class ResultsDiff(BaseModel):
    """A structured diff between two runs of the same (or a comparable)
    theme -- deterministic, no LLM involved, since the join key
    ('{company_id}:{activity_id}') is exact, unlike TaxonomyComparison's
    fuzzy LLM-matched activity pairs (arp/research/taxonomy_sources/
    compare.py). See arp/research/results_diff.py.
    """

    run_id_a: str
    run_id_b: str
    added: list[str] = Field(description="Keys present only in run B.")
    dropped: list[str] = Field(description="Keys present only in run A.")
    verdict_changed: list[MatchDiffEntry] = Field(default_factory=list)
    confidence_changed: list[MatchDiffEntry] = Field(
        default_factory=list, description="Same verdict in both runs, but confidence moved by more than the configured threshold."
    )
    unchanged_count: int = Field(description="Keys present in both runs with the same verdict and no material confidence change.")
