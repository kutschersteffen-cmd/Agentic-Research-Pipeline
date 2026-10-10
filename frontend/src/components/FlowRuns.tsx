import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { ACTIVE_STATUSES, isTrialRun, runTypeLabel, TRIAL_TITLE, when } from "../lib/runs";
import { runEndedAt, runScope } from "../lib/stagedFlow";
import type { RunManifest } from "../types";
import { pollAfter } from "../lib/poll";

type Scope = "all" | "batch" | "single";
const SCOPES: { id: Scope; label: string }[] = [
  { id: "batch", label: "Batch" },
  { id: "single", label: "Single" },
  { id: "all", label: "All" },
];

function readCollapsed(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function inputLabel(r: RunManifest): string {
  const path = r.params.universe_path;
  const file = typeof path === "string" && path ? path.split(/[\\/]/).filter(Boolean).pop() : undefined;
  const schema = r.params.datapoint_schema as { name?: unknown } | null | undefined;
  const name = schema && typeof schema === "object" && typeof schema.name === "string" ? schema.name : null;
  return [file ?? `${r.company_count} companies`, name].filter(Boolean).join(" · ");
}

export function FlowRuns(p: {
  runTypes: string[];
  runIds: string[];
  selected: string | null;
  onSelect: (runId: string) => void;
  onRerun?: (run: RunManifest) => void;
  onReview?: (run: RunManifest) => void;
  compact?: boolean;
  storageKey: string;
}) {
  const { runTypes, runIds, storageKey } = p;
  const [runs, setRuns] = useState<RunManifest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const [scope, setScope] = useState<Scope>("all");
  const [collapsed, setCollapsed] = useState(() => readCollapsed(storageKey));

  const typesKey = runTypes.join(",");
  const idsKey = runIds.join(",");

  const seq = useRef(0);
  const load = useCallback(async () => {
    const mySeq = ++seq.current;
    try {
      const wanted = new Set(idsKey ? idsKey.split(",") : []);
      const results = await Promise.all(
        (typesKey ? typesKey.split(",") : []).map((t) => api.listRuns(t) as Promise<{ runs: RunManifest[] }>),
      );
      const mine = results.flatMap((res) => res.runs).filter((r) => wanted.has(r.run_id));
      if (mySeq !== seq.current) return; // a newer request owns the list
      mine.sort((a, b) => {
        const live = Number(ACTIVE_STATUSES.has(b.status)) - Number(ACTIVE_STATUSES.has(a.status));
        return live || b.created_at.localeCompare(a.created_at);
      });
      setRuns(mine);
      setError(null);
    } catch (err) {
      if (mySeq !== seq.current) return;
      setError(`Runs could not be loaded: ${(err as Error).message}.`);
    }
  }, [typesKey, idsKey]);

  useEffect(() => {
    load();
  }, [load]);

  const anyLive = runs.some((r) => ACTIVE_STATUSES.has(r.status));
  useEffect(() => {
    if (!anyLive) return;
    let cancel = pollAfter(function tick() {
      load();
      cancel = pollAfter(tick, 3000);
    }, 3000);
    return () => cancel();
  }, [anyLive, load]);

  function toggle() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(storageKey, next ? "1" : "0");
    } catch {
      /* private mode: the toggle still works for this visit */
    }
  }

  async function stop(runId: string) {
    setStopError(null);
    try {
      await api.cancelRun(runId);
      await load();
    } catch (err) {
      setStopError(`Run could not be stopped: ${(err as Error).message}.`);
    }
  }

  const running = runs.filter((r) => ACTIVE_STATUSES.has(r.status)).length;
  const done = runs.filter((r) => r.status === "completed").length;
  const summary = runs.length === 0 ? "No runs yet" : [running && `${running} running`, `${done} done`].filter(Boolean).join(" · ");
  const shown = scope === "all" ? runs : runs.filter((r) => runScope(r) === scope);

  return (
    <section className={`card flow-runs${p.compact ? " compact" : ""}`}>
      <div className="toolbar">
        <h2>Current runs</h2>
        {collapsed && <span className="muted">{summary}</span>}
        <button className="secondary" type="button" aria-expanded={!collapsed} onClick={toggle}>
          {collapsed ? "Show" : "Hide"}
        </button>
      </div>
      {!collapsed && (
        <>
          {error && <p className="error-text" role="alert">{error}</p>}
          {stopError && <p className="error-text" role="alert">{stopError}</p>}
          {runs.length === 0 ? (
            <p className="muted">No runs yet in this flow.</p>
          ) : (
            <>
              <div className="view-toggle" role="group" aria-label="Run scope">
                {SCOPES.map((s) => (
                  <button key={s.id} type="button" className={scope === s.id ? "active" : ""} aria-pressed={scope === s.id} onClick={() => setScope(s.id)}>
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Started</th>
                      <th>Ended</th>
                      <th>Status</th>
                      <th>Input</th>
                      <th>Cost</th>
                      <th>Error</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((r) => {
                      const ended = runEndedAt(r);
                      return (
                        <tr key={r.run_id} className={r.run_id === p.selected ? "selected-row" : undefined}>
                          <td>
                            <span className="mono">{r.run_id}</span>
                            <div className="muted">{runTypeLabel(r.run_type)}</div>
                          </td>
                          <td className="mono">{when(r.created_at)}</td>
                          <td className="mono">{ended ? when(ended) : "—"}</td>
                          <td>
                            <span className={`status-pill status-${r.status}`}>{r.status}</span>
                            {isTrialRun(r) && <> <span className="badge badge-mid" title={TRIAL_TITLE}>trial</span></>}
                            <div className="mono">
                              {r.completed_count}/{r.company_count}
                              {r.failed_count > 0 && <span className="muted"> · {r.failed_count} failed</span>}
                              {r.review_count > 0 && <span className="await-text"> · {r.review_count} to review</span>}
                            </div>
                          </td>
                          <td>{inputLabel(r)}</td>
                          <td>
                            <span className="mono">${r.estimated_cost_usd.toFixed(2)}</span>
                            <div className="muted">
                              {(r.input_tokens + r.output_tokens).toLocaleString()} tokens{r.model ? ` · ${r.model}` : ""}
                            </div>
                          </td>
                          <td>{r.error && <div className="run-error">{r.error}</div>}</td>
                          <td>
                            {r.status === "running" && (
                              <button type="button" onClick={() => stop(r.run_id)}>Stop</button>
                            )}
                            {p.onRerun && !ACTIVE_STATUSES.has(r.status) && (
                              <button type="button" onClick={() => p.onRerun?.(r)}>Rerun</button>
                            )}{" "}
                            <button className="link-button" type="button" onClick={() => p.onSelect(r.run_id)}>Open</button>
                            {r.review_count > 0 && p.onReview && (
                              <>
                                {" "}
                                <button className="link-button" type="button" onClick={() => p.onReview?.(r)}>Review →</button>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
