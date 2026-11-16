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

/** Calls `fn` when the page is back in view: the window regains focus or the tab becomes visible. A call made while
 * the previous one is still running is skipped, so switching back and forth never stacks requests. Returns the unsubscribe. */
export function onReturn(win: EventTarget, doc: EventTarget & { hidden: boolean }, fn: () => unknown): () => void {
  const refetch = oneAtATime(fn);
  const run = () => {
    if (!doc.hidden) refetch();
  };
  win.addEventListener("focus", run);
  doc.addEventListener("visibilitychange", run);
  return () => {
    win.removeEventListener("focus", run);
    doc.removeEventListener("visibilitychange", run);
  };
}

/** `onReturn` for a component: the latest `fn` runs, wired once. */
export function useRefetchOnFocus(fn: () => unknown) {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => onReturn(window, document, () => fnRef.current()), []);
}
