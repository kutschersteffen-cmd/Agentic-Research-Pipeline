import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunManifest } from "../types";

export function RunProgress({ runId, pollMs = 2500 }: { runId: string; pollMs?: number }) {
  const [manifest, setManifest] = useState<RunManifest | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const m = await api.getRun(runId);
        if (!cancelled) setManifest(m as RunManifest);
        const status = (m as RunManifest).status;
        if (!cancelled && (status === "running" || status === "pending")) {
          timer = window.setTimeout(poll, pollMs);
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, pollMs * 2);
      }
    }
    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [runId, pollMs]);

  if (!manifest) return <p>Loading run status...</p>;

  const pct = manifest.company_count > 0 ? Math.round((manifest.completed_count / manifest.company_count) * 100) : 0;

  return (
    <div className="run-progress">
      <div className="run-progress-header">
        <strong>{manifest.run_id}</strong>
        <span className={`status-pill status-${manifest.status}`}>{manifest.status}</span>
      </div>
      <div className="progress-bar">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="run-progress-stats">
        <span>{manifest.completed_count}/{manifest.company_count} companies</span>
        <span>{manifest.failed_count} failed</span>
        <span>{manifest.review_count} flagged for review</span>
        <span>${manifest.estimated_cost_usd.toFixed(2)} est. cost</span>
        <span>{(manifest.input_tokens + manifest.output_tokens).toLocaleString()} tokens</span>
      </div>
      {manifest.error && <p className="error-text">{manifest.error}</p>}
    </div>
  );
}
