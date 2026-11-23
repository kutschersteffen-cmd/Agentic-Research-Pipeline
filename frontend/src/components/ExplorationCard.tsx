import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { canTurnIntoPlan, draftPlanFromExploration, explorationBadge, focusAfterDraft, resultTable, type FocusAfter } from "../lib/agent";
import type { Plan } from "../lib/plans";
import type { Exploration } from "../types";

/** An exploration in the Agent stream (spec agent-panel-code-mode, Phase 4): the question, the code (collapsed), the
 * result as a table when it is a list of flat objects (JSON otherwise), the tool calls, and a badge until accepted.
 * A done, accepted exploration offers "Turn into a plan…" (Phase 6), which drafts a plan and hands it to `onDrafted`. */
export function ExplorationCard({ exploration: e, busy, onAccept, onDrafted }: {
  exploration: Exploration; busy: boolean; onAccept: () => void; onDrafted: (plan: Plan) => void;
}) {
  const badge = explorationBadge(e);
  // Accept removes its own button: once the card shows the acceptance, focus moves to that line (WCAG 2.4.3).
  const accepting = useRef(false);
  const acceptedLine = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!badge && accepting.current) {
      accepting.current = false;
      acceptedLine.current?.focus();
    }
  }, [badge]);
  const table = e.status === "done" ? resultTable(e.result) : null;
  return (
    <>
      <article className="card agent-card" aria-labelledby="agent-exploration-h">
        <h2 id="agent-exploration-h">{e.question}</h2>
        {e.source_ask && (
          <p className="agent-meta"><a href={`#/agent/ask/${encodeURIComponent(e.source_ask.thread_id)}`}>From ask: {e.source_ask.question}</a></p>
        )}
        <p className="agent-meta">
          <span className={`status-pill status-${e.status}`}>{e.status}</span>{" "}
          {badge ? <span className="agent-badge">{badge}</span> : <span ref={acceptedLine} tabIndex={-1} className="muted">Accepted by {e.accepted_by}</span>}
        </p>
        {badge && (
          <div className="toolbar">
            <button disabled={busy} onClick={() => { accepting.current = true; onAccept(); }}>Accept</button>
          </div>
        )}
        {canTurnIntoPlan(e) && <TurnIntoPlan exploration={e} onDrafted={onDrafted} />}
        <details className="agent-exploration-code">
          <summary>Code</summary>
          <pre className="mono plan-script agent-wrap" aria-label="Exploration code">{e.code}</pre>
        </details>
      </article>

      <article className="card agent-card" aria-labelledby="agent-result-h">
        <h3 id="agent-result-h">Result</h3>
        {e.status !== "done" ? (
          <p className="error-text">{e.status === "timeout" ? `Timed out. ${e.error ?? ""}` : e.error}</p>
        ) : table ? (
          <div className="table-wrap">
            <table className="data-table" aria-label="Exploration result">
              <thead><tr>{table.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
              <tbody>
                {table.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v === null ? "–" : String(v)}</td>)}</tr>)}
              </tbody>
            </table>
          </div>
        ) : (
          <pre className="mono plan-script agent-wrap" aria-label="Exploration result">{JSON.stringify(e.result, null, 2)}</pre>
        )}
      </article>

      <article className="card agent-card" aria-labelledby="agent-tools-h">
        <h3 id="agent-tools-h">Tool calls</h3>
        {e.tool_calls.length === 0 ? (
          <p className="muted">The code called no ARP capability.</p>
        ) : (
          <ol className="agent-steps">
            {e.tool_calls.map((c, i) => (
              <li key={i}>
                <span className="mono">{c.capability_id}</span> <code className="agent-params">{JSON.stringify(c.args)}</code>{" "}
                <span className="muted">{c.result_bytes} bytes</span>
              </li>
            ))}
          </ol>
        )}
      </article>
    </>
  );
}

/** "Turn into a plan…": a brief field prefilled with the question, and "Draft plan". On a failure the field stays open
 * with the response's detail under it. */
function TurnIntoPlan({ exploration: e, onDrafted }: { exploration: Exploration; onDrafted: (plan: Plan) => void }) {
  const [brief, setBrief] = useState<string | null>(null); // null: the field is closed
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Cancel and a refused draft remove or disable the control that had focus; focus goes to the button that opens the
  // field again, or to the error (WCAG 2.4.3). A drafted plan's brief takes focus on the Agent screen.
  const refocus = useRef<FocusAfter>(null);
  const openButton = useRef<HTMLButtonElement>(null);
  const errorLine = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    const target = refocus.current === "open" ? openButton.current : refocus.current === "error" ? errorLine.current : null;
    if (!target) return;
    refocus.current = null;
    target.focus();
  }, [brief, error]);
  async function draft() {
    setDrafting(true);
    setError(null);
    const out = await draftPlanFromExploration(e, brief ?? "", (path, body) => api.agentPost<Plan>(path, body));
    setDrafting(false);
    refocus.current = focusAfterDraft(out);
    if (out.ok) onDrafted(out.plan);
    else setError(out.error);
  }
  if (brief === null) {
    return (
      <div className="toolbar">
        <button ref={openButton} type="button" className="secondary" onClick={() => setBrief(e.question)}>Turn into a plan…</button>
      </div>
    );
  }
  return (
    <form className="agent-turn-into-plan" onSubmit={(ev) => { ev.preventDefault(); draft(); }}>
      <label htmlFor="agent-exploration-brief">Brief for the plan</label>
      <textarea id="agent-exploration-brief" rows={2} value={brief} disabled={drafting} autoFocus
        onChange={(ev) => setBrief(ev.target.value)} aria-describedby={error ? "agent-exploration-plan-error" : undefined} />
      <div className="toolbar">
        <button type="submit" disabled={drafting}>Draft plan</button>
        <button type="button" className="secondary" disabled={drafting} onClick={() => { refocus.current = "open"; setBrief(null); setError(null); }}>Cancel</button>
      </div>
      {error && <p id="agent-exploration-plan-error" ref={errorLine} tabIndex={-1} className="error-text" role="alert">{error}</p>}
    </form>
  );
}
