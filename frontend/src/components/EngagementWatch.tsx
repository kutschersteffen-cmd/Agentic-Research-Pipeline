import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { OBJECTIVE_RESULTS, INFLUENCE_LEVELS, issueTopics } from "../lib/engagement";
import type { EngagementIssue, Objective, WatchItemKind, WatchTopic } from "../types";

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

function ObjectiveRow({ ctx, objective: o, onSaved, onClosed }: { ctx: Ctx; objective: Objective; onSaved: () => Promise<unknown>; onClosed: () => void }) {
  const [recording, setRecording] = useState(false);
  const [result, setResult] = useState("");
  const [level, setLevel] = useState("");
  const [outcome, setOutcome] = useState("");
  const trigger = useFocusOnClose<HTMLButtonElement>(recording);
  const isOpen = o.status === "initiated" || o.status === "in_progress";
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
        </div>
        <ProofLine ctx={ctx} kind="objective" id={o.objective_id} label={o.description} proof={o.proof_statement} open={isOpen} onSaved={onSaved} />
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
              <button onClick={save} disabled={ctx.busy || !result || !outcome.trim()}>
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

export function ObjectivesSection({ ctx, issue, onSaved }: { ctx: Ctx; issue: EngagementIssue; onSaved: () => Promise<unknown> }) {
  const heading = useRef<HTMLHeadingElement>(null);
  if (issue.objectives.length === 0) return null;
  return (
    <div className="panel-section">
      <h3 ref={heading} tabIndex={-1}>
        Objectives
      </h3>
      {issue.objectives.map((o) => (
        <ObjectiveRow key={o.objective_id} ctx={ctx} objective={o} onSaved={onSaved} onClosed={() => heading.current?.focus()} />
      ))}
    </div>
  );
}

/** Keyed by issue in the panel, so switching issues starts with a fresh form and list. */
export function WatchTopicsSection({ ctx, closed }: { ctx: Ctx; closed: boolean }) {
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
