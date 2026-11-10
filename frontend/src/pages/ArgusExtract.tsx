import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { flowHref, progressHeader } from "../lib/argusFlow";
import type { ArgusFlow as Flow, FlowProgress } from "../types";

const ACTIVE = new Set(["pending", "running"]);

/** Step 4: the flow's run, live per company; Stop lets running companies finish, Retry re-runs one that failed. */
export function ArgusExtract({ flow }: { flow: Flow }) {
  const [p, setP] = useState<FlowProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => api.getFlowProgress(flow.flow_id).then(setP, (e: Error) => setError(e.message)), [flow.flow_id]);

  useEffect(() => {
    void load();
  }, [load]);
  const running = !!p && ACTIVE.has(p.status);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void api.getFlowProgress(flow.flow_id).then(setP, () => {}), 2500); // a failed poll waits for the next
    return () => clearInterval(t);
  }, [running, flow.flow_id]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!p) return error ? <p className="error-text" role="alert">{error}</p> : <p className="muted" role="status">Loading…</p>;
  return (
    <section className="argus-progress" aria-label="Extract">
      <div className="argus-progress-head">
        <p className="argus-progress-line" role="status">{progressHeader(p)}</p>
        {running && (
          <button type="button" className="danger-outline" disabled={busy} onClick={() => act(() => api.cancelRun(p.run_id))}>
            Stop
          </button>
        )}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data-table stack-on-phone" aria-label="Companies in this run">
          <thead>
            <tr>
              <th scope="col">Company</th>
              <th scope="col">Status</th>
              <th scope="col">Progress</th>
              <th scope="col">Needs you</th>
            </tr>
          </thead>
          <tbody>
            {p.companies.map((c) => (
              <tr key={c.company_id} className={c.status === "Failed" ? "argus-row-await" : undefined}>
                <td data-label="Company">{c.name}</td>
                <td data-label="Status">
                  <div>
                    <span className={c.status === "Failed" ? "await-text" : undefined}>{c.status}</span>
                    {c.reason && <span className="xbrl-sub">{c.reason}</span>}
                    {c.status === "Failed" && (
                      <span className="row-actions argus-progress-fix">
                        <button type="button" className="secondary" disabled={busy || running} title={running ? "Retry once the other companies have finished" : undefined}
                          onClick={() => act(() => api.retryFlowCompany(flow.flow_id, c.company_id))}>
                          Retry
                        </button>
                        {c.document_problem && <a href={flowHref(flow.flow_id, 2)}>Replace file</a>}
                      </span>
                    )}
                  </div>
                </td>
                <td data-label="Progress">
                  <div className="progress-bar" role="progressbar" aria-label={`${c.name} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={c.percent}>
                    <div className="progress-bar-fill" style={{ transform: `scaleX(${c.percent / 100})` }} />
                  </div>
                </td>
                <td data-label="Needs you">{c.needs_you ? `${c.needs_you} to review` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!running && (
        <div className="row-actions argus-flow-actions">
          <a className="button-link" href={flowHref(flow.flow_id, 5)}>See results</a>
        </div>
      )}
    </section>
  );
}
