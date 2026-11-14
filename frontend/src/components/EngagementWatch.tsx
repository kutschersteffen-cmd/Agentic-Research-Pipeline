import { useEffect, useState } from "react";
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

const badge = (status: string) =>
  `badge ${["verified", "closed", "achieved"].includes(status) ? "badge-high" : ["missed", "abandoned"].includes(status) ? "badge-low" : "badge-mid"}`;

/** `Proof: …` under an item, or for an open item without one, an "Add proof statement" link. */
export function ProofLine({ ctx, kind, id, proof, open, onSaved }: { ctx: Ctx; kind: WatchItemKind; id: string; proof?: string | null; open: boolean; onSaved: () => Promise<unknown> }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  if (proof) return <div className="activity-meta">Proof: {proof}</div>;
  if (!open) return null;
  if (!editing)
    return (
      <button className="link-button" onClick={() => setEditing(true)}>
        Add proof statement
      </button>
    );
  const save = () =>
    ctx.run(async () => {
      await api.setProofStatement(kind, id, { company_id: ctx.companyId, issue_id: ctx.issueId, proof_statement: text });
      setEditing(false);
      await onSaved();
    });
  return (
    <div className="inline-fields">
      <input aria-label="Proof statement" placeholder="What counts as proof" value={text} onChange={(e) => setText(e.target.value)} />
      <button onClick={save} disabled={ctx.busy || !text.trim()}>
        Save
      </button>
    </div>
  );
}

function RecordResult({ ctx, objective, onSaved }: { ctx: Ctx; objective: Objective; onSaved: () => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState("");
  const [level, setLevel] = useState("");
  const [outcome, setOutcome] = useState("");
  if (!open)
    return (
      <button onClick={() => setOpen(true)} disabled={ctx.busy}>
        Record result
      </button>
    );
  const save = () =>
    ctx.run(async () => {
      await api.recordObjectiveResult(objective.objective_id, {
        company_id: ctx.companyId,
        issue_id: ctx.issueId,
        result,
        influence_level: level || null,
        outcome,
      });
      setOpen(false);
      await onSaved();
    });
  return (
    <div className="inline-fields">
      <label className="field-label">
        Result
        <select value={result} onChange={(e) => setResult(e.target.value)}>
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
      <label className="field-label">
        Outcome
        <textarea rows={2} value={outcome} onChange={(e) => setOutcome(e.target.value)} />
      </label>
      <button onClick={save} disabled={ctx.busy || !result || !outcome.trim()}>
        Save result
      </button>
      <button className="link-button" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </div>
  );
}

export function ObjectivesSection({ ctx, issue, onSaved }: { ctx: Ctx; issue: EngagementIssue; onSaved: () => Promise<unknown> }) {
  if (issue.objectives.length === 0) return null;
  return (
    <div className="panel-section">
      <h3>Objectives</h3>
      {issue.objectives.map((o) => {
        const isOpen = o.status === "initiated" || o.status === "in_progress";
        return (
          <div className="activity-row" key={o.objective_id}>
            <div className="activity-main">
              {o.description}
              <div className="activity-meta">
                <span className={badge(o.status)}>{o.status}</span>
                <span>{o.objective_type}</span>
                {o.result && <span>result: {o.result}</span>}
                {o.target_date && <span>due {o.target_date.slice(0, 10)}</span>}
              </div>
              <ProofLine ctx={ctx} kind="objective" id={o.objective_id} proof={o.proof_statement} open={isOpen} onSaved={onSaved} />
            </div>
            {isOpen && <RecordResult ctx={ctx} objective={o} onSaved={onSaved} />}
          </div>
        );
      })}
    </div>
  );
}

export function WatchTopicsSection({ ctx }: { ctx: Ctx }) {
  const [topics, setTopics] = useState<WatchTopic[]>([]);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [question, setQuestion] = useState("");
  const [proof, setProof] = useState("");
  const [due, setDue] = useState("");

  async function load() {
    try {
      setTopics(issueTopics((await api.listWatchTopics(ctx.companyId)).topics, ctx.issueId));
      setUnavailable(null);
    } catch (err) {
      setUnavailable((err as Error).message); // the file engagement store has no watch topics
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.companyId, ctx.issueId]);

  const add = () =>
    ctx.run(async () => {
      await api.addWatchTopic({
        company_id: ctx.companyId,
        issue_id: ctx.issueId,
        question,
        ...(proof.trim() ? { proof_statement: proof } : {}),
        ...(due ? { target_date: due } : {}),
      });
      setAdding(false);
      setQuestion("");
      setProof("");
      setDue("");
      await load();
    });

  return (
    <div className="panel-section">
      <h3>Watch topics</h3>
      {unavailable && <p className="muted">{unavailable}</p>}
      {!unavailable && topics.length === 0 && <p className="muted">None yet.</p>}
      {topics.map((t) => (
        <div className="activity-row" key={t.topic_id}>
          <div className="activity-main">
            {t.question}
            <div className="activity-meta">
              <span className={badge(t.status)}>{t.status}</span>
              {t.target_date && <span>due {t.target_date.slice(0, 10)}</span>}
            </div>
            <ProofLine ctx={ctx} kind="topic" id={t.topic_id} proof={t.proof_statement} open={t.status === "open"} onSaved={load} />
          </div>
          {t.status === "open" && (
            <button onClick={() => ctx.run(async () => { await api.closeWatchTopic(t.topic_id); await load(); })} disabled={ctx.busy}>
              Close topic
            </button>
          )}
        </div>
      ))}
      {!unavailable && !adding && (
        <button onClick={() => setAdding(true)} disabled={ctx.busy}>
          Add watch topic
        </button>
      )}
      {adding && (
        <div className="inline-fields">
          <label className="field-label">
            Question
            <input value={question} onChange={(e) => setQuestion(e.target.value)} />
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
