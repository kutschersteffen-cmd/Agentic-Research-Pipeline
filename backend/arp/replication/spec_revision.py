from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import now_iso
from arp.schemas.strategy_replication import (
    CompositeSignalComponent,
    RebalanceFrequency,
    ReportedPerformance,
    SignalType,
    StrategySpec,
    WeightingScheme,
)

_SYSTEM_PROMPT = """\
You are helping a quantitative researcher revise the specification of an \
already-drafted 'outperformance' strategy backtest, per their own \
natural-language instruction -- you are not extracting from a paper here, \
only applying a requested change to an existing specification.

Rules:
- Change ONLY what the instruction actually asks for. Copy every other \
  field's value EXACTLY as given in the current specification below -- do \
  not silently adjust, round, or 'improve' anything the instruction didn't \
  mention.
- Return the FULL specification (every field), not just the changed one(s).
- If the instruction is ambiguous or asks for something structurally \
  unsupported (e.g. a signal_type this schema doesn't have), make the \
  closest reasonable, clearly-scoped change rather than inventing new \
  structure.
- Never invent citations or performance figures the instruction didn't \
  supply -- reported_performance fields the instruction doesn't address \
  must be copied unchanged, not re-estimated.
"""

# Every StrategySpec field an instruction is allowed to change --
# deliberately excludes paper_citation (identity, not methodology),
# spec_id/created_at (identity/audit), and citations/grounded/confidence/
# needs_review/verifier_notes/provenance/extraction_notes (integrity/audit
# fields this module manages itself in revise_spec_via_instruction below,
# never the LLM's to set).
_REVISABLE_FIELDS = (
    "paper_title",
    "strategy_name",
    "signal_type",
    "universe_description",
    "formation_period_months",
    "skip_month",
    "holding_period_months",
    "rebalance_frequency",
    "rebalance_interval_months",
    "rebalance_anchor_month",
    "characteristic_name",
    "characteristic_lag_months",
    "composite_components",
    "num_portfolios",
    "long_leg_portfolio",
    "short_leg_portfolio",
    "weighting",
    "sample_period_start",
    "sample_period_end",
    "reported_performance",
    "num_trials_attempted",
)


class StrategySpecRevisionDraft(BaseModel):
    """The subset of StrategySpec an NL-instruction revision is allowed to
    touch -- see _REVISABLE_FIELDS. No citations/confidence field here: a
    live instruction has no source text to ground a citation against, so
    revise_spec_via_instruction below never lets the LLM assert either."""

    paper_title: str
    strategy_name: str
    signal_type: SignalType
    universe_description: str
    formation_period_months: int = 0
    skip_month: bool = False
    holding_period_months: int
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.MONTHLY
    rebalance_interval_months: int | None = None
    rebalance_anchor_month: int | None = Field(default=None, ge=1, le=12)
    characteristic_name: str | None = None
    characteristic_lag_months: int = 0
    composite_components: list[CompositeSignalComponent] = Field(default_factory=list)
    num_portfolios: int = 10
    long_leg_portfolio: int = 1
    short_leg_portfolio: int
    weighting: WeightingScheme = WeightingScheme.EQUAL
    sample_period_start: str
    sample_period_end: str
    reported_performance: ReportedPerformance = Field(default_factory=ReportedPerformance)
    num_trials_attempted: int = Field(default=1, ge=1)


def _current_revision_draft(spec: StrategySpec) -> StrategySpecRevisionDraft:
    return StrategySpecRevisionDraft(**{f: getattr(spec, f) for f in _REVISABLE_FIELDS})


async def revise_spec_via_instruction(
    spec: StrategySpec, instruction: str, llm: LLMClient
) -> tuple[StrategySpec, LLMUsage]:
    """Applies a free-text instruction ("use quarterly rebalancing instead",
    "combine this with a value signal") to `spec`, via one schema-forced LLM
    call (arp/llm/base.py::LLMClient.complete_structured -- same pattern as
    every other agent in this codebase). Returns the revised StrategySpec
    and the call's LLMUsage.

    Safety rule enforced here in CODE, not trusted from the LLM's own
    output: if the instruction changed anything at all, the resulting
    spec's `grounded` is forced to False and `needs_review` to True, and a
    timestamped note is appended to `extraction_notes` -- `grounded` is a
    whole-spec flag in this schema (StrategySpec.citations aren't tagged
    per-field), so a manual/instruction-driven change to ANY field means
    the spec as a whole can no longer be asserted as fully grounded against
    the original source text, even though its existing citations are left
    in place (some may still genuinely support unchanged fields) rather
    than deleted.
    """
    current = _current_revision_draft(spec)
    prompt = (
        f"Current specification (JSON):\n{current.model_dump_json(indent=2)}\n\n"
        f"Instruction: {instruction}\n\n"
        "Return the full revised specification with the instruction applied."
    )
    revised, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=StrategySpecRevisionDraft)

    changed_fields = [f for f in _REVISABLE_FIELDS if getattr(revised, f) != getattr(current, f)]
    updates = {f: getattr(revised, f) for f in _REVISABLE_FIELDS}
    if changed_fields:
        updates["grounded"] = False
        updates["needs_review"] = True
        note = (
            f"{now_iso()}: revised via instruction ({', '.join(changed_fields)} changed) -- "
            f"'{instruction}'. No longer fully grounded against the original source text."
        )
        updates["extraction_notes"] = (spec.extraction_notes + "\n" + note).strip() if spec.extraction_notes else note

    return spec.model_copy(update=updates), usage
