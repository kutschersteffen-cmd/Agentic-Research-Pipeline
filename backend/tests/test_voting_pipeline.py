from arp.config import Settings
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.review_queue import record_review_decision
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.voting import VotePosition
from arp.storage.run_store import RunStore
from arp.voting.ballot_casting import CastVoteError, ManualInstructionBallotPlatform, cast_vote
from arp.voting.pipeline import _process_company, cast_approved_votes, create_voting_run, execute_voting_run
from arp.voting.policy_agent import DEFAULT_POLICY_RULES
from arp.voting.proposal_agent import ProposalDraft, ProposalListDraft
from arp.schemas.voting import ProposalType


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
        engagements_dir=tmp_path / "engagements",
        ballots_dir=tmp_path / "ballots",
    )


def _proxy_doc() -> SourceDocument:
    return SourceDocument(
        company_id="C1",
        doc_type=DocType.PROXY_DEF14A,
        title="Proxy statement",
        full_text="Proposal 3 asks shareholders to ratify the appointment of the independent auditor.",
    )


async def test_process_company_grounds_citation_and_applies_deterministic_rule(tmp_path, fake_llm):
    doc = _proxy_doc()
    company = CompanyRef(company_id="C1", name="Acme Corp")
    proposal_draft = ProposalDraft(
        proposal_number="3",
        type=ProposalType.AUDITOR_RATIFICATION,
        sponsor="Management",
        resolution_text="Ratify the appointment of the independent auditor.",
        management_recommendation=VotePosition.FOR,
        supporting_data={"non_audit_fee_ratio": "0.1"},
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="ratify the appointment of the independent auditor")],
        confidence=0.9,
    )
    llm = fake_llm({"ProposalListDraft": [ProposalListDraft(proposals=[proposal_draft])]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _process_company(
        company, "2026-05-01", registry=registry, llm=llm, engagement_store=None, settings=_settings(tmp_path), rules=DEFAULT_POLICY_RULES, fund_name=None,
    )

    assert len(result.ballot.votes) == 1
    vote = result.ballot.votes[0]
    assert vote.proposal.citations[0].grounded is True
    assert vote.policy_recommendation.vote == VotePosition.FOR
    assert vote.policy_recommendation.policy_rule_id == "rule_auditor_independence"
    # Deterministic rule resolved it -- only the proposal extraction call hit the LLM.
    assert llm.calls == ["ProposalListDraft"]


async def test_process_company_no_documents_produces_empty_ballot(tmp_path, fake_llm):
    company = CompanyRef(company_id="C1", name="Acme Corp")
    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([])])

    result = await _process_company(
        company, None, registry=registry, llm=llm, engagement_store=None, settings=_settings(tmp_path), rules=DEFAULT_POLICY_RULES, fund_name=None
    )

    assert result.ballot.votes == []
    assert llm.calls == []


async def test_execute_voting_run_queues_every_proposal_for_review(tmp_path, fake_llm):
    doc = _proxy_doc()
    company = CompanyRef(company_id="C1", name="Acme Corp")
    proposal_draft = ProposalDraft(
        proposal_number="3",
        type=ProposalType.AUDITOR_RATIFICATION,
        sponsor="Management",
        resolution_text="Ratify the appointment of the independent auditor.",
        supporting_data={"non_audit_fee_ratio": "0.1"},
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="ratify the appointment of the independent auditor")],
        confidence=0.95,
    )
    llm = fake_llm({"ProposalListDraft": [ProposalListDraft(proposals=[proposal_draft])]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)

    run_id = create_voting_run([company], settings, run_store)
    await execute_voting_run(run_id, [company], llm=llm, registry=registry, engagement_store=None, settings=settings, run_store=run_store)

    manifest = run_store.load_manifest(run_id)
    assert manifest.completed_count == 1
    assert manifest.review_count == 1  # one proposal, mandatory review regardless of confidence

    review_rows = run_store.read_jsonl(run_store.review_queue_path(run_id))
    assert len(review_rows) == 1
    assert review_rows[0]["item_key"] == "C1:3"


def test_ballot_platform_writes_instruction_file_and_confirms(tmp_path):
    import asyncio

    from arp.schemas.voting import HumanVoteDecision, Proposal, VoteRecord

    platform = ManualInstructionBallotPlatform(tmp_path / "ballots")
    proposal = Proposal(company_id="C1", meeting_id="mtg1", proposal_number="3", type=ProposalType.AUDITOR_RATIFICATION, sponsor="Management", resolution_text="Ratify.")
    vote_record = VoteRecord(proposal=proposal, human_decision=HumanVoteDecision(vote=VotePosition.FOR, decided_by="jane.pm"))

    cast = asyncio.run(cast_vote(platform, vote_record))

    assert cast.cast_confirmation is not None
    assert cast.cast_confirmation.platform == "manual_instruction_file"
    assert (tmp_path / "ballots" / f"{vote_record.vote_record_id}.txt").exists()


async def test_cast_vote_refuses_without_human_decision():
    from arp.schemas.voting import Proposal, VoteRecord

    proposal = Proposal(company_id="C1", meeting_id="mtg1", proposal_number="3", type=ProposalType.OTHER, sponsor="Management", resolution_text="x")
    vote_record = VoteRecord(proposal=proposal)
    platform = ManualInstructionBallotPlatform.__new__(ManualInstructionBallotPlatform)  # never reaches cast()

    try:
        await cast_vote(platform, vote_record)
        assert False, "expected CastVoteError"
    except CastVoteError:
        pass


async def test_cast_vote_refuses_alignment_flag_without_cosign():
    from arp.schemas.voting import HumanVoteDecision, PolicyRecommendation, Proposal, VoteRecord

    proposal = Proposal(company_id="C1", meeting_id="mtg1", proposal_number="3", type=ProposalType.SAY_ON_PAY, sponsor="Management", resolution_text="x")
    recommendation = PolicyRecommendation(vote=VotePosition.FOR, rationale="x", engagement_alignment_flag=True, engagement_alignment_note="conflict")
    vote_record = VoteRecord(proposal=proposal, policy_recommendation=recommendation, human_decision=HumanVoteDecision(vote=VotePosition.FOR, decided_by="jane.pm"))
    platform = ManualInstructionBallotPlatform.__new__(ManualInstructionBallotPlatform)

    try:
        await cast_vote(platform, vote_record)
        assert False, "expected CastVoteError"
    except CastVoteError:
        pass


async def test_cast_approved_votes_respects_review_decisions(tmp_path, fake_llm):
    doc = _proxy_doc()
    company = CompanyRef(company_id="C1", name="Acme Corp")
    drafts = [
        ProposalDraft(
            proposal_number="1", type=ProposalType.OTHER, sponsor="Management", resolution_text="Routine item.",
            management_recommendation=VotePosition.FOR, confidence=0.9,
        ),
        ProposalDraft(
            proposal_number="2", type=ProposalType.OTHER, sponsor="Management", resolution_text="Another routine item.",
            management_recommendation=VotePosition.FOR, confidence=0.9,
        ),
        ProposalDraft(
            proposal_number="3", type=ProposalType.OTHER, sponsor="Management", resolution_text="A third item.",
            management_recommendation=VotePosition.FOR, confidence=0.9,
        ),
    ]
    llm = fake_llm({"ProposalListDraft": [ProposalListDraft(proposals=drafts)]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)

    run_id = create_voting_run([company], settings, run_store)
    await execute_voting_run(run_id, [company], llm=llm, registry=registry, engagement_store=None, settings=settings, run_store=run_store)

    # #1 approved as-is, #2 edited to AGAINST, #3 rejected (never cast), no decision recorded for a hypothetical #4.
    record_review_decision(run_store, run_id, "C1:1", "approve", "jane.pm", None)
    record_review_decision(run_store, run_id, "C1:2", "edit", "jane.pm", {"vote": "against"}, comment="Overriding management rec.")
    record_review_decision(run_store, run_id, "C1:3", "reject", "jane.pm", None)

    platform = ManualInstructionBallotPlatform(settings.ballots_dir)
    cast = await cast_approved_votes(run_id, run_store, platform)

    by_key = {f"{v.proposal.company_id}:{v.proposal.proposal_number}": v for v in cast}
    assert set(by_key) == {"C1:1", "C1:2"}
    assert by_key["C1:1"].human_decision.vote == VotePosition.FOR
    assert by_key["C1:2"].human_decision.vote == VotePosition.AGAINST
    assert all(v.cast_confirmation is not None for v in cast)

    # Idempotent: a second call doesn't re-cast already-cast items.
    cast_again = await cast_approved_votes(run_id, run_store, platform)
    assert cast_again == []
