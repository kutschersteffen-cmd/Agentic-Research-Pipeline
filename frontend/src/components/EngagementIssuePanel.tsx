import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  Contact,
  EngagementIssue,
  EngagementRecord,
  EscalationStage,
  MeetingSummaryDraft,
  MeetingTalkingPoints,
  OrchestratorDecision,
  OutreachLetterDraft,
  ResearchDossier,
} from "../types";

const ESCALATION_STAGES: EscalationStage[] = [
  "private_engagement",
  "joint_engagement",
  "written_escalation_to_board",
  "escalation_to_chair",
  "vote_against_management",
  "file_or_cofile_resolution",
  "public_statement",
];

function escalationClass(stage: string): string {
  const idx = ESCALATION_STAGES.indexOf(stage as EscalationStage);
  if (idx >= 4) return "stage-pill escalation-high";
  if (idx >= 1) return "stage-pill escalation-mid";
  return "stage-pill escalation-low";
}

function fmt(s: string): string {
  return s.replace(/_/g, " ");
}

export function EngagementIssuePanel({
  record,
  issue,
  onUpdated,
  onClose,
}: {
  record: EngagementRecord;
  issue: EngagementIssue;
  onUpdated: (record: EngagementRecord) => void;
  onClose: () => void;
}) {
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [nextAction, setNextAction] = useState<OrchestratorDecision | null>(null);
  const [escalateStage, setEscalateStage] = useState<EscalationStage>(issue.escalation_stage);
  const [escalateReason, setEscalateReason] = useState("");

  const [dossier, setDossier] = useState<ResearchDossier | null>(null);
  const [recipient, setRecipient] = useState("");
  const [houseStyle, setHouseStyle] = useState("");
  const [letter, setLetter] = useState<OutreachLetterDraft | null>(null);
  const [talkingPoints, setTalkingPoints] = useState<MeetingTalkingPoints | null>(null);
  const [notesOrTranscript, setNotesOrTranscript] = useState("");
  const [meetingSummary, setMeetingSummary] = useState<MeetingSummaryDraft | null>(null);

  const [newContactName, setNewContactName] = useState("");
  const [newContactRole, setNewContactRole] = useState("");
  const [newContactEmail, setNewContactEmail] = useState("");

  useEffect(() => {
    setDossier(null);
    setLetter(null);
    setTalkingPoints(null);
    setMeetingSummary(null);
    setNextAction(null);
    setEscalateStage(issue.escalation_stage);
    loadNextAction();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [issue.issue_id]);

  async function loadNextAction() {
    try {
      const res = (await api.getEngagementNextAction(record.company_id, issue.issue_id)) as OrchestratorDecision;
      setNextAction(res);
    } catch {
      /* best-effort */
    }
  }

  async function refreshRecord() {
    const updated = (await api.getEngagementRecord(record.company_id)) as EngagementRecord;
    onUpdated(updated);
    return updated;
  }

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError((err as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function escalate() {
    await run(async () => {
      await api.escalateEngagementIssue(record.company_id, issue.issue_id, {
        stage: escalateStage,
        decided_by: actor || "unknown",
        reason: escalateReason,
      });
      await refreshRecord();
      await loadNextAction();
      setEscalateReason("");
    });
  }

  async function draftDossier() {
    await run(async () => {
      const res = await api.draftDossier(record.company_id, issue.issue_id, { company_id: record.company_id, name: record.name });
      setDossier(res.dossier);
      setRecipient(res.dossier.recommended_contacts[0] ?? "");
    });
  }

  async function draftLetter() {
    if (!dossier) return;
    await run(async () => {
      const res = (await api.draftOutreachLetter(record.company_id, issue.issue_id, {
        company_name: record.name,
        recipient,
        dossier,
        house_style_notes: houseStyle,
      })) as OutreachLetterDraft;
      setLetter(res);
    });
  }

  async function draftPoints() {
    if (!dossier) return;
    await run(async () => {
      const res = (await api.draftTalkingPoints(record.company_id, issue.issue_id, { company_name: record.name, dossier })) as MeetingTalkingPoints;
      setTalkingPoints(res);
    });
  }

  async function logSent() {
    if (!letter) return;
    await run(async () => {
      await api.logOutreachSent(record.company_id, issue.issue_id, {
        summary: `${letter.subject} -- sent to ${letter.recommended_recipient}`,
        sent_by: actor || "unknown",
      });
      await refreshRecord();
      await loadNextAction();
    });
  }

  async function draftSummary() {
    if (!notesOrTranscript.trim()) return;
    await run(async () => {
      const res = (await api.draftMeetingSummary(record.company_id, issue.issue_id, {
        company_name: record.name,
        notes_or_transcript: notesOrTranscript,
      })) as MeetingSummaryDraft;
      setMeetingSummary(res);
    });
  }

  async function validateAndLogSummary() {
    if (!meetingSummary) return;
    await run(async () => {
      await api.logMeetingSummaryValidated(record.company_id, issue.issue_id, {
        summary: meetingSummary.summary,
        commitments: meetingSummary.commitments_identified,
        validated_by: actor || "unknown",
      });
      await refreshRecord();
      await loadNextAction();
      setMeetingSummary(null);
      setNotesOrTranscript("");
    });
  }

  async function verifyCommitment(commitmentId: string) {
    await run(async () => {
      await api.verifyCommitment(record.company_id, issue.issue_id, { commitment_id: commitmentId, verified_by: actor || "unknown" });
      await refreshRecord();
      await loadNextAction();
    });
  }

  async function addContact() {
    if (!newContactName.trim()) return;
    await run(async () => {
      const body: Partial<Contact> = { name: newContactName, role: newContactRole, email: newContactEmail || null };
      await api.addEngagementContact(record.company_id, body);
      await refreshRecord();
      setNewContactName("");
      setNewContactRole("");
      setNewContactEmail("");
    });
  }

  return (
    <section className="card">
      <div className="section-heading">
        <h3>
          {record.name} &middot; {issue.theme}
        </h3>
        <button className="link-button" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="chip-row">
        <span className={`status-pill status-${issue.status === "stalled" ? "failed" : issue.status === "resolved" || issue.status === "closed" ? "completed" : "running"}`}>
          {issue.status}
        </span>
        <span className="stage-pill">{fmt(issue.milestone_stage)}</span>
        <span className={escalationClass(issue.escalation_stage)}>{fmt(issue.escalation_stage)}</span>
        <span className="chip">severity: {issue.severity}</span>
        <span className="chip">source: {fmt(issue.source)}</span>
        <span className="chip">opened {new Date(issue.opened_at).toLocaleDateString()}</span>
      </div>

      {nextAction && (
        <p className="status-text">
          Orchestrator recommends: <strong>{fmt(nextAction.action)}</strong> &mdash; {nextAction.reason}
        </p>
      )}

      <label className="field-label">Acting as (used for all sign-offs below)</label>
      <input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="your name / handle" />
      {error && <p className="error-text">{error}</p>}

      <div className="panel-section">
        <h4>Escalation-lever decision</h4>
        <p className="help-text">
          The one non-negotiable human checkpoint for escalation -- this is the only way an issue's escalation stage
          moves.
        </p>
        <div className="inline-fields">
          <select value={escalateStage} onChange={(e) => setEscalateStage(e.target.value as EscalationStage)}>
            {ESCALATION_STAGES.map((s) => (
              <option key={s} value={s}>
                {fmt(s)}
              </option>
            ))}
          </select>
          <button onClick={escalate} disabled={busy || !actor}>
            Set escalation stage
          </button>
        </div>
        <textarea rows={1} placeholder="Reason (optional)" value={escalateReason} onChange={(e) => setEscalateReason(e.target.value)} />
      </div>

      <div className="panel-section">
        <h4>Milestone &amp; escalation history</h4>
        <ul className="timeline">
          {[...issue.milestone_history.map((t) => ({ label: `Milestone -> ${fmt(t.stage)}`, at: t.changed_at, note: t.reason })), ...issue.escalation_history.map((t) => ({ label: `Escalated -> ${fmt(t.stage)}`, at: t.changed_at, note: `${t.decided_by}${t.reason ? `: ${t.reason}` : ""}` }))]
            .sort((a, b) => (a.at < b.at ? -1 : 1))
            .map((t, i) => (
              <li key={i}>
                {t.label}
                <div className="timeline-meta">
                  {new Date(t.at).toLocaleString()}
                  {t.note ? ` -- ${t.note}` : ""}
                </div>
              </li>
            ))}
          {issue.milestone_history.length === 0 && issue.escalation_history.length === 0 && <li className="muted">No transitions logged yet.</li>}
        </ul>
      </div>

      <div className="panel-section">
        <h4>Correspondence</h4>
        {issue.correspondence.length === 0 && <p className="muted">None logged yet.</p>}
        <ul className="timeline">
          {issue.correspondence.map((c) => (
            <li key={c.entry_id}>
              [{c.type}] {c.summary}
              <div className="timeline-meta">
                {new Date(c.date).toLocaleString()} {c.logged_by ? `-- logged by ${c.logged_by}` : ""}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="panel-section">
        <h4>Commitments</h4>
        {issue.commitments.length === 0 && <p className="muted">None logged yet.</p>}
        {issue.commitments.map((c) => (
          <div className="activity-row" key={c.commitment_id}>
            <div className="activity-main">
              {c.text}
              <div className="activity-meta">
                <span className={`badge ${c.status === "verified" ? "badge-high" : c.status === "missed" ? "badge-low" : "badge-mid"}`}>{c.status}</span>
                <span>made {new Date(c.made_at).toLocaleDateString()}</span>
                {c.target_date && <span>target {c.target_date}</span>}
                {c.validated_by && <span>verified by {c.validated_by}</span>}
              </div>
            </div>
            {c.status === "open" && (
              <button onClick={() => verifyCommitment(c.commitment_id)} disabled={busy || !actor}>
                Verify
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="panel-section">
        <h4>Research Agent</h4>
        <button onClick={draftDossier} disabled={busy}>
          {dossier ? "Redraft dossier" : "Draft dossier"}
        </button>
        {dossier && (
          <div className="review-item">
            {dossier.needs_review && <div className="banner banner-warning">Flagged for review (low confidence and/or ungrounded citation).</div>}
            <p>
              <strong>Summary:</strong> {dossier.summary}
            </p>
            <p>
              <strong>Controversy context:</strong> {dossier.controversy_context}
            </p>
            <p>
              <strong>Peer benchmark:</strong> {dossier.peer_benchmark_notes}
            </p>
            <p className="muted">Confidence: {Math.round(dossier.confidence * 100)}% &middot; {dossier.citations.length} citation(s)</p>
          </div>
        )}
      </div>

      <div className="panel-section">
        <h4>Drafting Agent</h4>
        {!dossier && <p className="help-text">Draft a dossier first -- the letter/talking points reuse its grounded citations.</p>}
        {dossier && (
          <>
            <label className="field-label">Recipient</label>
            <input value={recipient} onChange={(e) => setRecipient(e.target.value)} placeholder="e.g. Investor Relations" />
            <label className="field-label">House style notes (optional)</label>
            <textarea rows={2} value={houseStyle} onChange={(e) => setHouseStyle(e.target.value)} />
            <div className="toolbar">
              <button onClick={draftLetter} disabled={busy || !recipient}>
                Draft outreach letter
              </button>
              <button onClick={draftPoints} disabled={busy}>
                Draft talking points
              </button>
            </div>
            {letter && (
              <div className="review-item">
                <p>
                  <strong>{letter.subject}</strong> &rarr; {letter.recommended_recipient}
                </p>
                <p style={{ whiteSpace: "pre-wrap" }}>{letter.body}</p>
                <div className="toolbar">
                  <button onClick={logSent} disabled={busy || !actor}>
                    Log outreach sent (human-authorized)
                  </button>
                </div>
              </div>
            )}
            {talkingPoints && (
              <div className="review-item">
                <p>
                  <strong>Objectives</strong>
                </p>
                <ul>
                  {talkingPoints.objectives.map((o, i) => (
                    <li key={i}>{o}</li>
                  ))}
                </ul>
                <p>
                  <strong>Points</strong>
                </p>
                <ul>
                  {talkingPoints.points.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>

      <div className="panel-section">
        <h4>Post-meeting summary &amp; validation</h4>
        <label className="field-label">Meeting notes or transcript</label>
        <textarea rows={4} value={notesOrTranscript} onChange={(e) => setNotesOrTranscript(e.target.value)} placeholder="Paste raw notes or a transcript..." />
        <button onClick={draftSummary} disabled={busy || !notesOrTranscript.trim()}>
          Draft summary
        </button>
        {meetingSummary && (
          <div className="review-item">
            <p>{meetingSummary.summary}</p>
            {meetingSummary.commitments_identified.length > 0 && (
              <>
                <p className="muted">Commitments identified:</p>
                <ul>
                  {meetingSummary.commitments_identified.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </>
            )}
            {meetingSummary.follow_up_actions.length > 0 && (
              <>
                <p className="muted">Follow-up actions:</p>
                <ul>
                  {meetingSummary.follow_up_actions.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </>
            )}
            <button onClick={validateAndLogSummary} disabled={busy || !actor}>
              Validate &amp; log (human checkpoint)
            </button>
          </div>
        )}
      </div>

      <div className="panel-section">
        <h4>Contacts</h4>
        {record.contacts.length === 0 && <p className="muted">None on file.</p>}
        <ul className="timeline">
          {record.contacts.map((c) => (
            <li key={c.contact_id}>
              {c.name} &middot; {c.role}
              {c.email && <span className="timeline-meta"> {c.email}</span>}
            </li>
          ))}
        </ul>
        <div className="inline-fields">
          <input placeholder="Name" value={newContactName} onChange={(e) => setNewContactName(e.target.value)} />
          <input placeholder="Role" value={newContactRole} onChange={(e) => setNewContactRole(e.target.value)} />
          <input placeholder="Email (optional)" value={newContactEmail} onChange={(e) => setNewContactEmail(e.target.value)} />
          <button onClick={addContact} disabled={busy || !newContactName.trim()}>
            Add contact
          </button>
        </div>
      </div>
    </section>
  );
}
