import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CompanyBallot, VoteRecord, VotePosition, VoteReviewDecision } from "../types";
import { Modal } from "./Modal";
import { DecisionBar } from "./DecisionBar";
import { CitationList } from "./CitationList";
import { SourcePanel, type ActiveSource } from "./SourcePanel";
import { REVIEWER_REQUIRED, useReviewer } from "../lib/reviewer";
import { ReviewerField } from "./ReviewerField";
import { ProposedTag } from "./ProposedTag";
import { Seal } from "./Seal";

const VOTE_POSITIONS: VotePosition[] = ["for", "against", "abstain", "withhold"];

const DECISION_LABEL: Record<string, string> = { approve: "approved", edit: "overridden", reject: "rejected" };

/** "12 Oct 2026 · in 5 days": the date a vote is due, and how soon. */
function meetingLabel(date: string | null | undefined): string {
  if (!date) return "Meeting date not found in the proxy statement";
  const d = new Date(date);
  const days = Math.ceil((d.getTime() - Date.now()) / 86_400_000);
  const when = days > 1 ? `in ${days} days` : days === 1 ? "tomorrow" : days === 0 ? "today" : `${-days} days ago`;
  return `Meeting ${d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })} · ${when}`;
}

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
  onOpenSource,
}: {
  runId: string;
  ballot: CompanyBallot;
  vote: VoteRecord;
  decision: VoteReviewDecision | undefined;
  castConfirmationId: string | undefined;
  onReviewed: () => void;
  onOpenSource: (s: ActiveSource) => void;
}) {
  const rec = vote.policy_recommendation;
  const alreadyCast = castConfirmationId !== undefined;
  // Nothing is pre-selected: a proposal is only decided when a person presses a decision.
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [chosenVote, setChosenVote] = useState<VotePosition>(rec?.vote ?? "for");
  const [coSignedBy, setCoSignedBy] = useState("");
  const [reviewer] = useReviewer();
  const [comment, setComment] = useState("");
  const [commentOpen, setCommentOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const key = itemKey(ballot.company_id, vote.proposal.proposal_number);
  const needsCoSign = rec?.engagement_alignment_flag === true;

  async function submit(reviewDecision: "approve" | "edit" | "reject") {
    if (!reviewer.trim()) {
      setError(REVIEWER_REQUIRED);
      return;
    }
    if (needsCoSign && coSignedBy.trim().toLowerCase() === reviewer.trim().toLowerCase()) {
      setError("The co-sign must come from a second person, not the reviewer.");
      return;
    }
    if (needsCoSign && !coSignedBy.trim()) {
      setError("This proposal has an engagement alignment flag: enter a second person’s name as co-signer first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.submitVotingReview(runId, {
        item_key: key,
        decision: reviewDecision,
        reviewer: reviewer.trim(),
        vote: reviewDecision === "edit" ? chosenVote : null,
        co_signed_by: coSignedBy || null,
        comment: comment || null,
      });
      setComment("");
      setCommentOpen(false);
      setOverrideOpen(false);
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
      {Object.keys(vote.proposal.supporting_data ?? {}).length > 0 && (
        <dl className="supporting-data">
          {Object.entries(vote.proposal.supporting_data).map(([k, v]) => (
            <div key={k}>
              <dt>{k.replace(/_/g, " ")}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {vote.proposal.citations.length > 0 ? (
        <CitationList citations={vote.proposal.citations} onOpenSource={onOpenSource} />
      ) : (
        <p className="muted">No citation from the proxy statement was recorded for this proposal.</p>
      )}

      {rec && (
        <div className={decision || alreadyCast ? "recommendation-line" : "recommendation-line proposed"}>
          {!decision && !alreadyCast && <ProposedTag>Proposed by the policy agent · awaiting a decision</ProposedTag>}
          Policy recommendation: <strong>{rec.vote}</strong> ({rec.policy_rule_id ? `rule: ${rec.policy_rule_id}` : "LLM judgment"},{" "}
          {Math.round(rec.confidence * 100)}% confidence)
          <br />
          <span className="muted">{rec.rationale}</span>
        </div>
      )}
      {rec?.engagement_alignment_flag && (
        <div className="banner banner-await">
          <strong>Needs a second person.</strong> Engagement alignment flag: {rec.engagement_alignment_note}
        </div>
      )}

      {alreadyCast && (
        <div className="banner banner-success">Cast &middot; confirmation {castConfirmationId}</div>
      )}

      {!alreadyCast && (
        <>
          {decision && (
            <p className="muted">
              Current decision: <strong>{DECISION_LABEL[decision.decision] ?? decision.decision}</strong> by {decision.reviewer ?? "unknown reviewer"}
              {decision.edited_value?.vote ? ` → ${decision.edited_value.vote}` : ""}
            </p>
          )}
          {needsCoSign && (
            <input
              aria-label="Co-signed by"
              placeholder="Co-signed by (required: alignment flag)"
              value={coSignedBy}
              onChange={(e) => setCoSignedBy(e.target.value)}
            />
          )}
          {commentOpen || comment ? (
            <textarea rows={2} autoFocus aria-label="Comment (optional)" placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
          ) : (
            <button className="link-button add-comment" onClick={() => setCommentOpen(true)}>
              Add comment
            </button>
          )}
          <DecisionBar
            approveLabel={rec ? `Approve: vote ${rec.vote}` : "Approve"}
            onApprove={() => submit("approve")}
            onOverride={() => setOverrideOpen((o) => !o)}
            overrideOpen={overrideOpen}
            onReject={() => submit("reject")}
            rejectLabel="Reject (do not cast)"
            disabled={busy}
          />
          {overrideOpen && (
            <div className="inline-fields">
              <select aria-label="Vote to cast instead" value={chosenVote} onChange={(e) => setChosenVote(e.target.value as VotePosition)}>
                {VOTE_POSITIONS.map((v) => (
                  <option key={v} value={v}>
                    Vote {v}
                  </option>
                ))}
              </select>
              <button className="secondary" onClick={() => submit("edit")} disabled={busy}>
                Record override
              </button>
            </div>
          )}
          {error && <p className="error-text" role="alert">{error}</p>}
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
  const [castResult, setCastResult] = useState<{ count: number; by: string; at: Date } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [reviewer] = useReviewer();

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
    setConfirming(false);
    setBusy(true);
    setError(null);
    setCastResult(null);
    try {
      const res = await api.castVotes(runId);
      setCastResult({ count: res.cast_count, by: reviewer.trim(), at: new Date() });
      await load();
    } catch (err) {
      setError(`Casting failed: ${(err as Error).message}. Nothing was marked cast; try again.`);
    } finally {
      setBusy(false);
    }
  }

  // What a cast would send right now, from the same rules the backend applies
  // (arp.voting.pipeline.cast_approved_votes): decided, not rejected, not cast.
  const counts = { approved: 0, overridden: 0, rejected: 0, pending: 0, missingCoSign: 0 };
  const outgoing: { key: string; company: string; number: string; vote: string; overridden: boolean }[] = [];
  for (const b of ballots) {
    for (const v of b.votes) {
      const k = itemKey(b.company_id, v.proposal.proposal_number);
      if (castByKey[k] !== undefined) continue;
      const d = decisions[k];
      if (!d) counts.pending++;
      else if (d.decision === "reject") counts.rejected++;
      else {
        if (d.decision === "edit") counts.overridden++;
        else counts.approved++;
        outgoing.push({
          key: k,
          company: b.name,
          number: v.proposal.proposal_number,
          vote: (d.decision === "edit" ? d.edited_value?.vote : v.policy_recommendation?.vote) ?? "—",
          overridden: d.decision === "edit",
        });
        if (v.policy_recommendation?.engagement_alignment_flag && !d.edited_value?.co_signed_by) counts.missingCoSign++;
      }
    }
  }
  const castable = counts.approved + counts.overridden;
  // Proposals not yet cast, decided or not: what the sticky bar counts down.
  const toDecide = castable + counts.rejected + counts.pending;
  const totalProposals = ballots.reduce((sum, b) => sum + b.votes.length, 0);
  const totalCast = Object.keys(castByKey).length;
  // Soonest meeting first: that is the order the deadlines arrive in.
  const byMeeting = [...ballots].sort((a, b) => (a.meeting_date ?? "9999").localeCompare(b.meeting_date ?? "9999"));
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  return (
    <section className="card">
      <div className="section-heading">
        <h3>
          Ballots <span className="muted">run {runId}</span>
        </h3>
        <button className="link-button" onClick={load}>
          Refresh
        </button>
      </div>
      <p className="help-text">
        Every proposal needs a decision from a named person; nothing is approved automatically. A proposal with an
        engagement alignment flag also needs a co-sign.
      </p>
      <p className="muted">
        {totalProposals} proposal{totalProposals === 1 ? "" : "s"} across {ballots.length} compan{ballots.length === 1 ? "y" : "ies"} &middot; {totalCast} cast &middot;{" "}
        {counts.pending} awaiting a decision
      </p>
      <div className="toolbar">
        <ReviewerField compact />
      </div>
      <div aria-live="polite">
        {castResult && (
          <div className="banner banner-success cast-sealed">
            <Seal className="cast-seal" draw />
            <span>
              {castResult.count} vote{castResult.count === 1 ? "" : "s"} countersigned and cast by {castResult.by} at {castResult.at.toLocaleString()}.
              Confirmation IDs are shown on each proposal below.
            </span>
          </div>
        )}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}

      {confirming && (
        <Modal title="Cast votes?" compact onClose={() => setConfirming(false)}>
          <p>
            This sends <strong>{castable}</strong> vote{castable === 1 ? "" : "s"} to the ballot platform. Cast votes cannot be recalled from here.
          </p>
          <ul className="confirm-list">
            <li>{counts.approved} approved as recommended</li>
            <li>{counts.overridden} overridden by a reviewer</li>
            <li>{counts.rejected} rejected (will not be cast)</li>
            <li>{counts.pending} still awaiting a decision (will not be cast)</li>
          </ul>
          <table className="data-table cast-list">
            <caption className="visually-hidden">Votes that will be cast</caption>
            <thead>
              <tr>
                <th>Company</th>
                <th>Proposal</th>
                <th>Vote</th>
              </tr>
            </thead>
            <tbody>
              {outgoing.map((o) => (
                <tr key={o.key}>
                  <td>{o.company}</td>
                  <td>#{o.number}</td>
                  <td>
                    <strong>{o.vote}</strong>
                    {o.overridden && <span className="muted"> (overridden)</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {counts.missingCoSign > 0 && (
            <div className="banner banner-danger">
              {counts.missingCoSign} flagged vote{counts.missingCoSign === 1 ? " has" : "s have"} no co-sign and will be refused by the platform.
            </div>
          )}
          <p className="muted">Recorded against the name you entered: {reviewer.trim()} (not verified by a login)</p>
          <div className="toolbar">
            <button onClick={castApproved}>Cast {castable} vote{castable === 1 ? "" : "s"}</button>
            <button className="secondary" onClick={() => setConfirming(false)}>
              Keep reviewing
            </button>
          </div>
        </Modal>
      )}

      <div className="split-review">
      <div className="split-review-main">
      {byMeeting.map((ballot) => (
        <div key={ballot.company_id} className="panel-section">
          <h4>
            {ballot.name} <span className="muted">({ballot.company_id})</span>
          </h4>
          <p className="meeting-line">{meetingLabel(ballot.meeting_date)}</p>
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
              onOpenSource={setActiveSource}
            />
          ))}
        </div>
      ))}
      </div>
      {activeSource && <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />}
      </div>
      {toDecide > 0 && (
        <div className="cast-bar">
          <span>
            <strong>{toDecide - counts.pending}</strong> of {toDecide} decided
            {counts.pending > 0 && <span className="muted"> · {counts.pending} awaiting a decision</span>}
          </span>
          <button onClick={() => (reviewer.trim() ? setConfirming(true) : setError(REVIEWER_REQUIRED))} disabled={busy || castable === 0}>
            Cast {castable} vote{castable === 1 ? "" : "s"}…
          </button>
        </div>
      )}
    </section>
  );
}
