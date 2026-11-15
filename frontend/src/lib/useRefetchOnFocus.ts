import { useEffect, useRef } from "react";

/** A runner that calls `fn` unless the previous call is still running (then the call is skipped, not queued). */
export function oneAtATime(fn: () => unknown): () => void {
  let running = false;
  return () => {
    if (running) return;
    running = true;
    Promise.resolve()
      .then(fn)
      .catch(() => undefined) // the caller shows its own errors
      .finally(() => {
        running = false;
      });
  };
}

/** Calls `fn` when the browser tab becomes visible again or the window regains focus. A call made while the
 * previous one is still running is skipped, so switching back and forth never stacks requests. */
export function useRefetchOnFocus(fn: () => unknown) {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => {
    const refetch = oneAtATime(() => fnRef.current());
    const run = () => {
      if (!document.hidden) refetch();
    };
    window.addEventListener("focus", run);
    document.addEventListener("visibilitychange", run);
    return () => {
      window.removeEventListener("focus", run);
      document.removeEventListener("visibilitychange", run);
    };
  }, []);
}
