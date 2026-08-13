from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from arp.schemas.voting import CastConfirmation, CastStatus, VoteRecord


class BallotPlatform(ABC):
    """Transmits an authorized vote instruction somewhere real: a custodian
    API, an ISS/Glass Lewis voting platform, or similar. Which platform to
    integrate is a house infrastructure decision (see
    docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #8), not an architectural one --
    swap implementations behind this interface without touching the agent
    that calls it."""

    name: str = "base"

    @abstractmethod
    async def cast(self, vote_record: VoteRecord) -> CastConfirmation:
        raise NotImplementedError


class ManualInstructionBallotPlatform(BallotPlatform):
    """No real custodian/proxy-platform integration is wired up yet -- this
    writes a human-readable voting instruction file instead of transmitting
    anywhere, so the rest of the pipeline (and its tests) can exercise the
    real cast_vote() contract today, with a real platform swapped in later
    against the same BallotPlatform interface."""

    name = "manual_instruction_file"

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    async def cast(self, vote_record: VoteRecord) -> CastConfirmation:
        confirmation = CastConfirmation(platform=self.name)
        instruction = (
            f"Company: {vote_record.proposal.company_id}\n"
            f"Meeting: {vote_record.proposal.meeting_id} ({vote_record.proposal.meeting_date or 'date unknown'})\n"
            f"Proposal #{vote_record.proposal.proposal_number}: {vote_record.proposal.resolution_text}\n"
            f"Vote: {vote_record.human_decision.vote.value if vote_record.human_decision else '(none)'}\n"
            f"Decided by: {vote_record.human_decision.decided_by if vote_record.human_decision else '(none)'}\n"
            f"Confirmation: {confirmation.confirmation_id}\n"
        )
        path = self.out_dir / f"{vote_record.vote_record_id}.txt"
        path.write_text(instruction)
        return confirmation


class CastVoteError(Exception):
    pass


async def cast_vote(platform: BallotPlatform, vote_record: VoteRecord) -> VoteRecord:
    """Executes an authorized vote. This function has no read access to a
    "recommendation" -- only to a `human_decision` -- by construction: it
    refuses outright if one isn't present, so an unauthorized vote can
    never be cast from here regardless of what upstream code does (see
    docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #6.4).

    A recommendation carrying an engagement_alignment_flag additionally
    requires a co-sign (see docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #6.5)
    before it can be cast.

    Idempotent: a vote_record that already has a cast_confirmation is
    returned unchanged rather than cast twice.
    """
    if vote_record.human_decision is None:
        raise CastVoteError(f"Refusing to cast {vote_record.vote_record_id}: no recorded human_decision.")
    if vote_record.policy_recommendation is not None and vote_record.policy_recommendation.engagement_alignment_flag:
        if not vote_record.human_decision.co_signed_by:
            raise CastVoteError(
                f"Refusing to cast {vote_record.vote_record_id}: engagement_alignment_flag is set and requires a co-sign."
            )
    if vote_record.cast_confirmation is not None:
        return vote_record

    confirmation = await platform.cast(vote_record)
    return vote_record.model_copy(update={"cast_confirmation": confirmation})
