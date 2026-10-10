import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { RunManifest } from "../types";

/** setTimeout for a poll loop: a tick that falls due while the tab is hidden
 * waits for the tab to be visible again, then runs at once. Returns a cancel. */
export function pollAfter(fn: () => void, ms: number): () => void {
  const onVisible = () => {
    if (document.hidden) return;
    document.removeEventListener("visibilitychange", onVisible);
    fn();
  };
  const timer = window.setTimeout(() => (document.hidden ? document.addEventListener("visibilitychange", onVisible) : fn()), ms);
  return () => {
    window.clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisible);
  };
}

/** Calls `fn`, then again `ms` after each call settles, while `enabled`, paused while the tab is hidden (see pollAfter).
 * The first call is immediate; a changed `ms` reschedules without an extra call. */
export function usePoll(fn: () => unknown, ms: number, enabled = true) {
  const fnRef = useRef(fn);
  const lastRef = useRef(0);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let cancel = () => {};
    const tick = async () => {
      lastRef.current = Date.now();
      try {
        await fnRef.current();
      } catch {
        // the caller shows its own errors; keep polling
      }
      if (live) cancel = pollAfter(tick, ms);
    };
    const wait = lastRef.current + ms - Date.now();
    if (wait > 0) cancel = pollAfter(tick, wait);
    else tick();
    return () => {
      live = false;
      cancel();
    };
  }, [enabled, ms]);
}

let inflight: Promise<RunManifest[]> | null = null;
/** Every run. Callers asking at the same moment (the nav counts and the start
 * page on load) share one request. */
export function listAllRuns(): Promise<RunManifest[]> {
  return (inflight ??= (api.listRuns() as Promise<{ runs: RunManifest[] }>)
    .then((r) => r.runs)
    .finally(() => {
      inflight = null;
    }));
}
