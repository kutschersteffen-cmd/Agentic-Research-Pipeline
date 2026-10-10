import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { RunManifest } from "../types";
import { pollAfter } from "../lib/poll";
import { batchWaitText } from "../lib/runs";

const RESUMABLE_STATUSES = new Set(["failed", "partially_completed", "cancelled"]);

export function RunProgress({
  runId,
  pollMs = 2500,
  runType = "theme",
}: {
  runId: string;
  pollMs?: number;
  runType?:
    | "theme"
    | "extraction"
    | "discovery"
    | "proxy_voting"
    | "financials"
    | "tnfd"
    | "identity"
    | "transition_plan"
    | "transition_barrier_refresh"
    | "taxonomy_research"
    | "calibration"
    | "emerging_themes";
}) {
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const timerRef = useRef<() => void>(() => {});
  const cancelledRef = useRef(false);

  async function poll() {
    try {
      const m = (await api.getRun(runId)) as RunManifest;
      if (cancelledRef.current) return;
      setManifest(m);
      setLoadError(null);
      if (m.status === "running" || m.status === "pending") {
        timerRef.current = pollAfter(poll, pollMs);
      }
    } catch (err) {
      // Say so instead of "Loading…" forever; keep retrying in the background,
      // slower, in case the backend comes back.
      if (cancelledRef.current) return;
      setLoadError((err as Error).message);
      timerRef.current = pollAfter(poll, pollMs * 4);
    }
  }

  useEffect(() => {
    cancelledRef.current = false;
    poll();
    return () => {
      cancelledRef.current = true;
      timerRef.current();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, pollMs]);

  async function cancelRun() {
    setActionBusy(true);
    setActionError(null);
    try {
      await api.cancelRun(runId);
      await poll();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  async function resumeRun() {
    setActionBusy(true);
    setActionError(null);
    try {
      await api.resumeThemeRun(runId);
      timerRef.current();
      await poll(); // status is "running" again server-side — re-arms continued polling
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  if (!manifest) {
    return loadError ? (
      <p className="error-text" role="alert">
        Run status could not be loaded: {loadError}.{" "}
        <button className="link-button" onClick={() => { timerRef.current(); poll(); }}>
          Retry
        </button>
      </p>
    ) : (
      <p className="status-text">Loading run status…</p>
    );
  }

  const pct = manifest.company_count > 0 ? Math.round((manifest.completed_count / manifest.company_count) * 100) : 0;
  const canCancel = manifest.status === "running" || manifest.status === "pending";
  const canResume = runType === "theme" && RESUMABLE_STATUSES.has(manifest.status);

  return (
    <div className="run-progress">
      <div className="run-progress-header">
        <strong>{manifest.run_id}</strong>
        <span className={`status-pill status-${manifest.status}`} role="status">{manifest.status}</span>
      </div>
      {manifest.batch_wait && <p className="help-text" role="status">{batchWaitText(manifest.batch_wait)}</p>}
      <div
        className="progress-bar"
        role="progressbar"
        aria-label={`Run ${manifest.run_id} progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${manifest.completed_count} of ${manifest.company_count} companies, ${manifest.failed_count} failed`}
      >
        <div className="progress-bar-fill" style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
      <div className="run-progress-stats">
        <span>{manifest.completed_count}/{manifest.company_count} companies</span>
        <span>{manifest.failed_count} failed</span>
        <span>{manifest.review_count} flagged for review</span>
        <span>${manifest.estimated_cost_usd.toFixed(2)} est. cost{(manifest.batch_saved_usd ?? 0) > 0 ? ` · saved $${manifest.batch_saved_usd!.toFixed(2)} by batching` : ""}</span>
        <span>{(manifest.input_tokens + manifest.output_tokens).toLocaleString()} tokens</span>
        {manifest.input_tokens > 0 && manifest.cache_read_tokens !== undefined && (
          <span title="Share of input tokens read from Anthropic's prompt cache, billed at a fraction of the input price">
            {Math.round((100 * manifest.cache_read_tokens) / manifest.input_tokens)}% of input from cache
          </span>
        )}
      </div>
      {(canCancel || canResume) && (
        <div className="toolbar">
          {canCancel && (
            <button onClick={cancelRun} disabled={actionBusy}>
              Cancel run
            </button>
          )}
          {canResume && (
            <button onClick={resumeRun} disabled={actionBusy}>
              Resume run
            </button>
          )}
        </div>
      )}
      {actionError && <p className="error-text" role="alert">{actionError}</p>}
      {manifest.error && <p className="error-text" role="alert">{manifest.error}</p>}
    </div>
  );
}
