import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CompanyBallot, VoteRecord, VotePosition, VoteReviewDecision } from "../types";

const VOTE_POSITIONS: VotePosition[] = ["for", "against", "abstain", "withhold"];

function itemKey(companyId: string, proposalNumber: string): string {
  return `${companyId}:${proposalNumber}`;
}

function ProposalReview({
  runId,
  ballot,
  vote,
  decision,
  castConfirmationId,
  onReviewed,
}: {
  runId: string;
  ballot: CompanyBallot;
  vote: VoteRecord;
  decision: VoteReviewDecision | undefined;
  castConfirmationId: string | undefined;
  onReviewed: () => void;
}) {
  const rec = vote.policy_recommendation;
  const alreadyCast = castConfirmationId !== undefined;
  const [reviewDecision, setReviewDecision] = useState<"approve" | "edit" | "reject">("approve");
  const [chosenVote, setChosenVote] = useState<VotePosition>(rec?.vote ?? "for");
  const [coSignedBy, setCoSignedBy] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const key = itemKey(ballot.company_id, vote.proposal.proposal_number);
  const needsCoSign = rec?.engagement_alignment_flag === true;

  async function submit() {
    if (!reviewer.trim()) {
      setError("Reviewer name is required.");
      return;
    }
    if (needsCoSign && !coSignedBy.trim()) {
      setError("This item carries an engagement alignment flag -- a co-sign is required before it can be cast.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.submitVotingReview(runId, {
        item_key: key,
        decision: reviewDecision,
        reviewer,
        vote: reviewDecision === "edit" ? chosenVote : null,
        co_signed_by: coSignedBy || null,
        comment: comment || null,
      });
      setComment("");
      onReviewed();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="proposal-card">
      <div className="proposal-header">
        <strong>
          #{vote.proposal.proposal_number} &middot; {vote.proposal.type.replace(/_/g, " ")}
        </strong>
        <span className="muted">sponsor: {vote.proposal.sponsor}</span>
      </div>
      <p className="proposal-text">{vote.proposal.resolution_text}</p>
      {vote.proposal.management_recommendation && (
        <p className="muted">Management recommends: {vote.proposal.management_recommendation}</p>
      )}

      {rec && (
        <p className="recommendation-line">
          Policy recommendation: <strong>{rec.vote}</strong> ({rec.policy_rule_id ? `rule: ${rec.policy_rule_id}` : "LLM judgment"},{" "}
          {Math.round(rec.confidence * 100)}% confidence)
          <br />
          <span className="muted">{rec.rationale}</span>
        </p>
      )}
      {rec?.engagement_alignment_flag && (
        <div className="banner banner-danger">Engagement alignment flag: {rec.engagement_alignment_note}</div>
      )}

      {alreadyCast && (
        <div className="banner banner-warning">Cast &mdash; confirmation {castConfirmationId}</div>
      )}

      {!alreadyCast && (
        <>
          {decision && (
            <p className="muted">
              Current decision: <strong>{decision.decision}</strong> by {decision.reviewer ?? "unknown"}
              {decision.edited_value?.vote ? ` -> ${decision.edited_value.vote}` : ""}
            </p>
          )}
          <div className="inline-fields">
            <select value={reviewDecision} onChange={(e) => setReviewDecision(e.target.value as typeof reviewDecision)}>
              <option value="approve">Approve recommendation</option>
              <option value="edit">Override vote</option>
              <option value="reject">Reject (do not cast)</option>
            </select>
            {reviewDecision === "edit" && (
              <select value={chosenVote} onChange={(e) => setChosenVote(e.target.value as VotePosition)}>
                {VOTE_POSITIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            )}
            <input placeholder="Reviewer name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </div>
          {needsCoSign && (
            <input
              placeholder="Co-signed by (required -- alignment flag)"
              value={coSignedBy}
              onChange={(e) => setCoSignedBy(e.target.value)}
            />
          )}
          <textarea rows={1} placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
          <button onClick={submit} disabled={busy}>
            Record decision
          </button>
          {error && <p className="error-text">{error}</p>}
        </>
      )}
    </div>
  );
}

export function BallotReview({ runId }: { runId: string }) {
  const [ballots, setBallots] = useState<CompanyBallot[]>([]);
  const [decisions, setDecisions] = useState<Record<string, VoteReviewDecision>>({});
  const [castByKey, setCastByKey] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [castResult, setCastResult] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const [ballotsRes, queueRes, castRes] = await Promise.all([
        api.getVotingBallots(runId),
        api.getVotingReviewQueue(runId),
        api.getCastVotes(runId),
      ]);
      setBallots(ballotsRes.ballots);
      const decisionMap: Record<string, VoteReviewDecision> = {};
      for (const d of queueRes.decided) decisionMap[d.item.item_key as string] = d.decision;
      setDecisions(decisionMap);
      const castMap: Record<string, string> = {};
      for (const v of castRes.votes) castMap[itemKey(v.proposal.company_id, v.proposal.proposal_number)] = v.cast_confirmation?.confirmation_id ?? "";
      setCastByKey(castMap);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  async function castApproved() {
    setBusy(true);
    setError(null);
    setCastResult(null);
    try {
      const res = await api.castVotes(runId);
      setCastResult(`Cast ${res.cast_count} vote(s).`);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const totalProposals = ballots.reduce((sum, b) => sum + b.votes.length, 0);
  const totalCast = Object.keys(castByKey).length;

  return (
    <section className="card">
      <div className="section-heading">
        <h3>Ballots for {runId}</h3>
        <button className="link-button" onClick={load}>
          Refresh
        </button>
      </div>
      <p className="help-text">
        Every proposal requires an explicit human decision, regardless of confidence -- there is no auto-approve
        path for voting. An engagement alignment flag additionally requires a co-sign before it can be cast.
      </p>
      <p className="muted">
        {totalProposals} proposal(s) across {ballots.length} compan{ballots.length === 1 ? "y" : "ies"} &middot; {totalCast} cast
      </p>
      <button onClick={castApproved} disabled={busy}>
        Cast approved votes
      </button>
      {castResult && <p className="status-text">{castResult}</p>}
      {error && <p className="error-text">{error}</p>}

      {ballots.map((ballot) => (
        <div key={ballot.company_id} className="panel-section">
          <h4>
            {ballot.name} <span className="muted">({ballot.company_id})</span>
          </h4>
          {ballot.votes.length === 0 && <p className="muted">No proposals found (no proxy statement available yet).</p>}
          {ballot.votes.map((vote) => (
            <ProposalReview
              key={vote.vote_record_id}
              runId={runId}
              ballot={ballot}
              vote={vote}
              decision={decisions[itemKey(ballot.company_id, vote.proposal.proposal_number)]}
              castConfirmationId={castByKey[itemKey(ballot.company_id, vote.proposal.proposal_number)] || undefined}
              onReviewed={load}
            />
          ))}
        </div>
      ))}
    </section>
  );
}
