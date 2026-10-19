import { useRef, useState } from "react";
import { api } from "../api/client";
import { resumeSummary } from "./runs";

// Shared by every "Resume" button. The ref lock is read synchronously so a second
// click before the next render is ignored.
export function useResume() {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<{ runId: string; message: string } | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const lock = useRef(false);

  async function resume(runId: string, after?: () => void | Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusyId(runId);
    setError(null);
    setSummary(null);
    try {
      await api.resumeRun(runId);
      await after?.();
    } catch (err) {
      setError({ runId, message: (err as Error).message });
    } finally {
      lock.current = false;
      setBusyId(null);
    }
  }

  // Resumes the runs one at a time; a refusal is listed in the summary and does not stop the pass.
  async function resumeAll(runIds: string[], after?: () => void | Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusyId("all");
    setError(null);
    setSummary(null);
    const refused: { runId: string; message: string }[] = [];
    try {
      for (const runId of runIds) {
        try {
          await api.resumeRun(runId);
        } catch (err) {
          refused.push({ runId, message: (err as Error).message });
        }
      }
      await after?.();
      setSummary(resumeSummary(runIds.length, refused));
    } finally {
      lock.current = false;
      setBusyId(null);
    }
  }

  return { busyId, error, summary, resume, resumeAll, clearError: () => setError(null) };
}
