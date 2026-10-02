import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { jobLabel, type Job } from "../../lib/jobs";
import type { StageState } from "../../lib/stagedFlow";
import type { RunDecision } from "../../types";

export interface ScoringRow { job: Job; runId: string; status: StageState }

/** One row per job with a run: framework, companies scored and tiers. A row re-loads when its run's status changes. */
export function ScoringSummary(p: {
  rows: ScoringRow[];
  onOpen: (jobId: string) => void;
  /** Reports each job's framework name, or "None attached", once its run has ended. */
  onFramework?: (jobId: string, name: string | null) => void;
}) {
  const { rows, onOpen, onFramework } = p;
  // undefined = loading, null = none attached
  const [decisions, setDecisions] = useState<Record<string, RunDecision | null>>({});
  const key = rows.map((r) => `${r.job.id}=${r.runId}:${r.status}`).join(",");

  useEffect(() => {
    let live = true;
    for (const r of rows) {
      api
        .getRunDecision(r.runId)
        .catch(() => null)
        .then((d) => {
          if (!live) return;
          setDecisions((s) => ({ ...s, [r.runId]: d }));
          onFramework?.(r.job.id, r.status === "running" ? null : d?.framework.name ?? "None attached");
        });
    }
    return () => {
      live = false;
    };
    // `key` covers every field of rows the effect reads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, onFramework]);

  if (!rows.length) return <></>;
  return (
    <section className="card">
      <h2>Scoring</h2>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Job</th>
              <th>Framework</th>
              <th>Scored / total</th>
              <th>Tiers</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ job, runId }) => {
              const d = decisions[runId];
              return (
                <tr key={job.id}>
                  <td>{jobLabel(job)}</td>
                  <td>{d === undefined ? "Loading…" : d ? d.framework.name : "None attached"}</td>
                  <td>{d ? `${d.result.scored_count} / ${d.result.entities.length}` : "—"}</td>
                  <td>{d ? d.result.tier_summary.map((t) => `${t.name}: ${t.count}`).join(" · ") : "—"}</td>
                  <td>
                    <button onClick={() => onOpen(job.id)}>Open</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
