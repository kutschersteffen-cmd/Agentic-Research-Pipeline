from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from arp.engagement.orchestrator import escalation_index
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.engagement import EngagementRecord, EscalationStage, IssueStatus
from arp.schemas.voting import PolicyRecommendation, Proposal, ProposalType, VotePosition

"""Policy Application Agent: applies house voting policy to a proposal.

Deterministic rules run first -- most routine cases (fee ratios, pay
ratios, disclosed thresholds) are checkable in code against extracted
data, the same "a hard disclosed number is never second-guessed by a
categorical LLM judgment" discipline the revenue/CapEx exposure cascade
uses elsewhere in this codebase. Only proposals no rule resolves fall
through to an LLM judgment call. Either way, every recommendation is then
cross-checked against the company's EngagementRecord before it's returned
-- see check_engagement_alignment.
"""

PolicyRule = Callable[[Proposal], VotePosition | None]


def rule_auditor_independence(proposal: Proposal) -> VotePosition | None:
    """Vote against auditor ratification when non-audit fees exceed half of
    audit fees -- an illustrative, commonly used independence threshold.
    Falls through (returns None) when the figure isn't disclosed."""
    if proposal.type != ProposalType.AUDITOR_RATIFICATION:
        return None
    raw = proposal.supporting_data.get("non_audit_fee_ratio")
    if raw is None:
        return None
    try:
        ratio = float(raw)
    except ValueError:
        return None
    return VotePosition.AGAINST if ratio > 0.5 else VotePosition.FOR


def rule_egregious_pay_ratio(proposal: Proposal) -> VotePosition | None:
    """Vote against say-on-pay only for a clearly egregious disclosed CEO
    pay ratio; anything else is left to LLM judgment (or house policy on
    compensation structure, which isn't reducible to one number)."""
    if proposal.type != ProposalType.SAY_ON_PAY:
        return None
    raw = proposal.supporting_data.get("ceo_pay_ratio")
    if raw is None:
        return None
    try:
        ratio = float(raw)
    except ValueError:
        return None
    return VotePosition.AGAINST if ratio > 400 else None


def rule_routine_management_proposal(proposal: Proposal) -> VotePosition | None:
    """Default-to-management for routine, low-stakes proposal types with no
    disclosed red flag -- capital actions and other routine business absent
    any other rule triggering. Deliberately narrow: director elections and
    shareholder resolutions always fall through to judgment."""
    if proposal.type not in (ProposalType.CAPITAL_ACTION, ProposalType.OTHER):
        return None
    return proposal.management_recommendation


DEFAULT_POLICY_RULES: list[PolicyRule] = [rule_auditor_independence, rule_egregious_pay_ratio, rule_routine_management_proposal]

_PROPOSAL_THEME_MAP: dict[ProposalType, str] = {
    ProposalType.SAY_ON_PAY: "executive_compensation",
    ProposalType.DIRECTOR_ELECTION: "board_governance",
    ProposalType.AUDITOR_RATIFICATION: "audit_independence",
}

_OPEN_STATUSES = (IssueStatus.OPEN, IssueStatus.STALLED)

_JUDGMENT_SYSTEM = """\
You are a proxy-voting policy analyst. You are given a ballot proposal \
that no deterministic house rule resolved. Decide a recommended vote \
(for/against/abstain/withhold) based on the resolution text, management's \
recommendation, and any supporting data, applying prudent, conventional \
stewardship-policy judgment (director independence, governance quality, \
alignment with long-term shareholder value). State your rationale plainly \
so a human reviewer -- who has the final say on every ballot item \
regardless of your confidence -- can evaluate it quickly."""


class PolicyJudgmentDraft(BaseModel):
    vote: VotePosition
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


def _looks_self_filed(sponsor: str, fund_name: str | None) -> bool:
    if not fund_name:
        return False
    return fund_name.strip().lower() in sponsor.strip().lower()


def check_engagement_alignment(
    vote: VotePosition, proposal: Proposal, record: EngagementRecord | None, fund_name: str | None = None
) -> tuple[bool, str | None]:
    """Cross-checks a proposed vote against the company's engagement
    record. Returns (flag, note); a True flag means this recommendation
    must never be auto-approved, no matter how confident the rule/LLM was
    (see arp.voting.pipeline, which queues every proposal for review
    regardless, and arp.voting.ballot_casting, which additionally requires
    a co-sign before casting a flagged item)."""
    if proposal.type == ProposalType.SHAREHOLDER_RESOLUTION and _looks_self_filed(proposal.sponsor, fund_name) and vote != VotePosition.FOR:
        return True, f"Recommendation is '{vote.value}' on a resolution that appears to be co-filed/sponsored by the fund ({proposal.sponsor})."

    if record is None:
        return False, None

    theme = _PROPOSAL_THEME_MAP.get(proposal.type)
    if theme is None:
        return False, None

    escalated_issues = [
        i
        for i in record.issues
        if i.theme == theme
        and i.status in _OPEN_STATUSES
        and escalation_index(i.escalation_stage) >= escalation_index(EscalationStage.VOTE_AGAINST_MANAGEMENT)
    ]
    if escalated_issues and vote == VotePosition.FOR:
        stages = ", ".join(sorted({i.escalation_stage.value for i in escalated_issues}))
        return True, f"Recommendation votes FOR management on '{theme}' while engagement on this company is escalated ({stages})."
    return False, None


async def apply_policy(
    proposal: Proposal,
    record: EngagementRecord | None,
    llm: LLMClient,
    *,
    rules: list[PolicyRule] = DEFAULT_POLICY_RULES,
    fund_name: str | None = None,
) -> tuple[PolicyRecommendation, LLMUsage]:
    usage = LLMUsage()
    vote: VotePosition | None = None
    matched_rule_id: str | None = None
    for rule in rules:
        result = rule(proposal)
        if result is not None:
            vote, matched_rule_id = result, rule.__name__
            break

    if vote is not None:
        recommendation = PolicyRecommendation(
            vote=vote,
            rationale=f"Deterministic policy rule '{matched_rule_id}' matched.",
            policy_rule_id=matched_rule_id,
            confidence=1.0,
        )
    else:
        prompt = (
            f"Proposal #{proposal.proposal_number} ({proposal.type.value})\n"
            f"Sponsor: {proposal.sponsor}\n"
            f"Management recommendation: {proposal.management_recommendation.value if proposal.management_recommendation else 'not stated'}\n"
            f"Resolution text: {proposal.resolution_text}\n"
            f"Supporting data: {proposal.supporting_data}"
        )
        draft, usage = await llm.complete_structured(system=_JUDGMENT_SYSTEM, prompt=prompt, output_model=PolicyJudgmentDraft)
        recommendation = PolicyRecommendation(vote=draft.vote, rationale=draft.rationale, policy_rule_id=None, confidence=draft.confidence)

    flag, note = check_engagement_alignment(recommendation.vote, proposal, record, fund_name)
    recommendation = recommendation.model_copy(update={"engagement_alignment_flag": flag, "engagement_alignment_note": note})
    return recommendation, usage
