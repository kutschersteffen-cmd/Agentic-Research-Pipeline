from arp.schemas.engagement import EngagementIssue, EngagementRecord, EscalationStage, TriggerSource
from arp.schemas.voting import Proposal, ProposalType, VotePosition
from arp.voting.policy_agent import (
    PolicyJudgmentDraft,
    apply_policy,
    check_engagement_alignment,
    rule_auditor_independence,
    rule_egregious_pay_ratio,
)


def _proposal(**overrides) -> Proposal:
    defaults = dict(
        company_id="C1",
        meeting_id="mtg_1",
        proposal_number="1",
        type=ProposalType.OTHER,
        sponsor="Management",
        resolution_text="Some resolution.",
    )
    defaults.update(overrides)
    return Proposal(**defaults)


def test_rule_auditor_independence_against_high_fee_ratio():
    proposal = _proposal(type=ProposalType.AUDITOR_RATIFICATION, supporting_data={"non_audit_fee_ratio": "0.62"})
    assert rule_auditor_independence(proposal) == VotePosition.AGAINST


def test_rule_auditor_independence_for_low_fee_ratio():
    proposal = _proposal(type=ProposalType.AUDITOR_RATIFICATION, supporting_data={"non_audit_fee_ratio": "0.1"})
    assert rule_auditor_independence(proposal) == VotePosition.FOR


def test_rule_auditor_independence_none_when_no_data():
    proposal = _proposal(type=ProposalType.AUDITOR_RATIFICATION, supporting_data={})
    assert rule_auditor_independence(proposal) is None


def test_rule_egregious_pay_ratio_only_flags_extreme_values():
    egregious = _proposal(type=ProposalType.SAY_ON_PAY, supporting_data={"ceo_pay_ratio": "600"})
    modest = _proposal(type=ProposalType.SAY_ON_PAY, supporting_data={"ceo_pay_ratio": "150"})
    assert rule_egregious_pay_ratio(egregious) == VotePosition.AGAINST
    assert rule_egregious_pay_ratio(modest) is None


def test_check_engagement_alignment_no_record_never_flags():
    proposal = _proposal(type=ProposalType.SAY_ON_PAY)
    flag, note = check_engagement_alignment(VotePosition.FOR, proposal, None)
    assert flag is False
    assert note is None


def test_check_engagement_alignment_flags_for_vote_during_active_escalation():
    issue = EngagementIssue(theme="executive_compensation", source=TriggerSource.MANUAL, escalation_stage=EscalationStage.VOTE_AGAINST_MANAGEMENT)
    record = EngagementRecord(company_id="C1", name="Acme Corp", issues=[issue])
    proposal = _proposal(type=ProposalType.SAY_ON_PAY)

    flag, note = check_engagement_alignment(VotePosition.FOR, proposal, record)

    assert flag is True
    assert "executive_compensation" in note


def test_check_engagement_alignment_does_not_flag_against_vote_during_escalation():
    issue = EngagementIssue(theme="executive_compensation", source=TriggerSource.MANUAL, escalation_stage=EscalationStage.VOTE_AGAINST_MANAGEMENT)
    record = EngagementRecord(company_id="C1", name="Acme Corp", issues=[issue])
    proposal = _proposal(type=ProposalType.SAY_ON_PAY)

    flag, _note = check_engagement_alignment(VotePosition.AGAINST, proposal, record)

    assert flag is False


def test_check_engagement_alignment_ignores_pre_escalation_stage():
    issue = EngagementIssue(theme="executive_compensation", source=TriggerSource.MANUAL, escalation_stage=EscalationStage.PRIVATE_ENGAGEMENT)
    record = EngagementRecord(company_id="C1", name="Acme Corp", issues=[issue])
    proposal = _proposal(type=ProposalType.SAY_ON_PAY)

    flag, _note = check_engagement_alignment(VotePosition.FOR, proposal, record)

    assert flag is False


def test_check_engagement_alignment_flags_self_filed_resolution_voted_against():
    proposal = _proposal(type=ProposalType.SHAREHOLDER_RESOLUTION, sponsor="Stewardship Fund LP")
    flag, note = check_engagement_alignment(VotePosition.AGAINST, proposal, None, fund_name="Stewardship Fund LP")
    assert flag is True
    assert "co-filed" in note


async def test_apply_policy_uses_deterministic_rule_and_sets_alignment_flag(fake_llm):
    issue = EngagementIssue(theme="audit_independence", source=TriggerSource.MANUAL, escalation_stage=EscalationStage.VOTE_AGAINST_MANAGEMENT)
    record = EngagementRecord(company_id="C1", name="Acme Corp", issues=[issue])
    proposal = _proposal(type=ProposalType.AUDITOR_RATIFICATION, supporting_data={"non_audit_fee_ratio": "0.1"})

    llm = fake_llm({})  # deterministic rule should resolve this; no LLM call expected
    recommendation, _usage = await apply_policy(proposal, record, llm)

    assert recommendation.vote == VotePosition.FOR
    assert recommendation.policy_rule_id == "rule_auditor_independence"
    assert recommendation.engagement_alignment_flag is True
    assert llm.calls == []


async def test_apply_policy_falls_back_to_llm_judgment_when_no_rule_matches(fake_llm):
    proposal = _proposal(type=ProposalType.DIRECTOR_ELECTION)
    judgment = PolicyJudgmentDraft(vote=VotePosition.FOR, rationale="Director appears independent.", confidence=0.8)
    llm = fake_llm({"PolicyJudgmentDraft": [judgment]})

    recommendation, _usage = await apply_policy(proposal, None, llm)

    assert recommendation.vote == VotePosition.FOR
    assert recommendation.policy_rule_id is None
    assert recommendation.engagement_alignment_flag is False
    assert llm.calls == ["PolicyJudgmentDraft"]
