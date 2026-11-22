import { explorationBadge, resultTable } from "../lib/agent";
import type { Exploration } from "../types";

/** An exploration in the Agent stream (spec agent-panel-code-mode, Phase 4): the question, the code (collapsed), the
 * result as a table when it is a list of flat objects (JSON otherwise), the tool calls, and a badge until accepted. */
export function ExplorationCard({ exploration: e, busy, onAccept }: { exploration: Exploration; busy: boolean; onAccept: () => void }) {
  const badge = explorationBadge(e);
  const table = e.status === "done" ? resultTable(e.result) : null;
  return (
    <>
      <article className="card agent-card" aria-labelledby="agent-exploration-h">
        <h2 id="agent-exploration-h">{e.question}</h2>
        <p className="agent-meta">
          <span className={`status-pill status-${e.status}`}>{e.status}</span>{" "}
          {badge ? <span className="agent-badge">{badge}</span> : <span className="muted">Accepted by {e.accepted_by}</span>}
        </p>
        {badge && (
          <div className="toolbar">
            <button disabled={busy} onClick={onAccept}>Accept</button>
          </div>
        )}
        <details className="agent-exploration-code">
          <summary>Code</summary>
          <pre className="mono agent-wrap" aria-label="Exploration code">{e.code}</pre>
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
          <pre className="mono agent-wrap" aria-label="Exploration result">{JSON.stringify(e.result, null, 2)}</pre>
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
