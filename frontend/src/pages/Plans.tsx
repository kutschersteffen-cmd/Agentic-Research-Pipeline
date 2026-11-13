import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { ACTIVE, canReplan, resultHref, stepRows, type Plan } from "../lib/plans";

const POLL_MS = 3000;

/** Research Plans: a brief becomes a plan script the owner reads, approves and runs; each step links to its run. */
export function Plans({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string) => void }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(() => {
    api.listPlans().then(setPlans).catch((e: Error) => setError(`Plans could not be loaded: ${e.message}.`));
  }, []);
  const loadPlan = useCallback(() => {
    if (!selectedId) return setPlan(null);
    api.getPlan(selectedId).then(setPlan).catch((e: Error) => setError(`The plan could not be loaded: ${e.message}.`));
  }, [selectedId]);

  useEffect(loadList, [loadList]);
  useEffect(loadPlan, [loadPlan]);
  useEffect(() => {
    if (!plan || !ACTIVE.has(plan.status)) return;
    const t = setInterval(loadPlan, POLL_MS);
    return () => clearInterval(t);
  }, [plan, loadPlan]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      loadPlan();
      loadList();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function draft(e: React.FormEvent) {
    e.preventDefault();
    await act(async () => {
      const p = await api.draftPlan(brief);
      setBrief("");
      onSelect(p.id);
    });
  }

  return (
    <div className="page">
      <h1>Research Plans</h1>
      <p className="help-text">
        Describe the research you want. A planner writes a short script that chains ARP’s existing runs; you read the
        steps it will take, approve it, and run it. Steps that need review pause until the review is done.
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}

      <section className="card" aria-labelledby="plans-new">
        <h2 id="plans-new">New plan</h2>
        <form onSubmit={draft}>
          <label className="field-label" htmlFor="plan-brief">Research brief</label>
          <textarea id="plan-brief" rows={3} value={brief} onChange={(e) => setBrief(e.target.value)}
            aria-describedby="plan-brief-help"
            placeholder={'Grid-storage companies in the saved universe "eu listed": extract green capex for significant names, score, report'} />
          <p id="plan-brief-help" className="muted">Name a saved universe in the brief. Save one on the Thematic Universe page first.</p>
          <div className="toolbar">
            <button type="submit" disabled={busy || !brief.trim()}>{busy ? "Drafting…" : "Draft plan"}</button>
          </div>
        </form>
      </section>

      <section className="card" aria-labelledby="plans-list">
        <h2 id="plans-list">Plans</h2>
        {plans.length === 0 ? (
          <p className="muted">No plans yet. Draft one above.</p>
        ) : (
          <ul>
            {plans.map((p) => (
              <li key={p.id}>
                <button className="link-button" aria-current={p.id === selectedId ? "true" : undefined} onClick={() => onSelect(p.id)}>
                  {p.brief}
                </button>{" "}
                <span className={`status-pill status-${p.status}`}>{p.status}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {plan && (
        <section className="card" aria-labelledby="plan-title">
          <h2 id="plan-title">
            {plan.brief} <span className={`status-pill status-${plan.status}`}>{plan.status}</span>{" "}
            <span className="muted">version {plan.version}</span>
          </h2>
          {plan.approved_by && <p className="muted">Approved by {plan.approved_by}.</p>}
          {plan.error && <p className="error-text">{plan.error}</p>}
          <div className="toolbar">
            {plan.status === "draft" && <button disabled={busy} onClick={() => act(() => api.approvePlan(plan.id))}>Approve</button>}
            {(plan.status === "approved" || plan.status === "failed") && (
              <button disabled={busy} onClick={() => act(() => api.runPlan(plan.id))}>{plan.status === "failed" ? "Resume" : "Run"}</button>
            )}
            {canReplan(plan) && (
              <button disabled={busy} onClick={() => act(() => api.replanPlan(plan.id))}>Re-plan</button>
            )}
            {ACTIVE.has(plan.status) && (
              <button className="danger" disabled={busy} onClick={() => act(() => api.cancelPlan(plan.id))}>Cancel</button>
            )}
          </div>

          <h3 className="section-heading">Script</h3>
          <pre className="mono plan-script" aria-label="Plan script">{plan.script}</pre>

          <h3 className="section-heading">Steps</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>#</th><th>Step</th><th>Inputs</th><th>Status</th><th>Result</th></tr>
              </thead>
              <tbody>
                {stepRows(plan).map(({ step, status, call }) => {
                  const href = call && call.status === "done" ? resultHref(call) : null;
                  return (
                    <tr key={step.seq}>
                      <td>{step.seq}</td>
                      <td className="mono">{step.kind}</td>
                      <td className="mono plan-inputs">
                        {JSON.stringify(call?.params ?? step.params)}
                        {step.depends_on && <span className="muted"> (depends on step {step.depends_on})</span>}
                      </td>
                      <td><span className={`status-pill status-${status}`}>{status}</span></td>
                      <td>{href ? <a href={href}>{call?.run_id ?? "Open"}</a> : <span className="muted">–</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {plan.previous_scripts.length > 0 && (
            <>
              <h3 className="section-heading">Previous versions</h3>
              <ul>
                {plan.previous_scripts.map((p) => (
                  <li key={p.version}>
                    <p>Version {p.version}{p.replanned_by && <span className="muted"> (re-planned by {p.replanned_by})</span>}</p>
                    <pre className="mono plan-script" aria-label={`Script version ${p.version}`}>{p.script}</pre>
                    {p.error && <p className="error-text">{p.error}</p>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </div>
  );
}
