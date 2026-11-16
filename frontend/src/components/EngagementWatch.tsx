import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { OBJECTIVE_RESULTS, INFLUENCE_LEVELS, canSaveResult, checkLine, evidenceText, evidenceWhere, foundHeader, foundLine, isDemo, issueTopics, loadSuggestions } from "../lib/engagement";
import type { EngagementIssue, EvidenceSuggestion, Objective, WatchItemKind, WatchListEntry, WatchTopic } from "../types";

// Watch list pieces of the issue panel (spec stewardship-commitment-loop, "What the user sees").
// Values are shown raw, and dates as the first 10 characters of the stored ISO value.

interface Ctx {
  companyId: string;
  issueId: string;
  busy: boolean;
  run: (fn: () => Promise<unknown>) => Promise<unknown>;
}

const STORE_409 = "Watch items need the Postgres engagement store.";

const badge = (status: string) =>
  `badge ${["verified", "closed"].includes(status) ? "badge-high" : ["missed", "abandoned"].includes(status) ? "badge-low" : "badge-mid"}`;

/** A ref for the element that opened an inline form: it gets focus back when the form closes (WCAG 2.4.3). */
function useFocusOnClose<T extends HTMLElement>(open: boolean) {
  const ref = useRef<T>(null);
  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) ref.current?.focus();
    wasOpen.current = open;
  }, [open]);
  return ref;
}

/** `Proof: …` under an item, or for an open item without one, an "Add proof statement" link. */
export function ProofLine({ ctx, kind, id, label, proof, open, onSaved }: { ctx: Ctx; kind: WatchItemKind; id: string; label: string; proof?: string | null; open: boolean; onSaved: () => Promise<unknown> }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  // after a save the proof line replaces the link, so focus lands on it instead
  const ref = useFocusOnClose<HTMLButtonElement & HTMLDivElement>(editing);
  if (proof)
    return (
      <div className="activity-meta" ref={ref} tabIndex={-1}>
        Proof: {proof}
      </div>
    );
  if (!open) return null;
  if (!editing)
    return (
      <button className="link-button" ref={ref} aria-label={`Add proof statement: ${label}`} onClick={() => setEditing(true)}>
        Add proof statement
      </button>
    );
  const save = () =>
    ctx.run(async () => {
      await api.setProofStatement(kind, id, { company_id: ctx.companyId, issue_id: ctx.issueId, proof_statement: text });
      await onSaved();
      setEditing(false);
    });
  return (
    <div className="inline-fields">
      <input aria-label="Proof statement" placeholder="What counts as proof" autoFocus value={text} onChange={(e) => setText(e.target.value)} />
      <button onClick={save} disabled={ctx.busy || !text.trim()}>
        Save
      </button>
      <button className="link-button" onClick={() => setEditing(false)}>
        Cancel
      </button>
    </div>
  );
}

function ObjectiveRow({ ctx, objective: o, demo, suggestions, closed, onSaved, onClosed }: { ctx: Ctx; objective: Objective; demo: boolean; suggestions: Suggestions; closed: boolean; onSaved: () => Promise<unknown>; onClosed: () => void }) {
  const [recording, setRecording] = useState(false);
  const [result, setResult] = useState("");
  const [level, setLevel] = useState("");
  const [outcome, setOutcome] = useState("");
  const trigger = useFocusOnClose<HTMLButtonElement>(recording);
  const isOpen = o.status === "initiated" || o.status === "in_progress";
  // a confirmed suggestion is evidence only: the person records the result, starting from the form prefilled
  const prefill = (s: EvidenceSuggestion) => {
    setResult(s.verdict === "found" ? "achieved" : "not_achieved");
    setOutcome(evidenceText(s));
    setRecording(true);
  };
  const save = () =>
    ctx.run(async () => {
      await api.recordObjectiveResult(o.objective_id, { company_id: ctx.companyId, issue_id: ctx.issueId, result, influence_level: level || null, outcome });
      await onSaved();
      onClosed(); // the row loses its button once closed: focus goes to the section heading
    });
  return (
    <div className="activity-row">
      <div className="activity-main">
        {o.description}
        <div className="activity-meta">
          <span className={badge(o.status)}>{o.status}</span>
          <span>{o.objective_type}</span>
          {o.result && <span>result: {o.result}</span>}
          {o.target_date && <span>due {o.target_date.slice(0, 10)}</span>}
          {demo && <span className="chip">Demo data</span>}
        </div>
        <ProofLine ctx={ctx} kind="objective" id={o.objective_id} label={o.description} proof={o.proof_statement} open={isOpen} onSaved={onSaved} />
        <ConfirmedEvidence suggestions={suggestions} itemId={o.objective_id} />
        {isOpen && !closed && suggestions.available && (
          <>
            <PendingEvidence ctx={ctx} suggestions={suggestions} itemId={o.objective_id} onConfirmed={prefill} />
            <CheckButton ctx={ctx} kind="objective" id={o.objective_id} label={o.description} onChecked={suggestions.reload} />
          </>
        )}
        {isOpen && recording && (
          <>
            <div className="inline-fields">
              <label className="field-label">
                Result
                <select autoFocus value={result} onChange={(e) => setResult(e.target.value)}>
                  <option value="">—</option>
                  {OBJECTIVE_RESULTS.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </label>
              <label className="field-label">
                Influence level
                <select value={level} onChange={(e) => setLevel(e.target.value)}>
                  <option value="">—</option>
                  {INFLUENCE_LEVELS.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field-label">
              Outcome
              <textarea rows={2} value={outcome} onChange={(e) => setOutcome(e.target.value)} />
            </label>
            <div className="toolbar">
              <button onClick={save} disabled={ctx.busy || !canSaveResult(result, level, outcome)}>
                Save result
              </button>
              <button className="link-button" onClick={() => setRecording(false)}>
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
      {isOpen && !recording && (
        <button ref={trigger} aria-label={`Record result: ${o.description}`} onClick={() => setRecording(true)} disabled={ctx.busy}>
          Record result
        </button>
      )}
    </div>
  );
}

export function ObjectivesSection({ ctx, issue, suggestions, closed, onSaved }: { ctx: Ctx; issue: EngagementIssue; suggestions: Suggestions; closed: boolean; onSaved: () => Promise<unknown> }) {
  const heading = useRef<HTMLHeadingElement>(null);
  if (issue.objectives.length === 0) return null;
  return (
    <div className="panel-section">
      <h3 ref={heading} tabIndex={-1}>
        Objectives
      </h3>
      {issue.objectives.map((o) => (
        <ObjectiveRow key={o.objective_id} ctx={ctx} objective={o} demo={isDemo(issue, o)} suggestions={suggestions} closed={closed} onSaved={onSaved} onClosed={() => heading.current?.focus()} />
      ))}
    </div>
  );
}

/** Keyed by issue in the panel, so switching issues starts with a fresh form and list. */
export function WatchTopicsSection({ ctx, closed, suggestions }: { ctx: Ctx; closed: boolean; suggestions: Suggestions }) {
  const [topics, setTopics] = useState<WatchTopic[] | null>(null); // null until the first load returns
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [question, setQuestion] = useState("");
  const [proof, setProof] = useState("");
  const [due, setDue] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const addButton = useFocusOnClose<HTMLButtonElement>(adding);

  async function load() {
    try {
      setTopics(issueTopics((await api.listWatchTopics(ctx.companyId)).topics, ctx.issueId));
      setUnavailable(null);
    } catch (err) {
      setUnavailable((err as Error).message);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const add = () =>
    ctx.run(async () => {
      await api.addWatchTopic({
        company_id: ctx.companyId,
        issue_id: ctx.issueId,
        question,
        ...(proof.trim() ? { proof_statement: proof } : {}),
        ...(due ? { target_date: due } : {}),
      });
      await load();
      setAdding(false);
      setQuestion("");
      setProof("");
      setDue("");
    });

  const close = (topicId: string) =>
    ctx.run(async () => {
      await api.closeWatchTopic(topicId);
      await load();
      heading.current?.focus();
    });

  const noStore = unavailable?.includes(STORE_409); // the file engagement store has no watch topics
  return (
    <div className="panel-section">
      <h3 ref={heading} tabIndex={-1}>
        Watch topics
      </h3>
      {unavailable && <p className="muted">{unavailable}</p>}
      {topics?.length === 0 && <p className="muted">None yet.</p>}
      {topics?.map((t) => (
        <div className="activity-row" key={t.topic_id}>
          <div className="activity-main">
            {t.question}
            <div className="activity-meta">
              <span className={badge(t.status)}>{t.status}</span>
              {t.target_date && <span>due {t.target_date.slice(0, 10)}</span>}
            </div>
            <ProofLine ctx={ctx} kind="topic" id={t.topic_id} label={t.question} proof={t.proof_statement} open={t.status === "open"} onSaved={load} />
            <ConfirmedEvidence suggestions={suggestions} itemId={t.topic_id} />
            {t.status === "open" && !closed && (
              <>
                <PendingEvidence ctx={ctx} suggestions={suggestions} itemId={t.topic_id} />
                <CheckButton ctx={ctx} kind="topic" id={t.topic_id} label={t.question} onChecked={suggestions.reload} />
              </>
            )}
          </div>
          {t.status === "open" && (
            <button aria-label={`Close topic: ${t.question}`} onClick={() => close(t.topic_id)} disabled={ctx.busy}>
              Close topic
            </button>
          )}
        </div>
      ))}
      {!noStore && !closed && !adding && (
        <button ref={addButton} onClick={() => setAdding(true)} disabled={ctx.busy}>
          Add watch topic
        </button>
      )}
      {adding && (
        <div className="inline-fields">
          <label className="field-label">
            Question
            <input autoFocus value={question} onChange={(e) => setQuestion(e.target.value)} />
          </label>
          <label className="field-label">
            What counts as proof
            <input value={proof} onChange={(e) => setProof(e.target.value)} />
          </label>
          <label className="field-label">
            Due date
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
          <button onClick={add} disabled={ctx.busy || !question.trim()}>
            Add topic
          </button>
          <button className="link-button" onClick={() => setAdding(false)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

// --- Suggestions from Argus (spec stewardship-commitment-loop, PR 2) ------------------------------------

export interface Suggestions {
  pending: EvidenceSuggestion[];
  confirmed: EvidenceSuggestion[];
  /** false on the file engagement store, which has no suggestions: no Check or Find buttons then */
  available: boolean;
  /** why the last load failed, shown as "Suggestions unavailable: <error>"; null on success and on the file store's 409 */
  error: string | null;
  reload: () => Promise<void>;
}

/** The company's pending and confirmed suggestions. Keyed by company in the panel. */
export function useSuggestions(companyId: string): Suggestions {
  const [pending, setPending] = useState<EvidenceSuggestion[]>([]);
  const [confirmed, setConfirmed] = useState<EvidenceSuggestion[]>([]);
  const [available, setAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = useRef(companyId);
  current.current = companyId;
  async function reload() {
    const { loaded, error } = await loadSuggestions((status) => api.listSuggestions(companyId, status));
    if (current.current !== companyId) return; // the panel moved to another company while this loaded
    if (loaded) {
      setPending(loaded.pending);
      setConfirmed(loaded.confirmed);
    }
    setAvailable(loaded !== null);
    setError(error);
  }
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);
  return { pending, confirmed, available, error, reload };
}

/** "Check against documents" and, once it ran, the one-line result. */
export function CheckButton({ ctx, kind, id, label, onChecked }: { ctx: Ctx; kind: WatchItemKind; id: string; label: string; onChecked: () => Promise<unknown> }) {
  const [line, setLine] = useState<string | null>(null);
  const check = () =>
    ctx.run(async () => {
      const r = await api.checkWatchItem(kind, id, ctx.companyId);
      setLine(checkLine(r));
      await onChecked();
    });
  return (
    <div className="inline-fields">
      <button aria-label={`Check against documents: ${label}`} onClick={check} disabled={ctx.busy}>
        Check against documents
      </button>
      {line && <span className="activity-meta" role="status">{line}</span>}
    </div>
  );
}

/** Reject with a required reason, shared by both kinds of suggestion. */
function RejectButton({ ctx, s, onDecided }: { ctx: Ctx; s: EvidenceSuggestion; onDecided: () => Promise<unknown> }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const trigger = useFocusOnClose<HTMLButtonElement>(rejecting);
  if (!rejecting)
    return (
      <button ref={trigger} className="link-button" onClick={() => setRejecting(true)} disabled={ctx.busy}>
        Reject
      </button>
    );
  const reject = () =>
    ctx.run(async () => {
      await api.rejectSuggestion(s.suggestion_id, reason);
      await onDecided();
    });
  return (
    <span className="inline-fields">
      <label className="field-label">
        Why reject? (required)
        <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <button onClick={reject} disabled={ctx.busy || !reason.trim()}>
        Confirm rejection
      </button>
      <button className="link-button" onClick={() => setRejecting(false)}>
        Cancel
      </button>
    </span>
  );
}

/** The pending evidence suggestions on one item. `onConfirmed` runs after a confirm, before the lists reload. */
export function PendingEvidence({ ctx, suggestions, itemId, onConfirmed, onSaved }: { ctx: Ctx; suggestions: Suggestions; itemId: string; onConfirmed?: (s: EvidenceSuggestion) => void; onSaved?: () => Promise<unknown> }) {
  const mine = suggestions.pending.filter((s) => s.kind === "evidence" && s.item_id === itemId);
  const decided = async () => {
    await suggestions.reload();
    await onSaved?.();
  };
  const confirm = (s: EvidenceSuggestion) =>
    ctx.run(async () => {
      await api.confirmSuggestion(s.suggestion_id);
      onConfirmed?.(s);
      await decided();
    });
  return (
    <>
      {mine.map((s) => (
        <div className="suggestion" key={s.suggestion_id}>
          <strong>Argus suggests: evidence {s.verdict}</strong>
          <blockquote>"{s.quote}"</blockquote>
          <div className="activity-meta">{evidenceWhere(s)}</div>
          {s.reason && <div className="activity-meta">{s.reason}</div>}
          <div className="toolbar">
            <button onClick={() => confirm(s)} disabled={ctx.busy}>
              Confirm
            </button>
            <RejectButton ctx={ctx} s={s} onDecided={decided} />
          </div>
        </div>
      ))}
    </>
  );
}

/** `Evidence: … (confirmed by …)` lines under an objective or topic, oldest first. */
export function ConfirmedEvidence({ suggestions, itemId }: { suggestions: Suggestions; itemId: string }) {
  const mine = suggestions.confirmed.filter((s) => s.kind === "evidence" && s.item_id === itemId).reverse();
  return (
    <>
      {mine.map((s) => (
        <div className="activity-meta" key={s.suggestion_id}>
          {s.verdict === "against" ? "Evidence against" : "Evidence"}: {evidenceText(s)} (confirmed by {s.decided_by})
        </div>
      ))}
    </>
  );
}

/** "Find commitments" on a call or meeting note, and once it ran, the one-line result. */
export function FindCommitmentsButton({ ctx, activityId, onFound }: { ctx: Ctx; activityId: string; onFound: () => Promise<unknown> }) {
  const [line, setLine] = useState<string | null>(null);
  const find = () =>
    ctx.run(async () => {
      const r = await api.findCommitments(activityId);
      setLine(foundLine(r.suggestions));
      await onFound();
    });
  return (
    <div className="inline-fields">
      <button onClick={find} disabled={ctx.busy}>
        Find commitments
      </button>
      {line && <span className="activity-meta" role="status">{line}</span>}
    </div>
  );
}

function FoundCommitment({ ctx, s, issue, closed, onDecided }: { ctx: Ctx; s: EvidenceSuggestion; issue: EngagementIssue; closed: boolean; onDecided: () => Promise<unknown> }) {
  const [due, setDue] = useState(s.target_date ?? "");
  const note = issue.correspondence.find((c) => c.entry_id === s.activity_id);
  const add = () =>
    ctx.run(async () => {
      await api.confirmSuggestion(s.suggestion_id, { target_date: due });
      await onDecided();
    });
  return (
    <div className="suggestion">
      <strong>{foundHeader(note)}</strong>
      <div>{s.text}</div>
      {s.proof_statement && <div className="activity-meta">Proof: {s.proof_statement}</div>}
      <blockquote>"{s.quote}"</blockquote>
      <label className="field-label">
        Due date
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </label>
      {!s.target_date && <span className="muted">Not stated in the note</span>}
      <div className="toolbar">
        <button onClick={add} disabled={ctx.busy || !due || closed}>
          Add commitment
        </button>
        <RejectButton ctx={ctx} s={s} onDecided={onDecided} />
      </div>
      {closed && <span className="muted">This engagement is closed. Reopen it to add a commitment.</span>}
    </div>
  );
}

/** Pending commitments Argus found in this engagement's notes, shown at the top of Commitments. */
export function FoundCommitments({ ctx, issue, suggestions, closed, onSaved }: { ctx: Ctx; issue: EngagementIssue; suggestions: Suggestions; closed: boolean; onSaved: () => Promise<unknown> }) {
  const mine = suggestions.pending.filter((s) => s.kind === "new_commitment" && s.engagement_id === issue.issue_id);
  const decided = async () => {
    await suggestions.reload();
    await onSaved();
  };
  return (
    <>
      {mine.map((s) => (
        <FoundCommitment key={s.suggestion_id} ctx={ctx} s={s} issue={issue} closed={closed} onDecided={decided} />
      ))}
    </>
  );
}

const WATCH_KIND = { objective: "Objective", commitment: "Commitment", topic: "Watch topic" } as const;

/** The dossier's watch list, built by the API: flagged entries first, each with its proof and confirmed evidence. */
export function DossierWatchList({ entries }: { entries: WatchListEntry[] }) {
  return (
    <>
      <h4>Watch list</h4>
      {entries.length === 0 && <p className="muted">No open objectives, commitments or watch topics.</p>}
      {entries.map((e) => (
        <div className="activity-row" key={e.item_id}>
          <div className="activity-main">
            {WATCH_KIND[e.item_kind]}: {e.text}
            <div className="activity-meta">
              {e.target_date && <span>due {e.target_date.slice(0, 10)}</span>}
              {e.flag && <span className="badge badge-low">{e.flag}</span>}
            </div>
            {e.proof_statement && <div className="activity-meta">Proof: {e.proof_statement}</div>}
            {e.evidence.map((line) => (
              <div className="activity-meta" key={line}>
                {line}
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
