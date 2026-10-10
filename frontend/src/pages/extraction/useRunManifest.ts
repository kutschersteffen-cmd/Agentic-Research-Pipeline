import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { ACTIVE_STATUSES } from "../../lib/runs";
import type { RunManifest } from "../../types";
import { pollAfter } from "../../lib/poll";

/** Polls the run manifest while it is active; `onEnd` fires once it is not. Returns the manifest of `runId` only. */
export function useRunManifest(runId: string, onEnd?: () => void): RunManifest | null {
  const [manifest, setManifest] = useState<RunManifest | null>(null);
  const endRef = useRef(onEnd);
  endRef.current = onEnd;
  useEffect(() => {
    let live = true;
    let cancel = () => {};
    async function poll() {
      try {
        const m = (await api.getRun(runId)) as RunManifest;
        if (!live) return;
        setManifest(m);
        if (!ACTIVE_STATUSES.has(m.status)) {
          endRef.current?.();
          return;
        }
      } catch {
        // keep polling; RunProgress shows the load error
      }
      if (live) cancel = pollAfter(poll, 2500);
    }
    poll();
    return () => {
      live = false;
      cancel();
    };
  }, [runId]);
  return manifest && manifest.run_id === runId ? manifest : null;
}
