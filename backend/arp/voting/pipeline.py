from __future__ import annotations

import logging

from arp.config import Settings
from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import read_done_keys, run_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import latest_decisions, queue_for_review
from arp.schemas.common import CompanyRef, DocType, new_id
from arp.schemas.voting import CompanyBallot, HumanVoteDecision, Proposal, VoteRecord, VotePosition
from arp.storage.engagement_store import EngagementStore
from arp.storage.run_store import RunStore
from arp.voting.ballot_casting import BallotPlatform, CastVoteError, cast_vote
from arp.voting.policy_agent import DEFAULT_POLICY_RULES, PolicyRule, apply_policy
from arp.voting.proposal_agent import extract_proposals

logger = logging.getLogger(__name__)


def _item_key(company_id: str, proposal_number: str) -> str:
    return f"{company_id}:{proposal_number}"


class CompanyBallotResult:
    def __init__(self, ballot: CompanyBallot, usage: LLMUsage) -> None:
        self.ballot = ballot
        self.usage = usage


async def _process_company(
    company: CompanyRef,
    meeting_date: str | None,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    engagement_store: EngagementStore | None,
    settings: Settings,
    rules: list[PolicyRule],
    fund_name: str | None,
    max_evidence_chunks: int = 20,
) -> CompanyBallotResult:
    documents = await registry.fetch_all(company, doc_types=[DocType.PROXY_DEF14A])
    documents_by_id = {d.doc_id: d for d in documents}
    chunks = []
    for doc in documents:
        chunks.extend(chunk_document(doc))
    chunks = chunks[:max_evidence_chunks]

    meeting_id = new_id("mtg")
    usages: list[LLMUsage] = []
    votes: list[VoteRecord] = []

    if chunks:
        draft, usage = await extract_proposals(company.name, meeting_date, chunks, llm)
        usages.append(usage)
        record = engagement_store.get(company.company_id) if engagement_store else None
        for p_draft in draft.proposals:
            grounded_citations = ground_citations(p_draft.citations, documents_by_id, settings.grounding_fuzzy_threshold)
            proposal = Proposal(
                company_id=company.company_id,
                meeting_id=meeting_id,
                meeting_date=meeting_date,
                proposal_number=p_draft.proposal_number,
                type=p_draft.type,
                sponsor=p_draft.sponsor,
                resolution_text=p_draft.resolution_text,
                management_recommendation=p_draft.management_recommendation,
                supporting_data=p_draft.supporting_data,
                citations=grounded_citations,
                confidence=p_draft.confidence,
                source_doc_id=documents[0].doc_id if documents else None,
            )
            recommendation, policy_usage = await apply_policy(proposal, record, llm, rules=rules, fund_name=fund_name)
            usages.append(policy_usage)
            votes.append(VoteRecord(proposal=proposal, policy_recommendation=recommendation))

    ballot = CompanyBallot(company_id=company.company_id, name=company.name, meeting_id=meeting_id, meeting_date=meeting_date, votes=votes)
    return CompanyBallotResult(ballot, combine_usage(*usages) if usages else LLMUsage())


def create_voting_run(companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run("proxy_voting", {}, len(companies), model=settings.llm_model)
    return manifest.run_id


async def execute_voting_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    engagement_store: EngagementStore | None,
    settings: Settings,
    run_store: RunStore,
    meeting_dates: dict[str, str] | None = None,
    rules: list[PolicyRule] = DEFAULT_POLICY_RULES,
    fund_name: str | None = None,
) -> str:
    """Orchestrates the voting module's research/policy half (Proposal
    Analysis Agent -> Policy Application Agent, including the engagement-
    alignment cross-check) across a company universe, checkpointed and
    resumable the same way extraction runs are.

    Unlike extraction, EVERY proposal is queued for review, not just
    low-confidence ones -- casting a vote is irreversible and deadline-
    bound, so no confidence threshold is allowed to skip the human decision
    checkpoint (see docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #6.5). Casting
    itself is a separate step: see cast_approved_votes.
    """
    job_manager = JobManager(run_store)
    meeting_dates = meeting_dates or {}

    def _on_success(company: CompanyRef, result: CompanyBallotResult) -> None:
        for vote in result.ballot.votes:
            queue_for_review(
                run_store, run_id, _item_key(company.company_id, vote.proposal.proposal_number), vote.model_dump(mode="json")
            )
        cost = estimate_cost_usd(settings.llm_model, result.usage)
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=len(result.ballot.votes),
            input_tokens_delta=result.usage.input_tokens,
            output_tokens_delta=result.usage.output_tokens,
            cost_delta_usd=cost,
        )

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    def _cancel_check() -> bool:
        current = run_store.load_manifest(run_id)
        return current is not None and current.cancel_requested

    async def _worker(company: CompanyRef) -> CompanyBallotResult:
        result = await _process_company(
            company,
            meeting_dates.get(company.company_id),
            registry=registry,
            llm=llm,
            engagement_store=engagement_store,
            settings=settings,
            rules=rules,
            fund_name=fund_name,
        )
        # Set before result_to_json/on_success run, so both the persisted
        # results.jsonl row and the review-queue entry agree on run_id.
        result.ballot.votes = [v.model_copy(update={"run_id": run_id}) for v in result.ballot.votes]
        return result

    await run_batch(
        companies,
        item_key=lambda c: c.company_id,
        worker=_worker,
        results_path=run_store.results_path(run_id),
        errors_path=run_store.errors_path(run_id),
        concurrency=settings.max_concurrent_llm_calls,
        result_to_json=lambda r: r.ballot.model_dump(mode="json"),
        on_success=_on_success,
        on_error=_on_error,
        cancel_check=_cancel_check,
    )

    job_manager.finish_run(run_id)
    return run_id


async def run_voting(
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    registry: DocumentSourceRegistry,
    engagement_store: EngagementStore | None,
    settings: Settings,
    run_store: RunStore,
    meeting_dates: dict[str, str] | None = None,
    rules: list[PolicyRule] = DEFAULT_POLICY_RULES,
    fund_name: str | None = None,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI."""
    run_id = create_voting_run(companies, settings, run_store)
    return await execute_voting_run(
        run_id,
        companies,
        llm=llm,
        registry=registry,
        engagement_store=engagement_store,
        settings=settings,
        run_store=run_store,
        meeting_dates=meeting_dates,
        rules=rules,
        fund_name=fund_name,
    )


def _cast_confirmations_path(run_store: RunStore, run_id: str):
    return run_store.run_dir(run_id) / "cast_confirmations.jsonl"


def _human_decision_from_review_row(recommendation, row: dict) -> HumanVoteDecision | None:
    edited = row.get("edited_value") or {}
    vote_str = edited.get("vote")
    if vote_str:
        vote = VotePosition(vote_str)
    elif recommendation is not None:
        vote = recommendation.vote
    else:
        return None
    return HumanVoteDecision(
        vote=vote,
        decided_by=row.get("reviewer") or "unknown",
        override_note=row.get("comment"),
        co_signed_by=edited.get("co_signed_by"),
    )


async def cast_approved_votes(run_id: str, run_store: RunStore, platform: BallotPlatform) -> list[VoteRecord]:
    """Ballot Casting Agent entry point: casts every vote in `run_id` that
    has a recorded human review decision and hasn't been cast yet.

    - decision == 'reject' -> explicitly declined; never cast.
    - decision == 'approve' -> casts the policy recommendation as-is.
    - decision == 'edit' -> casts edited_value['vote'] (a human override);
      edited_value['co_signed_by'] carries the second sign-off required for
      alignment-flagged items (see arp.voting.ballot_casting.cast_vote).
    - no decision yet -> skipped, not an error; the item is still awaiting
      its mandatory human checkpoint.

    Idempotent and resumable like everything else in this codebase: already
    -cast items (tracked in cast_confirmations.jsonl) are skipped on rerun.
    """
    ballot_rows = run_store.read_jsonl(run_store.results_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    confirmations_path = _cast_confirmations_path(run_store, run_id)
    already_cast = read_done_keys(confirmations_path)

    cast_records: list[VoteRecord] = []
    for row in ballot_rows:
        ballot = CompanyBallot.model_validate(row)
        for vote in ballot.votes:
            item_key = _item_key(ballot.company_id, vote.proposal.proposal_number)
            if item_key in already_cast:
                continue
            decision_row = decisions.get(item_key)
            if decision_row is None or decision_row["decision"] == "reject":
                continue
            human_decision = _human_decision_from_review_row(vote.policy_recommendation, decision_row)
            if human_decision is None:
                continue
            vote = vote.model_copy(update={"human_decision": human_decision})
            try:
                vote = await cast_vote(platform, vote)
            except CastVoteError as exc:
                run_store.append_jsonl(run_store.errors_path(run_id), {"key": item_key, "error": str(exc)})
                continue
            record = vote.model_dump(mode="json")
            record["_key"] = item_key
            run_store.append_jsonl(confirmations_path, record)
            cast_records.append(vote)
    return cast_records


def get_cast_votes(run_store: RunStore, run_id: str) -> list[VoteRecord]:
    return [VoteRecord.model_validate(row) for row in run_store.read_jsonl(_cast_confirmations_path(run_store, run_id))]


def get_ballots(run_store: RunStore, run_id: str) -> list[CompanyBallot]:
    """Raw per-company ballots as produced by the Proposal/Policy agents,
    without decisions or cast confirmations overlaid -- use together with
    get_cast_votes() and the run's review-queue endpoints to show full
    status."""
    return [CompanyBallot.model_validate(row) for row in run_store.read_jsonl(run_store.results_path(run_id))]
