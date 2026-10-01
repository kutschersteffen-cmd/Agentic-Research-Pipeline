import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CompanyBallot, VoteRecord, VotePosition, VoteReviewDecision } from "../types";
import { Modal } from "./Modal";
import { ConfirmDecision } from "./ConfirmDecision";
import { DecisionBar } from "./DecisionBar";
import { CitationList } from "./CitationList";
import { SourcePanel, type ActiveSource } from "./SourcePanel";
import { REVIEWER_REQUIRED, useReviewer } from "../lib/reviewer";
import { ReviewerField } from "./ReviewerField";
import { ProposedTag } from "./ProposedTag";
import { announce } from "../lib/announce";
import { useCardKeys } from "../lib/cardKeys";
import { CommentField } from "./CommentField";

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

/** Routine: the policy recommends a vote and nothing flags it for a second
 * person. Routine proposals read as one row and can be approved as a batch;
 * flagged ones always get the full card and a decision of their own. */
const isRoutine = (v: VoteRecord) => Boolean(v.policy_recommendation && !v.policy_recommendation.engagement_alignment_flag);

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(!isRoutine(vote));

  const key = itemKey(ballot.company_id, vote.proposal.proposal_number);
  const needsCoSign = rec?.engagement_alignment_flag === true;
  // A flagged vote is decided only with a second, different person's name;
  // until then every decision button waits.
  const coSignOk = !needsCoSign || (coSignedBy.trim() !== "" && coSignedBy.trim().toLowerCase() !== reviewer.trim().toLowerCase());

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
      setOverrideOpen(false);
      announce(`Proposal ${vote.proposal.proposal_number} for ${ballot.name} ${DECISION_LABEL[reviewDecision]}.`);
      onReviewed();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!expanded && rec) {
    const status = alreadyCast ? `Cast · ${castConfirmationId}` : decision ? `${DECISION_LABEL[decision.decision] ?? decision.decision} by ${decision.reviewer ?? "unknown"}` : null;
    return (
      <div className="proposal-card proposal-compact" tabIndex={-1}>
        <strong className="proposal-num">#{vote.proposal.proposal_number}</strong>
        <span className="proposal-clip" title={vote.proposal.resolution_text}>
          {vote.proposal.resolution_text}
        </span>
        <span className="proposal-policy">
          Policy: <strong>{rec.vote}</strong> · {rec.policy_rule_id ?? "LLM judgment"} · {Math.round(rec.confidence * 100)}%
        </span>
        {status ? (
          <span className="muted">{status}</span>
        ) : (
          <button className="secondary" onClick={() => submit("approve")} disabled={busy}>
            Approve: vote {rec.vote}
          </button>
        )}
        <button className="link-button" onClick={() => setExpanded(true)} aria-expanded={false}>
          Details
        </button>
        {error && <p className="error-text" role="alert">{error}</p>}
      </div>
    );
  }

  return (
    <div className={needsCoSign ? "proposal-card proposal-flagged" : "proposal-card"} tabIndex={-1}>
      {isRoutine(vote) && (
        <button className="link-button proposal-collapse" onClick={() => setExpanded(false)} aria-expanded>
          Less
        </button>
      )}
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
        <div className="banner banner-warning">
          <strong>Needs a second person.</strong> Engagement alignment flag: {rec.engagement_alignment_note || "no note recorded"}
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
            <label className="field-label">
              Co-signer: a second person who agrees with this decision
              <input value={coSignedBy} onChange={(e) => setCoSignedBy(e.target.value)} />
            </label>
          )}
          {needsCoSign && !coSignOk && (
            <p className="muted">
              {coSignedBy.trim()
                ? "The co-signer must be someone other than you."
                : "Waiting for a co-signer. Leave it undecided until they can sign: an undecided vote is never cast."}
            </p>
          )}
          <CommentField value={comment} onChange={setComment} />
          <DecisionBar
            approveLabel={rec ? `Approve: vote ${rec.vote}` : "Approve"}
            onApprove={() => submit("approve")}
            onOverride={() => setOverrideOpen((o) => !o)}
            overrideOpen={overrideOpen}
            onReject={() => submit("reject")}
            rejectLabel="Reject (do not cast)"
            disabled={busy || !coSignOk}
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
  const [confirmingBatch, setConfirmingBatch] = useState(false);
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

  // One named person approves every routine, undecided proposal at the policy's
  // vote. There is no batch endpoint: each is recorded as its own decision, so
  // the audit trail reads the same as approving them one by one.
  async function approveRoutine(by: string) {
    setConfirmingBatch(false);
    setBusy(true);
    setError(null);
    let done = 0;
    try {
      for (const r of routine) {
        await api.submitVotingReview(runId, { item_key: r.key, decision: "approve", reviewer: by, comment: "Approved in a batch at the policy recommendation" });
        done++;
      }
      announce(`${done} routine proposal${done === 1 ? "" : "s"} approved.`);
    } catch (err) {
      setError(`Stopped after ${done} of ${routine.length}: ${(err as Error).message}. The rest are still undecided.`);
    } finally {
      await load();
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
  const routine = ballots.flatMap((b) =>
    b.votes
      .filter((v) => isRoutine(v))
      .map((v) => ({ key: itemKey(b.company_id, v.proposal.proposal_number), company: b.name, number: v.proposal.proposal_number, vote: v.policy_recommendation!.vote, rule: v.policy_recommendation!.policy_rule_id }))
      .filter((r) => !decisions[r.key] && castByKey[r.key] === undefined),
  );
  const totalProposals = ballots.reduce((sum, b) => sum + b.votes.length, 0);
  const totalCast = Object.keys(castByKey).length;
  // Soonest meeting first: that is the order the deadlines arrive in.
  const byMeeting = [...ballots].sort((a, b) => (a.meeting_date ?? "9999").localeCompare(b.meeting_date ?? "9999"));
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  useCardKeys(".proposal-card");

  return (
    <section className="card">
      <div className="section-heading">
        <h2>Ballots for {runId}</h2>
        <button className="link-button" onClick={load}>
          Refresh
        </button>
      </div>
      <p className="help-text">
        Every proposal needs a decision from a named person; nothing is approved automatically. A proposal with an
        engagement alignment flag also needs a co-sign. <span className="kbd-hint">Press <kbd>J</kbd> / <kbd>K</kbd> to move between proposals.</span>
      </p>
      {/* Stays in view while scrolling the ballot: the first deadline, how far
          the decisions have got, and the one button that sends them. */}
      {ballots.length > 0 && (
      <div className="ballot-bar">
        <p className="ballot-bar-status">
          <strong>{meetingLabel(byMeeting.find((b) => b.meeting_date)?.meeting_date)}</strong>
          <span>
            {totalProposals - counts.pending} of {totalProposals} decided &middot; {totalCast} cast &middot; {ballots.length}{" "}
            compan{ballots.length === 1 ? "y" : "ies"}
          </span>
        </p>
        <div className="toolbar">
          {!reviewer.trim() && <ReviewerField compact />}
          {routine.length > 0 && (
            <button className="secondary" onClick={() => setConfirmingBatch(true)} disabled={busy}>
              Approve {routine.length} routine…
            </button>
          )}
          <button onClick={() => (reviewer.trim() ? setConfirming(true) : setError(REVIEWER_REQUIRED))} disabled={busy || castable === 0}>
            Cast {castable} decided vote{castable === 1 ? "" : "s"}…
          </button>
        </div>
      </div>
      )}
      <div aria-live="polite">
        {castResult && (
          <div className="banner banner-success">
            {castResult.count} vote{castResult.count === 1 ? "" : "s"} cast by {castResult.by} at {castResult.at.toLocaleString()}.
            Confirmation IDs are shown on each proposal below.
          </div>
        )}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}

      {confirmingBatch && (
        <ConfirmDecision
          title={`Approve ${routine.length} routine proposal${routine.length === 1 ? "" : "s"}?`}
          confirmLabel={`Approve ${routine.length}`}
          onConfirm={approveRoutine}
          onCancel={() => setConfirmingBatch(false)}
        >
          <p>
            Each is approved at the policy&apos;s recommended vote and recorded as your decision. Flagged proposals are not included:
            they still need their own decision and a co-sign. Nothing is cast until you press Cast.
          </p>
          <div className="table-wrap">
          <table className="data-table cast-list">
            <caption className="visually-hidden">Proposals that will be approved</caption>
            <thead>
              <tr>
                <th>Company</th>
                <th>Proposal</th>
                <th>Vote</th>
                <th>Rule</th>
              </tr>
            </thead>
            <tbody>
              {routine.map((r) => (
                <tr key={r.key}>
                  <td>{r.company}</td>
                  <td>#{r.number}</td>
                  <td>
                    <strong>{r.vote}</strong>
                  </td>
                  <td className="muted">{r.rule ?? "LLM judgment"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </ConfirmDecision>
      )}

      {confirming && (
        <Modal title="Cast votes?" compact noClose onClose={() => setConfirming(false)}>
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
      {ballots.length === 0 && (
        <p className="muted">
          No ballots in this run yet: none of its companies has a proxy statement for an upcoming meeting. Start a new voting run once
          one is filed.
        </p>
      )}
      {byMeeting.map((ballot) => (
        <div key={ballot.company_id} className="panel-section">
          <h3>
            {ballot.name} <span className="muted">({ballot.company_id})</span>
          </h3>
          {/* With one company the bar above already shows its meeting. */}
          {ballots.length > 1 && <p className="meeting-line">{meetingLabel(ballot.meeting_date)}</p>}
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
    </section>
  );
}
