import { useRef, useState } from "react";
import { api } from "../api/client";

// Shared by every "Resume" button. The ref lock is read synchronously so a second
// click before the next render is ignored.
export function useResume() {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<{ runId: string; message: string } | null>(null);
  const lock = useRef(false);

  async function resume(runId: string, after?: () => void | Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusyId(runId);
    setError(null);
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

  return { busyId, error, resume, clearError: () => setError(null) };
}
