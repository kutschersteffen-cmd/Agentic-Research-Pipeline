import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { RunManifest } from "../types";

const RESUMABLE_STATUSES = new Set(["failed", "partially_completed", "cancelled"]);

type StepState = "done" | "current" | "pending" | "error" | "stopped";
interface Step {
  label: string;
  detail: string;
  state: StepState;
}

// Where a run stands in its lifecycle, derived from the manifest alone.
// ponytail: run-level stages only; per-company agent steps (Advocate/Opposing/
// Adjudicator, extractor/verifier) need the pipelines to report a stage first.
function runSteps(m: RunManifest): Step[] {
  const processed = m.completed_count + m.failed_count;
  const terminal = !(m.status === "pending" || m.status === "running");
  const processing: StepState =
    m.status === "pending" ? "pending"
    : m.status === "running" ? "current"
    : m.status === "failed" ? "error"
    : m.status === "cancelled" ? "stopped"
    : "done";
  return [
    { label: "Queued", detail: m.status === "pending" ? "Waiting to start" : "Started", state: m.status === "pending" ? "current" : "done" },
    { label: "Processing", detail: `${processed}/${m.company_count} processed`, state: processing },
    {
      label: "Finished",
      detail: terminal ? m.status.replace("_", " ") : "Not yet",
      state: !terminal ? "pending" : m.status === "failed" ? "error" : m.status === "cancelled" ? "stopped" : "done",
    },
    {
      label: "Human review",
      detail: m.review_count > 0 ? `${m.review_count} flagged` : terminal ? "Nothing flagged" : "Collecting flags",
      // Flags stay "current" once the run ends: sign-off happens in the Review Queue,
      // whose decisions the manifest does not count.
      state: m.review_count > 0 && terminal ? "current" : terminal ? "done" : "pending",
    },
  ];
}

const STEP_MARK: Record<StepState, string> = { done: "✓", current: "●", pending: "", error: "!", stopped: "■" };

function RunStepper({ steps }: { steps: Step[] }) {
  return (
    <ol className="run-stepper" aria-label="Run stage">
      {steps.map((s) => (
        <li key={s.label} className={`run-step run-step-${s.state}`} aria-current={s.state === "current" ? "step" : undefined}>
          <span className="run-step-mark" aria-hidden="true">{STEP_MARK[s.state]}</span>
          <span className="run-step-label">{s.label}</span>
          <span className="run-step-detail">
            <span className="visually-hidden">{s.state}: </span>
            {s.detail}
          </span>
        </li>
      ))}
    </ol>
  );
}

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
  const timerRef = useRef<number | undefined>(undefined);
  const cancelledRef = useRef(false);

  async function poll() {
    try {
      const m = (await api.getRun(runId)) as RunManifest;
      if (cancelledRef.current) return;
      setManifest(m);
      if (m.status === "running" || m.status === "pending") {
        timerRef.current = window.setTimeout(poll, pollMs);
      }
    } catch {
      if (!cancelledRef.current) timerRef.current = window.setTimeout(poll, pollMs * 2);
    }
  }

  useEffect(() => {
    cancelledRef.current = false;
    poll();
    return () => {
      cancelledRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
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
      if (timerRef.current) window.clearTimeout(timerRef.current);
      await poll(); // status is "running" again server-side -- re-arms continued polling
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  if (!manifest) return <p>Loading run status...</p>;

  const pct = manifest.company_count > 0 ? Math.round((manifest.completed_count / manifest.company_count) * 100) : 0;
  const canCancel = manifest.status === "running" || manifest.status === "pending";
  const canResume = runType === "theme" && RESUMABLE_STATUSES.has(manifest.status);

  return (
    <div className="run-progress">
      <div className="run-progress-header">
        <strong>{manifest.run_id}</strong>
        <span className={`status-pill status-${manifest.status}`}>{manifest.status}</span>
      </div>
      <RunStepper steps={runSteps(manifest)} />
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
      {actionError && <p className="error-text">{actionError}</p>}
      {manifest.error && <p className="error-text">{manifest.error}</p>}
    </div>
  );
}
