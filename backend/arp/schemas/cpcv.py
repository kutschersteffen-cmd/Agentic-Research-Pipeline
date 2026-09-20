from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import new_id


class PBOReport(BaseModel):
    """Probability of Backtest Overfitting (Bailey, Borwein, Lopez de Prado
    & Zhu, "The Probability of Backtest Overfitting") across a set of
    candidate StrategySpec variants, estimated via Combinatorially
    Symmetric Cross-Validation (CSCV) -- see arp/replication/cpcv.py.

    A low PBO does not certify that any one candidate is "the" true
    strategy; it only says that picking the best-looking candidate
    in-sample was not, historically, a coin flip about which one would
    also look best out-of-sample. A high PBO (roughly >0.5) is the
    practical warning sign: the in-sample selection process itself is not
    trustworthy, regardless of how good any single candidate's own
    backtest looks.
    """

    report_id: str = Field(default_factory=lambda: new_id("pbo"))
    candidate_spec_ids: list[str]
    num_blocks: int
    num_splits: int = Field(description="C(num_blocks, num_blocks/2) -- every way of choosing half the blocks as the test set.")
    purge_months: int
    embargo_months: int
    logits: list[float] = Field(
        default_factory=list,
        description="One logit(omega) per split -- omega is the normalized out-of-sample rank of whichever "
        "candidate looked best in-sample on that split. A negative logit means that candidate performed at or "
        "below the out-of-sample median; PBO is the fraction of splits where that happens.",
    )
    probability_of_backtest_overfitting: float = Field(
        description="Fraction of splits (in [0, 1]) where the in-sample-best candidate ranked at or below the "
        "out-of-sample median across all candidates -- Bailey et al.'s PBO estimate. Higher is worse; the paper "
        "itself treats anything materially above 0.5 as a red flag for the selection process, not just the winner."
    )
    per_candidate_selection_count: dict[str, int] = Field(
        default_factory=dict, description="How many splits picked each spec_id as the in-sample-best candidate -- a candidate selected on almost every split despite a high PBO is especially suspect."
    )
    notes: str = ""
