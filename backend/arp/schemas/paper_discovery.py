from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import new_id
from arp.schemas.strategy_replication import SignalType


class PaperCandidate(BaseModel):
    """One candidate 'outperformance' strategy paper surfaced by literature
    discovery (arp/replication/paper_discovery.py), presented for a human
    to review and select -- nothing here is fetched, read, or turned into
    a StrategySpec automatically. Mirrors SourceCandidate
    (arp/schemas/taxonomy_sources.py)'s "propose, never auto-apply" shape.
    """

    candidate_id: str = Field(default_factory=lambda: new_id("paper"))
    title: str
    url: str
    snippet: str = ""
    replication_worthiness_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="LLM-assessed replication-worthiness, set by rank_candidate_papers."
    )
    worthiness_reasoning: str | None = Field(default=None, description="Why this looks (or doesn't look) like a good replication target, from title/URL/snippet alone.")
    suggested_signal_type: SignalType | None = Field(
        default=None, description="Best guess at which SignalType this paper's strategy would map to -- a starting hint for the reviewer, not a claim the paper was actually read."
    )
